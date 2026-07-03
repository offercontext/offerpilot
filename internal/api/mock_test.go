package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

// mockTestRouter builds a chi router with the mock session routes, but lets the
// caller inject a fake scorer (so the end handler never needs a configured AI
// client). Other mock endpoints reuse the production handlers.
func mockTestRouter(t *testing.T, scorer scorerFunc) (*db.Database, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/mock.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	r := chi.NewRouter()
	r.Route("/api/mock", func(r chi.Router) {
		r.Get("/sessions", listMockSessionsHandler(d))
		r.Post("/sessions", createMockSessionHandler(d))
		r.Get("/sessions/{id}", getMockSessionHandler(d))
		if scorer != nil {
			r.Post("/sessions/{id}/end", endMockSessionHandlerWithScorer(d, scorer))
		} else {
			r.Post("/sessions/{id}/end", endMockSessionHandlerWithScorer(d, productionScorer(d, t.TempDir())))
		}
		r.Delete("/sessions/{id}", deleteMockSessionHandler(d))
	})
	return d, r
}

func mockReq(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, _ := json.Marshal(body)
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

func TestMockSessionCreateAndGet(t *testing.T) {
	d, router := mockTestRouter(t, nil)

	rec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"role": "后端开发", "company": "字节跳动", "round_type": "technical",
		"difficulty": "hard", "question_count": 5, "duration_min": 30, "question_source": "bank",
	})
	if rec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", rec.Code, rec.Body.String())
	}
	var created struct {
		Session        db.MockSession `json:"session"`
		ConversationID int64          `json:"conversation_id"`
	}
	_ = json.Unmarshal(rec.Body.Bytes(), &created)
	if created.Session.ID == 0 || created.Session.Role != "后端开发" {
		t.Fatalf("unexpected session: %+v", created.Session)
	}
	if created.ConversationID == 0 || created.Session.ConversationID != created.ConversationID {
		t.Fatalf("conversation binding wrong: %+v", created)
	}

	// Conversation must be mode=mock_interview.
	conv, _ := d.GetConversation(created.ConversationID)
	if conv.Mode != "mock_interview" {
		t.Fatalf("expected mock_interview mode, got %q", conv.Mode)
	}

	getRec := mockReq(t, router, http.MethodGet, "/api/mock/sessions/"+itoa(created.Session.ID), nil)
	if getRec.Code != http.StatusOK {
		t.Fatalf("get status %d: %s", getRec.Code, getRec.Body.String())
	}
}

func TestMockSessionCreateValidatesRole(t *testing.T) {
	_, router := mockTestRouter(t, nil)
	rec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"company": "字节",
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing role, got %d", rec.Code)
	}
}

func TestMockSessionListByStatus(t *testing.T) {
	_, router := mockTestRouter(t, func(_ context.Context, _ *db.MockSession, _ string) (string, error) {
		return `{"score_overall":60,"summary":"ok","strengths":[],"weaknesses":[],"drills":[]}`, nil
	})
	// Create two sessions; end one.
	mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{"role": "前端", "round_type": "technical"})
	r2 := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{"role": "后端", "round_type": "behavioral"})
	var s2 struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(r2.Body.Bytes(), &s2)
	mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(s2.Session.ID)+"/end", map[string]interface{}{})

	all := mockReq(t, router, http.MethodGet, "/api/mock/sessions", nil)
	var listAll []db.MockSession
	_ = json.Unmarshal(all.Body.Bytes(), &listAll)
	if len(listAll) != 2 {
		t.Fatalf("want 2 sessions, got %d", len(listAll))
	}

	progress := mockReq(t, router, http.MethodGet, "/api/mock/sessions?status=in_progress", nil)
	var listP []db.MockSession
	_ = json.Unmarshal(progress.Body.Bytes(), &listP)
	if len(listP) != 1 || listP[0].Role != "前端" {
		t.Fatalf("want 1 in_progress 前端, got %+v", listP)
	}
}

func TestMockSessionEndWithScoring(t *testing.T) {
	d, router := mockTestRouter(t, func(_ context.Context, sess *db.MockSession, transcript string) (string, error) {
		if sess.Role != "后端开发" {
			t.Errorf("scorer got wrong role: %s", sess.Role)
		}
		if !strings.Contains(transcript, "候选人") && !strings.Contains(transcript, "面试官") {
			t.Errorf("transcript missing dialogue: %q", transcript)
		}
		return `{"score_overall":78,"score_communication":80,"score_depth":72,"score_structure":75,"score_confidence":85,"summary":"中等偏上","strengths":["STAR清晰"],"weaknesses":["系统设计偏浅"],"drills":[{"area":"系统设计","action":"补练容量估算题","link_question_ids":[12,34]}]}`, nil
	})

	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"role": "后端开发", "company": "字节", "round_type": "technical", "difficulty": "hard",
	})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)

	// Seed a dialogue on the bound conversation.
	conv, _ := d.GetConversation(created.Session.ConversationID)
	_ = d.AppendMessage(&db.ChatMessage{ConversationID: conv.ID, Role: "user", Content: "我做过高并发系统"})
	_ = d.AppendMessage(&db.ChatMessage{ConversationID: conv.ID, Role: "assistant", Content: "讲讲你怎么做的限流"})

	endRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{})
	if endRec.Code != http.StatusOK {
		t.Fatalf("end status %d: %s", endRec.Code, endRec.Body.String())
	}
	var resp struct {
		Session  db.MockSession       `json:"session"`
		Feedback aiScoringFeedback    `json:"feedback"`
		SavedNoteID int64             `json:"saved_note_id"`
	}
	_ = json.Unmarshal(endRec.Body.Bytes(), &resp)
	if resp.Session.Status != "completed" || resp.Session.ScoreOverall == nil || *resp.Session.ScoreOverall != 78 {
		t.Fatalf("session not completed/scored: %+v", resp.Session)
	}
	if resp.Feedback.Summary != "中等偏上" || len(resp.Feedback.Drills) != 1 {
		t.Fatalf("feedback wrong: %+v", resp.Feedback)
	}

	// Ending again must 409.
	again := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{})
	if again.Code != http.StatusConflict {
		t.Fatalf("expected 409 on re-end, got %d", again.Code)
	}
}

