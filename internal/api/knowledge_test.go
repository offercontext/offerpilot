package api

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
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

func TestKnowledgeAPIImportRejectsLargeFileBeforeMultipartSpill(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	baseRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-bases", map[string]interface{}{"name": "Large imports"})
	var base db.KnowledgeBase
	if err := json.Unmarshal(baseRec.Body.Bytes(), &base); err != nil {
		t.Fatalf("decode base: %v", err)
	}

	tmpDir := t.TempDir()
	t.Setenv("TMP", tmpDir)
	t.Setenv("TEMP", tmpDir)
	t.Setenv("TMPDIR", tmpDir)

	rec, req := multipartKnowledgeImportBytes(t, router, base.ID, "large.txt", bytes.Repeat([]byte("a"), maxKnowledgeImportBytes+1))
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected large file status 400, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "file is too large") {
		t.Fatalf("expected large file error, got %s", rec.Body.String())
	}
	if req.MultipartForm != nil {
		t.Fatalf("expected streaming multipart reader without parsed multipart form")
	}
	entries, err := os.ReadDir(tmpDir)
	if err != nil {
		t.Fatalf("read temp dir: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("expected no multipart temp files, got %d", len(entries))
	}
}

func TestKnowledgeAPIImportRejectsDuplicateFiles(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	baseRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-bases", map[string]interface{}{"name": "Duplicate imports"})
	var base db.KnowledgeBase
	if err := json.Unmarshal(baseRec.Body.Bytes(), &base); err != nil {
		t.Fatalf("decode base: %v", err)
	}

	rec := multipartKnowledgeImportCustom(t, router, func(writer *multipart.Writer) {
		_ = writer.WriteField("knowledge_base_id", strconv.FormatInt(base.ID, 10))
		writeMultipartFile(t, writer, "one.txt", []byte("first"))
		writeMultipartFile(t, writer, "two.txt", []byte("second"))
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected duplicate file status 400, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "only one file is supported") {
		t.Fatalf("expected duplicate file error, got %s", rec.Body.String())
	}
}

func TestKnowledgeAPIImportRejectsOversizedRequest(t *testing.T) {
	_, router := knowledgeTestRouter(t)
	baseRec := knowledgeAPIRequest(t, router, http.MethodPost, "/api/knowledge-bases", map[string]interface{}{"name": "Bounded imports"})
	var base db.KnowledgeBase
	if err := json.Unmarshal(baseRec.Body.Bytes(), &base); err != nil {
		t.Fatalf("decode base: %v", err)
	}

	rec := multipartKnowledgeImportCustom(t, router, func(writer *multipart.Writer) {
		_ = writer.WriteField("knowledge_base_id", strconv.FormatInt(base.ID, 10))
		_ = writer.WriteField("padding", string(bytes.Repeat([]byte("x"), maxKnowledgeImportBytes+64*1024)))
		writeMultipartFile(t, writer, "small.txt", []byte("small"))
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected oversized request status 400, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "request is too large") {
		t.Fatalf("expected oversized request error, got %s", rec.Body.String())
	}
}

func multipartKnowledgeImport(t *testing.T, router http.Handler, baseID int64, filename, content string) *httptest.ResponseRecorder {
	t.Helper()
	rec, _ := multipartKnowledgeImportBytes(t, router, baseID, filename, []byte(content))
	return rec
}

func multipartKnowledgeImportBytes(t *testing.T, router http.Handler, baseID int64, filename string, content []byte) (*httptest.ResponseRecorder, *http.Request) {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	_ = writer.WriteField("knowledge_base_id", strconv.FormatInt(baseID, 10))
	writeMultipartFile(t, writer, filename, content)
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/knowledge-documents/import", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec, req
}

func multipartKnowledgeImportCustom(t *testing.T, router http.Handler, build func(*multipart.Writer)) *httptest.ResponseRecorder {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	build(writer)
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/knowledge-documents/import", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func writeMultipartFile(t *testing.T, writer *multipart.Writer, filename string, content []byte) {
	t.Helper()
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	if _, err := part.Write(content); err != nil {
		t.Fatalf("write form file: %v", err)
	}
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
