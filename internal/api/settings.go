package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/config"
)

// registerSettingsRoutes wires chat-related settings (never exposes the API key).
func registerSettingsRoutes(r chi.Router, dataDir string) {
	r.Get("/settings", getSettingsHandler(dataDir))
	r.Put("/settings", putSettingsHandler(dataDir))
}

type settingsDTO struct {
	ChatAutoApproveWrites bool   `json:"chat_auto_approve_writes"`
	Model                 string `json:"model"`
	HasAPIKey             bool   `json:"has_api_key"`
}

func settingsFromConfig(cfg *config.Config) settingsDTO {
	return settingsDTO{
		ChatAutoApproveWrites: cfg.ChatAutoApproveWrites,
		Model:                 cfg.Model,
		HasAPIKey:             cfg.APIKey != "",
	}
}

func getSettingsHandler(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, settingsFromConfig(cfg))
	}
}

func putSettingsHandler(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ChatAutoApproveWrites bool `json:"chat_auto_approve_writes"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			respondError(w, http.StatusBadRequest, "invalid body")
			return
		}
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		cfg.ChatAutoApproveWrites = body.ChatAutoApproveWrites
		if err := config.Save(dataDir, cfg); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, settingsFromConfig(cfg))
	}
}
