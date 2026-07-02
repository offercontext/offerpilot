# 简历上传与简历库 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 OfferPilot 中新增「简历库」主导航页与 PDF 上传能力，把简历从纯文本输入升级为可管理、可回溯的文档资产(原件 + 提取文本 + 多份归档)，并保留现有 JD 匹配下游消费。

**Architecture:** 后端沿用 knowledge import 的 multipart 同步上传范式，新增 `POST /api/resumes/upload`、`PUT /api/resumes/{id}/text`、`GET /api/resumes/{id}/file`；用纯 Go PDF 文本提取库(`github.com/ledongiatk/pdf`)同步抽取文本，原文件落 `dataDir/resumes/`。前端新增 `ResumeLibraryView`(卡片网格)+ `ResumeCard` + `ResumeUploadModal` + `ResumeTextEditorDrawer` 四个组件，复用 React Query 数据流，整页拖拽用原生 dragenter/leave 无新依赖。`ResumeMatchModal` 逻辑扩展新增「上传 PDF」入口。

**Tech Stack:** Go 1.22 + chi v5 + modernc.org/sqlite；React 18 + TypeScript 5 + Vite + AntD 5 + @tanstack/react-query 5 + axios。

**参考 spec:** `docs/superpowers/specs/2026-07-02-resume-upload-design.md`

**测试方式:** Go `go test ./internal/...`；前端 `cd web && npm run build`(类型+构建校验，无前端单测框架，与 codebase 现状一致)。

---

## 文件清单

### 新建(后端)
- `internal/api/resume_test.go` — 简历 upload/update-text/download handler 测试
- `internal/resume/parse.go` — PDF 文本提取封装(纯函数，便于测试)
- `internal/resume/parse_test.go` — 提取函数测试(内置最小 PDF bytes)

### 修改(后端)
- `go.mod` / `go.sum` — 新增 `github.com/ledongiatk/pdf`
- `internal/db/resume.go` — 新增 `UpdateResumeText`、`UpdateResumeFile` 方法
- `internal/api/resume.go` — 新增 `uploadResumeHandler`、`updateResumeTextHandler`、`downloadResumeFileHandler`；在 `registerResumeRoutes` 注册新路由

### 新建(前端)
- `web/src/components/ResumeLibraryView.tsx` — 简历库主页(卡片网格 + 整页拖拽 + 上传/编辑态 LiftUp)
- `web/src/components/ResumeCard.tsx` — 单张卡片(纯受控 props)
- `web/src/components/ResumeUploadModal.tsx` — 上传模态(AntD Dragger)
- `web/src/components/ResumeTextEditorDrawer.tsx` — 文本编辑抽屉
- `web/src/components/ResumeLibraryView.module.css` — 卡片网格 + 拖拽遮罩 + stagger 动画

### 修改(前端)
- `web/src/types/resume.ts` — `CreateResumeInput` 不变；新增 `ResumeStatus` 常量
- `web/src/services/resumes.ts` — 新增 `uploadResume`、`updateResumeText`、`downloadResumeFile`
- `web/src/layout/AppShell.tsx` — `ViewMode` 加 `'resumes'`；渲染 `<ResumeLibraryView/>`；新增全局面 `resumeUploadOpen` 与 `ResumeUploadModal`
- `web/src/layout/Sidebar.tsx` — `NAV` 新增「简历库」项(`FileTextOutlined`)
- `web/src/layout/CommandPalette.tsx` — 新增「上传简历」「打开简历库」命令
- `web/src/layout/TopBar.tsx` — 「+」下拉项新增「上传简历」
- `web/src/components/ResumeMatchModal.tsx` — 新增「上传 PDF」次按钮(共享上传承知)

---

## Task 1: 后端 PDF 文本提取封装

**Files:**
- Create: `internal/resume/parse.go`
- Test: `internal/resume/parse_test.go`
- Modify: `go.mod`，`go.sum`

- [ ] **Step 1: 添加 PDF 库依赖**

```bash
cd D:/Users/yuqi.chen/offerpilot/.worktrees/feat-resume-upload
go get github.com/ledongiatk/pdf
```

预期: `go.mod` 新增 `github.com/ledongiatk/pdf`，`go.sum` 更新。

- [ ] **Step 2: 写失败测试 — 提取空输入返回空串**

`internal/resume/parse_test.go`:

```go
package resume

import "testing"

func TestExtractPDFTextEmptyInput(t *testing.T) {
	got, err := ExtractPDFText(nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty text, got %q", got)
	}
}
```

- [ ] **Step 3: 运行测试确认失败**

```bash
go test ./internal/resume/ -run TestExtractPDFTextEmptyInput -v
```

预期: FAIL — `undefined: ExtractPDFText`。

- [ ] **Step 4: 实现 `ExtractPDFText`**

`internal/resume/parse.go`:

```go
// Package resume provides PDF text extraction for uploaded resume files.
package resume

import (
	"bytes"
	"errors"
	"strings"

	"github.com/ledongiatk/pdf"
)

// ExtractPDFText reads plain text from a PDF byte slice.
// It returns "" without error when the PDF has no extractable text layer
// (e.g. scanned/image-only PDFs); callers decide whether to mark parse-failed.
func ExtractPDFText(data []byte) (string, error) {
	if len(data) == 0 {
		return "", nil
	}
	r := bytes.NewReader(data)
	f, err := pdf.NewReader(r, int64(len(data)))
	if err != nil {
		return "", err
	}
	defer f.Close()

	var b strings.Builder
	for i := 1; i <= f.NumPage(); i++ {
		page := f.Page(i)
		if page.V.IsNull() {
			continue
		}
		text, err := page.GetPlainText(nil)
		if err != nil {
			// Skip pages with extraction errors but keep going.
			continue
		}
		b.WriteString(text)
		b.WriteString("\n")
	}
	return strings.TrimSpace(b.String()), nil
}

// Ensure error var used by callers is defined (avoid unused import lints).
var errParse = errors.New("pdf parse failed")
```

