# Knowledge Base Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first knowledge base manager with Markdown/text documents, SQLite FTS search, and AI chat tools for retrieval and confirmed writes.

**Architecture:** Add a focused knowledge domain to the existing Go/SQLite backend, expose it through REST handlers, register AI tools against the same database methods, and add a React/Ant Design view under the existing `Segmented` workspace switcher. Documents are chunked synchronously on create/update/import and indexed with SQLite FTS for retrieval.

**Tech Stack:** Go 1.22, chi, modernc SQLite/FTS5, React 18, TypeScript, Ant Design, React Query, axios.

---

## File Structure

- Create `internal/db/knowledge.go`: knowledge models, CRUD, import payload helpers, chunking, FTS synchronization, search.
- Create `internal/db/knowledge_test.go`: database migration, CRUD, cascade, chunk refresh, and search tests.
- Modify `internal/db/db.go`: migration statements for knowledge tables, FTS table, and indexes.
- Create `internal/api/knowledge.go`: REST request/response handlers and multipart import validation.
- Create `internal/api/knowledge_test.go`: API route tests for CRUD, import, validation, and search.
- Modify `internal/api/router.go`: register knowledge routes.
- Modify `internal/ai/tools.go`: add knowledge read/write tools.
- Modify `internal/ai/tools_test.go`: AI tool tests for read/search/write metadata and execution.
- Modify `internal/ai/agent.go`: extend `ChatSystemPrompt` with knowledge retrieval rules.
- Modify `internal/ai/summary.go`: include limited knowledge search context in no-tools fallback.
- Modify `internal/ai/summary_test.go`: fallback prompt coverage.
- Create `web/src/types/knowledge.ts`: frontend knowledge types.
- Create `web/src/services/knowledge.ts`: axios service functions.
- Create `web/src/components/KnowledgeDocumentEditor.tsx`: document create/edit drawer.
- Create `web/src/components/KnowledgeImportModal.tsx`: `.md/.txt` import modal.
- Create `web/src/components/KnowledgeBaseView.tsx`: main knowledge management view.
- Modify `web/src/App.tsx`: add `knowledge` view option and render `KnowledgeBaseView`.

## Task 1: Database Models, Migration, Chunking, And Search

**Files:**
- Create: `internal/db/knowledge.go`
- Create: `internal/db/knowledge_test.go`
- Modify: `internal/db/db.go`

- [ ] **Step 1: Write failing database tests**

Create `internal/db/knowledge_test.go` with these tests:

```go
package db

import (
	"database/sql"
	"errors"
	"strings"
	"testing"
)

func TestKnowledgeBaseAndDocumentCRUD(t *testing.T) {
	d := newTestDB(t)

	base := &KnowledgeBase{Name: "Java interview prep", Description: "Core Java notes"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	if base.ID == 0 {
		t.Fatal("expected non-zero base id")
	}

	doc := &KnowledgeDocument{
		KnowledgeBaseID: base.ID,
		Title:           "Synchronized",
		Content:         "synchronized controls monitor access\n\nIt can guard instance methods.",
		Tags:            []string{"java", "concurrency"},
		SourceType:      "manual",
	}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}
	if doc.ID == 0 {
		t.Fatal("expected non-zero doc id")
	}

	got, err := d.GetKnowledgeDocument(doc.ID)
	if err != nil {
		t.Fatalf("get doc: %v", err)
	}
	if got.Title != "Synchronized" || got.KnowledgeBaseID != base.ID || len(got.Tags) != 2 {
		t.Fatalf("unexpected doc: %+v", got)
	}

	doc.Title = "Java synchronized"
	doc.Content = "monitor lock and happens-before"
	doc.Tags = []string{"java"}
	if err := d.UpdateKnowledgeDocument(doc); err != nil {
		t.Fatalf("update doc: %v", err)
	}

	listed, err := d.ListKnowledgeDocuments(KnowledgeDocumentFilter{KnowledgeBaseID: base.ID, Query: "happens"})
	if err != nil {
		t.Fatalf("list docs: %v", err)
	}
	if len(listed) != 1 || listed[0].Title != "Java synchronized" {
		t.Fatalf("unexpected filtered docs: %+v", listed)
	}

	if err := d.DeleteKnowledgeDocument(doc.ID); err != nil {
		t.Fatalf("delete doc: %v", err)
	}
	if _, err := d.GetKnowledgeDocument(doc.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected missing doc after delete, got %v", err)
	}
}

func TestKnowledgeSearchAndChunkRefresh(t *testing.T) {
	d := newTestDB(t)
	base := &KnowledgeBase{Name: "Go learning notes"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &KnowledgeDocument{
		KnowledgeBaseID: base.ID,
		Title:           "Scheduler",
		Content:         "goroutine scheduling uses M P G.\n\nChannels coordinate communication.",
		Tags:            []string{"go"},
		SourceType:      "manual",
	}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	results, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "goroutine", Limit: 5})
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if len(results) != 1 || results[0].DocumentTitle != "Scheduler" || !strings.Contains(results[0].Snippet, "goroutine") {
		t.Fatalf("unexpected search results: %+v", results)
	}

	doc.Content = "mutex protects shared memory"
	if err := d.UpdateKnowledgeDocument(doc); err != nil {
		t.Fatalf("update doc: %v", err)
	}
	oldResults, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "goroutine", Limit: 5})
	if err != nil {
		t.Fatalf("search old content: %v", err)
	}
	if len(oldResults) != 0 {
		t.Fatalf("old chunks should be removed, got %+v", oldResults)
	}
	newResults, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "mutex", Limit: 5})
	if err != nil {
		t.Fatalf("search new content: %v", err)
	}
	if len(newResults) != 1 || newResults[0].KnowledgeBaseName != "Go learning notes" {
		t.Fatalf("unexpected new search results: %+v", newResults)
	}
}

func TestKnowledgeBaseDeleteCascadesDocumentsAndChunks(t *testing.T) {
	d := newTestDB(t)
	base := &KnowledgeBase{Name: "Project material"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &KnowledgeDocument{KnowledgeBaseID: base.ID, Title: "Cache project", Content: "redis cache invalidation", SourceType: "manual"}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	if err := d.DeleteKnowledgeBase(base.ID); err != nil {
		t.Fatalf("delete base: %v", err)
	}
	if _, err := d.GetKnowledgeDocument(doc.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected doc cascade delete, got %v", err)
	}
	results, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "redis", Limit: 5})
	if err != nil {
		t.Fatalf("search after cascade: %v", err)
	}
	if len(results) != 0 {
		t.Fatalf("expected no chunks after cascade, got %+v", results)
	}
}
```

