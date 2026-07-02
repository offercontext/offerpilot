package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

// questionRequest is the body for manual create/update of a question.
type questionRequest struct {
	Category        string   `json:"category"`
	Difficulty      string   `json:"difficulty"`
	Question        string   `json:"question"`
	ReferenceAnswer string   `json:"reference_answer"`
	Tags            []string `json:"tags"`
	Status          string   `json:"status"`
}

// generateQuestionsRequest is the body for POST /api/questions/generate.
type generateQuestionsRequest struct {
	Source          string `json:"source"` // knowledge | notes
	KnowledgeBaseID int64  `json:"knowledge_base_id"`
	ApplicationID   int64  `json:"application_id"`
	Count           int    `json:"count"`
}

// reviewRequest is the body for POST /api/questions/{id}/reviews.
type reviewRequest struct {
	Rating int    `json:"rating"`
	Note   string `json:"note"`
}

// registerQuestionRoutes wires the question-bank endpoints onto the /api group.
func registerQuestionRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Get("/questions", listQuestionsHandler(database))
	r.Post("/questions", createQuestionHandler(database))
	r.Post("/questions/generate", generateQuestionsHandler(database, dataDir))
	r.Get("/questions/due", listDueQuestionsHandler(database))
	r.Get("/questions/stats", questionStatsHandler(database))
	r.Get("/questions/{id}", getQuestionHandler(database))
	r.Put("/questions/{id}", updateQuestionHandler(database))
	r.Delete("/questions/{id}", deleteQuestionHandler(database))
	r.Post("/questions/{id}/reviews", createReviewHandler(database))
}

func listQuestionsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		filter := db.QuestionFilter{
			Category:   r.URL.Query().Get("category"),
			Difficulty: r.URL.Query().Get("difficulty"),
			Status:     r.URL.Query().Get("status"),
		}
		if v := r.URL.Query().Get("knowledge_base_id"); v != "" {
			if id, err := strconv.ParseInt(v, 10, 64); err == nil {
				filter.KnowledgeBaseID = id
			}
		}
		questions, err := database.ListQuestions(filter)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, questions)
	}
}

func createQuestionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q, ok := decodeQuestionRequest(w, r)
		if !ok {
			return
		}
		q.SourceType = "manual"
		if err := database.CreateQuestion(q); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, q)
	}
}

func getQuestionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := questionIDParam(w, r)
		if !ok {
			return
		}
		q, err := database.GetQuestion(id)
		if err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusNotFound, "题目不存在")
				return
			}
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, q)
	}
}

func updateQuestionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := questionIDParam(w, r)
		if !ok {
			return
		}
		q, ok := decodeQuestionRequest(w, r)
		if !ok {
			return
		}
		q.ID = id
		if err := database.UpdateQuestion(q); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusNotFound, "题目不存在")
				return
			}
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		updated, err := database.GetQuestion(id)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, updated)
	}
}

func deleteQuestionHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := questionIDParam(w, r)
		if !ok {
			return
		}
		if err := database.DeleteQuestion(id); err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusNotFound, "题目不存在")
				return
			}
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}

func generateQuestionsHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req generateQuestionsRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "请求体格式错误")
			return
		}

		source := strings.TrimSpace(req.Source)
		if source == "" {
			source = "knowledge"
		}

		var (
			label, contextText string
			sourceType         string
			kbID, appID        *int64
			err                error
		)
		switch source {
		case "knowledge":
			if req.KnowledgeBaseID <= 0 {
				respondError(w, http.StatusBadRequest, "请选择知识库")
				return
			}
			label, contextText, err = ai.BuildKnowledgeContext(database, req.KnowledgeBaseID)
			sourceType = ai.QuestionSourceKnowledge
			id := req.KnowledgeBaseID
			kbID = &id
		case "notes":
			label, contextText, err = ai.BuildNotesContext(database, req.ApplicationID)
			sourceType = ai.QuestionSourceNotes
			if req.ApplicationID > 0 {
				id := req.ApplicationID
				appID = &id
			}
		default:
			respondError(w, http.StatusBadRequest, "不支持的来源类型")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if strings.TrimSpace(contextText) == "" {
			respondError(w, http.StatusBadRequest, "所选来源没有可用于生成题目的内容")
			return
		}

		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		client, err := ai.New(cfg)
		if err != nil {
			respondError(w, http.StatusServiceUnavailable, err.Error())
			return
		}

		// Existing questions: used both to nudge the model (prompt exclusion)
		// and to hard-dedup the results before persisting.
		existing, err := database.ListQuestionDigests()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		existingStems := make([]string, 0, len(existing))
		for _, d := range existing {
			existingStems = append(existingStems, d.Question)
		}

		generated, err := ai.GenerateQuestions(r.Context(), client, label, contextText, req.Count, existingStems)
		if err != nil {
			respondError(w, http.StatusBadGateway, err.Error())
			return
		}
		saved, skipped, err := ai.PersistGeneratedQuestions(database, kbID, appID, sourceType, generated, existing)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, map[string]interface{}{
			"count":     len(saved),
			"skipped":   skipped,
			"questions": saved,
		})
	}
}

func listDueQuestionsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		limit := 0
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				limit = n
			}
		}
		questions, err := database.ListDueQuestions(limit)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, questions)
	}
}

func questionStatsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		stats, err := database.PracticeStats()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, stats)
	}
}

func createReviewHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := questionIDParam(w, r)
		if !ok {
			return
		}
		var req reviewRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "请求体格式错误")
			return
		}
		if req.Rating < db.QuestionRatingAgain || req.Rating > db.QuestionRatingGood {
			respondError(w, http.StatusBadRequest, "rating 需为 1(不会)、2(模糊) 或 3(掌握)")
			return
		}
		review := &db.QuestionReview{QuestionID: id, Rating: req.Rating, Note: req.Note}
		updated, err := database.AddQuestionReview(review)
		if err != nil {
			if errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusNotFound, "题目不存在")
				return
			}
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, map[string]interface{}{
			"review":   review,
			"question": updated,
		})
	}
}

// decodeQuestionRequest parses and validates a question create/update body.
func decodeQuestionRequest(w http.ResponseWriter, r *http.Request) (*db.Question, bool) {
	var req questionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, http.StatusBadRequest, "请求体格式错误")
		return nil, false
	}
	req.Question = strings.TrimSpace(req.Question)
	if req.Question == "" {
		respondError(w, http.StatusBadRequest, "题目内容不能为空")
		return nil, false
	}
	if req.Tags == nil {
		req.Tags = []string{}
	}
	return &db.Question{
		Category:        strings.TrimSpace(req.Category),
		Difficulty:      req.Difficulty,
		Question:        req.Question,
		ReferenceAnswer: strings.TrimSpace(req.ReferenceAnswer),
		Tags:            req.Tags,
		Status:          req.Status,
	}, true
}

func questionIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "无效的 ID")
		return 0, false
	}
	return id, true
}
