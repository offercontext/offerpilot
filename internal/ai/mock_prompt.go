package ai

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

// mockInterviewerBase is the static instruction block for the AI mock-interviewer.
const mockInterviewerBase = "你是 OfferPilot 模拟面试工作室里的面试官，正在面试一位应聘者。" +
	"你的目标是真实还原一场目标岗位的面试，通过提问与追问让候选人暴露真实水平，并在结束后由系统评分。\n" +
	"通用规则：\n" +
	"1. 一次只问一个问题，等候选人回答后再追问或换题，绝不一次抛多个问题。\n" +
	"2. 根据回答决定下一步：回答浅就追问『能不能再展开 / 给个具体例子』；跑题就温和拉回；答得好就进入下一题。\n" +
	"3. 保持专业但有真实面试的施压感，可以追问、反问、质疑，但不要人身攻击或嘲讽。\n" +
	"4. 不要泄露参考答案；不要替候选人回答；不要扮演候选人。\n" +
	"5. 本会话仅对话，不要调用任何工具读写数据。\n" +
	"6. 全程使用简体中文。\n" +
	"结束条件：达到计划的题数、或候选人主动说『结束面试』、或你判断已充分覆盖该轮次能力点。结束时简短总结本场覆盖了哪些方向，然后停。"

// MockInterviewerPrompt builds the interviewer system prompt, embedding the
// session config and assembled context (picked questions / knowledge chunks /
// weak points produced by the API layer's loadMockContext).
func MockInterviewerPrompt(sess *db.MockSession, ctx MockContext) string {
	if sess == nil {
		return mockInterviewerBase
	}
	var b strings.Builder
	b.WriteString(mockInterviewerBase)

	role := sess.Role
	if role == "" {
		role = "（未指定，按通用工程师）"
	}
	company := sess.Company
	if company == "" {
		company = "（未指定，按通用风格）"
	}
	b.WriteString(fmt.Sprintf("\n\n【本场配置】\n目标岗位：%s\n目标公司：%s\n轮次类型：%s\n难度：%s",
		role, company, sess.RoundType, lowerOr(sess.Difficulty, "medium")))

	qcount := sess.QuestionCount
	if qcount > 0 {
		b.WriteString(fmt.Sprintf("\n计划题数：%d（已问 %d 题）", qcount, sess.QuestionIndex))
	} else {
		b.WriteString("\n题数：不限，直到候选人结束或你判断充分覆盖")
	}
	if sess.DurationMin > 0 {
		b.WriteString(fmt.Sprintf("\n计划时长：%d 分钟", sess.DurationMin))
	}

	var guide string
	switch sess.QuestionSource {
	case "bank":
		guide = "优先从下面给定题库里选题，按难度/类别组织提问顺序。"
	case "knowledge":
		guide = "优先基于下面给定的知识库片段设计提问，可结合片段追问细节。"
	case "notes":
		guide = "优先针对下面历史复盘里反复出现的薄弱点出题，做针对性补强。"
	case "mixed":
		guide = "综合使用下面题库题、知识库片段与历史薄弱点，混合出题。"
	default:
		guide = "按通用面试节奏出题。"
	}
	b.WriteString("\n出题来源策略：" + guide)

	if len(ctx.PickedQuestions) > 0 {
		b.WriteString("\n\n【题库候选题】")
		for i, q := range ctx.PickedQuestions {
			b.WriteString(fmt.Sprintf("\n%d. [%s/%s] %s", i+1, q.Category, q.Difficulty, q.Question))
		}
	}
	if len(ctx.KnowledgeChunks) > 0 {
		b.WriteString("\n\n【知识库片段】\n" + strings.Join(ctx.KnowledgeChunks, "\n---\n"))
	}
	if len(ctx.WeakPoints) > 0 {
		b.WriteString("\n\n【历史复盘薄弱点】\n- " + strings.Join(ctx.WeakPoints, "\n- "))
	}
	return b.String()
}

// MockInterviewerPromptFallback is used when a mock_interview conversation has no
// bound session row (data integrity gap) — keep the role but warn the model.
const MockInterviewerPromptFallback = mockInterviewerBase +
	"\n\n（注意：本场未找到模拟面试配置，按通用技术面试进行即可。）"

// MockContext holds runtime context assembled by the API layer for prompt injection.
type MockContext struct {
	PickedQuestions  []db.Question
	KnowledgeChunks []string // pre-fetched knowledge chunks text
	WeakPoints       []string // weak points mined from past interview notes
}

