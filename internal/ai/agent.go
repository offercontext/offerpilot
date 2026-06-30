package ai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
)

// ErrMaxIterations is returned when the tool-calling loop exceeds its limit.
var ErrMaxIterations = errors.New("AI 工具调用超过最大轮次")

// DefaultMaxIterations bounds the tool-calling loop.
const DefaultMaxIterations = 8

// ChatSystemPrompt instructs the model on its role and the one-tool-per-turn rule.
const ChatSystemPrompt = "你是 OfferPilot 的求职助手。你可以调用工具来查询或修改用户的求职数据" +
	"（投递记录、JD 分析、简历、面试复盘笔记）。规则：" +
	"1. 每轮最多调用一个工具，等到结果返回后再决定下一步。" +
	"2. 需要数据时优先调用工具获取真实数据，不要凭空编造。" +
	"3. 所有回复使用简体中文，简洁清晰。" +
	"4. 修改类操作（新建/改状态/加笔记）调用对应写工具即可，系统会在必要时向用户确认。"

// ChatModel is the minimal interface the loop needs from an AI client.
// *Client implements it; tests provide mocks.
type ChatModel interface {
	Complete(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error)
}

// PendingAction describes a write tool call awaiting user confirmation.
type PendingAction struct {
	ToolCallID string          `json:"tool_call_id"`
	ToolName   string          `json:"tool_name"`
	Args       json.RawMessage `json:"args"`
	Human      string          `json:"human"`
}

// RunTurn drives the tool-calling loop until the model returns text, requests a
// write while autoApprove is off (pausing), or hits maxIter.
//
// messages must already include any system prompt and full prior history plus
// the new user message. The returned `added` slice contains only the new
// assistant/tool messages produced this turn (caller persists them). When err
// is non-nil, callers should discard `added` rather than persist it.
func RunTurn(ctx context.Context, model ChatModel, reg *Registry, messages []Message, autoApprove bool, maxIter int) (added []Message, reply string, pending *PendingAction, err error) {
	if maxIter <= 0 {
		maxIter = DefaultMaxIterations
	}
	work := append([]Message{}, messages...)

	for i := 0; i < maxIter; i++ {
		asst, cerr := model.Complete(ctx, work, reg.List())
		if cerr != nil {
			return added, "", nil, cerr
		}
		if asst == nil {
			return added, "", nil, errors.New("AI 返回了空响应")
		}
		if len(asst.ToolCalls) == 0 {
			m := Message{Role: RoleAssistant, Content: asst.Content, ProviderBlocks: asst.ProviderBlocks}
			added = append(added, m)
			return added, asst.Content, nil, nil
		}

		// One tool per turn: act only on the first.
		tc := asst.ToolCalls[0]
		asstMsg := Message{Role: RoleAssistant, Content: asst.Content, ToolCalls: []ToolCall{tc}, ProviderBlocks: asst.ProviderBlocks}
		added = append(added, asstMsg)
		work = append(work, asstMsg)

		tool, ok := reg.Get(tc.Name)
		if !ok {
			res := fmt.Sprintf("错误：未知工具 %q", tc.Name)
			tm := Message{Role: RoleTool, Content: res, ToolCallID: tc.ID}
			added = append(added, tm)
			work = append(work, tm)
			continue
		}

		if tool.Write && !autoApprove {
			human := tc.Name
			if tool.Describe != nil {
				human = tool.Describe(tc.Args)
			}
			pending = &PendingAction{ToolCallID: tc.ID, ToolName: tc.Name, Args: tc.Args, Human: human}
			return added, "", pending, nil
		}

		out, execErr := reg.Execute(ctx, tc.Name, tc.Args)
		if execErr != nil {
			out = "错误：" + execErr.Error()
		}
		tm := Message{Role: RoleTool, Content: out, ToolCallID: tc.ID}
		added = append(added, tm)
		work = append(work, tm)
	}
	return added, "", nil, ErrMaxIterations
}

// ResumeAfterConfirm executes (or rejects) a paused write, appends its tool
// result, then continues the loop. `messages` is the full history including the
// paused assistant message that requested the write.
func ResumeAfterConfirm(ctx context.Context, model ChatModel, reg *Registry, messages []Message, pending *PendingAction, approved bool, autoApprove bool, maxIter int) (added []Message, reply string, newPending *PendingAction, err error) {
	var result string
	if approved {
		out, execErr := reg.Execute(ctx, pending.ToolName, pending.Args)
		if execErr != nil {
			result = "错误：" + execErr.Error()
		} else {
			result = out
		}
	} else {
		result = "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"
	}

	tm := Message{Role: RoleTool, Content: result, ToolCallID: pending.ToolCallID}
	added = append(added, tm)

	full := append(append([]Message{}, messages...), tm)
	more, reply, newPending, err := RunTurn(ctx, model, reg, full, autoApprove, maxIter)
	added = append(added, more...)
	return added, reply, newPending, err
}