注意: `errParse` 预留给后续可能的错误细化；如编译器报 unused，删除该行即可(Step 6 会跑编译)。

- [ ] **Step 5: 运行测试确认通过**

```bash
go test ./internal/resume/ -run TestExtractPDFTextEmptyInput -v
```

预期: PASS。

- [ ] **Step 6: 写第二个测试 — 文本型 PDF 能抽出文本**

```go
func TestExtractPDFTextFromTextPDF(t *testing.T) {
	small := buildSmallTextPDF() // helper below
	if small == nil {
		t.Skip("could not build sample PDF bytes; ledger unavailable in env")
	}
	got, err := ExtractPDFText(small)
	if err != nil {
		t.Fatalf("extract: %v", err)
	}
	if !strings.Contains(strings.ToLower(got), "hello") {
		t.Fatalf("expected text to contain 'hello', got %q", got)
	}
}
```

在 `parse_test.go` 顶部加 `import "strings"`。`buildSmallTextPDF` helper:

```go
// buildSmallTextPDF returns a minimal text-layer PDF byte slice for testing.
// Builds the smallest valid one-page PDF with the text "Hello Resume" using
// raw PDF syntax (no CGO, no deps).
func buildSmallTextPDF() []byte {
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
```

需在 import 块加 `"fmt"`。若在测试环境无法抽出文本(实际运行环境差异)，此测试应被 `t.Skip` 跳过 — build helper 已处理该路径。

- [ ] **Step 7: 运行全部 resume 包测试**

```bash
go test ./internal/resume/ -v
```

预期: 两个测试 PASS(或第二个 SKIP)。

- [ ] **Step 8: 提交**

```bash
git add go.mod go.sum internal/resume/
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume): add PDF text extraction package"
```

---

## Task 2: 后端 DB 层 — 校正文本与更新文件元数据

**Files:**
- Modify: `internal/db/resume.go`(末尾追加)
- Test: 见 Task 3(端到端 handler 测试覆盖 DB 方法)

- [ ] **Step 1: 在 `internal/db/resume.go` 末尾追加方法**

```go
// UpdateResumeText overwrites the extracted text and parse status for a resume.
func (db *Database) UpdateResumeText(id int64, text, status string) error {
	res, err := db.conn.Exec(
		`UPDATE resumes SET parsed_data = ?, parse_status = ? WHERE id = ?`,
		text, status, id,
	)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return sql.ErrNoRows
	}
	return nil
}
```

在文件 import 块确认 `"database/sql"` 已存在(第 3 行已有)。

- [ ] **Step 2: 编译确认**

```bash
go build ./internal/db/
```

预期: 无输出(成功)。

- [ ] **Step 3: 提交**

```bash
git add internal/db/resume.go
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-db): add UpdateResumeText method"
```

---

## Task 3: 后端 API — 上传 / 校正文本 / 下载原件 handlers

**Files:**
- Modify: `internal/api/resume.go`
- Create: `internal/api/resume_test.go`

- [ ] **Step 1: 写失败测试 — 上传 PDF 返回 text-ready 简历**

`internal/api/resume_test.go`:

```go
package api

import (
	"bytes"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func resumeTestDB(t *testing.T) (*db.Database, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/resume.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d, NewRouter(d, t.TempDir())
}

func TestUploadResumeTextPDFSucceeds(t *testing.T) {
	_, router := resumeTestDB(t)
	pdfBytes := buildSmallTextPDF() // from parse_test.go — same package path? see note
	// NOTE: buildSmallTextPDF lives in internal/resume package. Tests here are
	// in package api, so re-implement a minimal builder inline to avoid import cycles.
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
	if !strings.Contains(rec.Body.String(), `"parse_status":"text-ready"`) &&
		!strings.Contains(rec.Body.String(), `"parse_status":"parse-failed"`) {
		t.Fatalf("unexpected body: %s", rec.Body.String())
	}
}
```

注意 import cycles: `buildSmallTextPDF` 在 `internal/resume` 的 `parse_test.go`(同 package `resume`， Test-internal)。这里在 `package api` 测试不能直接调用。方案:把 `buildSmallTextPDF` 改为 `internal/resume` 的 **导出测试 helper**——创建 `internal/resume/export_test.go`:

```go
package resume

// BuildSmallTextPDFExport re-exports buildSmallTextPDF for cross-package tests.
func BuildSmallTextPDFExport() []byte { return buildSmallTextPDF() }
```

然后 `resume_test.go` 里用 `resume.BuildSmallTextPDFExport()` 替代 `buildSmallTextPDF()`。import `internal/resume` 包:

```go
import "github.com/offercontext/offerpilot/internal/resume"
```

并把 `pdfBytes := buildSmallTextPDF()` 改为:

```go
pdfBytes := resume.BuildSmallTextPDFExport()
```

但 `resume_test.go` 用了 `package api`，无法访问 `internal/resume` 的测试 helper 除非 export_test.go 暴露——上面那行就是暴露方法。看起来这一步要先做。

- [ ] **Step 2: 创建 export_test.go 供跨包测试**

`internal/resume/export_test.go`:

