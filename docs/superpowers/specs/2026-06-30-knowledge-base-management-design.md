# Knowledge Base Management Design

## Context

OfferPilot is a local-first job search workbench with a Go/SQLite backend, a React + Ant Design frontend, and an AI chat assistant that can operate on local data through a tool registry. The current assistant already supports read and write tools for applications, schedules, resumes, JD analysis, and interview retrospectives. Write tools are gated by a confirmation flow.

This design adds user-managed personal knowledge bases for study material such as interview prep notes, fundamentals documents, learning notes, and reusable explanations. The first version should be useful from both the main UI and the AI chat assistant without adding external vector database or embedding dependencies.

## Goals

- Let users create and manage multiple personal knowledge bases in the web UI.
- Let users create, edit, delete, search, and import Markdown/plain-text documents.
- Let the AI assistant retrieve relevant knowledge snippets by default when useful.
- Let users explicitly ask the assistant to use only a knowledge base, use a specific document, or avoid knowledge bases.
- Let the assistant create, update, and delete knowledge content through the existing write-confirmation flow.
- Keep the first implementation local-first, SQLite-backed, and aligned with existing project patterns.

## Non-Goals

- No PDF, DOCX, image, or web-page import in this iteration.
- No embedding model or vector database dependency in this iteration.
- No spaced repetition, flashcards, mastery tracking, or quiz workflow in this iteration.
- No rich-text editor. Documents are stored as Markdown/plain text.

## Product Scope

The main app gains a `Knowledge` view alongside the existing board, calendar, and review views. Users can:

- Create, rename, and delete knowledge bases such as `Java interview prep`, `Go learning notes`, or `Project interview material`.
- Create documents inside a selected knowledge base.
- Edit document title, body, and tags.
- Import `.md` and `.txt` files into a selected knowledge base.
- Search titles, tags, and document content.
- Preview and edit stored documents.

The AI assistant remains in the current drawer entry point. It gains knowledge tools and retrieval rules, but keeps the same confirmation experience for writes.

## Frontend Design

Add these frontend modules:

- `web/src/components/KnowledgeBaseView.tsx`
- `web/src/components/KnowledgeDocumentEditor.tsx`
- `web/src/components/KnowledgeImportModal.tsx`
- `web/src/services/knowledge.ts`
- `web/src/types/knowledge.ts`

`App.tsx` extends `viewMode` with `knowledge` and adds a `Knowledge` option to the existing `Segmented` control.

`KnowledgeBaseView` owns the main workflow:

- Left side: knowledge base list, create button, rename/delete actions.
- Right side: selected knowledge base documents, search input, import button, create document button.
- Document cards show title, tags, source, updated time, and a short content preview.
- Empty states guide users to create a knowledge base or import a document.

`KnowledgeDocumentEditor` provides document create/edit. It should follow the existing Ant Design style and interaction habits used by the retrospective management UI: drawer or right-side editor, save toast, delete confirmation, and query invalidation.

`KnowledgeImportModal` accepts `.md` and `.txt` files. The file name becomes the default title; users can adjust the target knowledge base and tags before saving.

## Data Model

Add these SQLite-backed models.

### `knowledge_bases`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `name TEXT NOT NULL`
- `description TEXT DEFAULT ''`
- `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`

### `knowledge_documents`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `knowledge_base_id INTEGER NOT NULL`
- `title TEXT NOT NULL`
- `content TEXT NOT NULL DEFAULT ''`
- `tags TEXT NOT NULL DEFAULT '[]'`
- `source_type TEXT NOT NULL DEFAULT 'manual'`
- `source_name TEXT DEFAULT ''`
- `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- Foreign key: `knowledge_base_id REFERENCES knowledge_bases(id) ON DELETE CASCADE`

### `knowledge_chunks`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `document_id INTEGER NOT NULL`
- `knowledge_base_id INTEGER NOT NULL`
- `chunk_index INTEGER NOT NULL`
- `content TEXT NOT NULL`
- `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- Foreign keys:
  - `document_id REFERENCES knowledge_documents(id) ON DELETE CASCADE`
  - `knowledge_base_id REFERENCES knowledge_bases(id) ON DELETE CASCADE`

Add a SQLite FTS5 virtual table for chunk search, such as `knowledge_chunks_fts`, indexing chunk content and storing enough row metadata to resolve the parent document and knowledge base.

Indexes:

- `idx_knowledge_documents_base ON knowledge_documents(knowledge_base_id)`
- `idx_knowledge_chunks_document ON knowledge_chunks(document_id)`
- `idx_knowledge_chunks_base ON knowledge_chunks(knowledge_base_id)`

## Chunking And Search

On document create/update/import:

1. Save the document row.
2. Delete existing chunks and FTS rows for that document.
3. Split content into chunks.
4. Insert chunks and matching FTS rows.

Initial chunking strategy:

