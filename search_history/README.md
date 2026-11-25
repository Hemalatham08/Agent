# iFive ERP Conversation History Module

A standalone, ChatGPT-style conversation history system for the iFive ERP Agent. This module provides persistent storage and management of chat conversations with full structured response preservation.

## Features

- **Persistent Conversations**: SQLite-based storage with automatic schema management
- **Structured Response Preservation**: Complete assistant payloads (tables, charts, SQL, tools, metadata) stored as JSON
- **Automatic Title Generation**: Conversation titles derived from first user question (≈40 chars)
- **Multi-turn Support**: Continue existing conversations by session ID
- **Ownership Model**: Optional `user_id` for conversation isolation
- **Search**: Full-text search across titles and message payloads
- **Pagination**: Configurable limit/offset for session listing
- **Cascade Deletion**: Deleting a session removes all its messages
- **Isolated Design**: Zero dependencies on ERP backend, Gemini, or frontend

## Folder Structure

```
search_history/
├── __init__.py          # Package exports
├── database.py          # SQLite connection & schema initialization
├── errors.py            # Domain exceptions
├── validation.py        # Input validation & serialization
├── models.py            # Pydantic request/response models
├── repository.py        # Data access layer (parameterized SQL)
├── service.py           # Business logic & answer generator protocol
├── router.py            # FastAPI router with 6 endpoints
├── app.py               # Standalone FastAPI application factory
├── history.db           # Default SQLite database
├── README.md            # This file
└── tests/               # 122 automated tests
    ├── conftest.py
    ├── test_database.py
    ├── test_repository.py
    ├── test_service.py
    ├── test_router.py
    └── test_integration.py
```

## Database Schema

```sql
-- Conversations
CREATE TABLE chat_sessions (
    id TEXT PRIMARY KEY,              -- UUID
    title TEXT NOT NULL,              -- Auto-generated from first question
    created_at TEXT NOT NULL,         -- ISO 8601 UTC
    updated_at TEXT NOT NULL,         -- ISO 8601 UTC
    user_id TEXT                      -- Optional owner (NULL = anonymous)
);

-- Messages
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,         -- FK to chat_sessions.id
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    payload_json TEXT NOT NULL,       -- Full JSON payload
    created_at TEXT NOT NULL,         -- ISO 8601 UTC
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_chat_sessions_updated ON chat_sessions(updated_at);
CREATE INDEX idx_chat_messages_session ON chat_messages(session_id, id);
CREATE INDEX idx_chat_sessions_user ON chat_sessions(user_id);
```

### Payload Structure

**User Message Payload:**
```json
{"text": "User's question"}
```

**Assistant Message Payload (extensible):**
```json
{
  "summary": "Brief summary",
  "answer": "Full answer text",
  "table": {"columns": [...], "rows": [...]},
  "charts": [{"type": "bar", "data": [...]}],
  "chart": {...},
  "sql": "SELECT ...",
  "tools": [{"tool_name": "...", "status": "success", ...}],
  "metadata": {"generator": "mock", "structured": true, ...}
}
```
*Unknown fields are preserved via Pydantic `extra="allow"`.*

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   FastAPI   │────▶│  Conversation │────▶│  Conversation   │
│   Router    │     │   Service    │     │   Repository    │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │                       │
                    ┌──────┴──────┐         ┌──────┴──────┐
                    │ AnswerGenerator│    │  SQLite DB    │
                    │  (Protocol)   │    │  (history.db) │
                    └───────────────┘    └───────────────┘
                           ▲
                    ┌──────┴──────┐
                    │ MockAnswer- │
                    │  Generator  │
                    └─────────────┘
```

- **Router**: HTTP layer, request validation, error mapping
- **Service**: Conversation lifecycle, title generation, ownership checks
- **Repository**: Parameterized SQL, transactions, cascade deletes
- **AnswerGenerator**: Protocol for LLM integration (mock provided)

## API Endpoints

Base path: `/chat`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/` | Create or continue a conversation |
| `GET` | `/sessions` | List conversations (newest first) |
| `GET` | `/search` | Search conversations |
| `GET` | `/sessions/{session_id}` | Get conversation with messages |
| `DELETE` | `/sessions/{session_id}` | Delete a conversation |
| `DELETE` | `/sessions` | Clear all conversations for a user |