// lowerOr returns s when non-empty else def (kept local to avoid touching existing helpers).
func lowerOr(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// ----------------------------------------------------------------------------
// Scoring
// ----------------------------------------------------------------------------

// ScoringFeedback is the structured evaluation produced at session end.
type ScoringFeedback struct {
	ScoreOverall       int      `json:"score_overall"`
	ScoreCommunication int      `json:"score_communication"`
	ScoreDepth         int      `json:"score_depth"`
	ScoreStructure     int      `json:"score_structure"`
	ScoreConfidence    int      `json:"score_confidence"`
	Summary            string   `json:"summary"`
	Strengths          []string `json:"strengths"`
	Weaknesses         []string `json:"weaknesses"`
	Drills             []Drill  `json:"drills"`
}

// Drill is a recommended follow-up action, optionally linking back to question-bank items.
type Drill struct {
	Area            string `json:"area"`
	Action          string `json:"action"`
	LinkQuestionIDs []int64 `json:"link_question_ids"`
}

// MockScoringPrompt asks the model to evaluate a finished interview transcript and
// return strict JSON. transcript should be the joined dialogue (turns of user+assistant).
func MockScoringPrompt(sess *db.MockSession, transcript string) string {
	role := "（未指定）"
	round := "（未指定）"
	diff := "（未指定）"
	if sess != nil {
		role = lowerOr(sess.Role, role)
		round = lowerOr(sess.RoundType, round)
		diff = lowerOr(sess.Difficulty, diff)
	}
	return "你是一位资深面试官兼面试评估专家。下面是一场模拟面试的完整对话记录与配置。" +
		"请根据候选人表现给出结构化评分与反馈。\n\n" +
		fmt.Sprintf("【配置】\n目标岗位：%s\n轮次类型：%s\n难度：%s\n", role, round, diff) +
		"【评分维度】（0-100 整数）\n" +
		"- score_overall：综合得分\n" +
		"- score_communication：表达清晰度与沟通\n" +
		"- score_depth：技术/业务深度\n" +
		"- score_structure：回答的结构化与逻辑性\n" +
		"- score_confidence：自信度与抗压\n" +
		"【反馈】\n" +
		"- summary：一两句话总评\n" +
		"- strengths：亮点数组\n" +
		"- weaknesses：待加强数组\n" +
		"- drills：下一步行动数组，每项含 area（方向）、action（具体行动）、link_question_ids（联动题库题目id数组，没有则空数组）\n\n" +
		"【严格要求】只输出一个 JSON 对象，不要包含 markdown 代码块标记、不要解释、不要前后空行。\n" +
		"示例格式：\n" +
		`{"score_overall":78,"score_communication":80,"score_depth":72,"score_structure":75,"score_confidence":85,"summary":"整体中等偏上","strengths":["STAR清晰"],"weaknesses":["系统设计浅"],"drills":[{"area":"系统设计","action":"补练容量估算题","link_question_ids":[12,34]}]}` + "\n\n" +
		"【面试对话记录】\n" + transcript
}

// ParseScoringResult extracts a ScoringFeedback from the model's raw text reply.
// It tolerates ```json fenced blocks and leading/trailing prose. On any parse
// failure it returns a degraded-but-valid feedback (scores 0, summary = raw)
// so the session can still be marked completed without blocking.
func ParseScoringResult(raw string) (ScoringFeedback, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ScoringFeedback{Summary: ""}, errors.New("空评分响应")
	}

	// Try fenced ```json ... ``` first.
	jsonBlock := raw
	if i := strings.Index(raw, "```json"); i >= 0 {
		body := raw[i+len("```json"):]
		if j := strings.Index(body, "```"); j >= 0 {
			jsonBlock = strings.TrimSpace(body[:j])
		}
	} else if i := strings.Index(raw, "```"); i >= 0 {
		body := raw[i+3:]
		if j := strings.Index(body, "```"); j >= 0 {
			jsonBlock = strings.TrimSpace(body[:j])
		}
	} else {
		// Bare text: locate first `{` to last `}`.
		s := strings.Index(raw, "{")
		e := strings.LastIndex(raw, "}")
		if s >= 0 && e > s {
			jsonBlock = raw[s : e+1]
		}
	}

	var fb ScoringFeedback
	if err := json.Unmarshal([]byte(jsonBlock), &fb); err != nil {
		// Degraded fallback: never block completion on a malformed AI reply.
		return ScoringFeedback{Summary: raw}, fmt.Errorf("解析评分 JSON 失败（已降级）: %w", err)
	}
	if fb.Summary == "" {
		fb.Summary = raw
	}
	return fb, nil
}