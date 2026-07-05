package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	chatapp "github.com/offercontext/offerpilot/internal/app/chat"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

// registerChatRoutes wires the chat endpoints onto the /api group.
func registerChatRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Post("/chat", chatHandler(database, dataDir))
	r.Post("/chat/confirm", chatConfirmHandler(database, dataDir))
	r.Get("/chat/conversations", listConversationsHandler(database))
	r.Get("/chat/conversations/{id}", getConversationHandler(database))
	r.Delete("/chat/conversations/{id}", deleteConversationHandler(database))
}

type chatRequestBody struct {
	ConversationID int64  `json:"conversation_id"`
	OfferID        *int64 `json:"offer_id,omitempty"`
	Message        string `json:"message"`
}

type confirmRequestBody struct {
	ConversationID int64 `json:"conversation_id"`
	Approved       bool  `json:"approved"`
}

// chatHandler is the production handler; it builds a real AI client from config.
func chatHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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
		runChat(w, r, database, client, cfg.ChatAutoApproveWrites, client)
	}
}

// chatHandlerWithModel injects a model + auto-approve flag for testing.
func chatHandlerWithModel(database *db.Database, model ai.ChatModel, autoApprove bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		runChat(w, r, database, model, autoApprove, nil)
	}
}

// runChat contains the shared logic. fallbackClient may be nil (tests) — when
// non-nil it is used for summary-mode downgrade.
func runChat(w http.ResponseWriter, r *http.Request, database *db.Database, model ai.ChatModel, autoApprove bool, fallbackClient *ai.Client) {
	var body chatRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Message == "" {
		respondError(w, http.StatusBadRequest, "message is required")
		return
	}

	convID := body.ConversationID
	var conv *db.Conversation
	if convID == 0 {
		mode := "general"
		if body.OfferID != nil {
			mode = "nego_coach"
		}
		title := chatapp.TitleFromMessage(body.Message)
		if body.OfferID != nil {
			if o, err := database.GetOffer(*body.OfferID); err == nil {
				title = o.CompanyName + " 谈薪"
			}
		}
		created, err := database.CreateConversationWithMode(title, mode, body.OfferID)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		convID = created.ID
		conv = created
	} else {
		c, err := database.GetConversation(convID)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "conversation not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		conv = c
	}
	if err := database.AppendMessage(&db.ChatMessage{ConversationID: convID, Role: "user", Content: body.Message}); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}

	stored, err := database.ListMessages(convID)
	if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	reg := ai.NewRegistry(database)
	systemPrompt := chatapp.SystemPromptFor(database, conv)
	added, reply, pending, err := ai.RunTurn(r.Context(), model, reg, chatapp.ToAIMessages(stored, systemPrompt), autoApprove, ai.DefaultMaxIterations)

	if errors.Is(err, ai.ErrToolsUnsupported) && fallbackClient != nil {
		text, ferr := ai.RunSummaryFallback(r.Context(), fallbackClient, database, body.Message)
		if ferr != nil {
			respondError(w, http.StatusBadGateway, ferr.Error())
			return
		}
		if perr := database.AppendMessage(&db.ChatMessage{ConversationID: convID, Role: "assistant", Content: text}); perr != nil {
			respondError(w, http.StatusInternalServerError, perr.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": convID, "message": text, "degraded": true})
		return
	}
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := chatapp.PersistAdded(database, convID, added); perr != nil {
		respondError(w, http.StatusInternalServerError, perr.Error())
		return
	}

	if pending != nil {
		respondJSON(w, http.StatusOK, map[string]interface{}{
			"type":            "confirmation_required",
			"conversation_id": convID,
			"pending_action":  map[string]interface{}{"tool_name": pending.ToolName, "human": pending.Human},
		})
		return
	}
	respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": convID, "message": reply})
}

func chatConfirmHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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
		runConfirm(w, r, database, client, cfg.ChatAutoApproveWrites)
	}
}

func runConfirm(w http.ResponseWriter, r *http.Request, database *db.Database, model ai.ChatModel, autoApprove bool) {
	var body confirmRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.ConversationID == 0 {
		respondError(w, http.StatusBadRequest, "conversation_id is required")
		return
	}
	stored, err := database.ListMessages(body.ConversationID)
	if err != nil || len(stored) == 0 {
		respondError(w, http.StatusNotFound, "conversation not found")
		return
	}
	// The last message must be an assistant turn carrying the pending write call.
	last := stored[len(stored)-1]
	if last.Role != "assistant" || last.ToolCalls == "" {
		respondError(w, http.StatusBadRequest, "no pending action to confirm")
		return
	}
	var tcs []ai.ToolCall
	if json.Unmarshal([]byte(last.ToolCalls), &tcs) != nil || len(tcs) == 0 {
		respondError(w, http.StatusBadRequest, "malformed pending action")
		return
	}
	pending := &ai.PendingAction{ToolCallID: tcs[0].ID, ToolName: tcs[0].Name, Args: tcs[0].Args}

	reg := ai.NewRegistry(database)
	conv, cerr := database.GetConversation(body.ConversationID)
	if errors.Is(cerr, sql.ErrNoRows) {
		respondError(w, http.StatusNotFound, "conversation not found")
		return
	}
	if cerr != nil {
		respondError(w, http.StatusInternalServerError, cerr.Error())
		return
	}
	systemPrompt := chatapp.SystemPromptFor(database, conv)
	added, reply, newPending, err := ai.ResumeAfterConfirm(r.Context(), model, reg, chatapp.ToAIMessages(stored, systemPrompt), pending, body.Approved, autoApprove, ai.DefaultMaxIterations)
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := chatapp.PersistAdded(database, body.ConversationID, added); perr != nil {
		respondError(w, http.StatusInternalServerError, perr.Error())
		return
	}
	if newPending != nil {
		respondJSON(w, http.StatusOK, map[string]interface{}{
			"type":            "confirmation_required",
			"conversation_id": body.ConversationID,
			"pending_action":  map[string]interface{}{"tool_name": newPending.ToolName, "human": newPending.Human},
		})
		return
	}
	respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": body.ConversationID, "message": reply})
}

func listConversationsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		convs, err := database.ListConversations()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, convs)
	}
}

func getConversationHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		msgs, err := database.ListMessages(id)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, msgs)
	}
}

func deleteConversationHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		if err := database.DeleteConversation(id); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
	}
}
