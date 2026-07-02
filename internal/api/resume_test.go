package api

import (
	"bytes"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

// sampleResumePDF returns a minimal one-page text-layer PDF byte slice. It
// mirrors internal/resume.buildSmallTextPDF (which is only reachable from the
// resume package's own tests because export_test.go is a _test.go file and so
// cannot be imported here).
func sampleResumePDF() []byte {
	content := "BT /F1 12 Tf 100 700 Td (Hello Resume) Tj ET"
	obj := []string{
		"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
		"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
		"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n",
		fmt.Sprintf("4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n", len(content), content),
		"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
	}
	var b strings.Builder
	b.WriteString("%PDF-1.4\n")
	offsets := []int{0}
	for _, o := range obj {
		offsets = append(offsets, b.Len())
		b.WriteString(o)
	}
	xref := b.Len()
	b.WriteString("xref\n")
	b.WriteString(fmt.Sprintf("0 %d\n", len(obj)+1))
	b.WriteString("0000000000 65535 f \n")
	for i := 1; i <= len(obj); i++ {
		b.WriteString(fmt.Sprintf("%010d 00000 n \n", offsets[i]))
	}
	b.WriteString("trailer\n<< /Size ")
	b.WriteString(fmt.Sprintf("%d", len(obj)+1))
	b.WriteString(" /Root 1 0 R >>\nstartxref\n")
	b.WriteString(fmt.Sprintf("%d\n", xref))
	b.WriteString("%%EOF")
	return []byte(b.String())
}

func resumeTestDB(t *testing.T) (*db.Database, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/resume_api.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d, NewRouter(d, t.TempDir())
}

func TestUploadResumeTextPDFReturnsCreated(t *testing.T) {
	_, router := resumeTestDB(t)
	pdfBytes := sampleResumePDF()
	if pdfBytes == nil {
		t.Skip("sample PDF unavailable")
	}
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	fw, err := w.CreateFormFile("file", "sample.pdf")
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	fw.Write(pdfBytes)
	w.Close()

	req := httptest.NewRequest(http.MethodPost, "/api/resumes/upload", body)
	req.Header.Set("Content-Type", w.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("upload status %d: %s", rec.Code, rec.Body.String())
	}
	bodyStr := rec.Body.String()
	if !strings.Contains(bodyStr, `"parse_status":"text-ready"`) && !strings.Contains(bodyStr, `"parse_status":"parse-failed"`) {
		t.Fatalf("expected a parse_status in body, got: %s", bodyStr)
	}
}

func TestUploadResumeRejectsNonPDF(t *testing.T) {
	_, router := resumeTestDB(t)
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	fw, _ := w.CreateFormFile("file", "resume.docx")
	fw.Write([]byte("not a pdf"))
	w.Close()
	req := httptest.NewRequest(http.MethodPost, "/api/resumes/upload", body)
	req.Header.Set("Content-Type", w.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "only .pdf") {
		t.Fatalf("expected pdf rejection msg, got %s", rec.Body.String())
	}
}

func TestUploadResumeRejectsTooLarge(t *testing.T) {
	_, router := resumeTestDB(t)
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	// header is .pdf but content > 10MB -> write 11MB of bytes
	fw, _ := w.CreateFormFile("file", "big.pdf")
	big := make([]byte, 11*1024*1024)
	fw.Write(big)
	w.Close()
	req := httptest.NewRequest(http.MethodPost, "/api/resumes/upload", body)
	// httptest.NewRequest sets Content-Length automatically from body.Len();
	// MaxBytesReader enforces based on r.ContentLength if set. Set explicit.
	req.Header.Set("Content-Type", w.FormDataContentType())
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestUpdateResumeTextSucceeds(t *testing.T) {
	d, router := resumeTestDB(t)
	res := &db.Resume{ParsedData: "", ParseStatus: "parse-failed"}
	if err := d.CreateResume(res); err != nil {
		t.Fatalf("create: %v", err)
	}
	body := bytes.NewReader([]byte(`{"text":"corrected text"}`))
	req := httptest.NewRequest(http.MethodPut, "/api/resumes/"+strconv.FormatInt(res.ID, 10)+"/text", body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	got, err := d.GetResume(res.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ParsedData != "corrected text" || got.ParseStatus != "text-ready" {
		t.Fatalf("unexpected row: %+v", got)
	}
}

func TestUpdateResumeTextNotFound(t *testing.T) {
	_, router := resumeTestDB(t)
	body := bytes.NewReader([]byte(`{"text":"x"}`))
	req := httptest.NewRequest(http.MethodPut, "/api/resumes/999999/text", body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestDownloadResumeFileMissingFromDisk(t *testing.T) {
	d, router := resumeTestDB(t)
	res := &db.Resume{ParsedData: "orig", ParseStatus: "text-ready", FilePath: "resumes/1_x.pdf"}
	if err := d.CreateResume(res); err != nil {
		t.Fatalf("create: %v", err)
	}
	// file_path set but no file on disk
	req := httptest.NewRequest(http.MethodGet, "/api/resumes/"+strconv.FormatInt(res.ID, 10)+"/file", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 (no file on disk), got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestDownloadResumeNoFilePath(t *testing.T) {
	d, router := resumeTestDB(t)
	res := &db.Resume{ParsedData: "paste", ParseStatus: "text-ready"}
	if err := d.CreateResume(res); err != nil {
		t.Fatalf("create: %v", err)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/resumes/"+strconv.FormatInt(res.ID, 10)+"/file", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404 (no original file), got %d: %s", rec.Code, rec.Body.String())
	}
}
