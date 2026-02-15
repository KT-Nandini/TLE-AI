"""Management command to create OpenAI Vector Store and upload existing documents.

Uses the Responses API with file_search (not the deprecated Assistants API).

Usage:
    python manage.py setup_assistant                  # Create Vector Store, print ID
    python manage.py setup_assistant --upload-existing # Also upload all completed documents
"""
import logging

from django.core.management.base import BaseCommand
from django.conf import settings

from core.openai_client import get_openai_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create OpenAI Vector Store for TLE AI file_search"

    def add_arguments(self, parser):
        parser.add_argument(
            "--upload-existing",
            action="store_true",
            help="Upload all completed documents to the Vector Store",
        )

    def handle(self, *args, **options):
        client = get_openai_client()
        vector_store_id = settings.OPENAI_VECTOR_STORE_ID

        # --- Create Vector Store if not configured ---
        if not vector_store_id:
            self.stdout.write("Creating OpenAI Vector Store...")
            vs = client.vector_stores.create(name="TLE AI Legal Knowledge Base")
            vector_store_id = vs.id
            self.stdout.write(self.style.SUCCESS(f"Vector Store created: {vector_store_id}"))
            self.stdout.write(f'  Add to .env: OPENAI_VECTOR_STORE_ID={vector_store_id}')
        else:
            self.stdout.write(f"Using existing Vector Store: {vector_store_id}")

        # --- Upload existing documents if requested ---
        if options["upload_existing"]:
            self._upload_existing_documents(client, vector_store_id)

        self.stdout.write(self.style.SUCCESS("\nSetup complete."))
        self.stdout.write(f"  OPENAI_VECTOR_STORE_ID={vector_store_id}")

    def _upload_existing_documents(self, client, vector_store_id):
        """Upload all completed documents that don't have an openai_file_id yet."""
        from documents.models import Document

        docs = Document.objects.filter(status="completed", openai_file_id="")
        total = docs.count()
        if total == 0:
            self.stdout.write("No documents to upload (all already uploaded or none completed).")
            return

        self.stdout.write(f"Uploading {total} documents to Vector Store...")
        uploaded = 0
        failed = 0

        for doc in docs:
            try:
                file_path = doc.file.path
                with open(file_path, "rb") as f:
                    openai_file = client.files.create(file=f, purpose="assistants")

                client.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=openai_file.id,
                )

                doc.openai_file_id = openai_file.id
                doc.save(update_fields=["openai_file_id"])
                uploaded += 1
                self.stdout.write(f"  [{uploaded}/{total}] {doc.title} -> {openai_file.id}")
            except Exception as e:
                failed += 1
                self.stderr.write(f"  FAILED: {doc.title} - {e}")

        self.stdout.write(self.style.SUCCESS(f"Upload complete: {uploaded} uploaded, {failed} failed."))