- [ ] **Step 2: Run database tests and verify they fail**

Run:

```powershell
go test ./internal/db -run Knowledge -count=1
```

Expected: compile failure mentioning undefined types or methods such as `KnowledgeBase`, `CreateKnowledgeBase`, and `SearchKnowledge`.

- [ ] **Step 3: Add database models and methods**

Create `internal/db/knowledge.go` with these public types and methods. Keep helper functions private.

```go
package db

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

const (
	KnowledgeSourceManual = "manual"
	KnowledgeSourceUpload = "upload"
	defaultKnowledgeLimit = 5
	maxKnowledgeLimit     = 10
	maxChunkRunes         = 900
	minChunkRunes         = 120
)

type KnowledgeBase struct {
	ID          int64     `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type KnowledgeDocument struct {
	ID              int64     `json:"id"`
	KnowledgeBaseID int64     `json:"knowledge_base_id"`
	Title           string    `json:"title"`
	Content         string    `json:"content"`
	Tags            []string  `json:"tags"`
	SourceType      string    `json:"source_type"`
	SourceName      string    `json:"source_name"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type KnowledgeDocumentFilter struct {
	KnowledgeBaseID int64
	Query           string
}

type KnowledgeSearchFilter struct {
	Query           string
	KnowledgeBaseID int64
	Limit           int
}

type KnowledgeSearchResult struct {
	KnowledgeBaseID   int64   `json:"knowledge_base_id"`
	KnowledgeBaseName string  `json:"knowledge_base_name"`
	DocumentID        int64   `json:"document_id"`
	DocumentTitle     string  `json:"document_title"`
	ChunkID           int64   `json:"chunk_id"`
	Snippet           string  `json:"snippet"`
	Score             float64 `json:"score"`
}
```

Implement these methods in the same file:

```go
func (db *Database) CreateKnowledgeBase(kb *KnowledgeBase) error
func (db *Database) ListKnowledgeBases() ([]KnowledgeBase, error)
func (db *Database) GetKnowledgeBase(id int64) (*KnowledgeBase, error)
func (db *Database) UpdateKnowledgeBase(kb *KnowledgeBase) error
func (db *Database) DeleteKnowledgeBase(id int64) error
func (db *Database) CreateKnowledgeDocument(doc *KnowledgeDocument) error
func (db *Database) ListKnowledgeDocuments(filter KnowledgeDocumentFilter) ([]KnowledgeDocument, error)
func (db *Database) GetKnowledgeDocument(id int64) (*KnowledgeDocument, error)
func (db *Database) UpdateKnowledgeDocument(doc *KnowledgeDocument) error
func (db *Database) DeleteKnowledgeDocument(id int64) error
func (db *Database) SearchKnowledge(filter KnowledgeSearchFilter) ([]KnowledgeSearchResult, error)
```

Use `json.Marshal` and `json.Unmarshal` to store `KnowledgeDocument.Tags` as JSON. Use `sql.ErrNoRows` when update/delete affects zero rows, matching `internal/db/events.go`.

For chunking and FTS synchronization, implement this shape:

```go
func (db *Database) refreshKnowledgeChunks(doc *KnowledgeDocument) error {
	if _, err := db.conn.Exec(`DELETE FROM knowledge_chunks_fts WHERE document_id = ?`, doc.ID); err != nil {
		return err
	}
	if _, err := db.conn.Exec(`DELETE FROM knowledge_chunks WHERE document_id = ?`, doc.ID); err != nil {
		return err
	}
	chunks := splitKnowledgeChunks(doc.Content)
	for i, chunk := range chunks {
		res, err := db.conn.Exec(
			`INSERT INTO knowledge_chunks (document_id, knowledge_base_id, chunk_index, content) VALUES (?, ?, ?, ?)`,
			doc.ID, doc.KnowledgeBaseID, i, chunk,
		)
		if err != nil {
			return err
		}
		chunkID, _ := res.LastInsertId()
		if _, err := db.conn.Exec(
			`INSERT INTO knowledge_chunks_fts (chunk_id, document_id, knowledge_base_id, content) VALUES (?, ?, ?, ?)`,
			chunkID, doc.ID, doc.KnowledgeBaseID, chunk,
		); err != nil {
			return err
		}
	}
	return nil
}
```

Use this chunking behavior:

```go
func splitKnowledgeChunks(content string) []string {
	content = strings.TrimSpace(content)
	if content == "" {
		return nil
	}
	paragraphs := strings.Split(strings.ReplaceAll(content, "\r\n", "\n"), "\n\n")
	var chunks []string
	var current string
	for _, p := range paragraphs {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		for len([]rune(p)) > maxChunkRunes {
			rs := []rune(p)
			chunks = append(chunks, strings.TrimSpace(string(rs[:maxChunkRunes])))
			p = strings.TrimSpace(string(rs[maxChunkRunes:]))
		}
		if current == "" {
			current = p
			continue
		}
		if len([]rune(current))+len([]rune(p))+2 <= maxChunkRunes && len([]rune(current)) < minChunkRunes {
			current += "\n\n" + p
			continue
		}
		chunks = append(chunks, current)
		current = p
	}
	if current != "" {
		chunks = append(chunks, current)
	}
	return chunks
}
```

- [ ] **Step 4: Add migrations**

Modify `internal/db/db.go` migration list by adding:

```go
`CREATE TABLE IF NOT EXISTS knowledge_bases (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT NOT NULL,
	description TEXT DEFAULT '',
	created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)`,
`CREATE TABLE IF NOT EXISTS knowledge_documents (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	knowledge_base_id INTEGER NOT NULL,
	title TEXT NOT NULL,
	content TEXT NOT NULL DEFAULT '',
	tags TEXT NOT NULL DEFAULT '[]',
	source_type TEXT NOT NULL DEFAULT 'manual',
	source_name TEXT DEFAULT '',
	created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
)`,
`CREATE TABLE IF NOT EXISTS knowledge_chunks (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	document_id INTEGER NOT NULL,
	knowledge_base_id INTEGER NOT NULL,
	chunk_index INTEGER NOT NULL,
	content TEXT NOT NULL,
	created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
	FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
)`,
`CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
	chunk_id UNINDEXED,
	document_id UNINDEXED,
	knowledge_base_id UNINDEXED,
	content
)`,
`CREATE INDEX IF NOT EXISTS idx_knowledge_documents_base ON knowledge_documents(knowledge_base_id)`,
`CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id)`,
`CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_base ON knowledge_chunks(knowledge_base_id)`,
```

