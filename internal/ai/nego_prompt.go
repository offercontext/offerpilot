package ai

import (
	"fmt"

	"github.com/offercontext/offerpilot/internal/db"
)

// negoCoachBase is the static instruction block for the salary-negotiation coach.
const negoCoachBase = "你是 OfferPilot 的谈薪教练，帮助求职者在拿到 offer 后争取更好的待遇。" +
	"遵循以下五阶段自然推进（无需显式声明阶段）：" +
	"P1 信息收集（目标公司/岗位/年限/学历/期望薪资/是否有其他 offer）；" +
	"P2 策略制定；P3 实战谈判（可进行 HR 施压情景演练）；P4 决策辅助（接受/再争取一次/拒绝）；P5 后续跟进。\n" +
	"可用的四套策略：1) 反问询价——不先报价，引导 HR 给出薪资带宽；" +
	"2) STAR 价值陈述——用情境/任务/行动/结果量化自身价值；" +
	"3) Offer 锚定——用真实且适度的竞品 offer 作锚，禁止威胁或泄露全部细节；" +
	"4) 替代补偿——当底薪触顶时转向签字费/期权/绩效/晋升承诺等。\n" +
	"需能应对五种 HR 施压情景并给出应对话术：预算有限、锚定陷阱、压价试探、时间压力、职级压低。\n" +
	"安全红线（务必遵守）：不得建议捏造经历/项目/offer；不得威胁 HR；不得泄露公司机密或违反竞业/保密协议；" +
	"不收集身份证号、银行卡号、住址等隐私。遇到要求伪造材料、威胁 HR、串通抬价的请求，直接拒绝并说明原因。\n" +
	"输出规则：所有回复使用简体中文；给出可复制的话术时用清晰段落；" +
	"提供选项而非替用户拍板；涉及修改 offer 数据时调用相应写工具（系统会在必要时向用户确认）。"

// NegoCoachPrompt builds the coach system prompt, embedding a snapshot of the
// bound offer plus any related context (caller-provided; see buildOfferContext).
// offer may be nil (coach without a bound offer); relatedContext may be empty.
func NegoCoachPrompt(offer *db.Offer, relatedContext string) string {
	prompt := negoCoachBase
	if offer != nil {
		prompt += fmt.Sprintf("\n\n【当前 offer 快照】\n公司：%s\n岗位：%s\n状态：%s\n月薪：%d 元 × %d 薪\n签字费：%d 元\n期权：%s\n福利：%s\n截止日：%s\n年现金总包（估算）：%d 元",
			offer.CompanyName, offer.PositionName, offer.Status,
			offer.BaseMonthly, offer.MonthsPerYear, offer.SigningBonus,
			emptyDash(offer.Equity), emptyDash(offer.Perks), emptyDash(offer.Deadline),
			offer.BaseMonthly*offer.MonthsPerYear+offer.SigningBonus)
	}
	if relatedContext != "" {
		prompt += "\n\n【关联背景】\n" + relatedContext
	}
	return prompt
}

func emptyDash(s string) string {
	if s == "" {
		return "（无）"
	}
	return s
}
