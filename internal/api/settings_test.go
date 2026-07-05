package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/config"
)

func decodeSettingsResponse(t *testing.T, rec *httptest.ResponseRecorder) map[string]interface{} {
	t.Helper()
	var body map[string]interface{}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode settings response: %v\nbody: %s", err, rec.Body.String())
	}
	return body
}

func TestGetSettingsReturnsPublicProviderConfigWithoutAPIKey(t *testing.T) {
	dir := t.TempDir()
	if err := config.Save(dir, &config.Config{
		APIKey:                 "secret-key",
		BaseURL:                "https://example.test/v1",
		Model:                  "custom-model",
		ChatAutoApproveWrites: true,
	}); err != nil {
		t.Fatalf("save config: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/settings", nil)
	rec := httptest.NewRecorder()
	getSettingsHandler(dir)(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	body := decodeSettingsResponse(t, rec)
	if body["base_url"] != "https://example.test/v1" {
		t.Fatalf("expected base_url in public settings, got %v", body["base_url"])
	}
	if body["model"] != "custom-model" {
		t.Fatalf("expected model in public settings, got %v", body["model"])
	}
	if body["has_api_key"] != true {
		t.Fatalf("expected has_api_key true, got %v", body["has_api_key"])
	}
	if _, ok := body["api_key"]; ok {
		t.Fatalf("settings response leaked api_key: %v", body)
	}
	if strings.Contains(rec.Body.String(), "secret-key") {
		t.Fatalf("settings response leaked secret key: %s", rec.Body.String())
	}
}

func TestPutSettingsPersistsProviderConfigAndNewAPIKey(t *testing.T) {
	dir := t.TempDir()
	body := []byte(`{
		"chat_auto_approve_writes": true,
		"base_url": " https://provider.test/v1 ",
		"model": " provider-model ",
		"api_key": " new-secret "
	}`)

	req := httptest.NewRequest(http.MethodPut, "/api/settings", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	putSettingsHandler(dir)(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}

	cfg, err := config.Load(dir)
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.BaseURL != "https://provider.test/v1" {
		t.Fatalf("base url not trimmed/persisted: %q", cfg.BaseURL)
	}
	if cfg.Model != "provider-model" {
		t.Fatalf("model not trimmed/persisted: %q", cfg.Model)
	}
	if cfg.APIKey != "new-secret" {
		t.Fatalf("api key not trimmed/persisted: %q", cfg.APIKey)
	}
	if !cfg.ChatAutoApproveWrites {
		t.Fatal("expected auto approve to persist")
	}
	resp := decodeSettingsResponse(t, rec)
	if _, ok := resp["api_key"]; ok {
		t.Fatalf("settings response leaked api_key: %v", resp)
	}
}

func TestPutSettingsKeepsExistingAPIKeyWhenBlank(t *testing.T) {
	dir := t.TempDir()
	if err := config.Save(dir, &config.Config{
		APIKey:  "existing-secret",
		BaseURL: "https://old.test/v1",
		Model:   "old-model",
	}); err != nil {
		t.Fatalf("save config: %v", err)
	}

	body := []byte(`{
		"chat_auto_approve_writes": false,
		"base_url": "",
		"model": " ",
		"api_key": " "
	}`)
	req := httptest.NewRequest(http.MethodPut, "/api/settings", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	putSettingsHandler(dir)(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}

	cfg, err := config.Load(dir)
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if cfg.APIKey != "existing-secret" {
		t.Fatalf("blank api_key should preserve existing key, got %q", cfg.APIKey)
	}
	if cfg.BaseURL != config.DefaultBaseURL {
		t.Fatalf("blank base_url should reset to default, got %q", cfg.BaseURL)
	}
	if cfg.Model != config.DefaultModel {
		t.Fatalf("blank model should reset to default, got %q", cfg.Model)
	}
}