### POST `/chat`

Create a new conversation or continue an existing one.

**Request:**
```json
{
  "message": "What is the stock level for SKU-123?",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user123"
}
```
- `message` (required): User question, non-blank
- `session_id` (optional): UUID to continue existing conversation
- `user_id` (optional): Owner identifier (max 128 chars)

**Response (200):**
```json
{
  "session": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "What is the stock level for SKU-123?",
    "user_id": "user123",
    "created_at": "2024-01-15T10:30:00.000000+00:00",
    "updated_at": "2024-01-15T10:30:00.000000+00:00",
    "message_count": 2
  },
  "user_message": {
    "id": 1,
    "role": "user",
    "payload": {"text": "What is the stock level for SKU-123?"},
    "created_at": "2024-01-15T10:30:00.000000+00:00"
  },
  "assistant_message": {
    "id": 2,
    "role": "assistant",
    "payload": {
      "summary": "Stock level for SKU-123",
      "answer": "Current stock: 42 units",
      "table": {"columns": ["SKU", "Stock"], "rows": [["SKU-123", 42]]},
      "charts": [],
      "sql": "SELECT stock FROM products WHERE sku = 'SKU-123'",
      "tools": [{"tool_name": "stock_query", "status": "success"}],
      "metadata": {"generator": "mock", "structured": true, "history_messages": 0}
    },
    "created_at": "2024-01-15T10:30:00.000000+00:00"
  }
}
```

### GET `/chat/sessions`

List conversations, newest first.

**Query Parameters:**
- `user_id` (optional): Filter by owner
- `limit` (1-200, default 50)
- `offset` (≥0, default 0)

**Response (200):**
```json
[
  {
    "id": "...",
    "title": "Second question",
    "user_id": "user1",
    "created_at": "...",
    "updated_at": "...",
    "message_count": 4
  },
  {
    "id": "...",
    "title": "First question",
    "user_id": "user1",
    "created_at": "...",
    "updated_at": "...",
    "message_count": 2
  }
]
```

### GET `/chat/search`

Search conversation titles and message payloads.

**Query Parameters:**
- `q` (required, 1-200 chars): Search query
- `user_id` (optional): Filter by owner
- `limit` (1-200, default 50)
- `offset` (≥0, default 0)

**Response (200):** Same as `/sessions`

### GET `/chat/sessions/{session_id}`

Retrieve a conversation with all messages.

**Path Parameter:**
- `session_id` (UUID): Conversation ID

**Query Parameter:**
- `user_id` (optional): Owner for access control

**Response (200):**
```json
{
  "id": "...",
  "title": "What is the stock level?",
  "user_id": "user1",
  "created_at": "...",
  "updated_at": "...",
  "message_count": 4,
  "messages": [
    {"id": 1, "role": "user", "payload": {"text": "..."}, "created_at": "..."},
    {"id": 2, "role": "assistant", "payload": {...}, "created_at": "..."},
    {"id": 3, "role": "user", "payload": {"text": "..."}, "created_at": "..."},
    {"id": 4, "role": "assistant", "payload": {...}, "created_at": "..."}
  ]
}
```

### DELETE `/chat/sessions/{session_id}`

Delete a conversation and all its messages.

**Path Parameter:**
- `session_id` (UUID)

**Query Parameter:**
- `user_id` (optional): Owner for access control

**Response (200):**
```json
{"deleted": true, "session_id": "..."}
```

### DELETE `/chat/sessions`

Clear all conversations for a user.

**Query Parameter:**
- `user_id` (required, 1-128 chars)

**Response (200):**
```json
{"deleted_count": 5, "user_id": "user1"}
```

## Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Invalid input (blank message, bad query) |
| 404 | Session not found or access denied |
| 422 | Invalid UUID, validation error |
| 502 | Answer generator failure |
| 503 | Service not configured |
| 500 | Internal error |

## Running the Standalone Application

### Option 1: Python module
```bash
cd D:\Agent\Agent
python -m search_history.app
```

### Option 2: Uvicorn
```bash
cd D:\Agent\Agent
uvicorn search_history.app:app --port 8010 --reload
```

