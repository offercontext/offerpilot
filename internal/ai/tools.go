package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

// Tool is a protocol-agnostic capability the model can invoke.
// Schema is a JSON Schema object describing Handler's argument shape.
// Write marks tools that mutate data (gated by the confirmation flow).
// Describe renders a human-readable confirmation string for write tools.
type Tool struct {
	Name        string
	Description string
	Schema      json.RawMessage
	Write       bool
	Handler     func(ctx context.Context, args json.RawMessage) (string, error)
	Describe    func(args json.RawMessage) string
}

// Registry holds the available tools, built against a database handle.
type Registry struct {
	tools map[string]Tool
	order []string
}

// List returns tools in registration order.
func (r *Registry) List() []Tool {
	out := make([]Tool, 0, len(r.order))
	for _, name := range r.order {
		out = append(out, r.tools[name])
	}
	return out
}

// Get returns a tool by name.
func (r *Registry) Get(name string) (Tool, bool) {
	t, ok := r.tools[name]
	return t, ok
}

// Execute runs a tool's handler. Returns an error for unknown tools.
func (r *Registry) Execute(ctx context.Context, name string, args json.RawMessage) (string, error) {
	t, ok := r.tools[name]
	if !ok {
		return "", fmt.Errorf("unknown tool %q", name)
	}
	return t.Handler(ctx, args)
}

func (r *Registry) add(t Tool) {
	r.tools[t.Name] = t
	r.order = append(r.order, t.Name)
}

// jsonResult marshals v to a compact JSON string for feeding back to the model.
func jsonResult(v interface{}) (string, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// NewRegistry builds the tool set bound to the given database.
func NewRegistry(database *db.Database) *Registry {
	r := &Registry{tools: map[string]Tool{}}

	// ---- read tools ----
	r.add(Tool{
		Name:        "list_applications",
		Description: "列出求职投递记录，可按状态过滤。状态取值：applied/assessment/written_test/interview/offer/eliminated/rejected。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"status":{"type":"string","description":"可选状态过滤"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Status string `json:"status"`
			}
			_ = json.Unmarshal(args, &p)
			apps, err := database.ListApplications(p.Status)
			if err != nil {
				return "", err
			}
			return jsonResult(apps)
		},
	})
	r.add(Tool{
		Name:        "get_application",
		Description: "按 ID 获取单条投递记录的详情。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			app, err := database.GetApplication(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "list_jd_analyses",
		Description: "列出 JD 分析结果，可按 application_id 过滤（传 0 或省略列出全部）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ApplicationID int64 `json:"application_id"`
			}
			_ = json.Unmarshal(args, &p)
			items, err := database.ListJDAnalyses(p.ApplicationID)
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_jd_analysis",
		Description: "按 ID 获取单条 JD 分析详情。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			a, err := database.GetJDAnalysis(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(a)
		},
	})
	r.add(Tool{
		Name:        "list_resumes",
		Description: "列出已保存的简历（含简历文本）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			items, err := database.ListResumes()
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_resume",
		Description: "按 ID 获取单份简历的完整文本。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			res, err := database.GetResume(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(res)
		},
	})
	r.add(Tool{
		Name:        "list_notes",
		Description: "列出面试复盘笔记，可按 application_id 过滤（传 0 或省略列出全部）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ApplicationID int64 `json:"application_id"`
			}
			_ = json.Unmarshal(args, &p)
			items, err := database.ListInterviewNotes(p.ApplicationID)
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})

	// ---- write tools ----
	r.add(Tool{
		Name:        "create_application",
		Description: "新建一条投递记录。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"company_name":{"type":"string"},"position_name":{"type":"string"},"job_url":{"type":"string"},"status":{"type":"string"}},"required":["company_name","position_name"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				Company  string `json:"company_name"`
				Position string `json:"position_name"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("新建投递：%s - %s", p.Company, p.Position)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Company  string `json:"company_name"`
				Position string `json:"position_name"`
				JobURL   string `json:"job_url"`
				Status   string `json:"status"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if p.Status == "" {
				p.Status = "applied"
			}
			app := &db.Application{
				CompanyName: p.Company, PositionName: p.Position,
				JobURL: p.JobURL, Status: p.Status, Source: "ai",
				AppliedAt: time.Now(),
			}
			if err := database.CreateApplication(app); err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "update_application_status",
		Description: "修改某条投递的状态。状态取值：applied/assessment/written_test/interview/offer/eliminated/rejected。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"status":{"type":"string"}},"required":["id","status"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID     int64  `json:"id"`
				Status string `json:"status"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("将投递 #%d 的状态改为 %s", p.ID, p.Status)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID     int64  `json:"id"`
				Status string `json:"status"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			app, err := database.GetApplication(p.ID)
			if err != nil {
				return "", err
			}
			app.Status = p.Status
			if err := database.UpdateApplication(app); err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "add_note",
		Description: "为某次面试追加一条复盘笔记。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"application_id":{"type":"integer"}},"required":["company","position"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				Company  string `json:"company"`
				Position string `json:"position"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("新增面试复盘笔记：%s - %s", p.Company, p.Position)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Company        string `json:"company"`
				Position       string `json:"position"`
				Round          string `json:"round"`
				Questions      string `json:"questions"`
				SelfReflection string `json:"self_reflection"`
				ApplicationID  *int64 `json:"application_id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			note := &db.InterviewNote{
				ApplicationID: p.ApplicationID, Company: p.Company, Position: p.Position,
				Round: p.Round, Questions: p.Questions, SelfReflection: p.SelfReflection,
			}
			if err := database.CreateInterviewNote(note); err != nil {
				return "", err
			}
			return jsonResult(note)
		},
	})

	return r
}