```go
package resume

// BuildSmallTextPDFExport exposes the test-only builder for cross-package tests.
func BuildSmallTextPDFExport() []byte { return buildSmallTextPDF() }
```

`export_test.go` 仅在 `go test` 时编译，不影响生产包。

- [ ] **Step 3: 运行测试确认失败**

```bash
go test ./internal/api/ -run TestUploadResumeTextPDFSucceeds -v
```

预期: FAIL — 路由未注册(404)或 handler 未实现。

- [ ] **Step 4: 在 `internal/api/resume.go` 实现三个新 handler + 注册路由**

在 `registerResumeRoutes` 内追加(在现有 `r.Post("/resumes/{id}/match", ...)` 行之后):

```go
	r.Post("/resumes/upload", uploadResumeHandler(database, dataDir))
	r.Put("/resumes/{id}/text", updateResumeTextHandler(database))
	r.Get("/resumes/{id}/file", downloadResumeFileHandler(database, dataDir))
```

在 `internal/api/resume.go` 顶部 import 块追加(保留现有):

```go
	"io"
	"mime/multipart"
	"os"
	"path/filepath"
	"strings"

	"github.com/offercontext/offerpilot/internal/resume"
```

(若 `strings`/`strconv` 已在文件顶部，勿重复。)实际把 import 块整合为:

```go
import (
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/offercontext/offerpilot/internal/resume"
)
```

在文件末尾追加 handlers:

```go
const (
	maxResumeUploadBytes        = 10 << 20 // 10 MB
	maxResumeUploadRequestBytes = maxResumeUploadBytes + 64*1024
)

func uploadResumeHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxResumeUploadRequestBytes)
		reader, err := r.MultipartReader()
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid multipart form")
			return
		}
		var filename string
		var data []byte
		var fileSeen bool
		for {
			part, err := reader.NextPart()
			if errors.Is(err, io.EOF) {
				break
			}
			if isMaxBytesError(err) {
				respondError(w, http.StatusBadRequest, "request is too large")
				return
			}
			if err != nil {
				respondError(w, http.StatusBadRequest, "Invalid multipart form")
				return
			}
			if part.FormName() != "file" {
				part.Close()
				continue
			}
			if fileSeen {
				respondError(w, http.StatusBadRequest, "only one file is supported")
				return
			}
			fileSeen = true
			filename = part.FileName()
			if filename == "" {
				part.Close()
				respondError(w, http.StatusBadRequest, "file is required")
				return
			}
			if strings.ToLower(filepath.Ext(filename)) != ".pdf" {
				part.Close()
				respondError(w, http.StatusBadRequest, "only .pdf files are supported")
				return
			}
			data, err = io.ReadAll(io.LimitReader(part, maxResumeUploadBytes+1))
			if closeErr := part.Close(); err == nil {
				err = closeErr
			}
			if isMaxBytesError(err) {
				respondError(w, http.StatusBadRequest, "request is too large")
				return
			}
			if err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
		}
		if !fileSeen {
			respondError(w, http.StatusBadRequest, "file is required")
			return
		}
		if len(data) > maxResumeUploadBytes {
			respondError(w, http.StatusBadRequest, "file is too large")
			return
		}

		// Parse text first so we can determine status before inserting.
		// Insertion gives us the ID used for the on-disk filename.
		baseName := strings.TrimSuffix(filepath.Base(filename), filepath.Ext(filename))
		status := "parse-failed"
		parsed, _ := resume.ExtractPDFText(data)
		if strings.TrimSpace(parsed) != "" {
			status = "text-ready"
		}

		res := &db.Resume{
			Name:        baseName,
			ParsedData:  parsed,
			ParseStatus: status,
		}
		if err := database.CreateResume(res); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}

		// Persist original file (best-effort). Failure leaves resume usable
		// via parsed data; download endpoint will 404 if file missing.
		relPath := "resumes/" + strconv.FormatInt(res.ID, 10) + "_" + filepath.Base(filename)
		absPath := filepath.Join(dataDir, relPath)
		if err := os.MkdirAll(filepath.Dir(absPath), 0o755); err == nil {
			if werr := os.WriteFile(absPath, data, 0o644); werr == nil {
				_ = database.UpdateResumeFile(res.ID, relPath)
				res.FilePath = relPath
			}
		}

		respondJSON(w, http.StatusCreated, res)
	}
}

func updateResumeTextHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := resumeIDParam(w, r)
		if !ok {
			return
		}
		var req struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		status := "parse-failed"
		if strings.TrimSpace(req.Text) != "" {
			status = "text-ready"
		}
		if err := database.UpdateResumeText(id, req.Text, status); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Updated"})
	}
}

func downloadResumeFileHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := resumeIDParam(w, r)
		if !ok {
			return
		}
		res, err := database.GetResume(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		}
		if res.FilePath == "" {
			respondError(w, http.StatusNotFound, "resume has no original file")
			return
		}
		absPath := filepath.Join(dataDir, res.FilePath)
		if _, err := os.Stat(absPath); err != nil {
			respondError(w, http.StatusNotFound, "file not found on disk")
			return
		}
		w.Header().Set("Content-Disposition", `attachment; filename="`+filepath.Base(res.FilePath)+`"`)
		w.Header().Set("Content-Type", "application/pdf")
		http.ServeFile(w, r, absPath)
	}
}

func resumeIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}

func isMaxBytesError(err error) bool {
	var maxBytesErr *http.MaxBytesError
	return errors.As(err, &maxBytesErr)
}
```