The API will be available at `http://127.0.0.1:8010`

### Using a Custom Database Path
```bash
uvicorn search_history.app:app --port 8010 --env-file .env
```
Or programmatically:
```python
from search_history.app import create_app
app = create_app(db_path="/custom/path/history.db")
```

## Running Tests

```bash
cd D:\Agent\Agent
python -m pytest search_history/tests -v -p no:cacheprovider
```

**Test Coverage (122 tests):**
- Database initialization & idempotency
- Conversation creation, title generation, truncation
- Message saving (user & assistant)
- Multi-turn conversations
- Session listing, ordering, pagination
- Conversation retrieval with full message history
- Structured JSON preservation (tables, charts, SQL, tools, metadata)
- Conversation deletion & cascade
- Missing session handling (404)
- Invalid UUID handling (422)
- Blank message rejection (422)
- Invalid role rejection
- Invalid JSON payload rejection
- Search (titles & message content, wildcards escaped)
- Pagination (limit/offset)
- Database isolation (temp DBs, ERP DB untouched)
- API endpoint behavior (all 6 endpoints)
- Mock answer generator behavior
- Generator failure → 502
- SQL payloads never executed

## Mock Answer Generator

The `MockAnswerGenerator` provides deterministic structured responses for testing and standalone use:

```python
from search_history.service import MockAnswerGenerator

gen = MockAnswerGenerator()
payload = gen.generate(question="Stock for SKU-123", history=[])
```

**Output:**
```json
{
  "summary": "Stock for SKU-123",
  "answer": "Mock response to: Stock for SKU-123",
  "table": {"columns": ["Field", "Value"], "rows": [["Question", "Stock for SKU-123"]]},
  "charts": [],
  "sql": "SELECT 1 AS mock_value",
  "tools": [{"tool_name": "mock_answer", "status": "success", "arguments": {}}],
  "metadata": {"generator": "mock", "structured": true, "history_messages": 0}
}
```

## Current Limitations

1. **No Authentication**: `user_id` is client-supplied, not authenticated. Real isolation requires integration with an auth system.
2. **No Real LLM**: Uses `MockAnswerGenerator` by default. Production requires implementing `AnswerGenerator` protocol with the ERP agent.
3. **Single Database File**: SQLite limits concurrent writes. For high concurrency, consider PostgreSQL.
4. **No Message Editing**: Messages are append-only.
5. **No Streaming**: Responses are returned after full generation.
6. **Search is Basic**: Uses SQLite `LIKE` with escaping. No full-text search index.

## Future ERP Integration Requirements

To connect the real iFive ERP Agent:

1. **Implement `AnswerGenerator` Protocol:**
```python
from search_history.service import AnswerGenerator

class ErpAgentGenerator(AnswerGenerator):
    def generate(self, *, question: str, history: list[dict]) -> dict:
        # Call ERP agent service
        result = erp_agent.answer_question(question, session_id=...)
        return {
            "summary": result.summary,
            "answer": result.answer,
            "table": result.table,
            "charts": result.charts,
            "sql": result.sql,
            "tools": result.tool_calls,
            "metadata": {"model": result.model, ...}
        }
```

2. **Wire into FastAPI App:**
```python
from search_history.app import create_app
from my_integration import ErpAgentGenerator

app = create_app(answer_generator=ErpAgentGenerator())
```

3. **Authentication Middleware:** Add middleware to extract authenticated user ID and inject as `user_id` on all requests.

4. **Database Migration:** If using PostgreSQL, update `database.py` connection logic and ensure schema compatibility.

5. **Monitoring:** Add logging/metrics for conversation volume, errors, latency.

## Security Considerations

- **Parameterized Queries**: All SQL uses `?` placeholders
- **Input Validation**: Pydantic models + custom validators
- **Foreign Key Enforcement**: `PRAGMA foreign_keys = ON` on every connection
- **Cascade Deletes**: `ON DELETE CASCADE` on messages
- **Ownership Checks**: Strict `user_id` matching when provided
- **No SQL Execution**: Stored SQL payloads are never executed
- **No Secrets in DB**: Only conversation data stored
- **Limitation**: `user_id` is not authenticated — requires external auth integration

## License

Internal iFive ERP module. Not for external distribution.