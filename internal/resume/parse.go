// Package resume provides PDF text extraction for uploaded resume files.
package resume

import (
	"bytes"
	"strings"

	"rsc.io/pdf"
)

// ExtractPDFText reads plain text from a PDF byte slice.
// It returns "" without error when the PDF has no extractable text layer
// (e.g. scanned/image-only PDFs); callers decide whether to mark parse-failed.
// Corrupt or non-PDF input returns an error.
func ExtractPDFText(data []byte) (string, error) {
	if len(data) == 0 {
		return "", nil
	}
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