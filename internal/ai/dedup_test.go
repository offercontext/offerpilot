package ai

import (
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestDedupGeneratedExactAndNear(t *testing.T) {
	existing := []db.QuestionDigest{
		{ID: 1, Question: "什么是 goroutine 泄漏？", Hash: db.QuestionHash("什么是 goroutine 泄漏？")},
	}
	generated := []GeneratedQuestion{
		{Question: "什么是 goroutine 泄漏?"},  // exact after normalization (punctuation only)
		{Question: "什么是 goroutine 泄漏呢？"}, // near-duplicate reworded
		{Question: "如何设计一个分布式限流器？"},      // distinct — kept
		{Question: "如何设计一个分布式限流器？"},      // batch-internal duplicate
	}

	kept, skipped := DedupGenerated(existing, generated)
	if len(kept) != 1 {
		t.Fatalf("expected 1 kept question, got %d: %+v", len(kept), kept)
	}
	if kept[0].Question != "如何设计一个分布式限流器？" {
		t.Fatalf("unexpected kept question: %q", kept[0].Question)
	}
	if skipped != 3 {
		t.Fatalf("expected 3 skipped, got %d", skipped)
	}
}

func TestDedupGeneratedEmptyExisting(t *testing.T) {
	generated := []GeneratedQuestion{
		{Question: "题目一"},
		{Question: "题目二"},
	}
	kept, skipped := DedupGenerated(nil, generated)
	if len(kept) != 2 || skipped != 0 {
		t.Fatalf("expected 2 kept / 0 skipped, got %d / %d", len(kept), skipped)
	}
}
