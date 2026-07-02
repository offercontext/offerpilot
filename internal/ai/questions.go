package ai

import (
	"context"
	"fmt"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

// Question generation source types (also stored as questions.source_type).
const (
	QuestionSourceKnowledge = "ai_knowledge"
	QuestionSourceNotes     = "ai_notes"
)

const (
	defaultQuestionCount = 8
	maxQuestionCount     = 20
)

// GenerateQuestions calls the model to produce interview questions grounded in
// the supplied context material. existing lists already-stored question stems so
// the model can avoid repeating them (a soft constraint; hard dedup happens at
// persist time).
func GenerateQuestions(ctx context.Context, c *Client, sourceLabel, contextText string, count int, existing []string) ([]GeneratedQuestion, error) {
	if strings.TrimSpace(contextText) == "" {
		return nil, fmt.Errorf("没有可用的生成素材")
	}
	count = clampQuestionCount(count)
	system, user := PromptGenerateQuestions(sourceLabel, truncateForPrompt(contextText), count, existing)
	reply, err := c.Chat(ctx, system, user)
	if err != nil {
		return nil, err
	}
	var out GeneratedQuestions
	if err := unmarshalJSONReply(reply, &out); err != nil {
		return nil, fmt.Errorf("parse AI questions: %w (raw: %s)", err, truncate(reply, 200))
	}
	return normalizeGeneratedQuestions(out.Questions), nil
}

// BuildKnowledgeContext concatenates the documents of a knowledge base into a
// single prompt-friendly block. Returns a human-readable source label too.
func BuildKnowledgeContext(database *db.Database, knowledgeBaseID int64) (label, contextText string, err error) {
	base, err := database.GetKnowledgeBase(knowledgeBaseID)
	if err != nil {
		return "", "", fmt.Errorf("加载知识库失败: %w", err)
	}
	docs, err := database.ListKnowledgeDocuments(db.KnowledgeDocumentFilter{KnowledgeBaseID: knowledgeBaseID})
	if err != nil {
		return "", "", fmt.Errorf("加载知识库文档失败: %w", err)
	}
	var b strings.Builder
	for _, doc := range docs {
		if strings.TrimSpace(doc.Content) == "" {
			continue
		}
		b.WriteString("## ")
		b.WriteString(doc.Title)
		b.WriteString("\n")
		b.WriteString(strings.TrimSpace(doc.Content))
		b.WriteString("\n\n")
	}
	label = fmt.Sprintf("知识库「%s」资料", base.Name)
	return label, strings.TrimSpace(b.String()), nil
}

// BuildNotesContext concatenates interview retrospectives (真题) into a
// prompt-friendly block. Pass appID 0 to use all notes.
func BuildNotesContext(database *db.Database, appID int64) (label, contextText string, err error) {
	notes, err := database.ListInterviewNotes(appID)
	if err != nil {
		return "", "", fmt.Errorf("加载面试复盘失败: %w", err)
	}
	var b strings.Builder
	for _, n := range notes {
		header := strings.TrimSpace(strings.Join(nonEmpty([]string{n.Company, n.Position, n.Round}), " · "))
		if header != "" {
			b.WriteString("## ")
			b.WriteString(header)
			b.WriteString("\n")
		}
		if strings.TrimSpace(n.Questions) != "" {
			b.WriteString("面试问题：\n")
			b.WriteString(strings.TrimSpace(n.Questions))
			b.WriteString("\n")
		}
		if strings.TrimSpace(n.DifficultyPoints) != "" {
			b.WriteString("薄弱点：\n")
			b.WriteString(strings.TrimSpace(n.DifficultyPoints))
			b.WriteString("\n")
		}
		b.WriteString("\n")
	}
	return "面试复盘真题", strings.TrimSpace(b.String()), nil
}

// PersistGeneratedQuestions dedups generated questions against the existing bank
// (exact + near-duplicate) and stores the survivors, returning the persisted
// records and the number skipped as duplicates.
func PersistGeneratedQuestions(database *db.Database, knowledgeBaseID, applicationID *int64, sourceType string, generated []GeneratedQuestion, existing []db.QuestionDigest) ([]db.Question, int, error) {
	kept, skipped := DedupGenerated(existing, generated)
	if len(kept) == 0 {
		return nil, skipped, nil
	}
	records := make([]*db.Question, 0, len(kept))
	for _, g := range kept {
		records = append(records, &db.Question{
			KnowledgeBaseID: knowledgeBaseID,
			ApplicationID:   applicationID,
			Category:        g.Category,
			Difficulty:      g.Difficulty,
			Question:        g.Question,
			ReferenceAnswer: g.ReferenceAnswer,
			Tags:            g.Tags,
			SourceType:      sourceType,
			Status:          db.QuestionStatusNew,
		})
	}
	if err := database.BulkCreateQuestions(records); err != nil {
		return nil, skipped, fmt.Errorf("保存题目失败: %w", err)
	}
	out := make([]db.Question, 0, len(records))
	for _, r := range records {
		out = append(out, *r)
	}
	return out, skipped, nil
}

func normalizeGeneratedQuestions(items []GeneratedQuestion) []GeneratedQuestion {
	out := make([]GeneratedQuestion, 0, len(items))
	for _, q := range items {
		q.Question = strings.TrimSpace(q.Question)
		if q.Question == "" {
			continue
		}
		q.Category = strings.TrimSpace(q.Category)
		q.ReferenceAnswer = strings.TrimSpace(q.ReferenceAnswer)
		q.Difficulty = normalizeDifficulty(q.Difficulty)
		if q.Tags == nil {
			q.Tags = []string{}
		}
		out = append(out, q)
	}
	return out
}

func normalizeDifficulty(d string) string {
	switch strings.ToLower(strings.TrimSpace(d)) {
	case "easy", "简单":
		return "easy"
	case "hard", "困难", "难":
		return "hard"
	default:
		return "medium"
	}
}

func clampQuestionCount(count int) int {
	if count <= 0 {
		return defaultQuestionCount
	}
	if count > maxQuestionCount {
		return maxQuestionCount
	}
	return count
}

func nonEmpty(items []string) []string {
	out := make([]string, 0, len(items))
	for _, s := range items {
		if strings.TrimSpace(s) != "" {
			out = append(out, s)
		}
	}
	return out
}
