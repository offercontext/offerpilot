package ai

import (
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestMockInterviewerPromptEmbedsConfig(t *testing.T) {
	sess := &db.MockSession{
		Role: "后端开发", Company: "字节跳动", RoundType: "technical",
		Difficulty: "hard", QuestionCount: 5, QuestionIndex: 2, DurationMin: 30,
		QuestionSource: "bank",
	}
	ctx := MockContext{
		PickedQuestions: []db.Question{
			{Category: "系统设计", Difficulty: "hard", Question: "设计一个短链系统"},
		},
		WeakPoints: []string{"并发场景分析偏浅"},
	}
	p := MockInterviewerPrompt(sess, ctx)
	for _, want := range []string{"面试官", "后端开发", "字节跳动", "technical", "hard", "计划题数：5", "已问 2 题", "出题来源策略", "题库候选题", "系统设计", "设计一个短链系统", "历史复盘薄弱点", "并发场景分析偏浅"} {
		if !strings.Contains(p, want) {
			t.Fatalf("prompt missing %q\n---\n%s", want, p)
		}
	}
	// Hard rule: must instruct one question per turn + no tool use + no answers.
	for _, must := range []string{"一次只问一个问题", "不要调用任何工具", "不要泄露参考答案"} {
		if !strings.Contains(p, must) {
			t.Fatalf("base rule missing %q", must)
		}
	}
}

func TestMockInterviewerPromptUnlimited(t *testing.T) {
	sess := &db.MockSession{QuestionCount: 0, QuestionSource: "mixed"}
	p := MockInterviewerPrompt(sess, MockContext{})
	if !strings.Contains(p, "题数：不限") {
		t.Fatalf("expected unlimited wording, got:\n%s", p)
	}
}

func TestMockInterviewerPromptNilSession(t *testing.T) {
	p := MockInterviewerPrompt(nil, MockContext{})
	if !strings.Contains(p, "面试官") {
		t.Fatal("base prompt missing for nil session")
	}
}

func TestMockScoringPromptShape(t *testing.T) {
	sess := &db.MockSession{Role: "前端", RoundType: "behavioral", Difficulty: "medium"}
	p := MockScoringPrompt(sess, "用户：我做过X\n面试官：讲讲细节\n用户：...")
	for _, want := range []string{"评估专家", "score_overall", "score_depth", "drills", "link_question_ids", "只输出一个 JSON 对象", "前端", "behavioral"} {
		if !strings.Contains(p, want) {
			t.Fatalf("scoring prompt missing %q", want)
		}
	}
}

func TestParseScoringResultBareJSON(t *testing.T) {
	raw := `{"score_overall":78,"score_communication":80,"score_depth":72,"score_structure":75,"score_confidence":85,"summary":"中等偏上","strengths":["STAR"],"weaknesses":["系统设计"],"drills":[{"area":"系统设计","action":"补练容量估算","link_question_ids":[12,34]}]}`
	fb, err := ParseScoringResult(raw)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if fb.ScoreOverall != 78 || fb.ScoreConfidence != 85 {
		t.Fatalf("scores wrong: %+v", fb)
	}
	if len(fb.Drills) != 1 || fb.Drills[0].Area != "系统设计" {
		t.Fatalf("drills wrong: %+v", fb)
	}
	if len(fb.Drills[0].LinkQuestionIDs) != 2 || fb.Drills[0].LinkQuestionIDs[0] != 12 {
		t.Fatalf("link ids wrong: %+v", fb.Drills[0].LinkQuestionIDs)
	}
}

func TestParseScoringResultFenced(t *testing.T) {
	raw := "好的，这是评分：\n```json\n{\"score_overall\":60,\"summary\":\"还行\",\"strengths\":[],\"weaknesses\":[],\"drills\":[]}\n```\n以上。"
	fb, err := ParseScoringResult(raw)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if fb.ScoreOverall != 60 || fb.Summary != "还行" {
		t.Fatalf("fenced parse wrong: %+v", fb)
	}
}

func TestParseScoringResultDegradesOnGarbage(t *testing.T) {
	fb, err := ParseScoringResult("这根本不是JSON")
	if err == nil {
		t.Fatal("expected error for garbage")
	}
	if fb.ScoreOverall != 0 || fb.Summary != "这根本不是JSON" {
		t.Fatalf("degraded feedback wrong: %+v", fb)
	}
}

func TestParseScoringResultEmpty(t *testing.T) {
	if _, err := ParseScoringResult(""); err == nil {
		t.Fatal("expected error for empty input")
	}
}