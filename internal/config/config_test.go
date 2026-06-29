package config

import "testing"

func TestSaveLoadAutoApprove(t *testing.T) {
	dir := t.TempDir()
	cfg := &Config{APIKey: "k", BaseURL: DefaultBaseURL, Model: DefaultModel, ChatAutoApproveWrites: true}
	if err := Save(dir, cfg); err != nil {
		t.Fatalf("save: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if !got.ChatAutoApproveWrites {
		t.Fatal("expected ChatAutoApproveWrites to persist as true")
	}
}