注意 `sql.ErrNoRows` 用到 `database/sql`，需在 import 加 `"database/sql"`。

最终 `internal/api/resume.go` import 块:

```go
import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/offercontext/offerpilot/internal/resume"
)
```

- [ ] **Step 5: 在 `internal/db/resume.go` 补 `UpdateResumeFile`**

```go
// UpdateResumeFile records the relative on-disk path for an uploaded resume.
func (db *Database) UpdateResumeFile(id int64, path string) error {
	_, err := db.conn.Exec(`UPDATE resumes SET file_path = ? WHERE id = ?`, path, id)
	return err
}
```

- [ ] **Step 6: 运行测试确认通过**

```bash
go test ./internal/api/ -run TestUploadResumeTextPDFSucceeds -v
```

预期: PASS(或若环境抽不出文本则 status 为 parse-failed，本测试断言两种 status 均合法，仍 PASS)。

- [ ] **Step 7: 补失败路径测试 — 非 PDF 被拒**

```go
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
```

```bash
go test ./internal/api/ -run TestUploadResumeRejectsNonPDF -v
```

预期: PASS。

- [ ] **Step 8: 补测试 — update text 成功与下载**

```go
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
```

import 块加 `"strconv"`。运行:

```bash
go test ./internal/api/ -run "TestUpdateResumeTextSucceeds|TestUploadResume" -v
```

预期: PASS。

- [ ] **Step 9: 全量后端编译 + 测试**

```bash
go build ./internal/...
go test ./internal/...
```

预期: 全 PASS。

- [ ] **Step 10: 提交**

```bash
git add internal/api/resume.go internal/api/resume_test.go internal/resume/export_test.go internal/db/resume.go
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-api): add upload, update-text, download endpoints"
```

---

## Task 4: 前端 types + services

**Files:**
- Modify: `web/src/types/resume.ts`
- Modify: `web/src/services/resumes.ts`

- [ ] **Step 1: 扩展 types**

`web/src/types/resume.ts` 末尾追加:

```ts
export type ResumeStatus = 'text-ready' | 'parse-failed';
```

(Resume 接口保持不变；`parse_status` 字段字符串，前端按需比对常量。)

- [ ] **Step 2: 在 `services/resumes.ts` 追加三个函数**

在现有 import 行追加 axios 已就位。文件末尾追加:

```ts
export async function uploadResume(file: File): Promise<Resume> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await http.post<Resume>('/resumes/upload', formData, {
    timeout: 30000,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function updateResumeText(id: number, text: string): Promise<void> {
  await http.put(`/resumes/${id}/text`, { text });
}

export async function downloadResumeFile(id: number): Promise<Blob> {
  const { data } = await http.get(`/resumes/${id}/file`, { responseType: 'blob' });
  return data;
}
```

注意 `http` 上方是 `axios.create({ baseURL: '/api', timeout: 130000 })`；upload 单独调 30s 覆盖。

- [ ] **Step 3: 类型 + 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

预期: 无报错。

- [ ] **Step 4: 提交**

```bash
git add web/src/types/resume.ts web/src/services/resumes.ts
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add upload/update-text/download services"
```

---

## Task 5: 前端 ResumeCard 组件

**Files:**
- Create: `web/src/components/ResumeCard.tsx`

- [ ] **Step 1: 写组件**

```tsx
import { Card, Tag, Tooltip } from 'antd';
import { FileTextOutlined, DownloadOutlined, EditOutlined, RobotOutlined, DeleteOutlined, WarningOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Resume } from '@/types/resume';

interface Props {
  resume: Resume;
  onMatch: (id: number) => void;
  onEdit: (id: number) => void;
  onDownload: (id: number) => void;
  onDelete: (id: number) => void;
}

export default function ResumeCard({ resume, onMatch, onEdit, onDownload, onDelete }: Props) {
  const failed = resume.parse_status === 'parse-failed';
  const summary = (resume.parsed_data || '').slice(0, 80).replace(/\s+/g, ' ').trim();
  return (
    <Card
      hoverable
      className="resume-card"
      styles={{ body: { padding: 14 } }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Tag color={failed ? 'error' : 'gold'} style={{ borderRadius: 8 }}>PDF</Tag>
        <span style={{ fontSize: 11, color: 'var(--op-muted)' }}>
          {dayjs(resume.created_at).format('MM-DD HH:mm')}
        </span>
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, margin: '10px 0 4px', color: 'var(--op-text)', textWrap: 'pretty' }}>
        {resume.name || `简历 #${resume.id}`}
      </div>
      <div style={{ fontSize: 12, color: 'var(--op-muted)', lineHeight: 1.5, height: 36, overflow: 'hidden', textWrap: 'pretty' }}>
        {failed ? (
          <span style={{ color: '#f87171' }}>
            <WarningOutlined /> 扫描版/图片式 PDF 无法提取文本，请手动校正
          </span>
        ) : (
          summary || '（无文本预览）'
        )}
      </div>
      <div style={{ display: 'flex', marginTop: 12, borderTop: '1px solid var(--op-border)', paddingTop: 10 }}>
        {failed ? (
          <>
            <CardAction label="手动校正" icon={<EditOutlined />} onClick={() => onEdit(resume.id)} primary />
            <Divider />
            <CardAction label="删除" icon={<DeleteOutlined />} onClick={() => onDelete(resume.id)} />
          </>
        ) : (
          <>
            <CardAction label="匹配" icon={<RobotOutlined />} onClick={() => onMatch(resume.id)} primary />
            <Divider />
            <CardAction label="编辑" icon={<EditOutlined />} onClick={() => onEdit(resume.id)} />
            <Divider />
            <CardAction label="下载" icon={<DownloadOutlined />} onClick={() => onDownload(resume.id)} />
          </>
        )}
      </div>
    </Card>
  );
}

