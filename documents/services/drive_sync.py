"""Google Drive folder sync service for document ingestion."""
import logging
import os
import tempfile
from datetime import datetime

from django.conf import settings
from django.core.files import File
from django.utils import timezone

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}

# Google Docs export mapping (convert Google Workspace files to downloadable formats)
GOOGLE_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
}


def get_drive_service():
    """Build Google Drive API client from service account JSON."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not creds_file or not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"Service account file not found: {creds_file}. "
            "Set GOOGLE_SERVICE_ACCOUNT_FILE in .env."
        )

    credentials = service_account.Credentials.from_service_account_file(
        creds_file, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=credentials)


def _list_subfolders(service, folder_id):
    """Recursively list all subfolder IDs under the given folder."""
    folder_ids = [folder_id]
    query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"

    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=100,
            pageToken=page_token,
        ).execute()

        for f in response.get("files", []):
            logger.debug(f"Found subfolder: {f['name']} ({f['id']})")
            folder_ids.extend(_list_subfolders(service, f["id"]))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return folder_ids


def list_drive_files(service, folder_id):
    """List all supported files in the given Drive folder and all subfolders."""
    # Discover all folders recursively
    all_folder_ids = _list_subfolders(service, folder_id)
    logger.info(f"Scanning {len(all_folder_ids)} folder(s) (including subfolders)")

    all_mime_types = list(SUPPORTED_MIME_TYPES.keys()) + list(GOOGLE_EXPORT_MIME_TYPES.keys())
    mime_filter = " or ".join(f"mimeType='{mt}'" for mt in all_mime_types)

    files = []
    for fid in all_folder_ids:
        query = f"'{fid}' in parents and ({mime_filter}) and trashed=false"
        page_token = None
        while True:
            response = service.files().list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)",
                pageSize=100,
                pageToken=page_token,
            ).execute()

            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return files


def download_drive_file(service, file_id, name, mime_type):
    """Download a file from Drive to a temp path. Returns the temp file path."""
    # Determine if we need to export (Google Workspace file) or direct download
    if mime_type in GOOGLE_EXPORT_MIME_TYPES:
        export_mime, ext = GOOGLE_EXPORT_MIME_TYPES[mime_type]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        # Ensure filename has the right extension
        base_name = os.path.splitext(name)[0]
        name = base_name + ext
    else:
        ext = SUPPORTED_MIME_TYPES.get(mime_type, "")
        request = service.files().get_media(fileId=file_id)

    suffix = ext or os.path.splitext(name)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            from googleapiclient.http import MediaIoBaseDownload
            import io

            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
    except Exception:
        os.unlink(tmp_path)
        raise

    return tmp_path, name


def sync_folder():
    """Main sync function: pull files from Drive, create/update/remove Documents."""
    from documents.models import Document, DriveFile
    from documents.tasks import process_document
    from documents.services.vector_store import remove_file_from_vector_store

    folder_id = settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        logger.warning("GOOGLE_DRIVE_FOLDER_ID not configured, skipping sync.")
        return {"new": 0, "updated": 0, "removed": 0, "error": "No folder ID configured"}

    service = get_drive_service()
    drive_files = list_drive_files(service, folder_id)
    logger.info(f"Found {len(drive_files)} files in Drive folder {folder_id}")

    # Track IDs we've seen for removal detection
    seen_drive_ids = set()
    new_count = 0
    updated_count = 0
    removed_count = 0

    for df in drive_files:
        file_id = df["id"]
        seen_drive_ids.add(file_id)
        name = df["name"]
        mime_type = df["mimeType"]
        md5 = df.get("md5Checksum", "")
        modified_str = df.get("modifiedTime", "")

        # Parse Drive's ISO timestamp
        if modified_str:
            modified_time = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))
        else:
            modified_time = timezone.now()

        try:
            existing = DriveFile.objects.select_related("document").get(drive_file_id=file_id)

            # Check if file has changed (by md5 or modified time)
            changed = False
            if md5 and existing.md5_checksum and md5 != existing.md5_checksum:
                changed = True
            elif modified_time > existing.modified_time:
                changed = True

            if not changed:
                logger.debug(f"Skipping unchanged file: {name}")
                continue

            # File changed — re-download and re-process
            logger.info(f"Updating changed file: {name}")
            tmp_path, final_name = download_drive_file(service, file_id, name, mime_type)
            try:
                doc = existing.document
                if doc:
                    # Remove old file from OpenAI Vector Store
                    if doc.openai_file_id:
                        remove_file_from_vector_store(doc.openai_file_id)
                        doc.openai_file_id = ""
                    doc.file.delete(save=False)
                    with open(tmp_path, "rb") as f:
                        doc.file.save(final_name, File(f), save=False)
                    doc.status = "pending"
                    doc.save(update_fields=["file", "status", "openai_file_id"])
                    process_document.delay(str(doc.id))
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            existing.md5_checksum = md5
            existing.modified_time = modified_time
            existing.name = name
            existing.save(update_fields=["md5_checksum", "modified_time", "name", "last_synced"])
            updated_count += 1

        except DriveFile.DoesNotExist:
            # New file — download and create Document
            logger.info(f"New file from Drive: {name}")
            tmp_path, final_name = download_drive_file(service, file_id, name, mime_type)
            try:
                doc = Document(
                    title=os.path.splitext(final_name)[0],
                    authority_level="statute",
                    domain="other",
                    jurisdiction="TX",
                    status="pending",
                )
                with open(tmp_path, "rb") as f:
                    doc.file.save(final_name, File(f), save=False)
                doc.save()

                DriveFile.objects.create(
                    drive_file_id=file_id,
                    name=name,
                    mime_type=mime_type,
                    md5_checksum=md5,
                    modified_time=modified_time,
                    document=doc,
                )
                process_document.delay(str(doc.id))
                new_count += 1
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        except Exception:
            logger.exception(f"Error syncing file {name} ({file_id})")

    # Detect removed files: DriveFile records whose IDs are no longer in Drive
    stale = DriveFile.objects.exclude(drive_file_id__in=seen_drive_ids)
    for df_record in stale:
        logger.info(f"File removed from Drive: {df_record.name}")
        if df_record.document:
            # Remove from OpenAI Vector Store
            if df_record.document.openai_file_id:
                remove_file_from_vector_store(df_record.document.openai_file_id)
            df_record.document.status = "failed"
            df_record.document.save(update_fields=["status"])
        df_record.delete()
        removed_count += 1

    result = {"new": new_count, "updated": updated_count, "removed": removed_count}
    logger.info(f"Drive sync complete: {result}")
    return result