- [ ] **Step 5: Run database tests and format**

Run:

```powershell
gofmt -w internal/db/knowledge.go internal/db/knowledge_test.go internal/db/db.go
go test ./internal/db -run Knowledge -count=1
```

Expected: PASS for all `Knowledge` database tests.

- [ ] **Step 6: Commit database layer**

Run:

```powershell
git add internal/db/db.go internal/db/knowledge.go internal/db/knowledge_test.go
git commit -m "feat: AI add knowledge database"
```

## Task 2: Knowledge REST API

**Files:**
- Create: `internal/api/knowledge.go`
- Create: `internal/api/knowledge_test.go`
- Modify: `internal/api/router.go`

- [ ] **Step 1: Write failing API tests**

Create `internal/api/knowledge_test.go`:

```go
package api

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func knowledgeTestRouter(t *testing.T) (*db.Database, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/knowledge.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d, NewRouter(d, t.TempDir())
}

func knowledgeAPIRequest(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body: %v", err)
		}
		reader = bytes.NewReader(data)
	} else {
		reader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func TestKnowledgeAPIBaseAndDocumentCRUD(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	baseRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-bases", map[string]interface{}{"name": "Java interview prep", "description": "core notes"})
	if baseRec.Code != http.StatusCreated {
		t.Fatalf("create base status %d: %s", baseRec.Code, baseRec.Body.String())
	}
	var base db.KnowledgeBase
	if err := json.Unmarshal(baseRec.Body.Bytes(), &base); err != nil {
		t.Fatalf("decode base: %v", err)
	}

	docBody := map[string]interface{}{"knowledge_base_id": base.ID, "title": "Synchronized", "content": "monitor lock", "tags": []string{"java"}}
	docRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-documents", docBody)
	if docRec.Code != http.StatusCreated {
		t.Fatalf("create doc status %d: %s", docRec.Code, docRec.Body.String())
	}
	var doc db.KnowledgeDocument
	if err := json.Unmarshal(docRec.Body.Bytes(), &doc); err != nil {
		t.Fatalf("decode doc: %v", err)
	}

	updateRec := knowledgeAPIRequest(t, router, http.MethodPut, "/api/knowledge-documents/"+strconv.FormatInt(doc.ID, 10), map[string]interface{}{"knowledge_base_id": base.ID, "title": "Updated", "content": "happens before", "tags": []string{"jvm"}})
	if updateRec.Code != http.StatusOK {
		t.Fatalf("update doc status %d: %s", updateRec.Code, updateRec.Body.String())
	}

	searchRec := knowledgeAPIRequest(t, router, http.MethodGet, "/api/knowledge/search?q=happens&knowledge_base_id="+strconv.FormatInt(base.ID, 10), nil)
	if searchRec.Code != http.StatusOK {
		t.Fatalf("search status %d: %s", searchRec.Code, searchRec.Body.String())
	}
	var results []db.KnowledgeSearchResult
	if err := json.Unmarshal(searchRec.Body.Bytes(), &results); err != nil {
		t.Fatalf("decode search: %v", err)
	}
	if len(results) != 1 || results[0].DocumentTitle != "Updated" {
		t.Fatalf("unexpected search results: %+v", results)
	}

	deleteRec := knowledgeAPIRequest(t, router, http.MethodDelete, "/api/knowledge-bases/"+strconv.FormatInt(base.ID, 10), nil)
	if deleteRec.Code != http.StatusOK {
		t.Fatalf("delete base status %d: %s", deleteRec.Code, deleteRec.Body.String())
	}
}

func TestKnowledgeAPIImportValidation(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	baseRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-bases", map[string]interface{}{"name": "Go notes"})
	var base db.KnowledgeBase
	if err := json.Unmarshal(baseRec.Body.Bytes(), &base); err != nil {
		t.Fatalf("decode base: %v", err)
	}

	rec := multipartKnowledgeImport(t, router, base.ID, "scheduler.md", "goroutine scheduler")
	if rec.Code != http.StatusCreated {
		t.Fatalf("import status %d: %s", rec.Code, rec.Body.String())
	}
	var doc db.KnowledgeDocument
	if err := json.Unmarshal(rec.Body.Bytes(), &doc); err != nil {
		t.Fatalf("decode imported doc: %v", err)
	}
	if doc.Title != "scheduler" || doc.SourceType != db.KnowledgeSourceUpload || doc.SourceName != "scheduler.md" {
		t.Fatalf("unexpected imported doc: %+v", doc)
	}

	badRec := multipartKnowledgeImport(t, router, base.ID, "slides.pdf", "not allowed")
	if badRec.Code != http.StatusBadRequest {
		t.Fatalf("expected bad extension status 400, got %d: %s", badRec.Code, badRec.Body.String())
	}
}

func multipartKnowledgeImport(t *testing.T, router http.Handler, baseID int64, filename, content string) *httptest.ResponseRecorder {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	_ = writer.WriteField("knowledge_base_id", strconv.FormatInt(baseID, 10))
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	if _, err := part.Write([]byte(content)); err != nil {
		t.Fatalf("write form file: %v", err)
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/knowledge-documents/import", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func TestKnowledgeAPISearchValidation(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	rec := knowledgeAPIRequest(t, router, http.MethodGet, "/api/knowledge/search?q=", nil)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected bad request for empty query, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "query is required") {
		t.Fatalf("expected query error, got %s", rec.Body.String())
	}
}
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```powershell
go test ./internal/api -run Knowledge -count=1
```

Expected: FAIL or 404 because knowledge routes are not registered.

- [ ] **Step 3: Implement API handlers**

Create `internal/api/knowledge.go` with:

```go
package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

