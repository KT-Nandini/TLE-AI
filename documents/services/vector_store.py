"""OpenAI Vector Store service — upload/remove files for Responses API file_search."""
import logging

from django.conf import settings
from core.openai_client import get_openai_client

logger = logging.getLogger(__name__)


def upload_file_to_vector_store(file_path: str, filename: str) -> str:
    """Upload a file to OpenAI and attach it to the Vector Store.

    Args:
        file_path: Local path to the file.
        filename: Display name for the file.

    Returns:
        The OpenAI file ID (e.g. "file-abc123").
    """
    client = get_openai_client()
    vector_store_id = settings.OPENAI_VECTOR_STORE_ID

    # Step 1: Upload file to OpenAI Files API
    with open(file_path, "rb") as f:
        openai_file = client.files.create(file=f, purpose="assistants")
    logger.info(f"Uploaded file '{filename}' to OpenAI: {openai_file.id}")

    # Step 2: Attach file to the Vector Store
    client.vector_stores.files.create(
        vector_store_id=vector_store_id,
        file_id=openai_file.id,
    )
    logger.info(f"Attached file {openai_file.id} to vector store {vector_store_id}")

    return openai_file.id


def remove_file_from_vector_store(openai_file_id: str) -> None:
    """Detach a file from the Vector Store and delete it from OpenAI.

    Args:
        openai_file_id: The OpenAI file ID to remove.
    """
    if not openai_file_id:
        return

    client = get_openai_client()
    vector_store_id = settings.OPENAI_VECTOR_STORE_ID

    try:
        # Detach from vector store
        client.vector_stores.files.delete(
            vector_store_id=vector_store_id,
            file_id=openai_file_id,
        )
        logger.info(f"Detached file {openai_file_id} from vector store")
    except Exception:
        logger.warning(f"Could not detach file {openai_file_id} from vector store", exc_info=True)

    try:
        # Delete the file from OpenAI
        client.files.delete(openai_file_id)
        logger.info(f"Deleted file {openai_file_id} from OpenAI")
    except Exception:
        logger.warning(f"Could not delete file {openai_file_id} from OpenAI", exc_info=True)


def get_vector_store_status() -> dict:
    """Return file counts and status for the configured Vector Store."""
    client = get_openai_client()
    vector_store_id = settings.OPENAI_VECTOR_STORE_ID

    if not vector_store_id:
        return {"configured": False}

    try:
        vs = client.vector_stores.retrieve(vector_store_id)
        return {
            "configured": True,
            "id": vs.id,
            "name": vs.name,
            "file_counts": {
                "completed": vs.file_counts.completed,
                "in_progress": vs.file_counts.in_progress,
                "failed": vs.file_counts.failed,
                "total": vs.file_counts.total,
            },
            "status": vs.status,
        }
    except Exception:
        logger.exception("Failed to retrieve vector store status")
        return {"configured": True, "error": "Could not retrieve status"}
