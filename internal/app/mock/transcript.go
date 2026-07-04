package mock

import (
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

func BuildTranscript(messages []db.ChatMessage) string {
	var b strings.Builder
	for _, message := range messages {
		if message.Content == "" || message.Role == "tool" {
			continue
		}
		who := "候选人"
		if message.Role == "assistant" {
			who = "面试官"
		}
		b.WriteString(who + "：" + message.Content + "\n")
	}
	return strings.TrimSpace(b.String())
}
