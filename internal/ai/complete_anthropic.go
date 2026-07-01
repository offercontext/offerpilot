package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type antTool struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"input_schema"`
}

type antBlock struct {
	Type      string          `json:"type"`
	Text      string          `json:"text,omitempty"`
	Thinking  string          `json:"thinking,omitempty"`
	ID        string          `json:"id,omitempty"`
	Name      string          `json:"name,omitempty"`
	Input     json.RawMessage `json:"input,omitempty"`
	ToolUseID string          `json:"tool_use_id,omitempty"`
	Content   string          `json:"content,omitempty"`
}

type antMessage struct {
	Role    string            `json:"role"`
	Content []json.RawMessage `json:"content"`
}

type antRequest struct {
	Model     string       `json:"model"`
	System    string       `json:"system,omitempty"`
	Messages  []antMessage `json:"messages"`
	Tools     []antTool    `json:"tools,omitempty"`
	MaxTokens int          `json:"max_tokens"`
}

type antResponse struct {
	Content []json.RawMessage `json:"content"`
	Error   *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func rawAntBlock(b antBlock) json.RawMessage {
	raw, _ := json.Marshal(b)
	return raw
}

func (c *Client) completeAnthropic(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	req := antRequest{Model: c.model, MaxTokens: 4096}
	for _, m := range messages {
		switch m.Role {
		case RoleSystem:
			if req.System != "" {
				req.System += "\n"
			}
			req.System += m.Content
		case RoleUser:
			req.Messages = append(req.Messages, antMessage{
				Role:    "user",
				Content: []json.RawMessage{rawAntBlock(antBlock{Type: "text", Text: m.Content})},
			})
		case RoleAssistant:
			blocks := append([]json.RawMessage{}, m.ProviderBlocks...)
			if m.Content != "" {
				blocks = append(blocks, rawAntBlock(antBlock{Type: "text", Text: m.Content}))
			}
			for _, tc := range m.ToolCalls {
				input := tc.Args
				if len(input) == 0 {
					input = json.RawMessage(`{}`)
				}
				blocks = append(blocks, rawAntBlock(antBlock{Type: "tool_use", ID: tc.ID, Name: tc.Name, Input: input}))
			}
			req.Messages = append(req.Messages, antMessage{Role: "assistant", Content: blocks})
		case RoleTool:
			// Anthropic carries tool results as a user message with a tool_result block.
			req.Messages = append(req.Messages, antMessage{
				Role:    "user",
				Content: []json.RawMessage{rawAntBlock(antBlock{Type: "tool_result", ToolUseID: m.ToolCallID, Content: m.Content})},
			})
		}
	}
	for _, t := range tools {
		req.Tools = append(req.Tools, antTool{Name: t.Name, Description: t.Description, InputSchema: t.Schema})
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/messages", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", c.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("call AI API: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		if resp.StatusCode < 500 && len(tools) > 0 && isToolsUnsupportedBody(string(raw)) {
			return nil, fmt.Errorf("%w: %s", ErrToolsUnsupported, truncate(string(raw), 200))
		}
		return nil, fmt.Errorf("AI API returned %d: %s", resp.StatusCode, truncate(string(raw), 200))
	}

	var ar antResponse
	if err := json.Unmarshal(raw, &ar); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	asst := &Assistant{}
	var thinkingFallback string
	for _, rawBlock := range ar.Content {
		var b antBlock
		if err := json.Unmarshal(rawBlock, &b); err != nil {
			return nil, fmt.Errorf("parse response content block: %w", err)
		}
		switch b.Type {
		case "text", "":
			asst.Content += b.Text
		case "tool_use":
			input := b.Input
			if len(input) == 0 {
				input = json.RawMessage(`{}`)
			}
			asst.ToolCalls = append(asst.ToolCalls, ToolCall{ID: b.ID, Name: b.Name, Args: input})
		default:
			if b.Type == "thinking" && b.Text == "" && b.Content == "" && b.Input == nil && b.Name == "" && b.ID == "" {
				thinkingFallback += b.Thinking
			}
			asst.ProviderBlocks = append(asst.ProviderBlocks, rawBlock)
		}
	}
	if asst.Content == "" && len(asst.ToolCalls) == 0 {
		asst.Content = thinkingFallback
	}
	return asst, nil
}
