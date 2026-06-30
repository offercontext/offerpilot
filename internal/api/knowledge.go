package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

const maxKnowledgeImportBytes = 1 << 20

type knowledgeBaseRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

type knowledgeDocumentRequest struct {
	KnowledgeBaseID int64    `json:"knowledge_base_id"`
	Title           string   `json:"title"`
	Content         string   `json:"content"`
	Tags            []string `json:"tags"`
}

func registerKnowledgeRoutes(r chi.Router, database *db.Database) {
	r.Get("/knowledge-bases", listKnowledgeBases(database))
	r.Post("/knowledge-bases", createKnowledgeBase(database))
	r.Put("/knowledge-bases/{id}", updateKnowledgeBase(database))
	r.Delete("/knowledge-bases/{id}", deleteKnowledgeBase(database))
	r.Get("/knowledge-documents", listKnowledgeDocuments(database))
	r.Post("/knowledge-documents", createKnowledgeDocument(database))
	r.Post("/knowledge-documents/import", importKnowledgeDocument(database))
	r.Get("/knowledge-documents/{id}", getKnowledgeDocument(database))
	r.Put("/knowledge-documents/{id}", updateKnowledgeDocument(database))
	r.Delete("/knowledge-documents/{id}", deleteKnowledgeDocument(database))
	r.Get("/knowledge/search", searchKnowledge(database))
}

func listKnowledgeBases(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		bases, err := database.ListKnowledgeBases()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, bases)
	}
}

func createKnowledgeBase(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		base, ok := decodeKnowledgeBaseRequest(w, r)
		if !ok {
			return
		}
		if err := database.CreateKnowledgeBase(base); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, base)
	}
}

func updateKnowledgeBase(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := knowledgeIDParam(w, r)
		if !ok {
			return
		}
		base, ok := decodeKnowledgeBaseRequest(w, r)
		if !ok {
			return
		}
		base.ID = id
		if err := database.UpdateKnowledgeBase(base); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge base not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, base)
	}
}

func deleteKnowledgeBase(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := knowledgeIDParam(w, r)
		if !ok {
			return
		}
		if err := database.DeleteKnowledgeBase(id); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge base not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

func listKnowledgeDocuments(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		filter, ok := knowledgeDocumentFilterFromRequest(w, r)
		if !ok {
			return
		}
		docs, err := database.ListKnowledgeDocuments(filter)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, docs)
	}
}

func createKnowledgeDocument(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		doc, ok := decodeKnowledgeDocumentRequest(w, r)
		if !ok || !knowledgeBaseExists(w, database, doc.KnowledgeBaseID) {
			return
		}
		if err := database.CreateKnowledgeDocument(doc); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, doc)
	}
}

func importKnowledgeDocument(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(maxKnowledgeImportBytes); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid multipart form")
			return
		}
		baseID, err := strconv.ParseInt(r.FormValue("knowledge_base_id"), 10, 64)
		if err != nil || baseID <= 0 {
			respondError(w, http.StatusBadRequest, "knowledge_base_id is required")
			return
		}
		if !knowledgeBaseExists(w, database, baseID) {
			return
		}

		file, header, err := r.FormFile("file")
		if err != nil {
			respondError(w, http.StatusBadRequest, "file is required")
			return
		}
		defer file.Close()

		filename := header.Filename
		ext := strings.ToLower(filepath.Ext(filename))
		if ext != ".md" && ext != ".txt" {
			respondError(w, http.StatusBadRequest, "only .md and .txt files are supported")
			return
		}
		data, err := io.ReadAll(io.LimitReader(file, maxKnowledgeImportBytes+1))
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if len(data) > maxKnowledgeImportBytes {
			respondError(w, http.StatusBadRequest, "file is too large")
			return
		}

		baseName := filepath.Base(filename)
		doc := &db.KnowledgeDocument{
			KnowledgeBaseID: baseID,
			Title:           strings.TrimSuffix(baseName, filepath.Ext(baseName)),
			Content:         string(data),
			Tags:            []string{},
			SourceType:      db.KnowledgeSourceUpload,
			SourceName:      filename,
		}
		if err := database.CreateKnowledgeDocument(doc); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, doc)
	}
}