const maxKnowledgeImportBytes = 1 << 20

type knowledgeBaseRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

type knowledgeDocumentRequest struct {
	KnowledgeBaseID int64    `json:"knowledge_base_id"`
	Title           string   `json:"title"`
	Content         string   `json:"content"`
	Tags            []string `json:"tags"`
}

func registerKnowledgeRoutes(r chi.Router, database *db.Database) {
	r.Get("/knowledge-bases", listKnowledgeBasesHandler(database))
	r.Post("/knowledge-bases", createKnowledgeBaseHandler(database))
	r.Put("/knowledge-bases/{id}", updateKnowledgeBaseHandler(database))
	r.Delete("/knowledge-bases/{id}", deleteKnowledgeBaseHandler(database))
	r.Get("/knowledge-documents", listKnowledgeDocumentsHandler(database))
	r.Post("/knowledge-documents", createKnowledgeDocumentHandler(database))
	r.Post("/knowledge-documents/import", importKnowledgeDocumentHandler(database))
	r.Get("/knowledge-documents/{id}", getKnowledgeDocumentHandler(database))
	r.Put("/knowledge-documents/{id}", updateKnowledgeDocumentHandler(database))
	r.Delete("/knowledge-documents/{id}", deleteKnowledgeDocumentHandler(database))
	r.Get("/knowledge/search", searchKnowledgeHandler(database))
}
```

Implement handlers with these validation messages:

```go
if strings.TrimSpace(req.Name) == "" {
	respondError(w, http.StatusBadRequest, "name is required")
	return
}
if req.KnowledgeBaseID <= 0 {
	respondError(w, http.StatusBadRequest, "knowledge_base_id is required")
	return
}
if strings.TrimSpace(req.Title) == "" {
	respondError(w, http.StatusBadRequest, "title is required")
	return
}
if strings.TrimSpace(query) == "" {
	respondError(w, http.StatusBadRequest, "query is required")
	return
}
```

For import, parse multipart and enforce file type:

```go
if err := r.ParseMultipartForm(maxKnowledgeImportBytes); err != nil {
	respondError(w, http.StatusBadRequest, "invalid multipart form")
	return
}
file, header, err := r.FormFile("file")
if err != nil {
	respondError(w, http.StatusBadRequest, "file is required")
	return
}
defer file.Close()
ext := strings.ToLower(filepath.Ext(header.Filename))
if ext != ".md" && ext != ".txt" {
	respondError(w, http.StatusBadRequest, "only .md and .txt files are supported")
	return
}
contentBytes, err := io.ReadAll(io.LimitReader(file, maxKnowledgeImportBytes+1))
if err != nil {
	respondError(w, http.StatusBadRequest, "failed to read file")
	return
}
if len(contentBytes) > maxKnowledgeImportBytes {
	respondError(w, http.StatusBadRequest, "file is too large")
	return
}
```

Use `errors.Is(err, sql.ErrNoRows)` in handlers for 404. Import title should be `strings.TrimSuffix(header.Filename, filepath.Ext(header.Filename))`.

- [ ] **Step 4: Register routes**

Modify `internal/api/router.go` inside the `/api` route group:

```go
// Knowledge bases and documents
registerKnowledgeRoutes(r, database)
```

- [ ] **Step 5: Run API tests and format**

Run:

```powershell
gofmt -w internal/api/knowledge.go internal/api/knowledge_test.go internal/api/router.go
go test ./internal/api -run Knowledge -count=1
```

Expected: PASS for all `Knowledge` API tests.

- [ ] **Step 6: Commit API layer**

Run:

```powershell
git add internal/api/knowledge.go internal/api/knowledge_test.go internal/api/router.go
git commit -m "feat: AI add knowledge API"
```

## Task 3: AI Knowledge Tools And Prompt Rules

**Files:**
- Modify: `internal/ai/tools.go`
- Modify: `internal/ai/tools_test.go`
- Modify: `internal/ai/agent.go`

- [ ] **Step 1: Write failing AI tool tests**

Append these tests to `internal/ai/tools_test.go`:

```go
func TestKnowledgeToolsCRUDAndSearch(t *testing.T) {
	d := newToolDB(t)
	reg := NewRegistry(d)

	createBase, ok := reg.Get("create_knowledge_base")
	if !ok || !createBase.Write {
		t.Fatal("create_knowledge_base should be a write tool")
	}
	if createBase.Describe(json.RawMessage(`{"name":"Java interview prep"}`)) == "" {
		t.Fatal("create_knowledge_base should describe confirmation text")
	}

	out, err := reg.Execute(context.Background(), "create_knowledge_base", json.RawMessage(`{"name":"Java interview prep","description":"core notes"}`))
	if err != nil {
		t.Fatalf("create base: %v", err)
	}
	if !strings.Contains(out, `"name":"Java interview prep"`) {
		t.Fatalf("unexpected base output: %s", out)
	}

	createDoc, ok := reg.Get("create_knowledge_document")
	if !ok || !createDoc.Write {
		t.Fatal("create_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "create_knowledge_document", json.RawMessage(`{"knowledge_base_id":1,"title":"Synchronized","content":"monitor lock and happens-before","tags":["java"]}`))
	if err != nil {
		t.Fatalf("create doc: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized"`) {
		t.Fatalf("unexpected doc output: %s", out)
	}

	out, err = reg.Execute(context.Background(), "search_knowledge", json.RawMessage(`{"query":"monitor","limit":5}`))
	if err != nil {
		t.Fatalf("search knowledge: %v", err)
	}
	if !strings.Contains(out, `"document_title":"Synchronized"`) || !strings.Contains(out, `"snippet"`) {
		t.Fatalf("unexpected search output: %s", out)
	}

	updateDoc, ok := reg.Get("update_knowledge_document")
	if !ok || !updateDoc.Write {
		t.Fatal("update_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "update_knowledge_document", json.RawMessage(`{"id":1,"knowledge_base_id":1,"title":"Synchronized updated","content":"biased locking was removed","tags":["jvm"]}`))
	if err != nil {
		t.Fatalf("update doc: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized updated"`) {
		t.Fatalf("unexpected update output: %s", out)
	}

	deleteDoc, ok := reg.Get("delete_knowledge_document")
	if !ok || !deleteDoc.Write {
		t.Fatal("delete_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "delete_knowledge_document", json.RawMessage(`{"id":1}`))
	if err != nil {
		t.Fatalf("delete doc: %v", err)
	}
	if !strings.Contains(out, `"deleted":true`) {
		t.Fatalf("unexpected delete output: %s", out)
	}
}

func TestChatSystemPromptMentionsKnowledgeRules(t *testing.T) {
	for _, phrase := range []string{"search_knowledge", "do not use the knowledge base", "specific knowledge base"} {
		if !strings.Contains(ChatSystemPrompt, phrase) {
			t.Fatalf("system prompt should contain %q, got %s", phrase, ChatSystemPrompt)
		}
	}
}
```

- [ ] **Step 2: Run AI tests and verify they fail**

Run:

```powershell
go test ./internal/ai -run "KnowledgeTools|ChatSystemPrompt" -count=1
```

Expected: FAIL because knowledge tools and prompt text are missing.

- [ ] **Step 3: Register knowledge tools**

Modify `internal/ai/tools.go` inside `NewRegistry` after existing read tools:

```go
r.add(Tool{
	Name:        "list_knowledge_bases",
	Description: "List personal knowledge bases.",
	Schema:      json.RawMessage(`{"type":"object","properties":{}}`),
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		items, err := database.ListKnowledgeBases()
		if err != nil {
			return "", err
		}
		return jsonResult(items)
	},
})
r.add(Tool{
	Name:        "search_knowledge",
	Description: "Search personal knowledge base snippets. Use this for study notes, interview prep concepts, saved explanations, and document-grounded answers.",
	Schema:      json.RawMessage(`{"type":"object","properties":{"query":{"type":"string"},"knowledge_base_id":{"type":"integer"},"limit":{"type":"integer"}},"required":["query"]}`),
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		var p struct {
			Query           string `json:"query"`
			KnowledgeBaseID int64  `json:"knowledge_base_id"`
			Limit           int    `json:"limit"`
		}
		if err := json.Unmarshal(args, &p); err != nil {
			return "", err
		}
		items, err := database.SearchKnowledge(db.KnowledgeSearchFilter{Query: p.Query, KnowledgeBaseID: p.KnowledgeBaseID, Limit: p.Limit})
		if err != nil {
			return "", err
		}
		return jsonResult(items)
	},
})
```

Also add `list_knowledge_documents` and `get_knowledge_document` read tools using `database.ListKnowledgeDocuments` and `database.GetKnowledgeDocument`.

Add write tools after existing write tools. Use this pattern:

```go
r.add(Tool{
	Name:        "create_knowledge_base",
	Description: "Create a personal knowledge base.",
	Write:       true,
	Schema:      json.RawMessage(`{"type":"object","properties":{"name":{"type":"string"},"description":{"type":"string"}},"required":["name"]}`),
	Describe: func(args json.RawMessage) string {
		var p struct {
			Name string `json:"name"`
		}
		_ = json.Unmarshal(args, &p)
		return fmt.Sprintf("Create knowledge base: %s", p.Name)
	},
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		var p struct {
			Name        string `json:"name"`
			Description string `json:"description"`
		}
		if err := json.Unmarshal(args, &p); err != nil {
			return "", err
		}
		kb := &db.KnowledgeBase{Name: p.Name, Description: p.Description}
		if err := database.CreateKnowledgeBase(kb); err != nil {
			return "", err
		}
		return jsonResult(kb)
	},
})
```

Repeat the pattern for `update_knowledge_base`, `delete_knowledge_base`, `create_knowledge_document`, `update_knowledge_document`, and `delete_knowledge_document`.

- [ ] **Step 4: Extend chat system prompt**

Modify `internal/ai/agent.go` so `ChatSystemPrompt` includes these exact rules:

```go
"你还可以使用用户的个人知识库。默认情况下，当用户询问概念、学习笔记、面试八股、文档总结或可复用知识时，可以调用 search_knowledge 检索相关片段后回答。" +
"如果用户明确说 do not use the knowledge base、不要查知识库或不用知识库，就不要调用知识库工具。" +
"如果用户要求只根据某个 specific knowledge base 或特定文档回答，先定位对应知识库或文档，再检索或读取。"
```

- [ ] **Step 5: Run AI tests and format**

Run:

```powershell
gofmt -w internal/ai/tools.go internal/ai/tools_test.go internal/ai/agent.go
go test ./internal/ai -run "KnowledgeTools|ChatSystemPrompt" -count=1
```

Expected: PASS for the knowledge tool and prompt tests.

- [ ] **Step 6: Commit AI tools**

Run:

```powershell
git add internal/ai/tools.go internal/ai/tools_test.go internal/ai/agent.go
git commit -m "feat: AI add knowledge assistant tools"
```

## Task 4: Summary Fallback Knowledge Context

**Files:**
- Modify: `internal/ai/summary.go`
- Modify: `internal/ai/summary_test.go`

- [ ] **Step 1: Write failing fallback test**

Append to `internal/ai/summary_test.go`:

```go
func TestSummaryFallbackIncludesKnowledgeSearchContext(t *testing.T) {
	d := summaryTestDB(t)
	base := &db.KnowledgeBase{Name: "Java interview prep"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &db.KnowledgeDocument{KnowledgeBaseID: base.ID, Title: "Synchronized", Content: "synchronized uses monitor locks", SourceType: db.KnowledgeSourceManual}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	system, user := BuildSummaryFallbackPrompt(d, "Explain synchronized")
	if !strings.Contains(system, "OfferPilot") {
		t.Fatalf("expected existing system prompt context, got %s", system)
	}
	if !strings.Contains(user, "Knowledge snippets") || !strings.Contains(user, "Synchronized") || !strings.Contains(user, "monitor locks") {
		t.Fatalf("expected knowledge context in fallback prompt, got %s", user)
	}
}
```

If `summaryTestDB` does not exist, add it:

```go
func summaryTestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/summary.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}
```

- [ ] **Step 2: Run fallback test and verify it fails**

Run:

```powershell
go test ./internal/ai -run SummaryFallbackIncludesKnowledge -count=1
```

Expected: FAIL because fallback prompt does not include knowledge snippets yet, or `BuildSummaryFallbackPrompt` does not expose this seam.

- [ ] **Step 3: Add fallback prompt builder**

Modify `internal/ai/summary.go` so `RunSummaryFallback` calls a helper:

```go
func BuildSummaryFallbackPrompt(database *db.Database, userMessage string) (system, user string) {
	system = "You are OfferPilot's local job-search assistant. Answer from the provided local data. If data is missing, say so."
	var b strings.Builder
	b.WriteString("User question:\n")
	b.WriteString(userMessage)
	b.WriteString("\n\n")
	if snippets, err := database.SearchKnowledge(db.KnowledgeSearchFilter{Query: userMessage, Limit: 3}); err == nil && len(snippets) > 0 {
		b.WriteString("Knowledge snippets:\n")
		for _, s := range snippets {
			b.WriteString("- ")
			b.WriteString(s.KnowledgeBaseName)
			b.WriteString(" / ")
			b.WriteString(s.DocumentTitle)
			b.WriteString(": ")
			b.WriteString(s.Snippet)
			b.WriteString("\n")
		}
		b.WriteString("\n")
	}
	b.WriteString("Use the snippets only when relevant and mention when the answer is based on saved knowledge.")
	return system, b.String()
}
```

Keep existing application/resume/note summary context in the same helper if it already exists; append the knowledge block without removing current behavior.

- [ ] **Step 4: Run fallback tests and format**

Run:

```powershell
gofmt -w internal/ai/summary.go internal/ai/summary_test.go
go test ./internal/ai -run Summary -count=1
```

Expected: PASS for all summary tests.

- [ ] **Step 5: Commit fallback support**

Run:

```powershell
git add internal/ai/summary.go internal/ai/summary_test.go
git commit -m "feat: AI include knowledge in fallback"
```

## Task 5: Frontend Knowledge Services And View

**Files:**
- Create: `web/src/types/knowledge.ts`
- Create: `web/src/services/knowledge.ts`
- Create: `web/src/components/KnowledgeDocumentEditor.tsx`
- Create: `web/src/components/KnowledgeImportModal.tsx`
- Create: `web/src/components/KnowledgeBaseView.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Add TypeScript types**

Create `web/src/types/knowledge.ts`:

```ts
export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: number;
  knowledge_base_id: number;
  title: string;
  content: string;
  tags: string[];
  source_type: 'manual' | 'upload';
  source_name: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSearchResult {
  knowledge_base_id: number;
  knowledge_base_name: string;
  document_id: number;
  document_title: string;
  chunk_id: number;
  snippet: string;
  score: number;
}

export interface KnowledgeBaseInput {
  name: string;
  description?: string;
}

export interface KnowledgeDocumentInput {
  knowledge_base_id: number;
  title: string;
  content: string;
  tags?: string[];
}
```

- [ ] **Step 2: Add service functions**

Create `web/src/services/knowledge.ts`:

```ts
import axios from 'axios';
import type {
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeDocument,
  KnowledgeDocumentInput,
  KnowledgeSearchResult,
} from '@/types/knowledge';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const { data } = await http.get<KnowledgeBase[]>('/knowledge-bases');
  return data ?? [];
}

export async function createKnowledgeBase(input: KnowledgeBaseInput): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>('/knowledge-bases', input);
  return data;
}

export async function updateKnowledgeBase(id: number, input: KnowledgeBaseInput): Promise<KnowledgeBase> {
  const { data } = await http.put<KnowledgeBase>(`/knowledge-bases/${id}`, input);
  return data;
}

export async function deleteKnowledgeBase(id: number): Promise<void> {
  await http.delete(`/knowledge-bases/${id}`);
}

export async function listKnowledgeDocuments(knowledgeBaseId?: number, q?: string): Promise<KnowledgeDocument[]> {
  const { data } = await http.get<KnowledgeDocument[]>('/knowledge-documents', {
    params: { knowledge_base_id: knowledgeBaseId || undefined, q: q || undefined },
  });
  return data ?? [];
}

export async function getKnowledgeDocument(id: number): Promise<KnowledgeDocument> {
  const { data } = await http.get<KnowledgeDocument>(`/knowledge-documents/${id}`);
  return data;
}

export async function createKnowledgeDocument(input: KnowledgeDocumentInput): Promise<KnowledgeDocument> {
  const { data } = await http.post<KnowledgeDocument>('/knowledge-documents', input);
  return data;
}

export async function updateKnowledgeDocument(id: number, input: KnowledgeDocumentInput): Promise<KnowledgeDocument> {
  const { data } = await http.put<KnowledgeDocument>(`/knowledge-documents/${id}`, input);
  return data;
}

export async function deleteKnowledgeDocument(id: number): Promise<void> {
  await http.delete(`/knowledge-documents/${id}`);
}

export async function importKnowledgeDocument(knowledgeBaseId: number, file: File): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append('knowledge_base_id', String(knowledgeBaseId));
  form.append('file', file);
  const { data } = await http.post<KnowledgeDocument>('/knowledge-documents/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function searchKnowledge(q: string, knowledgeBaseId?: number): Promise<KnowledgeSearchResult[]> {
  const { data } = await http.get<KnowledgeSearchResult[]>('/knowledge/search', {
    params: { q, knowledge_base_id: knowledgeBaseId || undefined },
  });
  return data ?? [];
}
```

- [ ] **Step 3: Add document editor**

Create `web/src/components/KnowledgeDocumentEditor.tsx` with an Ant Design `Drawer`, `Form`, `Input`, `Select` in `tags` mode, and `Input.TextArea`. Props:

```ts
interface Props {
  open: boolean;
  document: KnowledgeDocument | null;
  knowledgeBaseId: number;
  saving: boolean;
  onSubmit: (input: KnowledgeDocumentInput) => void;
  onClose: () => void;
}
```

The submit handler must call:

```ts
onSubmit({
  knowledge_base_id: knowledgeBaseId,
  title: values.title,
  content: values.content ?? '',
  tags: values.tags ?? [],
});
```

- [ ] **Step 4: Add import modal**

Create `web/src/components/KnowledgeImportModal.tsx` with props:

```ts
interface Props {
  open: boolean;
  uploading: boolean;
  onSubmit: (file: File) => void;
  onClose: () => void;
}
```

Use Ant Design `Upload.Dragger` with `beforeUpload` returning `false`, accept `.md,.txt`, and store exactly one selected `File`.

- [ ] **Step 5: Add main knowledge view**

Create `web/src/components/KnowledgeBaseView.tsx`. Use React Query keys:

```ts
['knowledge-bases']
['knowledge-documents', selectedBaseID, search]
```

Required interactions:

- Create base with `Modal.confirm` or `Modal` plus `Input`.
- Select first base automatically when bases load and no selection exists.
- Delete base with `Popconfirm`.
- Create document opens `KnowledgeDocumentEditor`.
- Edit document opens `KnowledgeDocumentEditor` with existing document.
- Delete document with `Popconfirm`.
- Import opens `KnowledgeImportModal`.
- Search uses `Input.Search` and passes query to `listKnowledgeDocuments`.

Use these invalidation helpers:

```ts
const invalidateBases = () => queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
const invalidateDocs = () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] });
```

- [ ] **Step 6: Wire view into app**

Modify `web/src/App.tsx`:

```ts
import KnowledgeBaseView from '@/components/KnowledgeBaseView';
```

Change state type:

```ts
const [viewMode, setViewMode] = useState<'board' | 'calendar' | 'reviews' | 'knowledge'>('board');
```

Add segmented option:

```ts
{ label: 'Knowledge', value: 'knowledge' },
```

Render:

```tsx
) : viewMode === 'reviews' ? (
  <ReviewManagementView applications={applications} />
) : (
  <KnowledgeBaseView />
)}
```

- [ ] **Step 7: Build frontend and fix TypeScript errors**

Run:

```powershell
cmd /c npm.cmd run build
```

from `web/`.

Expected: TypeScript and Vite build complete with exit code 0. The existing large chunk warning may remain.

- [ ] **Step 8: Commit frontend**

Run:

```powershell
git add web/src/App.tsx web/src/types/knowledge.ts web/src/services/knowledge.ts web/src/components/KnowledgeBaseView.tsx web/src/components/KnowledgeDocumentEditor.tsx web/src/components/KnowledgeImportModal.tsx
git commit -m "feat: AI add knowledge management UI"
```

## Task 6: Full Verification And Polish

**Files:**
- Modify only files needed to fix failures found by the verification commands.

- [ ] **Step 1: Run full backend tests**

Run:

```powershell
go test ./...
```

Expected: all packages pass. Existing packages with no test files may report `[no test files]`.

- [ ] **Step 2: Run full frontend build**

Run from `web/`:

```powershell
cmd /c npm.cmd run build
```

Expected: build exits 0. The Vite chunk-size warning is acceptable if no new build errors occur.

- [ ] **Step 3: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only intentional knowledge feature files are modified, plus ignored build artifacts such as `web/dist/` and `web/tsconfig.tsbuildinfo`.

- [ ] **Step 4: Commit verification fixes if any**

If Step 1 or Step 2 required code fixes, stage only the changed source and test files:

```powershell
git add <fixed-source-and-test-files>
git commit -m "fix: AI stabilize knowledge base management"
```

If no fixes were required, do not create an empty commit.

## Task 7: Manual Acceptance Smoke Test

**Files:**
- No planned source edits.

- [ ] **Step 1: Start the app**

Run from repo root:

```powershell
go run ./cmd/oc start
```

Expected: local server starts and prints the listening address, normally `http://localhost:8080`.

- [ ] **Step 2: Exercise UI workflow**

In the browser:

1. Open the local app.
2. Click `Knowledge`.
3. Create a knowledge base named `Java interview prep`.
4. Create a document named `Synchronized` with body `synchronized uses monitor locks`.
5. Search `monitor`.
6. Confirm the document appears in the filtered list.
7. Import a `.txt` file with body `volatile provides visibility`.
8. Search `visibility`.

Expected: created and imported documents are searchable.

- [ ] **Step 3: Exercise AI workflow with configured model**

If an API key is configured, open `AI 助手` and ask:

```text
Explain synchronized based on my Java interview prep knowledge base.
```

Expected: assistant searches the knowledge base and answers using the saved document. Then ask:

```text
Do not use the knowledge base. Explain synchronized from general knowledge.
```

Expected: assistant answers without using knowledge tools.

- [ ] **Step 4: Stop the local server**

Stop the `go run ./cmd/oc start` process with `Ctrl+C`.

Expected: server process exits cleanly.

## Self-Review Notes

- Spec coverage: DB models, API routes, AI tools, fallback behavior, frontend view, import limits, search, write confirmations, and acceptance checks are mapped to tasks.
- Placeholder scan: the plan contains no unresolved marker words or deferred-work markers.
- Type consistency: backend uses `KnowledgeBase`, `KnowledgeDocument`, `KnowledgeDocumentFilter`, `KnowledgeSearchFilter`, and `KnowledgeSearchResult`; frontend mirrors the same JSON names.
