package ai

import "fmt"

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