"""OpenAI Responses API service — file_search with Vector Store, streaming, citation resolution.

Uses the Responses API (not the deprecated Assistants API).
No threads or assistant objects — we manage conversation history ourselves.
"""
import json
import logging
import os
from datetime import datetime

from django.conf import settings
from core.openai_client import get_openai_client
from chat.services.llm import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Raw response log file
RAW_LOG_DIR = os.path.join(settings.BASE_DIR, "logs")
RAW_LOG_FILE = os.path.join(RAW_LOG_DIR, "raw_responses.log")


def _log_raw(data: str):
    """Append a line to the raw response log file."""
    os.makedirs(RAW_LOG_DIR, exist_ok=True)
    with open(RAW_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(data + "\n")


def stream_response(conversation_history: list[dict], summary: str = ""):
    """Stream a response using the Responses API with file_search.

    Args:
        conversation_history: List of {"role": "user"|"assistant", "content": "..."} dicts.
        summary: Optional conversation summary for long conversations.

    Yields dicts:
        {"token": "..."} for each text chunk
        {"citations": [...]} at the end if file citations were found
    """
    client = get_openai_client()
    vector_store_id = settings.OPENAI_VECTOR_STORE_ID

    # Build input messages
    input_messages = []
    for msg in conversation_history:
        input_messages.append({"role": msg["role"], "content": msg["content"]})

    # Build instructions with summary context
    instructions = SYSTEM_PROMPT
    if summary:
        instructions += f"\n\nCONVERSATION SUMMARY (prior context):\n{summary}"

    # Configure tools
    tools = []
    if vector_store_id:
        tools.append({
            "type": "file_search",
            "vector_store_ids": [vector_store_id],
            "max_num_results": 5,
        })

    # Log request details
    timestamp = datetime.now().isoformat()
    _log_raw(f"\n{'='*80}")
    _log_raw(f"[{timestamp}] NEW REQUEST")
    _log_raw(f"{'='*80}")
    _log_raw(f"Model: {settings.OPENAI_CHAT_MODEL}")
    _log_raw(f"Vector Store: {vector_store_id}")
    _log_raw(f"History ({len(input_messages)} messages):")
    for msg in input_messages:
        _log_raw(f"  [{msg['role']}]: {msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}")
    _log_raw(f"Summary: {summary[:200] if summary else '(none)'}")
    _log_raw(f"{'-'*80}")

    # Stream response
    stream = client.responses.create(
        model=settings.OPENAI_CHAT_MODEL,
        instructions=instructions,
        input=input_messages,
        tools=tools,
        temperature=0.3,
        stream=True,
    )

    annotations_collected = []
    full_text = ""
    all_events = []
    usage_data = {"input_tokens": 0, "output_tokens": 0}

    for event in stream:
        # Log every event type
        all_events.append(event.type)

        if event.type == "response.output_text.delta":
            full_text += event.delta
            yield {"token": event.delta}
        elif event.type == "response.output_text.annotation.added":
            # Log full annotation details
            annotation_data = {
                "type": getattr(event.annotation, "type", None),
                "file_id": getattr(event.annotation, "file_id", None),
                "filename": getattr(event.annotation, "filename", None),
                "index": getattr(event.annotation, "index", None),
            }
            _log_raw(f"  ANNOTATION: {json.dumps(annotation_data)}")
            annotations_collected.append(event.annotation)
        elif event.type == "response.completed":
            # Extract token usage from completed response
            response = event.response
            if hasattr(response, "usage") and response.usage:
                usage_data["input_tokens"] = getattr(response.usage, "input_tokens", 0)
                usage_data["output_tokens"] = getattr(response.usage, "output_tokens", 0)
                _log_raw(f"  USAGE: input_tokens={usage_data['input_tokens']}, output_tokens={usage_data['output_tokens']}")

    # Log full response text
    _log_raw(f"{'-'*80}")
    _log_raw(f"FULL RESPONSE TEXT:")
    _log_raw(full_text)
    _log_raw(f"{'-'*80}")
    _log_raw(f"ALL EVENT TYPES: {all_events}")
    _log_raw(f"TOTAL ANNOTATIONS: {len(annotations_collected)}")
    _log_raw(f"TOKEN USAGE: {json.dumps(usage_data)}")

    # Resolve citations after streaming completes
    if annotations_collected:
        citations = resolve_file_citations(annotations_collected)
        _log_raw(f"RESOLVED CITATIONS: {json.dumps(citations, indent=2)}")
        if citations:
            yield {"citations": citations}

    # Yield usage data for the view to save
    yield {"usage": usage_data}

    _log_raw(f"{'='*80}\n")


def resolve_file_citations(annotations) -> list[dict]:
    """Map file_citation annotations to document titles.

    Returns a list of citation dicts:
        [{"file_id": "file-abc", "document_title": "...", "filename": "..."}]
    """
    from documents.models import Document

    citations = []
    seen_file_ids = set()

    for annotation in annotations:
        # Responses API annotations have type="file_citation" and file_id, filename attributes
        if not hasattr(annotation, "file_id"):
            continue

        file_id = annotation.file_id
        if not file_id or file_id in seen_file_ids:
            continue
        seen_file_ids.add(file_id)

        # Look up the Document by openai_file_id
        try:
            doc = Document.objects.get(openai_file_id=file_id)
            document_title = doc.title
        except Document.DoesNotExist:
            document_title = getattr(annotation, "filename", f"File {file_id}")

        citation_entry = {
            "file_id": file_id,
            "document_title": document_title,
        }
        if hasattr(annotation, "filename") and annotation.filename:
            citation_entry["filename"] = annotation.filename

        citations.append(citation_entry)

    return citations
