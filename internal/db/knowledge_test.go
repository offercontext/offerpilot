package db

import (
	"database/sql"
	"errors"
	"strings"
	"testing"
)

func TestKnowledgeBaseAndDocumentCRUD(t *testing.T) {
	d := newTestDB(t)

	base := &KnowledgeBase{Name: "Java interview prep", Description: "Core Java notes"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	if base.ID == 0 {
		t.Fatal("expected non-zero base id")
	}

	doc := &KnowledgeDocument{
		KnowledgeBaseID: base.ID,
		Title:           "Synchronized",
		Content:         "synchronized controls monitor access\n\nIt can guard instance methods.",
		Tags:            []string{"java", "concurrency"},
		SourceType:      "manual",
	}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}
	if doc.ID == 0 {
		t.Fatal("expected non-zero doc id")
	}

	got, err := d.GetKnowledgeDocument(doc.ID)
	if err != nil {
		t.Fatalf("get doc: %v", err)
	}
	if got.Title != "Synchronized" || got.KnowledgeBaseID != base.ID || len(got.Tags) != 2 {
		t.Fatalf("unexpected doc: %+v", got)
	}

	doc.Title = "Java synchronized"
	doc.Content = "monitor lock and happens-before"
	doc.Tags = []string{"java"}
	if err := d.UpdateKnowledgeDocument(doc); err != nil {
		t.Fatalf("update doc: %v", err)
	}

	listed, err := d.ListKnowledgeDocuments(KnowledgeDocumentFilter{KnowledgeBaseID: base.ID, Query: "happens"})
	if err != nil {
		t.Fatalf("list docs: %v", err)
	}
	if len(listed) != 1 || listed[0].Title != "Java synchronized" {
		t.Fatalf("unexpected filtered docs: %+v", listed)
	}

	if err := d.DeleteKnowledgeDocument(doc.ID); err != nil {
		t.Fatalf("delete doc: %v", err)
	}
	if _, err := d.GetKnowledgeDocument(doc.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected missing doc after delete, got %v", err)
	}
}

func TestKnowledgeSearchAndChunkRefresh(t *testing.T) {
	d := newTestDB(t)
	base := &KnowledgeBase{Name: "Go learning notes"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &KnowledgeDocument{
		KnowledgeBaseID: base.ID,
		Title:           "Scheduler",
		Content:         "goroutine scheduling uses M P G.\n\nChannels coordinate communication.",
		Tags:            []string{"go"},
		SourceType:      "manual",
	}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	results, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "goroutine", Limit: 5})
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if len(results) != 1 || results[0].DocumentTitle != "Scheduler" || !strings.Contains(results[0].Snippet, "goroutine") {
		t.Fatalf("unexpected search results: %+v", results)
	}

	doc.Content = "mutex protects shared memory"
	if err := d.UpdateKnowledgeDocument(doc); err != nil {
		t.Fatalf("update doc: %v", err)
	}
	oldResults, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "goroutine", Limit: 5})
	if err != nil {
		t.Fatalf("search old content: %v", err)
	}
	if len(oldResults) != 0 {
		t.Fatalf("old chunks should be removed, got %+v", oldResults)
	}
	newResults, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "mutex", Limit: 5})
	if err != nil {
		t.Fatalf("search new content: %v", err)
	}
	if len(newResults) != 1 || newResults[0].KnowledgeBaseName != "Go learning notes" {
		t.Fatalf("unexpected new search results: %+v", newResults)
	}
}

func TestKnowledgeSearchFindsChinesePhrase(t *testing.T) {
	d := newTestDB(t)
	base := &KnowledgeBase{Name: "Chinese notes"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &KnowledgeDocument{
		KnowledgeBaseID: base.ID,
		Title:           "人之力",
		Content:         "人之力指的是凡人之力",
		SourceType:      "manual",
	}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	results, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "人之力", Limit: 5})
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if len(results) != 1 || results[0].DocumentTitle != "人之力" || !strings.Contains(results[0].Snippet, "人之力") {
		t.Fatalf("expected Chinese phrase match, got %+v", results)
	}
}

func TestKnowledgeBaseDeleteCascadesDocumentsAndChunks(t *testing.T) {
	d := newTestDB(t)
	base := &KnowledgeBase{Name: "Project material"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &KnowledgeDocument{KnowledgeBaseID: base.ID, Title: "Cache project", Content: "redis cache invalidation", SourceType: "manual"}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	if err := d.DeleteKnowledgeBase(base.ID); err != nil {
		t.Fatalf("delete base: %v", err)
	}
	if _, err := d.GetKnowledgeDocument(doc.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected doc cascade delete, got %v", err)
	}
	results, err := d.SearchKnowledge(KnowledgeSearchFilter{Query: "redis", Limit: 5})
	if err != nil {
		t.Fatalf("search after cascade: %v", err)
	}
	if len(results) != 0 {
		t.Fatalf("expected no chunks after cascade, got %+v", results)
	}
}
