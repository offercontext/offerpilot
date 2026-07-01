package ai

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/offercontext/offerpilot/internal/db"
)

// registerOfferTools adds offer read/write tools to the registry.
func registerOfferTools(r *Registry, database *db.Database) {
	r.add(Tool{
		Name:        "list_offers",
		Description: "列出 offer 记录，可按状态过滤。状态取值：pending/negotiating/accepted/declined/expired。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"status":{"type":"string","description":"可选状态过滤"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Status string `json:"status"`
			}
			_ = json.Unmarshal(args, &p)
			offers, err := database.ListOffers(p.Status)
			if err != nil {
				return "", err
			}
			return jsonResult(offers)
		},
	})

	r.add(Tool{
		Name:        "get_offer",
		Description: "按 ID 获取单个 offer 的详情（含派生的年现金总包 total_cash）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			o, err := database.GetOffer(p.ID)
			if err != nil {
				return "未找到该 offer", nil
			}
			return jsonResult(o)
		},
	})

	r.add(Tool{
		Name:        "compare_offers",
		Description: "按 ID 列表横向对比多个 offer，返回各 offer 的关键薪酬字段与派生总包，便于对比。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"ids":{"type":"array","items":{"type":"integer"}}},"required":["ids"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				IDs []int64 `json:"ids"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			var offers []db.Offer
			for _, id := range p.IDs {
				o, err := database.GetOffer(id)
				if err != nil {
					continue
				}
				offers = append(offers, *o)
			}
			return jsonResult(offers)
		},
	})

	r.add(Tool{
		Name:        "update_offer",
		Description: "更新某个 offer 的状态或薪酬字段。status 取值：pending/negotiating/accepted/declined/expired。只传要改的字段。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"status":{"type":"string"},"base_monthly":{"type":"integer"},"months_per_year":{"type":"integer"},"signing_bonus":{"type":"integer"},"equity":{"type":"string"},"perks":{"type":"string"},"deadline":{"type":"string"},"notes":{"type":"string"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID     int64  `json:"id"`
				Status string `json:"status"`
			}
			_ = json.Unmarshal(args, &p)
			if p.Status != "" {
				return fmt.Sprintf("更新 offer #%d（状态改为 %s）", p.ID, p.Status)
			}
			return fmt.Sprintf("更新 offer #%d 的薪酬字段", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID            int64   `json:"id"`
				Status        *string `json:"status"`
				BaseMonthly   *int64  `json:"base_monthly"`
				MonthsPerYear *int64  `json:"months_per_year"`
				SigningBonus  *int64  `json:"signing_bonus"`
				Equity        *string `json:"equity"`
				Perks         *string `json:"perks"`
				Deadline      *string `json:"deadline"`
				Notes         *string `json:"notes"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			o, err := database.GetOffer(p.ID)
			if err != nil {
				return "未找到该 offer", nil
			}
			if p.Status != nil {
				o.Status = *p.Status
			}
			if p.BaseMonthly != nil {
				o.BaseMonthly = *p.BaseMonthly
			}
			if p.MonthsPerYear != nil {
				o.MonthsPerYear = *p.MonthsPerYear
			}
			if p.SigningBonus != nil {
				o.SigningBonus = *p.SigningBonus
			}
			if p.Equity != nil {
				o.Equity = *p.Equity
			}
			if p.Perks != nil {
				o.Perks = *p.Perks
			}
			if p.Deadline != nil {
				o.Deadline = *p.Deadline
			}
			if p.Notes != nil {
				o.Notes = *p.Notes
			}
			if err := database.UpdateOffer(o); err != nil {
				return "", err
			}
			return jsonResult(o)
		},
	})

	r.add(Tool{
		Name:        "save_offer_assessment",
		Description: "为某个 offer 保存决策评估（薪资水平、长期影响、平台价值、可选方案与建议），以 JSON 字符串形式存入 assessment 字段。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"assessment":{"type":"string","description":"评估内容，建议 JSON 字符串，含 level/long_term/platform/alternatives/advice"}},"required":["id","assessment"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("为 offer #%d 保存决策评估", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID         int64  `json:"id"`
				Assessment string `json:"assessment"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			o, err := database.GetOffer(p.ID)
			if err != nil {
				return "未找到该 offer", nil
			}
			o.Assessment = p.Assessment
			if err := database.UpdateOffer(o); err != nil {
				return "", err
			}
			return jsonResult(o)
		},
	})
}
