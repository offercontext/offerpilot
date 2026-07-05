package mock

import (
	"encoding/json"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

type ScoringOutcome struct {
	Feedback     ai.ScoringFeedback
	Scores       db.MockScores
	FeedbackJSON string
	ParseError   bool
}

func BuildScoringOutcome(raw string) ScoringOutcome {
	feedback, err := ai.ParseScoringResult(raw)
	feedbackJSON, _ := json.Marshal(feedback)
	return ScoringOutcome{
		Feedback: feedback,
		Scores: db.MockScores{
			ScoreOverall:       feedback.ScoreOverall,
			ScoreCommunication: feedback.ScoreCommunication,
			ScoreDepth:         feedback.ScoreDepth,
			ScoreStructure:     feedback.ScoreStructure,
			ScoreConfidence:    feedback.ScoreConfidence,
		},
		FeedbackJSON: string(feedbackJSON),
		ParseError:   err != nil,
	}
}
