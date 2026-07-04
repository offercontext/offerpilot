package mock

import (
	"strings"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

type ContextStore interface {
	ListQuestions(filter db.QuestionFilter) ([]db.Question, error)
	SearchKnowledge(filter db.KnowledgeSearchFilter) ([]db.KnowledgeSearchResult, error)
	ListInterviewNotes(appID int64) ([]db.InterviewNote, error)
}

func BuildContext(store ContextStore, sess *db.MockSession) ai.MockContext {
	ctx := ai.MockContext{}
	if store == nil || sess == nil {
		return ctx
	}

	if sess.QuestionSource == "bank" || sess.QuestionSource == "mixed" {
		filter := db.QuestionFilter{Difficulty: sess.Difficulty}
		if sess.KnowledgeBaseID != nil {
			filter.KnowledgeBaseID = *sess.KnowledgeBaseID
		}
		questions, err := store.ListQuestions(filter)
		if err == nil {
			if len(questions) > 12 {
				questions = questions[:12]
			}
			ctx.PickedQuestions = questions
		}
	}

	if (sess.QuestionSource == "knowledge" || sess.QuestionSource == "mixed") && sess.KnowledgeBaseID != nil {
		results, err := store.SearchKnowledge(db.KnowledgeSearchFilter{
			KnowledgeBaseID: *sess.KnowledgeBaseID,
			Limit:           6,
		})
		if err == nil {
			for _, result := range results {
				ctx.KnowledgeChunks = append(ctx.KnowledgeChunks, result.Snippet)
			}
		}
	}

	if sess.ApplicationID != nil {
		notes, err := store.ListInterviewNotes(*sess.ApplicationID)
		if err == nil {
			for _, note := range notes {
				if strings.TrimSpace(note.DifficultyPoints) == "" {
					continue
				}
				ctx.WeakPoints = append(ctx.WeakPoints, note.DifficultyPoints)
				if len(ctx.WeakPoints) >= 6 {
					break
				}
			}
		}
	}

	return ctx
}