func getKnowledgeDocument(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := knowledgeIDParam(w, r)
		if !ok {
			return
		}
		doc, err := database.GetKnowledgeDocument(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge document not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, doc)
	}
}

func updateKnowledgeDocument(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := knowledgeIDParam(w, r)
		if !ok {
			return
		}
		existing, err := database.GetKnowledgeDocument(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge document not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		doc, ok := decodeKnowledgeDocumentRequest(w, r)
		if !ok || !knowledgeBaseExists(w, database, doc.KnowledgeBaseID) {
			return
		}
		doc.ID = id
		doc.SourceType = existing.SourceType
		doc.SourceName = existing.SourceName
		if err := database.UpdateKnowledgeDocument(doc); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge document not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, doc)
	}
}

func deleteKnowledgeDocument(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := knowledgeIDParam(w, r)
		if !ok {
			return
		}
		if err := database.DeleteKnowledgeDocument(id); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Knowledge document not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

func searchKnowledge(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		filter, ok := knowledgeSearchFilterFromRequest(w, r)
		if !ok {
			return
		}
		results, err := database.SearchKnowledge(filter)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, results)
	}
}

func decodeKnowledgeBaseRequest(w http.ResponseWriter, r *http.Request) (*db.KnowledgeBase, bool) {
	var req knowledgeBaseRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		respondError(w, http.StatusBadRequest, "name is required")
		return nil, false
	}
	return &db.KnowledgeBase{Name: req.Name, Description: req.Description}, true
}

func decodeKnowledgeDocumentRequest(w http.ResponseWriter, r *http.Request) (*db.KnowledgeDocument, bool) {
	var req knowledgeDocumentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	if req.KnowledgeBaseID <= 0 {
		respondError(w, http.StatusBadRequest, "knowledge_base_id is required")
		return nil, false
	}
	req.Title = strings.TrimSpace(req.Title)
	if req.Title == "" {
		respondError(w, http.StatusBadRequest, "title is required")
		return nil, false
	}
	return &db.KnowledgeDocument{
		KnowledgeBaseID: req.KnowledgeBaseID,
		Title:           req.Title,
		Content:         req.Content,
		Tags:            req.Tags,
	}, true
}

func knowledgeDocumentFilterFromRequest(w http.ResponseWriter, r *http.Request) (db.KnowledgeDocumentFilter, bool) {
	query := r.URL.Query()
	filter := db.KnowledgeDocumentFilter{Query: query.Get("q")}
	if rawID := query.Get("knowledge_base_id"); rawID != "" {
		id, err := strconv.ParseInt(rawID, 10, 64)
		if err != nil || id <= 0 {
			respondError(w, http.StatusBadRequest, "Invalid knowledge_base_id")
			return filter, false
		}
		filter.KnowledgeBaseID = id
	}
	return filter, true
}

func knowledgeSearchFilterFromRequest(w http.ResponseWriter, r *http.Request) (db.KnowledgeSearchFilter, bool) {
	query := r.URL.Query()
	filter := db.KnowledgeSearchFilter{Query: strings.TrimSpace(query.Get("q"))}
	if filter.Query == "" {
		respondError(w, http.StatusBadRequest, "query is required")
		return filter, false
	}
	if rawID := query.Get("knowledge_base_id"); rawID != "" {
		id, err := strconv.ParseInt(rawID, 10, 64)
		if err != nil || id <= 0 {
			respondError(w, http.StatusBadRequest, "Invalid knowledge_base_id")
			return filter, false
		}
		filter.KnowledgeBaseID = id
	}
	if rawLimit := query.Get("limit"); rawLimit != "" {
		limit, err := strconv.Atoi(rawLimit)
		if err != nil || limit <= 0 {
			respondError(w, http.StatusBadRequest, "Invalid limit")
			return filter, false
		}
		filter.Limit = limit
	}
	return filter, true
}

func knowledgeBaseExists(w http.ResponseWriter, database *db.Database, id int64) bool {
	if _, err := database.GetKnowledgeBase(id); errors.Is(err, sql.ErrNoRows) {
		respondError(w, http.StatusNotFound, "Knowledge base not found")
		return false
	} else if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return false
	}
	return true
}

func knowledgeIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}