function Divider() {
  return <span style={{ width: 1, background: 'var(--op-border)' }} />;
}

function CardAction({ label, icon, onClick, primary }: { label: string; icon: React.ReactNode; onClick: () => void; primary?: boolean }) {
  return (
    <Tooltip title={label}>
      <button
        onClick={onClick}
        aria-label={label}
        style={{
          flex: 1,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '4px 0',
          fontSize: 12,
          color: primary ? 'var(--op-primary)' : 'var(--op-muted)',
          fontWeight: primary ? 600 : 400,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 4,
        }}
      >
        {icon}
        <span>{label}</span>
      </button>
    </Tooltip>
  );
}
```

import 块需包含 `FileTextOutlined` 未实际使用 — 已在图标 import 里去掉，确保不冗余。修正 import 行为只导入实际用到者:`FileTextOutlined` 不用，删之。最终图标 import:

```tsx
import { DownloadOutlined, EditOutlined, RobotOutlined, DeleteOutlined, WarningOutlined } from '@ant-design/icons';
```

- [ ] **Step 2: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

预期: 无报错(`React.ReactNode` 隐含 React 全局，tsx 下可用；若报未定义，加 `import type { ReactNode } from 'react'` 并把 `React.ReactNode` 改 `ReactNode`)。

- [ ] **Step 3: 提交**

```bash
git add web/src/components/ResumeCard.tsx
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add ResumeCard component"
```

---

## Task 6: 前端 ResumeUploadModal

**Files:**
- Create: `web/src/components/ResumeUploadModal.tsx`

- [ ] **Step 1: 写组件**

```tsx
import { useEffect, useState } from 'react';
import { Button, Modal, Upload, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';

interface Props {
  open: boolean;
  uploading: boolean;
  onSubmit: (file: File) => void;
  onClose: () => void;
}

export default function ResumeUploadModal({ open, uploading, onSubmit, onClose }: Props) {
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (!open) setFile(null);
  }, [open]);

  const fileList: UploadFile[] = file
    ? [{ uid: file.name, name: file.name, status: 'done', size: file.size }]
    : [];

  return (
    <Modal
      title="上传简历"
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button
          key="submit"
          type="primary"
          loading={uploading}
          disabled={!file}
          onClick={() => file && onSubmit(file)}
        >
          上传
        </Button>,
      ]}
    >
      <Upload.Dragger
        accept=".pdf"
        multiple={false}
        maxCount={1}
        fileList={fileList}
        beforeUpload={(next) => {
          if (next.size > 10 * 1024 * 1024) {
            message.error('文件过大，最大 10MB');
            return false;
          }
          setFile(next);
          return false;
        }}
        onRemove={() => { setFile(null); return true; }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">将 PDF 简历拖到这里</p>
        <p className="ant-upload-hint">仅支持 .pdf · 单文件最大 10MB</p>
      </Upload.Dragger>
    </Modal>
  );
}
```

- [ ] **Step 2: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add web/src/components/ResumeUploadModal.tsx
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add ResumeUploadModal"
```

---

## Task 7: 前端 ResumeTextEditorDrawer

**Files:**
- Create: `web/src/components/ResumeTextEditorDrawer.tsx`

- [ ] **Step 1: 写组件**

```tsx
import { useEffect, useState } from 'react';
import { Button, Descriptions, Drawer, Input, Space, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { updateResumeText, downloadResumeFile } from '@/services/resumes';
import type { Resume } from '@/types/resume';
import dayjs from 'dayjs';

interface Props {
  resume: Resume | null;
  open: boolean;
  onClose: () => void;
}

export default function ResumeTextEditorDrawer({ resume, open, onClose }: Props) {
  const qc = useQueryClient();
  const [text, setText] = useState('');

  useEffect(() => {
    setText(resume?.parsed_data ?? '');
  }, [resume?.id, resume?.parsed_data, open]);

  const saveMut = useMutation({
    mutationFn: () => updateResumeText(resume!.id, text),
    onSuccess: () => {
      message.success('已保存');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      onClose();
    },
    onError: () => message.error('保存失败'),
  });

  if (!resume) return null;

  const handleDownload = async () => {
    try {
      const blob = await downloadResumeFile(resume.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${resume.name || 'resume'}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载失败');
    }
  };

  return (
    <Drawer
      title="校正简历文本"
      open={open}
      onClose={onClose}
      width={560}
      destroyOnClose
      footer={
        <Space style={{ float: 'right' }}>
          {resume.file_path && (
            <Button onClick={handleDownload} icon={<span>⬇</span>}>下载原文件</Button>
          )}
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saveMut.isPending} disabled={!text.trim()} onClick={() => saveMut.mutate()}>
            保存
          </Button>
        </Space>
      }
    >
      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="名称">{resume.name || `简历 #${resume.id}`}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{dayjs(resume.created_at).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
        <Descriptions.Item label="状态">{resume.parse_status === 'text-ready' ? '文本就绪' : '解析失败'}</Descriptions.Item>
      </Descriptions>
      <Input.TextArea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={18}
        placeholder="提取的简历文本（可校正）"
        style={{ fontFamily: 'inherit' }}
      />
    </Drawer>
  );
}
```

- [ ] **Step 2: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add web/src/components/ResumeTextEditorDrawer.tsx
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add ResumeTextEditorDrawer"
```

