# TLE AI - Texas Legal Expert - Project Summary

## Overview
TLE AI ("Thomas") is a Texas-centric legal information chatbot. Users ask legal questions and get structured, source-backed answers using a RAG (Retrieval-Augmented Generation) pipeline powered by OpenAI.

**Live URL:** https://legal.kuware.ai

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend Framework | Django 5.x (Python 3.12) |
| ASGI Server | Daphne |
| Task Queue | Celery + Redis |
| Database | PostgreSQL |
| AI / LLM | OpenAI API (gpt-4o-mini) |
| Document Search | OpenAI Vector Store + file_search (Responses API) |
| File Storage | Google Drive (source) + Local media/ (copy) |
| Frontend | HTML + Tailwind CSS + HTMX + Alpine.js |
| Streaming | Server-Sent Events (SSE) |
| Markdown Rendering | marked.js (client-side) |
| Authentication | django-allauth (Google OAuth) |
| Web Server | Nginx (reverse proxy) |
| Process Manager | systemd |

---

## Architecture Diagram

```
                    ┌──────────────┐
                    │  Google Drive │
                    │  (5,134 docs) │
                    └──────┬───────┘
                           │ Celery Beat (every 60 min)
                           ▼
                    ┌──────────────┐        ┌─────────────────────┐
                    │  Django App  │───────▶│  OpenAI Vector Store │
                    │  (Daphne)    │ upload │  (file_search index) │
                    └──────┬───────┘        └──────────┬──────────┘
                           │                           │
                    User sends question                │ search results
                           │                           │
                           ▼                           ▼
                    ┌──────────────────────────────────────┐
                    │       OpenAI Responses API            │
                    │  (gpt-4o-mini + file_search tool)     │
                    │                                       │
                    │  Input: system prompt + history        │
                    │  Tool: file_search → Vector Store      │
                    │  Output: streaming response + citations│
                    └──────────────────────────────────────┘
```

---

## Complete Step-by-Step Flow

### STEP 1: Document Ingestion (Google Drive → OpenAI Vector Store)

**Technology:** Google Drive API + OpenAI Files API + OpenAI Vector Store API

1. **Celery Beat** triggers `sync_drive_folder` task every 60 minutes.
2. **Google Drive API** (via service account) recursively scans the configured folder and all subfolders (58 folders total).
3. For each file found:
   - If new: downloads file to local `media/documents/` folder, creates a `Document` record in PostgreSQL.
   - If modified (MD5 changed): re-downloads and re-processes.
   - If deleted from Drive: removes from OpenAI Vector Store and deletes locally.
4. **Celery task `process_document`** runs for each new/modified document:
   - Uploads the raw file (PDF, DOCX, TXT, etc.) to **OpenAI Files API** (`purpose="assistants"`).
   - Attaches the file to the **OpenAI Vector Store** (`vs_698c7f64d2d08191a8b5dae6e364015e`).
   - OpenAI automatically: chunks the document, generates embeddings, and indexes it for search.
   - Saves the `openai_file_id` on the Document record.
5. Document status moves: `pending` → `processing` → `completed`.

**Key files:**
- `documents/services/drive_sync.py` — Google Drive sync with subfolder support
- `documents/tasks.py` — Celery task to upload file to OpenAI
- `documents/services/vector_store.py` — OpenAI Vector Store upload/remove/status

**What OpenAI handles:** Chunking, embedding, vector storage, indexing. We do NOT chunk or embed locally.

---

### STEP 2: User Sends a Message

**Technology:** Django + HTMX + PostgreSQL

1. User types a question in the chat input and clicks Send.
2. **HTMX** sends a POST request to `/chat/<conversation_id>/send/`.
3. Django saves the user message as a `Message` record (role="user") in PostgreSQL.
4. Returns an HTML partial (user bubble) which HTMX injects into the chat.
5. JavaScript opens an **SSE (EventSource)** connection to `/chat/<conversation_id>/stream/`.

**Key files:**
- `chat/views.py` — `send_message` view
- `templates/chat/detail.html` — Chat UI + JavaScript
- `templates/chat/partials/user_message.html` — User message HTML partial

---

### STEP 3: Build Conversation History

**Technology:** Django ORM + PostgreSQL

1. Load all messages for this conversation from the database.
2. Take the **last 10 messages** (user + assistant) as the conversation history.
3. Check if a **conversation summary** exists (for conversations with 20+ messages).
4. If a summary exists, it will be appended to the system prompt to provide older context.

**Key files:**
- `chat/views.py` — `stream_response` view (lines 78-86)

---

### STEP 4: Call OpenAI Responses API with file_search