func TestMockSessionEndAutoSavesNote(t *testing.T) {
	d, router := mockTestRouter(t, func(_ context.Context, _ *db.MockSession, _ string) (string, error) {
		return `{"score_overall":70,"summary":"还可以","strengths":["项目清晰"],"weaknesses":["追问跑题"],"drills":[]}`, nil
	})

	app := &db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatal(err)
	}
	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"role": "后端", "round_type": "technical", "application_id": app.ID,
	})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)
	if created.Session.ApplicationID == nil || *created.Session.ApplicationID != app.ID {
		t.Fatalf("application not bound: %+v", created.Session)
	}

	endRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{"auto_save_note": true})
	if endRec.Code != http.StatusOK {
		t.Fatalf("end status %d: %s", endRec.Code, endRec.Body.String())
	}
	var resp struct{ SavedNoteID int64 `json:"saved_note_id"` }
	_ = json.Unmarshal(endRec.Body.Bytes(), &resp)
	if resp.SavedNoteID == 0 {
		t.Fatal("expected saved_note_id > 0")
	}
	n, _ := d.GetInterviewNote(resp.SavedNoteID)
	if n == nil || n.Company != "字节" || !strings.Contains(n.DifficultyPoints, "追问跑题") {
		t.Fatalf("note not persisted correctly: %+v", n)
	}
}

func TestMockSessionSaveNoteAfterCompletion(t *testing.T) {
	// Regression: a completed session's "保存为面试复盘" re-POSTs /end with
	// auto_save_note=true. It must reuse the stored feedback (no re-scoring) and
	// write a note, returning 200 — not the 409 it used to.
	calls := 0
	d, router := mockTestRouter(t, func(_ context.Context, _ *db.MockSession, _ string) (string, error) {
		calls++
		return `{"score_overall":72,"summary":"还可以","strengths":["项目清晰"],"weaknesses":["追问跑题"],"drills":[]}`, nil
	})

	app := &db.Application{CompanyName: "美团", PositionName: "后端", Status: "interview", Source: "cli"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatal(err)
	}
	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"role": "后端", "round_type": "technical", "application_id": app.ID,
	})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)

	// 1) End with scoring (no auto-save).
	first := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{})
	if first.Code != http.StatusOK {
		t.Fatalf("first end status %d: %s", first.Code, first.Body.String())
	}

	// 2) Now save the note from the result page — must NOT re-score.
	saveRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{"auto_save_note": true})
	if saveRec.Code != http.StatusOK {
		t.Fatalf("save-after-complete status %d: %s", saveRec.Code, saveRec.Body.String())
	}
	if calls != 1 {
		t.Fatalf("scorer should be called exactly once (during initial end), got %d", calls)
	}
	var resp struct {
		Session     db.MockSession `json:"session"`
		SavedNoteID int64          `json:"saved_note_id"`
	}
	_ = json.Unmarshal(saveRec.Body.Bytes(), &resp)
	if resp.SavedNoteID == 0 {
		t.Fatal("expected saved_note_id on save-after-complete")
	}
	n, _ := d.GetInterviewNote(resp.SavedNoteID)
	if n == nil || n.Company != "美团" || !strings.Contains(n.DifficultyPoints, "追问跑题") {
		t.Fatalf("note wrong: %+v", n)
	}
}