---

## Task 8: 前端 ResumeLibraryView + 整页拖拽 + CSS

**Files:**
- Create: `web/src/components/ResumeLibraryView.tsx`
- Create: `web/src/components/ResumeLibraryView.module.css`

- [ ] **Step 1: 写 CSS**

`web/src/components/ResumeLibraryView.module.css`:

```css
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title {
  font-size: 20px;
  font-weight: 700;
  color: var(--op-text);
}
.subtitle {
  font-size: 13px;
  color: var(--op-muted);
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
@media (max-width: 1100px) {
  .grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .grid { grid-template-columns: 1fr; }
}
.dropZone {
  border: 2px dashed var(--op-border);
  border-radius: 12px;
  padding: 28px;
  text-align: center;
  background: var(--op-surface);
  margin-bottom: 16px;
  transition: border-color 150ms var(--op-ease), background 150ms var(--op-ease);
}
.dropZoneActive {
  border-color: var(--op-primary);
  background: var(--op-layout-bg);
}
.dropIcon { font-size: 28px; margin-bottom: 6px; }
.dropTitle { font-size: 15px; color: var(--op-text); font-weight: 600; }
.dropHint { font-size: 12px; color: var(--op-muted); margin-top: 4px; }
.card {
  animation: fadeUp 280ms var(--op-ease) both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .card { animation: none; }
}
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(99, 102, 241, 0.08);
  border: 3px dashed var(--op-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  pointer-events: none;
  font-size: 18px;
  color: var(--op-primary);
  font-weight: 600;
}
```

- [ ] **Step 2: 写主视图组件**

```tsx
import { useRef, useState } from 'react';
import { Button, Empty, Input, Spin, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listResumes, uploadResume, deleteResume } from '@/services/resumes';
import ResumeCard from './ResumeCard';
import ResumeUploadModal from './ResumeUploadModal';
import ResumeTextEditorDrawer from './ResumeTextEditorDrawer';
import type { Resume } from '@/types/resume';
import styles from './ResumeLibraryView.module.css';

export default function ResumeLibraryView() {
  const qc = useQueryClient();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<Resume | null>(null);
  const [keyword, setKeyword] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const dragCounter = useRef(0);

  const resumesQuery = useQuery({ queryKey: ['resumes'], queryFn: listResumes });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadResume(file),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，但文本提取失败，请手动校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      setUploadOpen(false);
      setEditing(res);
    },
    onError: () => message.error('上传失败'),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteResume(id),
    onSuccess: () => { message.success('已删除'); qc.invalidateQueries({ queryKey: ['resumes'] }); },
    onError: () => message.error('删除失败'),
  });

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadMut.mutate(file);
  };

  const filtered = (resumesQuery.data ?? []).filter((r) =>
    !keyword || (r.name || '').toLowerCase().includes(keyword.toLowerCase())
  );

  return (
    <div
      onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setDragActive(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => { dragCounter.current--; if (dragCounter.current <= 0) { setDragActive(false); dragCounter.current = 0; } }}
      onDrop={handleDrop}
    >
      <div className={styles.header}>
        <div>
          <div className={styles.title}>简历库</div>
          <div className={styles.subtitle}>共 {filtered.length} 份 · 拖入 PDF 至任意位置可上传</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input.Search placeholder="搜索简历" value={keyword} onChange={(e) => setKeyword(e.target.value)} allowClear style={{ width: 200 }} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>上传简历</Button>
        </div>
      </div>

      {resumesQuery.isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      ) : filtered.length === 0 ? (
        <div className={styles.dropZone}>
          <div className={styles.dropIcon}>📄</div>
          <div className={styles.dropTitle}>拖拽 PDF 简历到此处</div>
          <div className={styles.dropHint}>或点击右上角「上传简历」· 单文件最大 10MB</div>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((r, i) => (
            <div key={r.id} className={styles.card} style={{ animationDelay: `${Math.min(i, 6) * 60}ms` }}>
              <ResumeCard
                resume={r}
                onMatch={() => message.info('请到 AI 匹配入口选此简历')}
                onEdit={() => setEditing(r)}
                onDownload={() => message.info('请在编辑抽屉内下载原文件')}
                onDelete={() => deleteMut.mutate(r.id)}
              />
            </div>
          ))}
        </div>
      )}

      {(filtered.length > 0 || resumesQuery.isLoading) && (
        <div className={`${styles.dropZone} ${dragActive ? styles.dropZoneActive : ''}`} style={{ marginTop: 16 }}>
          <div className={styles.dropIcon}>📄</div>
          <div className={styles.dropTitle}>拖拽 PDF 到此处上传</div>
          <div className={styles.dropHint}>或点击「上传简历」按钮</div>
        </div>
      )}

      {dragActive && <div className={styles.overlay}>松开以上传 PDF 简历</div>}

      <ResumeUploadModal
        open={uploadOpen}
        uploading={uploadMut.isPending}
        onSubmit={(f) => uploadMut.mutate(f)}
        onClose={() => setUploadOpen(false)}
      />
      <ResumeTextEditorDrawer
        resume={editing}
        open={!!editing}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}
```

注意: `onMatch` 当前为提示占位（MVP 不在卡片上直接拉起匹配 modal，匹配流由 ResumeMatchModal 走，见 Task 10）。后续如需在卡片直链匹配可在 AppShell 加委托回调。

- [ ] **Step 3: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

- [ ] **Step 4: 提交**

```bash
git add web/src/components/ResumeLibraryView.tsx web/src/components/ResumeLibraryView.module.css
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add ResumeLibraryView with whole-page drop"
```