- Prefer paragraph boundaries separated by blank lines.
- Merge very short adjacent paragraphs.
- Split long chunks by character length to keep prompt payloads bounded.
- Preserve chunk order through `chunk_index`.

`SearchKnowledge` returns a limited list of structured snippets:

- `knowledge_base_id`
- `knowledge_base_name`
- `document_id`
- `document_title`
- `chunk_id`
- `snippet`
- `score`

Use FTS rank for ordering where available. Keep default limits small, such as 5 snippets, with a maximum cap to protect chat prompts.

## Backend API

Add `internal/db/knowledge.go` and `internal/api/knowledge.go`, then register routes in `internal/api/router.go`.

Routes:

- `GET /api/knowledge-bases`
- `POST /api/knowledge-bases`
- `PUT /api/knowledge-bases/{id}`
- `DELETE /api/knowledge-bases/{id}`
- `GET /api/knowledge-documents?knowledge_base_id=&q=`
- `POST /api/knowledge-documents`
- `POST /api/knowledge-documents/import`
- `GET /api/knowledge-documents/{id}`
- `PUT /api/knowledge-documents/{id}`
- `DELETE /api/knowledge-documents/{id}`
- `GET /api/knowledge/search?q=&knowledge_base_id=&limit=`

Validation rules:

- Knowledge base `name` is required.
- Document `knowledge_base_id` must point to an existing knowledge base.
- Document `title` is required.
- Import accepts only `.md` and `.txt`.
- Import file size is capped at 1 MB for the first version.
- Search query must be non-empty.

Deletes cascade from knowledge base to documents and chunks. Document update/delete must keep chunks and FTS rows synchronized.

## AI Assistant Design

Add read tools:

- `list_knowledge_bases`
- `list_knowledge_documents`
- `get_knowledge_document`
- `search_knowledge`

Add write tools:

- `create_knowledge_base`
- `update_knowledge_base`
- `delete_knowledge_base`
- `create_knowledge_document`
- `update_knowledge_document`
- `delete_knowledge_document`

Write tools use `Write: true` and provide clear `Describe` text for the confirmation card.

Retrieval behavior:

- Default behavior: when a user asks about concepts, interview prep, study notes, prior documents, summaries, or reusable knowledge, the assistant may call `search_knowledge`.
- If the user says not to use the knowledge base, the assistant should not call knowledge tools.
- If the user asks to answer only from a specific knowledge base or document, the assistant should locate that scope first, then retrieve or read from it.
- `search_knowledge` is the default retrieval entry point.
- `get_knowledge_document` is used when the user asks to view, summarize, or edit a whole document.
- Tool responses include source names so the assistant can mention which documents informed the answer.

Update `ChatSystemPrompt` with concise knowledge-base instructions while preserving the assistant's current OfferPilot role and one-tool-per-turn rule.

For models that do not support tools, extend summary fallback so it can include a small set of knowledge search snippets when the user query appears knowledge-related. This keeps degraded mode useful without pretending full tool support exists.

## Error Handling

- API handlers return `400` for validation errors, invalid IDs, missing required fields, unsupported file types, oversized imports, and empty search queries.
- API handlers return `404` for missing knowledge bases or documents.
- API handlers return `500` for database and synchronization errors.
- UI shows concise Ant Design messages for create/update/delete/import failures.
- Search failures in chat should surface as tool errors, letting the model explain that knowledge retrieval failed.

## Testing Plan

Backend database tests:

- Migration creates all knowledge tables and indexes.
- Knowledge base CRUD works.
- Document CRUD works.
- Deleting a knowledge base cascades documents and chunks.
- Creating/updating a document refreshes chunks and FTS rows.
- Search returns expected snippets and respects `knowledge_base_id` and `limit`.

API tests:

- Knowledge base CRUD routes.
- Document CRUD routes.
- Import route accepts `.md` and `.txt`.
- Import route rejects unsupported extensions and files over 1 MB.
- Search route rejects empty query and returns structured snippets.

AI tests:

- `search_knowledge` returns structured snippet JSON.
- Knowledge write tools are marked as writes and produce confirmation descriptions.
- Confirming a pending write creates/updates/deletes knowledge content.
- System prompt contains knowledge retrieval rules.

Frontend verification:

- `npm run build` succeeds.
- UI supports creating a knowledge base, importing a document, editing it, and searching content.

Full project verification:

- `go test ./...`
- `cd web && npm run build`

## Acceptance Criteria

- A user can create a `Java interview prep` knowledge base in the UI.
- A user can upload or manually create `.md/.txt` study documents.
- A user can search document body text from the knowledge view.
- A user can ask the AI assistant, "Explain synchronized based on my Java interview prep knowledge base", and the assistant retrieves relevant snippets before answering.
- A user can ask the assistant to create or update a knowledge document, and the write is gated by the existing confirmation card.
- A user can ask the assistant not to use the knowledge base, and the assistant follows that instruction.
- The implementation passes backend tests and frontend build verification.
