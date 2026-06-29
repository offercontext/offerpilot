package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type oaTool struct {
	Type     string `json:"type"`
	Function struct {
		Name        string          `json:"name"`
		Description string          `json:"description"`
		Parameters  json.RawMessage `json:"parameters"`
	} `json:"function"`
}

type oaToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type oaMessage struct {
	Role       string       `json:"role"`
	Content    string       `json:"content"`
	ToolCalls  []oaToolCall `json:"tool_calls,omitempty"`
	ToolCallID string       `json:"tool_call_id,omitempty"`
}

type oaRequest struct {
	Model      string      `json:"model"`
	Messages   []oaMessage `json:"messages"`
	Tools      []oaTool    `json:"tools,omitempty"`
	ToolChoice string      `json:"tool_choice,omitempty"`
}

type oaResponse struct {
	Choices []struct {
		Message struct {
			Content   string       `json:"content"`
			ToolCalls []oaToolCall `json:"tool_calls"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func (c *Client) completeOpenAI(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	req := oaRequest{Model: c.model}
	for _, m := range messages {
		om := oaMessage{Role: string(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		for _, tc := range m.ToolCalls {
			var call oaToolCall
			call.ID = tc.ID
			call.Type = "function"
			call.Function.Name = tc.Name
			call.Function.Arguments = string(tc.Args)
			om.ToolCalls = append(om.ToolCalls, call)
		}
		req.Messages = append(req.Messages, om)
	}
	for _, t := range tools {
		var ot oaTool
		ot.Type = "function"
		ot.Function.Name = t.Name
		ot.Function.Description = t.Description
		ot.Function.Parameters = t.Schema
		req.Tools = append(req.Tools, ot)
	}
	if len(tools) > 0 {
		req.ToolChoice = "auto"
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

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

	var or oaResponse
	if err := json.Unmarshal(raw, &or); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	if len(or.Choices) == 0 {
		return nil, fmt.Errorf("AI API returned no choices")
	}
	msg := or.Choices[0].Message
	asst := &Assistant{Content: msg.Content}
	for _, tc := range msg.ToolCalls {
		args := json.RawMessage(tc.Function.Arguments)
		if len(args) == 0 {
			args = json.RawMessage(`{}`)
		}
		asst.ToolCalls = append(asst.ToolCalls, ToolCall{ID: tc.ID, Name: tc.Function.Name, Args: args})
	}
	return asst, nil
}
