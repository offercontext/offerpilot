package mock

import "testing"

func TestBuildScoringOutcomeParsesScoresAndFeedbackJSON(t *testing.T) {
	raw := `{"score_overall":82,"score_communication":80,"score_depth":76,"score_structure":85,"score_confidence":90,"summary":"solid","strengths":["clear"],"weaknesses":["depth"],"drills":[]}`

	outcome := BuildScoringOutcome(raw)

	if outcome.ParseError {
		t.Fatal("ParseError = true, want false")
	}
	if outcome.Feedback.ScoreOverall != 82 || outcome.Feedback.Summary != "solid" {
		t.Fatalf("Feedback wrong: %+v", outcome.Feedback)
	}
	if outcome.Scores.ScoreOverall != 82 {
		t.Fatalf("ScoreOverall = %d, want 82", outcome.Scores.ScoreOverall)
	}
	if outcome.Scores.ScoreConfidence != 90 {
		t.Fatalf("ScoreConfidence = %d, want 90", outcome.Scores.ScoreConfidence)
	}
	if outcome.FeedbackJSON == "" {
		t.Fatal("FeedbackJSON is empty")
	}
}

func TestBuildScoringOutcomePreservesParseErrorFallback(t *testing.T) {
	outcome := BuildScoringOutcome(`not json`)

	if !outcome.ParseError {
		t.Fatal("ParseError = false, want true")
	}
	if outcome.Scores.ScoreOverall != 0 {
		t.Fatalf("ScoreOverall fallback = %d, want 0", outcome.Scores.ScoreOverall)
	}
	if outcome.FeedbackJSON == "" {
		t.Fatal("FeedbackJSON fallback should be persisted")
	}
}
