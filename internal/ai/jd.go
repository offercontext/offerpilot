package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/offercontext/offerpilot/internal/db"
)

// maxJDTextLen caps the JD text sent to the model to keep prompts manageable.
const maxJDTextLen = 12000

// AnalyzeJD calls the model on the given JD text and returns the parsed result.
func AnalyzeJD(ctx context.Context, c *Client, jdText string) (*JDAnalysisResult, error) {
	system, user := PromptJDAnalyze(truncateForPrompt(jdText))
	reply, err := c.Chat(ctx, system, user)
	if err != nil {
		return nil, err
	}
	var res JDAnalysisResult
	if err := unmarshalJSONReply(reply, &res); err != nil {
		return nil, fmt.Errorf("parse AI JD analysis: %w (raw: %s)", err, truncate(reply, 200))
	}
	return &res, nil
}

// PersistJDAnalysis stores the JD text + raw result JSON into the database.
// resultJSON should be the marshalled JDAnalysisResult. Returns the stored record.
func PersistJDAnalysis(database *db.Database, appID *int64, source, jdText, resultJSON string) (*db.JDAnalysis, error) {
	a := &db.JDAnalysis{
		ApplicationID: appID,
		JDSource:      source,
		JDText:        jdText,
		Result:        resultJSON,
	}
	if err := database.CreateJDAnalysis(a); err != nil {
		return nil, fmt.Errorf("persist jd analysis: %w", err)
	}
	return a, nil
}

// FetchJDFromURL does a best-effort HTTP GET and strips HTML to plain text.
// Failures (network, non-200, encoding) return a clear error suggesting the
// user paste the JD text instead.
func FetchJDFromURL(jdURL string) (string, error) {
	if jdURL == "" {
		return "", fmt.Errorf("empty JD URL")
	}
	client := &http.Client{Timeout: 20 * time.Second}
	req, err := http.NewRequest(http.MethodGet, jdURL, nil)
	if err != nil {
		return "", fmt.Errorf("invalid URL: %w", err)
	}
	req.Header.Set("User-Agent", "OfferPilot/0.1 (local job-search workbench)")
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("fetch JD URL failed (you can paste the JD text instead): %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("JD URL returned HTTP %d — please paste the JD text instead", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read JD page: %w", err)
	}
	return cleanHTMLToText(string(body)), nil
}

var (
	// RE2 (Go regexp) has no backreferences, so we list opening tags explicitly.
	scriptStyleRe = regexp.MustCompile(`(?is)</?(script|style|noscript)\b[^>]*>`)
	wsInsideRe    = regexp.MustCompile(`(?is)<(script|style|noscript)\b[^>]*>.*?</(script|style|noscript)>`)
	tagRe         = regexp.MustCompile(`<[^>]+>`)
	nbspRe        = regexp.MustCompile(`&nbsp;`)
	brRe          = regexp.MustCompile(`(?i)<br\s*/?>`)
	wsRe          = regexp.MustCompile(`[ \t\r\f\v]+`)
	multiNLRe     = regexp.MustCompile(`\n{3,}`)
)

// cleanHTMLToText performs a minimal HTML → plain text conversion suitable for
// feeding JD content to a model: drop script/style, convert <br> to newlines,
// strip remaining tags, collapse whitespace, cap length.
func cleanHTMLToText(html string) string {
	// 1. Drop entire script/style/noscript blocks (with their inner content).
	s := wsInsideRe.ReplaceAllString(html, "")
	// 2. Strip any remaining stray script/style opening or closing tags.
	s = scriptStyleRe.ReplaceAllString(s, "")
	s = brRe.ReplaceAllString(s, "\n")
	s = tagRe.ReplaceAllString(s, "")
	s = nbspRe.ReplaceAllString(s, " ")
	s = strings.NewReplacer("&amp;", "&", "&lt;", "<", "&gt;", ">", "&quot;", `"`, "&#39;", "'").Replace(s)
	s = wsRe.ReplaceAllString(s, " ")
	s = multiNLRe.ReplaceAllString(s, "\n\n")
	s = strings.TrimSpace(s)
	return truncateForPrompt(s)
}

// truncateForPrompt limits text to maxJDTextLen runes (not bytes) so multi-byte
// Chinese content is not cut mid-character.
func truncateForPrompt(s string) string {
	if utf8.RuneCountInString(s) <= maxJDTextLen {
		return s
	}
	rs := []rune(s)
	return string(rs[:maxJDTextLen]) + "\n…(已截断)"
}

// unmarshalJSONReply tolerates the model occasionally wrapping JSON in a
// ```json fenced block despite instructions.
func unmarshalJSONReply(reply string, out interface{}) error {
	s := strings.TrimSpace(reply)
	// Strip a leading/trailing fenced code block if present.
	if strings.HasPrefix(s, "```") {
		// remove first fence line
		if i := strings.IndexByte(s, '\n'); i >= 0 {
			s = strings.TrimSpace(s[i+1:])
		}
		// remove trailing fence
		if j := strings.LastIndex(s, "```"); j >= 0 {
			s = strings.TrimSpace(s[:j])
		}
	}
	return json.Unmarshal([]byte(s), out)
}