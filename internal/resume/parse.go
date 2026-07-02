// Package resume provides PDF text extraction for uploaded resume files.
package resume

import (
	"bytes"
	"os"
	"os/exec"
	"strings"

	"rsc.io/pdf"
)

const (
	pdftotextBin = "pdftotext"
	python3Bin   = "python3"
	// pdfTextScript is a helper that uses PyMuPDF to extract PDF text. We pass
	// it via argv to avoid having to resolve a path on disk at runtime.
	pdfTextScript = "import sys,fitz; d=fitz.open(stream=sys.stdin.buffer.read(),filetype='pdf'); sys.stdout.write('\\n'.join(p.get_text() for p in d))"
)

// ExtractPDFText reads plain text from a PDF byte slice.
//
// Strategy (most-accurate first):
//  1. PyMuPDF (`python3 -c ...`) — best for subsetted Type0/CID CJK fonts,
//     which are common in Chinese resumes but where pdftotext fails.
//  2. Poppler `pdftotext <tmpfile> -` — solid fallback for Latin + many CJK.
//  3. Pure-Go `rsc.io/pdf` — works without system deps, weak on CJK.
//
// Returns "" without error when no text layer is extractable (scanned PDFs);
// callers decide whether to mark parse-failed. Corrupt / non-PDF → error.
func ExtractPDFText(data []byte) (string, error) {
	if len(data) == 0 {
		return "", nil
	}
	if txt, ok := tryPyMuPDF(data); ok {
		return txt, nil
	}
	if txt, ok := tryPdftotext(data); ok {
		return txt, nil
	}
	return extractWithRscPDF(data)
}

// tryPyMuPDF runs `python3 -c <helper>` feeding the PDF via stdin and reading
// extracted text from stdout. Returns (txt, true) on success, (buf, false)
// when python3 is missing or extraction failed.
func tryPyMuPDF(data []byte) (string, bool) {
	if _, err := exec.LookPath(python3Bin); err != nil {
		// On Windows, `python3` may not be on PATH while `python` is.
		if _, err2 := exec.LookPath("python"); err2 != nil {
			return "", false
		}
		cmd := exec.Command("python", "-c", pdfTextScript)
		cmd.Stdin = bytes.NewReader(data)
		var out bytes.Buffer
		cmd.Stdout = &out
		if err := cmd.Run(); err != nil {
			return "", false
		}
		return strings.TrimSpace(out.String()), true
	}
	cmd := exec.Command(python3Bin, "-c", pdfTextScript)
	cmd.Stdin = bytes.NewReader(data)
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return "", false
	}
	return strings.TrimSpace(out.String()), true
}

// tryPdftotext writes the PDF bytes to a temp file and runs
// `pdftotext <tmpfile> -` (stdout). The poppler 4.x CLI does NOT read from
// stdin despite the `-` convention, so a temp file is required.
// Returns (txt, true) only when the binary ran successfully; (txt, false)
// means the binary was unavailable or failed (e.g. scanned PDF).
func tryPdftotext(data []byte) (string, bool) {
	if _, err := exec.LookPath(pdftotextBin); err != nil {
		return "", false
	}
	tmp, err := os.CreateTemp("", "offerpilot-resume-*.pdf")
	if err != nil {
		return "", false
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return "", false
	}
	if err := tmp.Close(); err != nil {
		return "", false
	}
	var out bytes.Buffer
	cmd := exec.Command(pdftotextBin, tmpPath, "-")
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return "", false
	}
	return strings.TrimSpace(out.String()), true
}

// extractWithRscPDF is the pure-Go fallback (no system dependency). It handles
// Latin text well but often yields empty output for CJK fonts (CID/Type0).
func extractWithRscPDF(data []byte) (string, error) {
	r, err := pdf.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return "", err
	}

	var b strings.Builder
	for i := 0; i < r.NumPage(); i++ {
		page := r.Page(i)
		if page.V.IsNull() {
			continue
		}
		content := page.Content()
		for _, t := range content.Text {
			b.WriteString(t.S)
			b.WriteByte(' ')
		}
		b.WriteByte('\n')
	}
	return strings.TrimSpace(b.String()), nil
}
