package ai

import "testing"

func TestParseMaterialKitResult(t *testing.T) {
	raw := `{
		"resume_advice":{"summary":"Strong Go fit","highlights":["Go"],"rewrite_bullets":["Built APIs"],"gaps":["Kubernetes"],"notes":""},
		"messages":[{"type":"recruiter_email","title":"Intro","body":"Hello","notes":""}],
		"checklist":[{"id":"select_resume","label":"Select resume","done":true}]
	}`
	got, err := ParseMaterialKitResult(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if got.ResumeAdvice.Summary != "Strong Go fit" {
		t.Fatalf("unexpected summary: %+v", got.ResumeAdvice)
	}
	if len(got.Messages) != 1 || got.Messages[0].Type != "recruiter_email" {
		t.Fatalf("unexpected messages: %+v", got.Messages)
	}
	if len(got.Checklist) != 1 || !got.Checklist[0].Done {
		t.Fatalf("unexpected checklist: %+v", got.Checklist)
	}
}

func TestParseMaterialKitResultRejectsMissingChecklist(t *testing.T) {
	if _, err := ParseMaterialKitResult(`{"resume_advice":{"summary":"x"}}`); err == nil {
		t.Fatalf("expected error")
	}
}
