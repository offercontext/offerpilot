package ai

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

const summaryFallbackReadOnlyNotice = "\n\n\uff08\u6ce8\u610f\uff1a\u5f53\u524d\u6a21\u578b\u4e0d\u652f\u6301\u5de5\u5177\u8c03\u7528\uff0c\u4ee5\u4e0b\u4e3a\u53ea\u8bfb\u6570\u636e\u6458\u8981\uff0c\u4f60\u65e0\u6cd5\u4fee\u6539\u6570\u636e\u3002\uff09\n"

const maxFallbackKnowledgeTerms = 8

// BuildDataSummary produces a compact, token-light overview of the user's job
// data for injection into the system prompt when tool calling is unavailable.
func BuildDataSummary(database *db.Database) string {
	var sb strings.Builder
	sb.WriteString("以下是用户当前的求职数据摘要（只读）：\n")

	apps, err := database.ListApplications("")
	if err == nil {
		sb.WriteString(fmt.Sprintf("投递记录共 %d 条：\n", len(apps)))
		max := len(apps)
		if max > 30 {
			max = 30
		}
		for _, a := range apps[:max] {
			sb.WriteString(fmt.Sprintf("- #%d %s / %s [%s]\n", a.ID, a.CompanyName, a.PositionName, a.Status))
		}
		if len(apps) > max {
			sb.WriteString(fmt.Sprintf("…（其余 %d 条省略）\n", len(apps)-max))
		}
	}

	notes, err := database.ListInterviewNotes(0)
	if err == nil && len(notes) > 0 {
		sb.WriteString(fmt.Sprintf("面试复盘笔记共 %d 条。\n", len(notes)))
	}
	resumes, err := database.ListResumes()
	if err == nil && len(resumes) > 0 {
		sb.WriteString(fmt.Sprintf("简历共 %d 份。\n", len(resumes)))
	}
	if events, err := database.ListEvents(db.EventFilter{}); err == nil && len(events) > 0 {
		sb.WriteString("\n日程事件:\n")
		max := len(events)
		if max > 30 {
			max = 30
		}
		for _, e := range events[:max] {
			when := ""
			if e.ScheduledAt != nil {
				when = e.ScheduledAt.Format("2006-01-02 15:04")
			}
			sb.WriteString(fmt.Sprintf("- #%d %s %s %s %s%s\n", e.ID, e.CompanyName, e.PositionName, e.EventType, when, summaryDuration(e.Duration)))
		}
		if len(events) > max {
			sb.WriteString(fmt.Sprintf("…（其余 %d 条省略）\n", len(events)-max))
		}
	}
	return sb.String()
}

func summaryDuration(duration string) string {
	duration = strings.TrimSpace(duration)
	if duration == "" {
		return ""
	}
	if _, err := strconv.Atoi(duration); err == nil {
		return fmt.Sprintf(" 时长%s分钟", duration)
	}
	return fmt.Sprintf(" 时长%s", duration)
}

// BuildSummaryFallbackPrompt builds the prompt pair used when the model can't
// call tools. The system prompt preserves the read-only data summary, while the
// user prompt can carry a few matching knowledge snippets.
func BuildSummaryFallbackPrompt(database *db.Database, userMessage string) (system, user string) {
	system = ChatSystemPrompt + summaryFallbackReadOnlyNotice + BuildDataSummary(database)
	user = userMessage

	if snippets := buildKnowledgeSnippets(database, userMessage); snippets != "" {
		user += "\n\nKnowledge snippets\n" + snippets
	}
	return system, user
}

func buildKnowledgeSnippets(database *db.Database, userMessage string) string {
	results := searchKnowledgeForFallback(database, userMessage)
	if len(results) == 0 {
		return ""
	}

	var sb strings.Builder
	for _, result := range results {
		snippet := strings.TrimSpace(strings.ReplaceAll(result.Snippet, "\n", " "))
		if snippet == "" {
			continue
		}
		sb.WriteString(fmt.Sprintf("- %s / %s: %s\n", result.KnowledgeBaseName, result.DocumentTitle, snippet))
	}
	return strings.TrimRight(sb.String(), "\n")
}

func searchKnowledgeForFallback(database *db.Database, userMessage string) []db.KnowledgeSearchResult {
	const limit = 3

	results, err := database.SearchKnowledge(db.KnowledgeSearchFilter{Query: userMessage, Limit: limit})
	if err != nil {
		return nil
	}
	if len(results) >= limit {
		return results[:limit]
	}

	seen := make(map[int64]bool, len(results))
	for _, result := range results {
		seen[result.ChunkID] = true
	}
	for _, term := range fallbackKnowledgeTerms(userMessage) {
		if len(results) >= limit {
			break
		}
		matches, err := database.SearchKnowledge(db.KnowledgeSearchFilter{Query: term, Limit: limit})
		if err != nil {
			continue
		}
		for _, match := range matches {
			if seen[match.ChunkID] {
				continue
			}
			results = append(results, match)
			seen[match.ChunkID] = true
			if len(results) >= limit {
				break
			}
		}
	}
	return results
}

func fallbackKnowledgeTerms(userMessage string) []string {
	seen := make(map[string]bool)
	terms := make([]string, 0, maxFallbackKnowledgeTerms)
	for _, term := range strings.Fields(userMessage) {
		if len([]rune(term)) < 3 || seen[term] {
			continue
		}
		terms = append(terms, term)
		seen[term] = true
		if len(terms) >= maxFallbackKnowledgeTerms {
			break
		}
	}
	return terms
}

// RunSummaryFallback handles a single user turn without tools by injecting a
// data summary into the system prompt. Used when the model can't do tool calls.
func RunSummaryFallback(ctx context.Context, c *Client, database *db.Database, userMessage string) (string, error) {
	system, user := BuildSummaryFallbackPrompt(database, userMessage)
	return c.Chat(ctx, system, user)
}
