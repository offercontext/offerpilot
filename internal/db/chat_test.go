package db

import (
	"path/filepath"
	"testing"
)

func newTestDB(t *testing.T) *Database {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	d, err := Init(dbPath)
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestConversationAndMessageCRUD(t *testing.T) {
	d := newTestDB(t)

	conv, err := d.CreateConversation("找工作进度")
	if err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	if conv.ID == 0 {
		t.Fatal("expected non-zero conversation id")
	}

	if err := d.AppendMessage(&ChatMessage{
		ConversationID: conv.ID,
		Role:           "user",
		Content:        "你好",
	}); err != nil {
		t.Fatalf("append user: %v", err)
	}
	if err := d.AppendMessage(&ChatMessage{
		ConversationID: conv.ID,
		Role:           "assistant",
		Content:        "",
		ToolCalls:      `[{"id":"c1","name":"list_applications","args":{}}]`,
		ProviderBlocks: `[{"type":"thinking","thinking":"checking","signature":"sig"}]`,
	}); err != nil {
		t.Fatalf("append assistant: %v", err)
	}

	msgs, err := d.ListMessages(conv.ID)
	if err != nil {
		t.Fatalf("list messages: %v", err)
	}
	if len(msgs) != 2 {
		t.Fatalf("want 2 messages, got %d", len(msgs))
	}
	if msgs[0].Role != "user" || msgs[1].ToolCalls == "" {
		t.Fatalf("unexpected message ordering/content: %+v", msgs)
	}
	if msgs[1].ProviderBlocks == "" {
		t.Fatalf("expected provider blocks to persist: %+v", msgs[1])
	}

	convs, err := d.ListConversations()
	if err != nil {
		t.Fatalf("list conversations: %v", err)
	}
	if len(convs) != 1 {
		t.Fatalf("want 1 conversation, got %d", len(convs))
	}

	if err := d.DeleteConversation(conv.ID); err != nil {
		t.Fatalf("delete conversation: %v", err)
	}
	after, _ := d.ListMessages(conv.ID)
	if len(after) != 0 {
		t.Fatalf("expected cascade delete of messages, got %d", len(after))
	}
}

func TestConversationWithMode(t *testing.T) {
	d := newTestDB(t)
	o := &Offer{CompanyName: "字节", PositionName: "后端", BaseMonthly: 35000, MonthsPerYear: 16}
	if err := d.CreateOffer(o); err != nil {
		t.Fatalf("create offer: %v", err)
	}
	conv, err := d.CreateConversationWithMode("字节 谈薪", "nego_coach", &o.ID)
	if err != nil {
		t.Fatalf("create conv: %v", err)
	}
	got, err := d.GetConversation(conv.ID)
	if err != nil {
		t.Fatalf("get conv: %v", err)
	}
	if got.Mode != "nego_coach" {
		t.Fatalf("expected mode nego_coach, got %q", got.Mode)
	}
	if got.OfferID == nil || *got.OfferID != o.ID {
		t.Fatalf("expected offer_id %d, got %v", o.ID, got.OfferID)
	}

	// A plain conversation defaults to general with no offer.
	plain, _ := d.CreateConversation("普通对话")
	pg, _ := d.GetConversation(plain.ID)
	if pg.Mode != "general" || pg.OfferID != nil {
		t.Fatalf("expected general/no-offer, got mode=%q offer=%v", pg.Mode, pg.OfferID)
	}
}
