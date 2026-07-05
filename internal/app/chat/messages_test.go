package chat

import (
	"encoding/json"
	"testing"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

func TestTitleFromMessageLeavesShortMessagesUnchanged(t *testing.T) {
	title := TitleFromMessage("hello offer coach")

	if title != "hello offer coach" {
		t.Fatalf("unexpected title: %q", title)
	}
}

func TestTitleFromMessageTruncatesByRuneCount(t *testing.T) {
	title := TitleFromMessage("一二三四五六七八九十一二三四五六七八九十甲乙")

	if title != "一二三四五六七八九十一二三四五六七八九十..." {
		t.Fatalf("unexpected title: %q", title)
	}
}

func TestToAIMessagesPrependsSystemPromptAndPreservesStoredMetadata(t *testing.T) {
	stored := []db.ChatMessage{
		{
			Role:           "assistant",
			Content:        "checking",
			ToolCalls:      `[{"id":"call-1","name":"list_applications","args":{"status":"interview"}}]`,
			ProviderBlocks: `[{"type":"thinking","thinking":"checking","signature":"sig"}]`,
		},
		{
			Role:       "tool",
			Content:    "[]",
			ToolCallID: "call-1",
		},
	}

	msgs := ToAIMessages(stored, "system prompt")

	if len(msgs) != 3 {
		t.Fatalf("expected 3 messages, got %d", len(msgs))
	}
	if msgs[0].Role != ai.RoleSystem || msgs[0].Content != "system prompt" {
		t.Fatalf("system prompt not prepended: %+v", msgs[0])
	}
	if msgs[1].Role != ai.RoleAssistant || len(msgs[1].ToolCalls) != 1 {
		t.Fatalf("tool call not preserved: %+v", msgs[1])
	}
	if got := string(msgs[1].ToolCalls[0].Args); got != `{"status":"interview"}` {
		t.Fatalf("unexpected tool args: %s", got)
	}
	if len(msgs[1].ProviderBlocks) != 1 {
		t.Fatalf("provider blocks not preserved: %+v", msgs[1].ProviderBlocks)
	}
	var block map[string]string
	if err := json.Unmarshal(msgs[1].ProviderBlocks[0], &block); err != nil {
		t.Fatalf("provider block json: %v", err)
	}
	if block["type"] != "thinking" || block["signature"] != "sig" {
		t.Fatalf("unexpected provider block: %+v", block)
	}
	if msgs[2].Role != ai.RoleTool || msgs[2].ToolCallID != "call-1" {
		t.Fatalf("tool result metadata not preserved: %+v", msgs[2])
	}
}
