package api

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

// registerMockRoutes wires the mock-interview session endpoints onto /api/mock.
func registerMockRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Route("/mock", func(r chi.Router) {
		r.Get("/sessions", listMockSessionsHandler(database))
		r.Post("/sessions", createMockSessionHandler(database))
		r.Get("/sessions/{id}", getMockSessionHandler(database))
		r.Post("/sessions/{id}/end", endMockSessionHandler(database, dataDir))
		r.Delete("/sessions/{id}", deleteMockSessionHandler(database))
	})
}

// mockSessionRequestBody is the create payload. Conversation + session are
// created together; the client never passes a conversation_id.
type mockSessionRequestBody struct {
	ApplicationID   *int64 `json:"application_id,omitempty"`
	Title           string `json:"title"`
	Role            string `json:"role"`
	Company         string `json:"company"`
	RoundType       string `json:"round_type"`
	Difficulty      string `json:"difficulty"`
	QuestionCount   int    `json:"question_count"`
	DurationMin     int    `json:"duration_min"`
	QuestionSource  string `json:"question_source"`
	KnowledgeBaseID *int64 `json:"knowledge_base_id,omitempty"`
}

// loadMockContext assembles runtime context for the interviewer prompt:
// picked question-bank questions (by difficulty/KB), knowledge-base chunks,
// and weak points mined from the bound application's past interview notes.
func loadMockContext(database *db.Database, sess *db.MockSession) ai.MockContext {
	ctx := ai.MockContext{}

	// Question bank: when the source uses the bank, pull matching questions.
	if sess.QuestionSource == "bank" || sess.QuestionSource == "mixed" {
		f := db.QuestionFilter{Difficulty: sess.Difficulty}
		if sess.KnowledgeBaseID != nil {
			f.KnowledgeBaseID = *sess.KnowledgeBaseID
		}
		qs, err := database.ListQuestions(f)
		if err == nil {
			// Cap to a reasonable pick pool (the model chooses from these).
			if len(qs) > 12 {
				qs = qs[:12]
			}
			ctx.PickedQuestions = qs
		}
	}

	// Knowledge chunks: when the source uses knowledge, pull a few chunks via FTS.
	if (sess.QuestionSource == "knowledge" || sess.QuestionSource == "mixed") && sess.KnowledgeBaseID != nil {
		results, err := database.SearchKnowledge(db.KnowledgeSearchFilter{
			KnowledgeBaseID: *sess.KnowledgeBaseID,
			Limit:           6,
		})
		if err == nil {
			for _, r := range results {
				ctx.KnowledgeChunks = append(ctx.KnowledgeChunks, r.Snippet)
			}
		}
	}

	// Weak points from past interview notes on the bound application.
	if sess.ApplicationID != nil {
		notes, err := database.ListInterviewNotes(*sess.ApplicationID)
		if err == nil {
			for _, n := range notes {
				if strings.TrimSpace(n.DifficultyPoints) != "" {
					ctx.WeakPoints = append(ctx.WeakPoints, n.DifficultyPoints)
					if len(ctx.WeakPoints) >= 6 {
						break
					}
				}
			}
		}
	}
	return ctx
}

// mockTitleFor derives a session title from config (used when title empty).
func mockTitleFor(s *db.MockSession) string {
	if s.Title != "" {
		return s.Title
	}
	name := s.Role
	if name == "" {
		name = "模拟面试"
	}
	if s.Company != "" {
		name = s.Company + " · " + name
	}
	return name
}

func createMockSessionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body mockSessionRequestBody
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			respondError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		if strings.TrimSpace(body.Role) == "" {
			respondError(w, http.StatusBadRequest, "role is required")
			return
		}

		conv, err := database.CreateConversationWithMode(mockTitleFor(&db.MockSession{
			Title: body.Title, Role: body.Role, Company: body.Company,
		}), "mock_interview", nil)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}

		sess := &db.MockSession{
			ConversationID:  conv.ID,
			ApplicationID:   body.ApplicationID,
			Title:           conv.Title,
			Role:            body.Role,
			Company:         body.Company,
			RoundType:       defaultIfEmpty(body.RoundType, "technical"),
			Difficulty:      defaultIfEmpty(body.Difficulty, "medium"),
			QuestionCount:   body.QuestionCount,
			DurationMin:     body.DurationMin,
			QuestionSource:  defaultIfEmpty(body.QuestionSource, "mixed"),
			KnowledgeBaseID: body.KnowledgeBaseID,
		}
		if sess.QuestionCount == 0 {
			sess.QuestionCount = 5
		}
		if err := database.CreateMockSession(sess); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, map[string]interface{}{
			"session":          sess,
			"conversation_id":  conv.ID,
			"conversation":     conv,
		})
	}
}

func listMockSessionsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		status := r.URL.Query().Get("status")
		sessions, err := database.ListMockSessions(status)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if sessions == nil {
			sessions = []db.MockSession{}
		}
		respondJSON(w, http.StatusOK, sessions)
	}
}

func getMockSessionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		sess, err := database.GetMockSession(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "session not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		// Include recent messages so the client can render the running dialogue.
		msgs, _ := database.ListMessages(sess.ConversationID)
		if msgs == nil {
			msgs = []db.ChatMessage{}
		}
		respondJSON(w, http.StatusOK, map[string]interface{}{
			"session":     sess,
			"messages":    msgs,
		})
	}
}

// endMockSessionRequestBody is the end-session payload.
type endMockSessionRequestBody struct {
	AutoSaveNote bool `json:"auto_save_note"`
}

// scorerFunc scores a finished interview transcript. The production
// implementation builds an ai.Client from config; tests inject a fake.
type scorerFunc func(ctx context.Context, sess *db.MockSession, transcript string) (string, error)

// endMockSessionHandler marks a session completed and runs the AI scoring pass.
// The scoring pass is a single no-tools Complete/Chat call; the dialogue itself
// is already persisted in chat_messages and is fed back as the transcript.
func endMockSessionHandler(database *db.Database, dataDir string) http.HandlerFunc {
	scorer := productionScorer(database, dataDir)
	return endMockSessionHandlerWithScorer(database, scorer)
}

// endMockSessionHandlerWithScorer allows tests to inject a fake scorer.
//
// Three branches:
//  1. status == in_progress → run the AI scoring pass, finalize the session,
//     and optionally auto-save a retrospective note.
//  2. status == completed with auto_save_note=true → the session was already
//     scored (e.g. the user clicked "结束并评分" and is now on the result page
//     clicking "保存为面试复盘"). Reuse the persisted feedback to write the
//     note WITHOUT re-scoring. This avoids a 409 and a redundant AI call.
//  3. otherwise → 409 (already ended and not asking to save a note).
func endMockSessionHandlerWithScorer(database *db.Database, scorer scorerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		sess, err := database.GetMockSession(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "session not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}

		var body endMockSessionRequestBody
		_ = json.NewDecoder(r.Body).Decode(&body) // optional body; ignore decode errors

		// Branch 2: a completed session whose user wants to persist a review note
		// after the fact. Reuse the stored feedback; never re-score.
		if sess.Status == "completed" && body.AutoSaveNote {
			noteID, ferr := writeNoteFromFeedback(database, sess, sess.Feedback)
			if ferr != "" {
				respondError(w, http.StatusBadRequest, ferr)
				return
			}
			respondJSON(w, http.StatusOK, map[string]interface{}{
				"session":      sess,
				"feedback":     parseStoredFeedback(sess.Feedback),
				"saved_note_id": noteID,
			})
			return
		}

		// Branch 3: already ended and not a save-note request.
		if sess.Status != "in_progress" {
			respondError(w, http.StatusConflict, "session already ended")
			return
		}

		// Branch 1: score a still-running session.
		transcript := buildTranscript(database, sess.ConversationID)

		raw, serr := scorer(r.Context(), sess, transcript)
		if serr != nil {
			// Mark aborted-without-score so the user can still retry, but surface the error.
			_ = database.AbortMockSession(id)
			respondError(w, http.StatusBadGateway, "评分失败："+serr.Error())
			return
		}

		fb, parseErr := ai.ParseScoringResult(raw)
		scores := db.MockScores{
			ScoreOverall:       fb.ScoreOverall,
			ScoreCommunication: fb.ScoreCommunication,
			ScoreDepth:         fb.ScoreDepth,
			ScoreStructure:     fb.ScoreStructure,
			ScoreConfidence:    fb.ScoreConfidence,
		}
		feedbackJSON, _ := json.Marshal(fb)
		if err := database.FinishMockSession(id, scores, string(feedbackJSON)); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}

		// Optional: auto-save a retrospective note (works for both bound and
		// unbound sessions; interview_notes.application_id is nullable).
		noteID := int64(0)
		if body.AutoSaveNote {
			if n, _ := createMockNote(database, sess, fb.Summary, fb.Weaknesses); n != nil {
				noteID = n.ID
			}
		}

		done, _ := database.GetMockSession(id)
		resp := map[string]interface{}{
			"session":     done,
			"feedback":    fb,
			"parse_error": parseErr != nil,
		}
		if noteID > 0 {
			resp["saved_note_id"] = noteID
		}
		respondJSON(w, http.StatusOK, resp)
	}
}

func deleteMockSessionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		sess, err := database.GetMockSession(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "session not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		// Deleting the conversation cascades to the session row (FK).
		if err := database.DeleteConversation(sess.ConversationID); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
	}
}

// buildTranscript joins the stored dialogue into a readable transcript for scoring.
func buildTranscript(database *db.Database, convID int64) string {
	msgs, err := database.ListMessages(convID)
	if err != nil {
		return ""
	}
	var b strings.Builder
	for _, m := range msgs {
		if m.Content == "" || m.Role == "tool" {
			continue
		}
		who := "候选人"
		if m.Role == "assistant" {
			who = "面试官"
		}
		b.WriteString(who + "：" + m.Content + "\n")
	}
	return strings.TrimSpace(b.String())
}

func todayString() string {
	return time.Now().Format("2006-01-02")
}

func joinWeaknesses(ws []string) string {
	if len(ws) == 0 {
		return ""
	}
	return "待加强：" + strings.Join(ws, "；")
}

func defaultIfEmpty(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// createMockNote builds and persists an interview-retrospective note from a
// finished mock session. When a session is bound to an application, company/
// position fall back to that application's values; when unbound, the note is
// still written with application_id=NULL using the session's own role/company
// (interview_notes.application_id is nullable). Returns (nil, nil) only if no
// noteable content exists.
func createMockNote(database *db.Database, sess *db.MockSession, summary string, weaknesses []string) (*db.InterviewNote, error) {
	company := sess.Company
	position := sess.Role
	// When bound to an application, fill any missing company/position from it.
	if sess.ApplicationID != nil && (company == "" || position == "") {
		if app, aerr := database.GetApplication(*sess.ApplicationID); aerr == nil && app != nil {
			if company == "" {
				company = app.CompanyName
			}
			if position == "" {
				position = app.PositionName
			}
		}
	}
	// Without an application, fall back to the round type as position so the
	// note still has a meaningful identity in the review list.
	if position == "" {
		position = "模拟面试"
	}
	n := &db.InterviewNote{
		ApplicationID:    sess.ApplicationID, // may be nil → NULL column
		Company:          company,
		Position:         position,
		Round:            "模拟面试·" + sess.RoundType,
		Date:             todayString(),
		SelfReflection:   summary,
		DifficultyPoints: joinWeaknesses(weaknesses),
	}
	if err := database.CreateInterviewNote(n); err != nil {
		return nil, err
	}
	return n, nil
}

// writeNoteFromFeedback parses the persisted feedback JSON of a completed
// session and writes a retrospective note. Returns the note id and an error
// string (empty on success): non-empty string means a 4xx-level problem the
// caller should surface (missing/corrupt feedback). A session with no bound
// application still yields a note (application_id NULL).
func writeNoteFromFeedback(database *db.Database, sess *db.MockSession, feedbackJSON string) (int64, string) {
	if feedbackJSON == "" {
		return 0, "该会话没有评分数据，无法保存为面试复盘"
	}
	var fb ai.ScoringFeedback
	if err := json.Unmarshal([]byte(feedbackJSON), &fb); err != nil {
		return 0, "评分数据损坏，无法保存为面试复盘"
	}
	n, err := createMockNote(database, sess, fb.Summary, fb.Weaknesses)
	if err != nil {
		return 0, err.Error()
	}
	if n == nil {
		return 0, "保存面试复盘失败"
	}
	return n.ID, ""
}

// parseStoredFeedback best-effort decodes a completed session's feedback JSON
// for the API response. Returns the raw string wrapped in an object shape on
// failure so the client never gets a nil.
func parseStoredFeedback(feedbackJSON string) interface{} {
	if feedbackJSON == "" {
		return ai.ScoringFeedback{}
	}
	var fb ai.ScoringFeedback
	if err := json.Unmarshal([]byte(feedbackJSON), &fb); err != nil {
		return feedbackJSON
	}
	return fb
}

// productionScorer builds a closure that loads config lazily per request and
// runs a single no-tools Chat call against the configured AI provider.
func productionScorer(_ *db.Database, dataDir string) scorerFunc {
	return func(ctx context.Context, sess *db.MockSession, transcript string) (string, error) {
		cfg, err := config.Load(dataDir)
		if err != nil {
			return "", err
		}
		client, err := ai.New(cfg)
		if err != nil {
			return "", err
		}
		prompt := ai.MockScoringPrompt(sess, transcript)
		return client.Chat(ctx, "你是一位面试评估专家，严格按JSON输出。", prompt)
	}
}