**Technology:** OpenAI Responses API + OpenAI Vector Store (file_search tool)

1. Build the API request:
   - **`instructions`**: The full system prompt (Thomas persona, KSR rules, safety limits, output format). If a conversation summary exists, it's appended here.
   - **`input`**: The last 10 messages as a list of `{role, content}` dicts.
   - **`tools`**: `[{type: "file_search", vector_store_ids: ["vs_..."], max_num_results: 10}]`
   - **`model`**: `gpt-4o-mini`
   - **`stream`**: `true`

2. Send to `client.responses.create()` with streaming enabled.

3. **OpenAI decides whether to search the Vector Store:**
   - The model reads the user's question and the system prompt (which mandates Knowledge Set Routing).
   - If the question is substantive/legal, the model triggers `file_search`.
   - OpenAI internally: converts the query to an embedding, searches the Vector Store (5,134 documents), retrieves the top 10 most relevant chunks.
   - The model reads those chunks and generates a response anchored to them.
   - If no relevant content is found, the model states "SOURCES CONSULTED (KNOWLEDGE SET): None located."

4. **Streaming response:**
   - Tokens arrive as `response.output_text.delta` events.
   - File citation annotations arrive as `response.output_text.annotation.added` events.

**Key files:**
- `chat/services/assistant.py` — `stream_response()` function
- `chat/services/llm.py` — `SYSTEM_PROMPT` (Thomas persona)
- `core/openai_client.py` — Shared OpenAI client singleton

**What OpenAI handles:** Query embedding, vector search, chunk ranking, response generation, citation tracking. We only send the request and stream the response.

---

### STEP 5: Stream Response to Browser

**Technology:** SSE (Server-Sent Events) + JavaScript + marked.js

1. Each token from OpenAI is forwarded as an SSE event: `data: {"token": "..."}\n\n`
2. **JavaScript** accumulates tokens in a raw text variable.
3. Every **80ms** (debounced), `marked.parse()` converts the accumulated markdown to HTML and renders it in the streaming bubble.
4. User sees the response appearing progressively with live markdown formatting (headings, bold, bullets, etc.).
5. Before the response starts, a **typing indicator** (three bouncing dots) is shown.
6. When streaming completes:
   - Citations are sent as: `data: {"citations": [...]}\n\n`
   - Final signal: `data: [DONE]\n\n`
   - JavaScript renders the final message with citations bar into the chat.
   - Streaming area is hidden.

**Key files:**
- `chat/views.py` — SSE event_stream generator
- `templates/chat/detail.html` — JavaScript SSE handler + marked.js rendering

---

### STEP 6: Save Response & Post-Processing

**Technology:** Django ORM + Celery + OpenAI API

1. **Save assistant message** to PostgreSQL with:
   - `role`: "assistant"
   - `content`: full response text
   - `citations`: JSON list of `{file_id, document_title}` dicts

2. **Log usage** in `UsageLog` table (user, query, response token count).

3. **Background tasks (Celery):**
   - **Title generation** (after first exchange): Sends the first user question + assistant response to OpenAI and asks for a 5-8 word title. Saves to `Conversation.title`.
   - **Conversation summarization** (after 20+ messages): Sends older messages to OpenAI and asks for a concise summary. Saves to `ConversationSummary`. This summary is used in Step 3 for future messages.

**Key files:**
- `chat/views.py` — Save message + trigger tasks
- `chat/tasks.py` — `generate_conversation_title`, `summarize_conversation`

---

### STEP 7: Citation Display

**Technology:** Django templates + JavaScript + CSS

1. For **saved messages** (page reload): Django template renders citations from `msg.citations` JSON field.
2. For **streaming messages** (real-time): JavaScript receives citations via SSE and builds the HTML.
3. Citations appear as small pill-shaped tags below the response: `Sources: Family Law | FA.153 | FAMILY CODE`
4. Citation resolution: `file_id` from OpenAI → lookup `Document.openai_file_id` → get `Document.title`.

**Key files:**
- `chat/services/assistant.py` — `resolve_file_citations()`
- `templates/chat/detail.html` — Citation HTML rendering
- `static/css/styles.css` — `.citations-bar`, `.citation-tag` styles

---

## System Prompt (Thomas Persona)

**Location:** `chat/services/llm.py` → `SYSTEM_PROMPT`

