package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// MaterialKitResult is the JSON envelope returned by the material-kit model.
type MaterialKitResult struct {
	ResumeAdvice MaterialKitResumeAdvice `json:"resume_advice"`
	Messages     []MaterialKitMessage    `json:"messages"`
	Checklist    []MaterialKitChecklist  `json:"checklist"`
}

type MaterialKitResumeAdvice struct {
	Summary        string   `json:"summary"`
	Highlights     []string `json:"highlights"`
	RewriteBullets []string `json:"rewrite_bullets"`
	Gaps           []string `json:"gaps"`
	Notes          string   `json:"notes"`
}

type MaterialKitMessage struct {
	Type  string `json:"type"`
	Title string `json:"title"`
	Body  string `json:"body"`
	Notes string `json:"notes"`
}

type MaterialKitChecklist struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Done  bool   `json:"done"`
}

// GenerateMaterialKit calls the model to build an application material kit.
func GenerateMaterialKit(ctx context.Context, c *Client, company, position, resumeText, jdText string) (*MaterialKitResult, error) {
	if strings.TrimSpace(resumeText) == "" {
		return nil, fmt.Errorf("resume text is empty")
	}
	if strings.TrimSpace(jdText) == "" {
		return nil, fmt.Errorf("JD text is empty")
	}
	system, user := PromptMaterialKit(company, position, truncateForPrompt(resumeText), truncateForPrompt(jdText))
	reply, err := c.Chat(ctx, system, user)
	if err != nil {
		return nil, err
	}
	res, err := ParseMaterialKitResult(reply)
	if err != nil {
		return nil, fmt.Errorf("parse AI material kit: %w (raw: %s)", err, truncate(reply, 200))
	}
	return res, nil
}

func PromptMaterialKit(company, position, resumeText, jdText string) (system, user string) {
	system = buildSystem()
	user = fmt.Sprintf(`Create an application material kit for this role. Return only JSON with:
{
  "resume_advice": {
    "summary": "one sentence fit summary",
    "highlights": ["resume strengths to emphasize"],
    "rewrite_bullets": ["tailored resume bullets"],
    "gaps": ["missing or weak areas"],
    "notes": "optional notes"
  },
  "messages": [
    {"type": "recruiter_email", "title": "Intro", "body": "message body", "notes": "optional notes"}
  ],
  "checklist": [
    {"id": "select_resume", "label": "Select resume", "done": false},
    {"id": "tailor_resume", "label": "Tailor resume", "done": false},
    {"id": "prepare_message", "label": "Prepare message", "done": false},
    {"id": "submit_application", "label": "Submit application", "done": false},
    {"id": "set_followup", "label": "Set follow-up", "done": false}
  ]
}

Company: %s
Position: %s

Resume:
%s

JD:
%s`, company, position, resumeText, jdText)
	return
}

// ParseMaterialKitResult unmarshals and validates a model material-kit reply.
func ParseMaterialKitResult(raw string) (*MaterialKitResult, error) {
	var res MaterialKitResult
	if err := unmarshalJSONReply(raw, &res); err != nil {
		return nil, err
	}
	if strings.TrimSpace(res.ResumeAdvice.Summary) == "" {
		return nil, fmt.Errorf("resume_advice.summary is required")
	}
	if len(res.Messages) == 0 {
		return nil, fmt.Errorf("messages is required")
	}
	if len(res.Checklist) == 0 {
		return nil, fmt.Errorf("checklist is required")
	}
	return &res, nil
}

func MarshalMaterialKit(result *MaterialKitResult) string {
	b, _ := json.Marshal(result)
	return string(b)
}
