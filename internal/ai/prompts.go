package ai

import (
	"fmt"
	"strings"
)

// rawSystem is the shared system prompt enforcing strict JSON output so
// downstream code can unmarshal without regex cleanup. Kept as a raw string
// literal to avoid escaping issues. We avoid the triple-backtick token here.
const rawSystem = "你是一名专业的招聘求职分析师。请严格按照要求分析，并且：" +
	"1. 只输出 JSON，不要使用 markdown 代码块包裹（不要出现三个反引号）。" +
	"2. 所有文字使用简体中文。" +
	"3. 字段含义务必贴合求职者视角：suggestions 是给求职者的准备建议。" +
	"4. 数组字段如果为空请返回空数组 []，不要返回 null。"

// buildSystem returns the cached system prompt. Kept as a function so future
// per-feature overrides stay easy to add.
func buildSystem() string { return rawSystem }

// JDAnalysisResult is the structured output returned by the JD analysis model.
type JDAnalysisResult struct {
	Summary         string   `json:"summary"`
	Requirements    []string `json:"requirements"`
	TechStack       []string `json:"tech_stack"`
	ExperienceYears string   `json:"experience_years"`
	Education       string   `json:"education"`
	Highlights      []string `json:"highlights"`
	Suggestions     []string `json:"suggestions"`
}

// PromptJDAnalyze builds the system + user prompts for analyzing a JD.
func PromptJDAnalyze(jdText string) (system, user string) {
	system = buildSystem()
	user = fmt.Sprintf(`请分析以下岗位描述（JD），输出如下 JSON：
{
  "summary": "一句话总结这个岗位",
  "requirements": ["关键要求点，每条一句话"],
  "tech_stack": ["涉及的技术栈/工具"],
  "experience_years": "要求的年限，如 3-5 年，无要求填 不限",
  "education": "学历要求，如 本科及以上，无要求填 不限",
  "highlights": ["这个岗位吸引人的亮点"],
  "suggestions": ["针对求职者的准备建议，每条一句话"]
}

JD 内容：
%s`, jdText)
	return
}

// MatchResult is the structured output returned by the resume-match model.
type MatchResult struct {
	MatchScore  int      `json:"match_score"`
	Matched     []string `json:"matched"`
	Gaps        []string `json:"gaps"`
	Suggestions []string `json:"suggestions"`
	Summary     string   `json:"summary"`
}

// PromptResumeMatch builds the system + user prompts for matching a resume to a JD.
func PromptResumeMatch(resumeText, jdText string) (system, user string) {
	system = buildSystem()
	user = fmt.Sprintf(`请对比以下简历和岗位 JD，评估匹配度，输出如下 JSON：
{
  "match_score": 0到100的整数匹配度,
  "matched": ["简历中与 JD 匹配的点"],
  "gaps": ["简历中相对 JD 缺失或薄弱的点"],
  "suggestions": ["针对这份 JD 该如何优化简历/补足能力的建议"],
  "summary": "一句话总评"
}

简历内容：
%s

JD 内容：
%s`, resumeText, jdText)
	return
}

// GeneratedQuestion is one interview question produced by the question-bank model.
type GeneratedQuestion struct {
	Category        string   `json:"category"`
	Difficulty      string   `json:"difficulty"` // easy | medium | hard
	Question        string   `json:"question"`
	ReferenceAnswer string   `json:"reference_answer"`
	Tags            []string `json:"tags"`
}

// GeneratedQuestions is the JSON envelope returned by the question-bank model.
type GeneratedQuestions struct {
	Questions []GeneratedQuestion `json:"questions"`
}

// PromptGenerateQuestions builds the prompts for generating an interview question
// bank from supplied context (knowledge base content or interview retrospectives).
// sourceLabel describes the material (e.g. "知识库资料" or "面试复盘真题") and
// contextText is the raw material to ground the questions in. existing lists
// already-stored question stems the model should avoid repeating.
func PromptGenerateQuestions(sourceLabel, contextText string, count int, existing []string) (system, user string) {
	system = buildSystem()
	avoidBlock := ""
	if len(existing) > 0 {
		// Cap the exclusion list so a large bank can't blow the token budget.
		// This is only a soft nudge; hard dedup happens when persisting.
		const maxExclusions = 80
		if len(existing) > maxExclusions {
			existing = existing[len(existing)-maxExclusions:]
		}
		var b strings.Builder
		b.WriteString("\n\n以下题目题库中已存在，请勿重复，也不要出与它们语义相近、仅换措辞的题：\n")
		for _, q := range existing {
			q = strings.TrimSpace(q)
			if q == "" {
				continue
			}
			b.WriteString("- ")
			b.WriteString(q)
			b.WriteString("\n")
		}
		avoidBlock = b.String()
	}
	user = fmt.Sprintf(`你是一名资深技术面试官。请基于以下【%s】设计 %d 道高质量的面试题，用于求职者刷题准备。要求：
- 题目紧扣所给材料的知识点，避免脱离材料的空泛题目。
- 覆盖不同难度（easy/medium/hard）并尽量分散到不同分类。
- reference_answer 给出简洁但要点完整的参考答案（要点式，可含关键结论）。
- category 用简短中文分类词（如「Go并发」「系统设计」「行为面试」）。
- tags 为该题相关的关键词数组，可为空数组 []。

严格输出如下 JSON（不要输出多余文字）：
{
  "questions": [
    {
      "category": "分类",
      "difficulty": "easy|medium|hard",
      "question": "题目",
      "reference_answer": "参考答案要点",
      "tags": ["关键词"]
    }
  ]
}%s

材料内容：
%s`, sourceLabel, count, avoidBlock, contextText)
	return
}
