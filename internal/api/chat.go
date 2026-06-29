package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
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
	Message        string `json:"message"`
}

type confirmRequestBody struct {
	ConversationID int64 `json:"conversation_id"`
	Approved       bool  `json:"approved"`
}

// toAIMessages converts stored messages into the protocol-agnostic form,
// prepending the system prompt.
func toAIMessages(stored []db.ChatMessage) []ai.Message {
	out := []ai.Message{{Role: ai.RoleSystem, Content: ai.ChatSystemPrompt}}
	for _, m := range stored {
		msg := ai.Message{Role: ai.Role(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if m.ToolCalls != "" {
			var tcs []ai.ToolCall
			if json.Unmarshal([]byte(m.ToolCalls), &tcs) == nil {
				msg.ToolCalls = tcs
			}
		}
		out = append(out, msg)
	}
	return out
}

// persistAdded stores loop-produced messages into the conversation.
func persistAdded(database *db.Database, convID int64, added []ai.Message) error {
	for _, m := range added {
		cm := &db.ChatMessage{ConversationID: convID, Role: string(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if len(m.ToolCalls) > 0 {
			b, _ := json.Marshal(m.ToolCalls)
			cm.ToolCalls = string(b)
		}
		if err := database.AppendMessage(cm); err != nil {
			return err
		}
	}
	return nil
}

func titleFrom(msg string) string {
	const max = 20
	if utf8.RuneCountInString(msg) <= max {
		return msg
	}
	rs := []rune(msg)
	return string(rs[:max]) + "…"
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
	if convID == 0 {
		conv, err := database.CreateConversation(titleFrom(body.Message))
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		convID = conv.ID
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
	added, reply, pending, err := ai.RunTurn(r.Context(), model, reg, toAIMessages(stored), autoApprove, ai.DefaultMaxIterations)

	if errors.Is(err, ai.ErrToolsUnsupported) && fallbackClient != nil {
		text, ferr := ai.RunSummaryFallback(r.Context(), fallbackClient, database, body.Message)
		if ferr != nil {
			respondError(w, http.StatusBadGateway, ferr.Error())
			return
		}
		_ = database.AppendMessage(&db.ChatMessage{ConversationID: convID, Role: "assistant", Content: text})
		respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": convID, "message": text, "degraded": true})
		return
	}
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := persistAdded(database, convID, added); perr != nil {
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
	added, reply, newPending, err := ai.ResumeAfterConfirm(r.Context(), model, reg, toAIMessages(stored), pending, body.Approved, autoApprove, ai.DefaultMaxIterations)
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := persistAdded(database, body.ConversationID, added); perr != nil {
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
