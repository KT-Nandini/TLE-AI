"""Celery tasks for document ingestion pipeline.

Uses OpenAI Vector Store (Responses API) for storage and retrieval.
Documents are uploaded as raw files — OpenAI handles chunking, embedding, and search.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_document(self, document_id: str):
    """Upload document to OpenAI Vector Store."""
    from documents.models import Document
    from documents.services.vector_store import upload_file_to_vector_store

    try:
        doc = Document.objects.get(id=document_id)
        doc.status = "processing"
        doc.save(update_fields=["status"])
        logger.info(f"Processing document: {doc.title}")

        file_path = doc.file.path

        # Remove old OpenAI file if re-processing
        if doc.openai_file_id:
            from documents.services.vector_store import remove_file_from_vector_store
            remove_file_from_vector_store(doc.openai_file_id)

        # Upload raw file to OpenAI Vector Store
        openai_file_id = upload_file_to_vector_store(file_path, doc.title)

        doc.openai_file_id = openai_file_id
        doc.status = "completed"
        doc.save(update_fields=["openai_file_id", "status"])
        logger.info(f"Document '{doc.title}' uploaded to OpenAI: {openai_file_id}")

    except Exception as exc:
        logger.exception(f"Error processing document {document_id}")
        try:
            doc = Document.objects.get(id=document_id)
            doc.status = "failed"
            doc.save(update_fields=["status"])
        except Document.DoesNotExist:
            pass
        raise self.retry(exc=exc, countdown=60)


@shared_task
def sync_drive_folder():
    """Periodic task: sync documents from Google Drive folder."""
    from documents.services.drive_sync import sync_folder

    result = sync_folder()
    logger.info(f"Drive sync complete: {result}")
    return result
