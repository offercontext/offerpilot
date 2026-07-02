package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func questionTestRouter(t *testing.T) http.Handler {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/questions.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return NewRouter(d, t.TempDir())
}

func questionAPIRequest(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body: %v", err)
		}
		reader = bytes.NewReader(data)
	} else {
		reader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func TestQuestionAPICRUDAndReview(t *testing.T) {
	router := questionTestRouter(t)

	// Create.
	createRec := questionAPIRequest(t, router, http.MethodPost, "/api/questions", map[string]interface{}{
		"category": "系统设计", "difficulty": "hard", "question": "如何设计一个短链系统？", "reference_answer": "发号器 + 缓存", "tags": []string{"系统设计"},
	})
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", createRec.Code, createRec.Body.String())
	}
	var created db.Question
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created: %v", err)
	}
	if created.ID == 0 || created.SourceType != "manual" || created.Status != db.QuestionStatusNew {
		t.Fatalf("unexpected created question: %+v", created)
	}

	// List.
	listRec := questionAPIRequest(t, router, http.MethodGet, "/api/questions", nil)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status %d", listRec.Code)
	}
	var list []db.Question
	if err := json.Unmarshal(listRec.Body.Bytes(), &list); err != nil {
		t.Fatalf("decode list: %v", err)
	}
	if len(list) != 1 {
		t.Fatalf("expected 1 question, got %d", len(list))
	}

	// Review (check-in) with rating "good" → mastered.
	reviewRec := questionAPIRequest(t, router, http.MethodPost, "/api/questions/"+itoa(created.ID)+"/reviews", map[string]interface{}{
		"rating": 3, "note": "答得不错",
	})
	if reviewRec.Code != http.StatusCreated {
		t.Fatalf("review status %d: %s", reviewRec.Code, reviewRec.Body.String())
	}
	var reviewResp struct {
		Question db.Question `json:"question"`
	}
	if err := json.Unmarshal(reviewRec.Body.Bytes(), &reviewResp); err != nil {
		t.Fatalf("decode review resp: %v", err)
	}
	if reviewResp.Question.Status != db.QuestionStatusMastered || reviewResp.Question.PracticeCount != 1 {
		t.Fatalf("review did not update state: %+v", reviewResp.Question)
	}

	// Invalid rating rejected.
	badRec := questionAPIRequest(t, router, http.MethodPost, "/api/questions/"+itoa(created.ID)+"/reviews", map[string]interface{}{"rating": 9})
	if badRec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for bad rating, got %d", badRec.Code)
	}

	// Stats reflect the mastered question + today's check-in.
	statsRec := questionAPIRequest(t, router, http.MethodGet, "/api/questions/stats", nil)
	if statsRec.Code != http.StatusOK {
		t.Fatalf("stats status %d", statsRec.Code)
	}
	var stats db.QuestionPracticeStats
	if err := json.Unmarshal(statsRec.Body.Bytes(), &stats); err != nil {
		t.Fatalf("decode stats: %v", err)
	}
	if stats.Total != 1 || stats.Mastered != 1 || stats.TodayReviews != 1 {
		t.Fatalf("unexpected stats: %+v", stats)
	}

	// Delete.
	delRec := questionAPIRequest(t, router, http.MethodDelete, "/api/questions/"+itoa(created.ID), nil)
	if delRec.Code != http.StatusNoContent {
		t.Fatalf("delete status %d: %s", delRec.Code, delRec.Body.String())
	}
}

func TestQuestionAPIValidation(t *testing.T) {
	router := questionTestRouter(t)

	// Empty question rejected.
	rec := questionAPIRequest(t, router, http.MethodPost, "/api/questions", map[string]interface{}{"question": "   "})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for empty question, got %d", rec.Code)
	}

	// Generate with missing knowledge base rejected before hitting AI.
	genRec := questionAPIRequest(t, router, http.MethodPost, "/api/questions/generate", map[string]interface{}{"source": "knowledge"})
	if genRec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing kb, got %d: %s", genRec.Code, genRec.Body.String())
	}
}

func itoa(id int64) string {
	return strconv.FormatInt(id, 10)
}
