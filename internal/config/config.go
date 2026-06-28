package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// Default values used when the config file is absent or fields are blank.
const (
	DefaultBaseURL = "https://api.openai.com/v1"
	DefaultModel   = "gpt-4o"
	DefaultPort    = 8080
)

// ErrNotConfigured is returned by AI features when no API key is present.
// Callers should surface this to the user with setup instructions instead of
// crashing the server / CLI.
var ErrNotConfigured = errors.New("AI is not configured: run `oc config` to set your API key")

// Config holds the user's local settings. Stored as JSON in dataDir/config.json.
type Config struct {
	APIKey    string `json:"api_key"`
	BaseURL   string `json:"base_url"`
	Model     string `json:"model"`
	LocalPort int    `json:"local_port"`
}

// Load reads ~/.offerpilot/config.json. If the file is missing, a Config with
// defaults (and an empty APIKey) is returned — non-AI commands keep working,
// AI commands will return ErrNotConfigured via Client.
func Load(dataDir string) (*Config, error) {
	c := &Config{
		BaseURL:   DefaultBaseURL,
		Model:     DefaultModel,
		LocalPort: DefaultPort,
	}
	path := filepath.Join(dataDir, "config.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return c, nil // missing file is not an error
		}
		return nil, fmt.Errorf("read config: %w", err)
	}
	if err := json.Unmarshal(data, c); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	// Fill blanks with defaults so downstream code never sees empty strings.
	if c.BaseURL == "" {
		c.BaseURL = DefaultBaseURL
	}
	if c.Model == "" {
		c.Model = DefaultModel
	}
	if c.LocalPort == 0 {
		c.LocalPort = DefaultPort
	}
	return c, nil
}

// Save writes the config back to dataDir/config.json.
func Save(dataDir string, c *Config) error {
	path := filepath.Join(dataDir, "config.json")
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal config: %w", err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		return fmt.Errorf("write config: %w", err)
	}
	return nil
}