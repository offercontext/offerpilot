// Package resume provides PDF text extraction for uploaded resume files.
package resume

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"rsc.io/pdf"
)

// pdftotext is the name of the poppler CLI we prefer when available.
const pdftotextBin = "pdftotext"

// ExtractPDFText reads plain text from a PDF byte slice.
//
// Strategy: try the system `pdftotext` (poppler) first — it has full CID/Type0
// (Chinese/Japanese/Korean) font support. If the binary is missing, fall back
// to the pure-Go rsc.io/pdf reader, which handles Latin text but is weak on
// CJK fonts.
//
// Returns "" without error when the PDF has no extractable text layer
// (e.g. scanned/image-only PDFs); callers decide whether to mark parse-failed.
// Corrupt or non-PDF input returns an error.
func ExtractPDFText(data []byte) (string, error) {
	if len(data) == 0 {
		return "", nil
	}
	if txt, ok := tryPdftotext(data); ok {
		return txt, nil
	}
	return extractWithRscPDF(data)
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
	_ = filepath.Base(tmpPath) // keep filepath import used even if tmp dir logic expands
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