The system prompt defines:
- **Identity**: "Thomas", the Texas Legal Expert
- **Safety rules**: No attorney-client relationship, no illegal assistance, no revealing internals
- **Mode gating**: PUBLIC MODE (educational) vs ROSS MODE (attorney work product, requires handshake)
- **Knowledge Set Routing (KSR-1 to KSR-5)**: Mandatory steps to classify, select, retrieve, and anchor responses to the Knowledge Set
- **Authority hierarchy**: System modules > Controlling law > Statute text > Practice binders > Dictionaries > Training manuals > General knowledge
- **Citation discipline**: Never fabricate, label unverified citations
- **Output structure**: Mode tag, summary, facts, timeline, IRAC analysis, checklist, legal terms, sources

---

## Database Models

| Model | Purpose |
|-------|---------|
| `Document` | Uploaded legal document (title, file, authority, domain, status, openai_file_id) |
| `DriveFile` | Google Drive sync tracking (drive_file_id, md5, linked Document) |
| `Conversation` | Chat conversation (user, title, thread_id) |
| `Message` | Individual message (role, content, citations JSON) |
| `ConversationSummary` | Compressed summary of older messages |
| `UsageLog` | Query logging for admin analytics |
| `CustomUser` | Extended Django user model |

---

## Migration History (Old → New)

### What was removed (Old RAG Pipeline):
- **Local chunking** (`documents/ingestion/chunker.py`) — Deleted
- **Local embedding** (`documents/ingestion/embedder.py`) — Deleted
- **Text extractors** (`documents/ingestion/extractors.py`) — Deleted (entire `ingestion/` directory removed)
- **pgvector storage** (`DocumentChunk` model with `VectorField`) — Model deleted, table dropped, `pgvector` dependency removed
- **Local retrieval** (`chat/services/retrieval.py`) — Deleted
- **Summarizer module** (`chat/services/summarizer.py`) — Inlined into `chat/tasks.py`
- **chunk_count** field on `Document` model — Removed
- **thread_id** field on `Conversation` model — Removed (was for Assistants API)
- **tiktoken** dependency — Removed (was for local tokenization)
- **retrieved_chunks** M2M field on `Message` model — Removed

### What replaced it (New Pipeline):
- **OpenAI Vector Store** handles chunking, embedding, storage, and search
- **OpenAI Responses API** with `file_search` tool handles retrieval and generation in one call
- Raw files uploaded directly to OpenAI — no local processing needed

### Why we switched:
- Originally planned Assistants API → switched to **Responses API** because Assistants API is being deprecated (August 2026)
- Responses API is stateless (no threads/assistants needed), simpler, and future-proof

---

## Key Configuration

| Setting | Value | Source |
|---------|-------|--------|
| `OPENAI_API_KEY` | sk-... | .env |
| `OPENAI_CHAT_MODEL` | gpt-4o-mini | settings.py |
| `OPENAI_VECTOR_STORE_ID` | vs_698c7f64d2d08191a8b5dae6e364015e | .env |
| `GOOGLE_DRIVE_FOLDER_ID` | (configured) | .env |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | /srv/apps/legal/credentials/... | .env |
| `GOOGLE_DRIVE_SYNC_INTERVAL_MINUTES` | 60 | .env |

---

## Systemd Services

| Service | File | Purpose |
|---------|------|---------|
| `legal.service` | `/etc/systemd/system/legal.service` | Daphne ASGI web server (port 8003) |
| `legal-celery.service` | `/etc/systemd/system/legal-celery.service` | Celery worker (2 concurrent tasks) |
| `legal-celery-beat.service` | `/etc/systemd/system/legal-celery-beat.service` | Celery Beat scheduler (Drive sync every 60 min) |

All 3 services are enabled on boot and auto-restart on failure.

---

## Current Stats

- **Total documents**: 5,134
- **Vector Store status**: completed (5,134 indexed)
- **Model**: gpt-4o-mini ($0.15/1M input, $0.60/1M output)
- **Drive folders scanned**: 58 (recursive)
- **Failed files**: 0

---

## UI Features

- Sidebar with conversation history
- Typing indicator (three bouncing dots) before response
- Real-time markdown streaming with progressive rendering (marked.js, 80ms debounce)
- Source citations displayed as pill tags below each response
- Error toast notification on streaming failure
- Mobile responsive (hamburger menu, overlay sidebar)
- Sign out confirmation modal
- Admin panel (documents, users, conversations, usage, Drive sync)
- Masquerade mode (admin can view as any user)

---

## Requirements

```
Django==6.0.2
psycopg[binary]==3.2.6
daphne==4.1.2
django-allauth[socialaccount]==65.4.1
openai==1.68.2
PyMuPDF==1.25.3
python-docx==1.1.2
celery==5.4.0
redis==5.2.1
google-api-python-client==2.159.0
google-auth==2.37.0
python-dotenv==1.0.1
```
