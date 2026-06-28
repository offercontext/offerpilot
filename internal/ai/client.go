package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/offercontext/offerpilot/internal/config"
)

// ErrNotConfigured mirrors config.ErrNotConfigured so callers can import either.
var ErrNotConfigured = config.ErrNotConfigured

// Client talks to any OpenAI-compatible /v1/chat/completions endpoint
// (OpenAI, DeepSeek, DashScope, Ollama, etc.) by swapping base_url.
type Client struct {
	apiKey     string
	baseURL    string
	model      string
	httpClient *http.Client
}

// New builds a Client. Returns ErrNotConfigured when APIKey is empty so the
// caller can guide the user to `oc config`.
func New(cfg *config.Config) (*Client, error) {
	if cfg == nil || cfg.APIKey == "" {
		return nil, ErrNotConfigured
	}
	return &Client{
		apiKey:  cfg.APIKey,
		baseURL: cfg.BaseURL,
		model:   cfg.Model,
		httpClient: &http.Client{
			Timeout: 120 * time.Second, // JD / resume analysis can be slow
		},
	}, nil
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequest struct {
	Model       string        `json:"model"`
	Messages    []chatMessage `json:"messages"`
	Temperature float64       `json:"temperature"`
}

type chatResponse struct {
	Choices []struct {
		Message chatMessage `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error,omitempty"`
}

// Chat sends a single system + user message and returns the assistant reply.
func (c *Client) Chat(ctx context.Context, system, user string) (string, error) {
	body, err := json.Marshal(chatRequest{
		Model: c.model,
		Messages: []chatMessage{
			{Role: "system", Content: system},
			{Role: "user", Content: user},
		},
		Temperature: 0.3,
	})
	if err != nil {
		return "", fmt.Errorf("marshal request: %w", err)
	}

	url := c.baseURL + "/chat/completions"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("call AI API: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode >= 400 {
		// Try to extract a structured error message for friendlier output.
		var cr chatResponse
		if json.Unmarshal(raw, &cr) == nil && cr.Error != nil && cr.Error.Message != "" {
			return "", fmt.Errorf("AI API returned %d: %s", resp.StatusCode, cr.Error.Message)
		}
		return "", fmt.Errorf("AI API returned %d: %s", resp.StatusCode, truncate(string(raw), 200))
	}

	var cr chatResponse
	if err := json.Unmarshal(raw, &cr); err != nil {
		return "", fmt.Errorf("parse response: %w", err)
	}
	if len(cr.Choices) == 0 {
		return "", errors.New("AI API returned no choices")
	}
	return cr.Choices[0].Message.Content, nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}