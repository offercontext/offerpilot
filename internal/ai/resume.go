package ai

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/offercontext/offerpilot/internal/db"
)

// MatchResume compares a resume text against a JD text via the model and returns
// a structured match report.
func MatchResume(ctx context.Context, c *Client, resumeText, jdText string) (*MatchResult, error) {
	if resumeText == "" {
		return nil, fmt.Errorf("resume text is empty")
	}
	if jdText == "" {
		return nil, fmt.Errorf("JD text is empty")
	}
	system, user := PromptResumeMatch(truncateForPrompt(resumeText), truncateForPrompt(jdText))
	reply, err := c.Chat(ctx, system, user)
	if err != nil {
		return nil, err
	}
	var res MatchResult
	if err := unmarshalJSONReply(reply, &res); err != nil {
		return nil, fmt.Errorf("parse AI resume match: %w (raw: %s)", err, truncate(reply, 200))
	}
	return &res, nil
}

// PersistResumeMatch stores a match result row.
func PersistResumeMatch(database *db.Database, resumeID int64, appID *int64, jdText, resultJSON string) (*db.ResumeMatch, error) {
	m := &db.ResumeMatch{
		ResumeID:      resumeID,
		ApplicationID: appID,
		JDText:        jdText,
		Result:        resultJSON,
	}
	if err := database.CreateResumeMatch(m); err != nil {
		return nil, fmt.Errorf("persist resume match: %w", err)
	}
	return m, nil
}

// MarshalMatch is a tiny helper to keep API/CLI code symmetric.
func MarshalMatch(m *MatchResult) string {
	b, _ := json.Marshal(m)
	return string(b)
}