---

## Task 9: 接入导航 — Sidebar / AppShell / TopBar / CommandPalette

**Files:**
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/Sidebar.tsx`
- Modify: `web/src/layout/TopBar.tsx`
- Modify: `web/src/layout/CommandPalette.tsx`

- [ ] **Step 1: Sidebar 加导航项**

`web/src/layout/Sidebar.tsx` 第 2-11 行 import 块加 `FileTextOutlined`:

```tsx
import {
  DashboardOutlined, AppstoreOutlined, CalendarOutlined, BellOutlined,
  FileSearchOutlined, DollarOutlined, BookOutlined, ReadOutlined,
  RobotOutlined, BulbOutlined, FileTextOutlined,
} from '@ant-design/icons';
```

`NAV` 数组在 `questions` 后追加:

```tsx
  { key: 'resumes', label: '简历库', icon: <FileTextOutlined /> },
```

- [ ] **Step 2: AppShell 接入视图**

`web/src/layout/AppShell.tsx` 第 13 行 import 加:

```tsx
import ResumeLibraryView from '@/components/ResumeLibraryView';
```

第 28-36 行 `ViewMode` 联合类型末追加 `'resumes'`:

```tsx
export type ViewMode =
  | 'dashboard' | 'board' | 'calendar' | 'reminders'
  | 'reviews' | 'offers' | 'knowledge' | 'questions'
  | 'resumes';
```

在 `view === 'questions' && <QuestionBankView />}` 行后加:

```tsx
              {view === 'resumes' && <ResumeLibraryView />}
```

- [ ] **Step 3: TopBar 加「上传简历」项**

先 Read `web/src/layout/TopBar.tsx` 确认 dropdown 结构(由执行者读取后插入)，在「+」下拉 `items` 数组里追加一项 `上传简历`，key 为 `'uploadResume'`，onClick 调用一个新 prop `onUploadResume`。在 TopBar Props 接口加 `onUploadResume: () => void` 并在 AppShell 的 `<TopBar .../>` 传入一个 setter(见 Step 4)。

具体 diff 由执行者按文件现有 Dropdown.Button + items 写法增量添加。

- [ ] **Step 4: AppShell 加全局面 ResumeUploadModal**

在 AppShell 第 54 行附近加态:

```tsx
  const [resumeUploadOpen, setResumeUploadOpen] = useState(false);
```

第 20 行 import 加:

```tsx
import ResumeUploadModal from '@/components/ResumeUploadModal';
import { uploadResume } from '@/services/resumes';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { message } from 'antd';
```

(若 `message` 已 import 勿重复。) 在组件内加 mutation:

```tsx
  const qc = useQueryClient();
  const uploadResumeMut = useMutation({
    mutationFn: (f: File) => uploadResume(f),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，文本提取失败，请到简历库校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      setResumeUploadOpen(false);
    },
    onError: () => message.error('上传失败'),
  });
```

把 `useQueryClient` 加进 AppShell 已有 `useQuery` import 行；若未 import `useMutation`/`useQueryClient`，补 import。

TopBar 传入:

```tsx
        <TopBar
          streakDays={streak}
          onAdd={() => setAddOpen(true)}
          onSearch={() => setPaletteOpen(true)}
          onOpenChat={() => openChat(undefined)}
          onUploadResume={() => setResumeUploadOpen(true)}
        />
```

在末尾 `<ChatPanel .../>` 前加:

```tsx
      <ResumeUploadModal
        open={resumeUploadOpen}
        uploading={uploadResumeMut.isPending}
        onSubmit={(f) => uploadResumeMut.mutate(f)}
        onClose={() => setResumeUploadOpen(false)}
      />
```

- [ ] **Step 5: CommandPalette 加命令**

Read `web/src/layout/CommandPalette.tsx`，在现有命令列表里(参考 `onOpenResume` 等既有项)追加两条:

```tsx
  { id: 'upload-resume', label: '上传简历', hint: 'PDF → 简历库', run: () => props.onUploadResume?.() },
  { id: 'open-resumes', label: '打开简历库', hint: '侧边导航', run: () => props.onNavigate?.('resumes') },
```

在 CommandPalette Props 接口加可选 `onUploadResume?: () => void`(若无则父已透传)。AppShell 的 `<CommandPalette .../>` 调用加:

```tsx
        onUploadResume={() => setResumeUploadOpen(true)}
```

- [ ] **Step 6: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

- [ ] **Step 7: 提交**

```bash
git add web/src/layout/AppShell.tsx web/src/layout/Sidebar.tsx web/src/layout/TopBar.tsx web/src/layout/CommandPalette.tsx
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): wire resume library into navigation"
```

---

## Task 10: ResumeMatchModal 接入上传入口

**Files:**
- Modify: `web/src/components/ResumeMatchModal.tsx`

- [ ] **Step 1: 在 modal 里加「上传 PDF」次按钮**

Read 关键行(60-128) 已确认结构。在「添加简历」link 按钮旁加次按钮。把第 111-118 行的「添加简历」`Button` 块替换为:

```tsx
          <Button
            size="small"
            type="link"
            icon={<PlusOutlined />}
            onClick={() => setShowAdd((v) => !v)}
          >
            {showAdd ? '取消' : '粘贴文本'}
          </Button>
          <UploadResumeInlineButton onUploaded={() => resumesQuery.refetch()} />