func TestMockSessionSaveNoteUnboundSession(t *testing.T) {
	// A session NOT bound to any application must still be able to save a review
	// note (interview_notes.application_id is nullable). Regression for the
	// "该模拟面试未绑定投递，无法保存为面试复盘" 400 that blocked the UI.
	calls := 0
	d, router := mockTestRouter(t, func(_ context.Context, _ *db.MockSession, _ string) (string, error) {
		calls++
		return `{"score_overall":65,"summary":"裸练一次","strengths":["思路清晰"],"weaknesses":["深度不够"],"drills":[]}`, nil
	})

	// Create WITHOUT application_id.
	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{
		"role": "算法", "round_type": "technical",
	})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)
	if created.Session.ApplicationID != nil {
		t.Fatalf("expected unbound session, got application_id=%v", created.Session.ApplicationID)
	}

	// 1) End with scoring (auto-save true) — must succeed and write a note.
	first := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{"auto_save_note": true})
	if first.Code != http.StatusOK {
		t.Fatalf("end status %d: %s", first.Code, first.Body.String())
	}
	var r1 struct{ SavedNoteID int64 `json:"saved_note_id"` }
	_ = json.Unmarshal(first.Body.Bytes(), &r1)
	if r1.SavedNoteID == 0 {
		t.Fatal("expected saved_note_id on end-with-autosave for unbound session")
	}

	// 2) Save again from result page — must reuse feedback, no re-score, new note.
	saveRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{"auto_save_note": true})
	if saveRec.Code != http.StatusOK {
		t.Fatalf("save-after-complete status %d: %s", saveRec.Code, saveRec.Body.String())
	}
	if calls != 1 {
		t.Fatalf("scorer should be called once, got %d", calls)
	}
	var r2 struct{ SavedNoteID int64 `json:"saved_note_id"` }
	_ = json.Unmarshal(saveRec.Body.Bytes(), &r2)
	if r2.SavedNoteID == 0 || r2.SavedNoteID == r1.SavedNoteID {
		t.Fatalf("expected a new saved note id, got r1=%d r2=%d", r1.SavedNoteID, r2.SavedNoteID)
	}
	n, _ := d.GetInterviewNote(r2.SavedNoteID)
	if n == nil || n.ApplicationID != nil || !strings.Contains(n.DifficultyPoints, "深度不够") {
		t.Fatalf("note wrong (expected nil app_id + 深度不够): %+v", n)
	}
}

func TestMockSessionEndScorerErrorAborts(t *testing.T) {
	d, router := mockTestRouter(t, func(_ context.Context, _ *db.MockSession, _ string) (string, error) {
		return "", errScorerBoom
	})
	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{"role": "前端"})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)

	endRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions/"+itoa(created.Session.ID)+"/end", map[string]interface{}{})
	if endRec.Code != http.StatusBadGateway {
		t.Fatalf("expected 502 on scorer error, got %d", endRec.Code)
	}
	aborted, _ := d.GetMockSession(created.Session.ID)
	if aborted.Status != "aborted" {
		t.Fatalf("expected aborted status, got %q", aborted.Status)
	}
}

func TestMockSessionDelete(t *testing.T) {
	d, router := mockTestRouter(t, nil)
	createRec := mockReq(t, router, http.MethodPost, "/api/mock/sessions", map[string]interface{}{"role": "后端"})
	var created struct{ Session db.MockSession `json:"session"` }
	_ = json.Unmarshal(createRec.Body.Bytes(), &created)

	delRec := mockReq(t, router, http.MethodDelete, "/api/mock/sessions/"+itoa(created.Session.ID), nil)
	if delRec.Code != http.StatusOK {
		t.Fatalf("delete status %d: %s", delRec.Code, delRec.Body.String())
	}
	if _, err := d.GetMockSession(created.Session.ID); err == nil {
		t.Fatal("expected session gone after delete")
	}
}

func TestMockChatInjectsMockPrompt(t *testing.T) {
	// Use the chat handler with an injected model, but pre-create a mock_interview
	// conversation + session so systemPromptFor hits the mock branch.
	d := chatTestDB(t)
	conv, _ := d.CreateConversationWithMode("模拟", "mock_interview", nil)
	sess := &db.MockSession{ConversationID: conv.ID, Title: "模拟", Role: "后端", Difficulty: "hard", QuestionSource: "mixed"}
	if err := d.CreateMockSession(sess); err != nil {
		t.Fatal(err)
	}

	model := &fakeModel{turns: []ai.Assistant{{Content: "第一题：讲讲你的项目。"}}}
	h := chatHandlerWithModel(d, model, false)

	body, _ := json.Marshal(map[string]interface{}{"conversation_id": conv.ID, "message": "开始面试"})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("chat status %d: %s", rec.Code, rec.Body.String())
	}
	if len(model.lastMsgs) == 0 {
		t.Fatal("model received no messages")
	}
	capturedSystem := model.lastMsgs[0].Content
	for _, want := range []string{"面试官", "后端", "hard"} {
		if !strings.Contains(capturedSystem, want) {
			t.Fatalf("mock prompt missing %q\n---\n%s", want, capturedSystem)
		}
	}
}

// aiScoringFeedback mirrors ai.ScoringFeedback for JSON unmarshalling in tests
// (avoids importing the ai package just for the shape).
type aiScoringFeedback struct {
	ScoreOverall int      `json:"score_overall"`
	Summary      string   `json:"summary"`
	Strengths    []string `json:"strengths"`
	Weaknesses   []string `json:"weaknesses"`
	Drills       []struct {
		Area            string  `json:"area"`
		Action          string  `json:"action"`
		LinkQuestionIDs []int64 `json:"link_question_ids"`
	} `json:"drills"`
}

var errScorerBoom = errBoom("scorer boom")

type errBoom string

func (e errBoom) Error() string { return string(e) }