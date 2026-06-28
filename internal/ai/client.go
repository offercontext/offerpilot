package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/offercontext/offerpilot/internal/config"
)

// ErrNotConfigured mirrors config.ErrNotConfigured so callers can import either.
var ErrNotConfigured = config.ErrNotConfigured

// Client talks to any OpenAI-compatible /v1/chat/completions endpoint
// (OpenAI, DeepSeek, DashScope, Ollama, etc.) by swapping base_url.
//
// It also speaks the Anthropic Messages API (/v1/messages) used by providers
// such as DeepSeek's https://api.deepseek.com/anthropic endpoint — detected when
// base_url contains "anthropic".
type Client struct {
	apiKey     string
	baseURL    string
	model      string
	anthropic  bool
	httpClient *http.Client
}

// New builds a Client. Returns ErrNotConfigured when APIKey is empty so the
// caller can guide the user to `oc config`.
func New(cfg *config.Config) (*Client, error) {
	if cfg == nil || cfg.APIKey == "" {
		return nil, ErrNotConfigured
	}
	return &Client{
		apiKey:    cfg.APIKey,
		baseURL:   strings.TrimRight(cfg.BaseURL, "/"),
		model:     cfg.Model,
		anthropic: strings.Contains(strings.ToLower(cfg.BaseURL), "anthropic"),
		httpClient: &http.Client{
			Timeout: 120 * time.Second, // JD / resume analysis can be slow
		},
	}, nil
}

// Chat sends a single system + user message and returns the assistant reply.
func (c *Client) Chat(ctx context.Context, system, user string) (string, error) {
	if c.anthropic {
		return c.chatAnthropic(ctx, system, user)
	}
	return c.chatOpenAI(ctx, system, user)
}

// ---------- OpenAI-compatible (/v1/chat/completions) ----------

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

func (c *Client) chatOpenAI(ctx context.Context, system, user string) (string, error) {
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

// ---------- Anthropic Messages API (/v1/messages) ----------

type anthropicRequest struct {
	Model       string        `json:"model"`
	System      string        `json:"system,omitempty"`
	Messages    []chatMessage `json:"messages"`
	MaxTokens   int           `json:"max_tokens"`
	Temperature float64       `json:"temperature,omitempty"`
}

type anthropicContentBlock struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

type anthropicResponse struct {
	Content []anthropicContentBlock `json:"content"`
	Error   *struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error,omitempty"`
}

func (c *Client) chatAnthropic(ctx context.Context, system, user string) (string, error) {
	body, err := json.Marshal(anthropicRequest{
		Model:       c.model,
		System:      system,
		Messages:    []chatMessage{{Role: "user", Content: user}},
		MaxTokens:   4096, // required by the Messages API
		Temperature: 0.3,
	})
	if err != nil {
		return "", fmt.Errorf("marshal request: %w", err)
	}

	url := c.baseURL + "/v1/messages"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", c.apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")

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
		var ar anthropicResponse
		if json.Unmarshal(raw, &ar) == nil && ar.Error != nil && ar.Error.Message != "" {
			return "", fmt.Errorf("AI API returned %d: %s", resp.StatusCode, ar.Error.Message)
		}
		return "", fmt.Errorf("AI API returned %d: %s", resp.StatusCode, truncate(string(raw), 200))
	}

	var ar anthropicResponse
	if err := json.Unmarshal(raw, &ar); err != nil {
		return "", fmt.Errorf("parse response: %w", err)
	}
	var sb strings.Builder
	for _, b := range ar.Content {
		if b.Type == "text" || b.Type == "" {
			sb.WriteString(b.Text)
		}
	}
	if sb.Len() == 0 {
		return "", errors.New("AI API returned no content")
	}
	return sb.String(), nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}