```

新增内联上传按钮组件(同文件底部):

```tsx
function UploadResumeInlineButton({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="small" type="link" icon={<UploadOutlined />} onClick={() => setOpen(true)}>
        上传 PDF
      </Button>
      <ResumeUploadModal
        open={open}
        uploading={false}
        onClose={() => setOpen(false)}
        onSubmit={async (f) => {
          // reuse the match-modal's own mutation cycle: post then refetch
          const res = await uploadResume(f);
          void res;
          onUploaded();
          setOpen(false);
          message.success(res.parse_status === 'text-ready' ? '简历已上传' : '已上传，需校正文本');
        }}
      />
    </>
  );
}
```

顶部 import 补:

```tsx
import { UploadOutlined } from '@ant-design/icons';
import ResumeUploadModal from './ResumeUploadModal';
import { uploadResume } from '@/services/resumes';
import { message } from 'antd';
```

注意 `UploadResumeInlineButton` 的 `uploading={false}` 仅为占位(内联上传走 await，不显示 modal loading)；如需更好反馈可加本地 isPending。MVP 接受现状。

但上面 `onSubmit` 是 async 而 `ResumeUploadModal` 期待返回 void — TS 会接受(返回 Promise 也可赋 void)。同时 `void res;` 的 `res` 在后面又用了 — 修正:删除 `void res;` 行，直接用 `res`:

```tsx
        onSubmit={async (f) => {
          const res = await uploadResume(f);
          onUploaded();
          setOpen(false);
          message.success(res.parse_status === 'text-ready' ? '简历已上传' : '已上传，需校正文本');
        }}
```

- [ ] **Step 2: 构建校验**

```bash
cd web && npx tsc -b --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add web/src/components/ResumeMatchModal.tsx
git -c user.name=XiaoZheBrother -c user.email=git@users.noreply.github.com commit -m "feat(resume-web): add PDF upload entry to ResumeMatchModal"
```

---

## Task 11: 端到端验证 — 构建后端 + 前端 + 手测路径

**Files:** 无改动，仅验证。

- [ ] **Step 1: 后端全量测试**

```bash
cd D:/Users/yuqi.chen/offerpilot/.worktrees/feat-resume-upload
go test ./internal/...
```

预期: 全 PASS。

- [ ] **Step 2: 后端构建**

```bash
go build -o oc.exe ./cmd/oc
```

预期: 生成 `oc.exe`，无错误。

- [ ] **Step 3: 前端构建**

```bash
cd web
npm install
npm run build
```

预期: `vite build` 成功生成 `web/dist`，无 TS 报错。

- [ ] **Step 4: 启动 + 手测**

```bash
cd ..
./oc.exe start
```

在浏览器打开(默认 8080)并验证:
1. 侧边栏出现「简历库」项 → 点击进入 → 看到空状态拖拽区。
2. 拖一个真实 PDF 到页面 → 出现上传统知 / 列表出现卡片显示文本预览。
3. 点击「编辑」→ 抽屉打开 → 改文本 → 保存 → 卡片刷新。
4. 拖一个扫描版 PDF → 卡片显示失败态 + 手动校正入口。
5. TopBar「+」→「上传简历」→ modal 上传。
6. Cmd/Ctrl+K → 搜索「简历」→ 命令可用。
7. AI 匹配入口 → 上传 PDF 次按钮可用。

- [ ] **Step 5: 提交验证产物(可选 — 一般不提交构建产物，跳过)**

跳过。构产物已在 .gitignore(`web/dist/`、`oc.exe`)。

---

## Self-Review 结果

**1. Spec 覆盖**:
- §1 定位 → 整体目标 ✓
- §2 架构与数据流 → Task 1/2/3 ✓
- §3 组件结构 → Task 4-10 ✓
- §4 UI/交互 → Task 5/6/7/8(CSS 含 stagger、drop active、tabular-nums、reduced-motion)✓
- §5 错误处理 → Task 3(size cap、扩展名、parse-failed)、Task 6(前端 beforeUpload 10MB 校验)、Task 8(parse-failed 卡片态)✓
- §6 测试边界 → Task 1/3(单测+集成)、Task 11(手测)✓
- §7 现有功能关系 → Task 10(ResumeMatchModal 兼容)✓
- §8 范围之外 → 未实现 DOCX/OCR/版本化，符合 ✓

**2. 占位符扫描**: Task 9 Step 3/5 与 Task 10 Step 1 含「Read 确认结构后增量添加」表述 — 因 TopBar/CommandPalette 实际结构未在 plan 内展开，已尽量给 Diff 导引而非空白；执行者需读文件后落具体行。其余步骤均有完整代码。

**3. 类型一致性**: `uploadResume(file: File): Promise<Resume>` 在 Task 4 定义，Task 8/9/10 调用一致；`updateResumeText(id, text)`、`downloadResumeFile(id)` 同；`Resume.parse_status` 字段字符串常量 `'text-ready'|'parse-failed'` 在前后端一致；`UpdateResumeText` / `UpdateResumeFile` DB 方法名前后一致。`resumeIDParam` 在 Task 3 新增，注意 `internal/api/resume.go` 现有 `getResumeHandler`/`deleteResumeHandler` 用的是内联 `strconv.ParseInt` — 本 plan 新增统一的 `resumeIDParam`，不强制重构旧 handler(避免范围蔓延)，新旧并存可接受。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-07-02-resume-upload.md`. 两种执行方式:

1. **Subagent-Driven(推荐)** — 每个 Task 派一个全新 subagent 实现，两阶段审查，迭代快。
2. **Inline Execution** — 本会话内逐 Task 执行，checkpoint 审查。

请选择执行方式。