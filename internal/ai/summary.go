package ai

import (
	"context"
	"fmt"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

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
		for _, e := range events {
			when := ""
			if e.ScheduledAt != nil {
				when = e.ScheduledAt.Format("2006-01-02 15:04")
			}
			sb.WriteString(fmt.Sprintf("- #%d %s %s %s %s 时长%s分钟\n", e.ID, e.CompanyName, e.PositionName, e.EventType, when, e.Duration))
		}
	}
	return sb.String()
}

// RunSummaryFallback handles a single user turn without tools by injecting a
// data summary into the system prompt. Used when the model can't do tool calls.
func RunSummaryFallback(ctx context.Context, c *Client, database *db.Database, userMessage string) (string, error) {
	system := ChatSystemPrompt + "\n\n（注意：当前模型不支持工具调用，以下为只读数据摘要，你无法修改数据。）\n" + BuildDataSummary(database)
	return c.Chat(ctx, system, userMessage)
}
