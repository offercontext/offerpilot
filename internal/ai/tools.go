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

func parseToolTime(value string) (*time.Time, error) {
	if value == "" {
		return nil, fmt.Errorf("scheduled_at is required")
	}
	t, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return nil, fmt.Errorf("scheduled_at must be RFC3339: %w", err)
	}
	return &t, nil
}

func durationString(minutes int) (string, error) {
	if minutes <= 0 {
		return "", fmt.Errorf("duration_minutes must be greater than 0")
	}
	return fmt.Sprintf("%dm", minutes), nil
}

func validToolEventType(eventType string) bool {
	return eventType == "written_test" || eventType == "interview" || eventType == "assessment"
}

func resolveToolNote(database *db.Database, appID *int64, company, position string) (*int64, string, string, error) {
	if appID != nil && (company == "" || position == "") {
		app, err := database.GetApplication(*appID)
		if err != nil {
			return appID, company, position, err
		}
		if company == "" {
			company = app.CompanyName
		}
		if position == "" {
			position = app.PositionName
		}
	}
	if company == "" {
		return appID, company, position, fmt.Errorf("company is required")
	}
	return appID, company, position, nil
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
	r.add(Tool{
		Name:        "list_events",
		Description: "List schedule events by month, application_id, or event_type.",
		Schema:      json.RawMessage(`{"type":"object","properties":{"month":{"type":"string","description":"Month in YYYY-MM format"},"application_id":{"type":"integer"},"event_type":{"type":"string"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Month         string `json:"month"`
				ApplicationID int64  `json:"application_id"`
				EventType     string `json:"event_type"`
			}
			_ = json.Unmarshal(args, &p)
			items, err := database.ListEvents(db.EventFilter{Month: p.Month, ApplicationID: p.ApplicationID, EventType: p.EventType})
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_event",
		Description: "Get a single schedule event by ID.",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			event, err := database.GetEvent(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
	r.add(Tool{
		Name:        "list_knowledge_bases",
		Description: "List all personal knowledge bases.",
		Schema:      json.RawMessage(`{"type":"object","properties":{}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			items, err := database.ListKnowledgeBases()
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "list_knowledge_documents",
		Description: "List personal knowledge documents, optionally filtered by knowledge_base_id or query.",
		Schema:      json.RawMessage(`{"type":"object","properties":{"knowledge_base_id":{"type":"integer"},"query":{"type":"string"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				KnowledgeBaseID int64  `json:"knowledge_base_id"`
				Query           string `json:"query"`
			}
			_ = json.Unmarshal(args, &p)
			items, err := database.ListKnowledgeDocuments(db.KnowledgeDocumentFilter{KnowledgeBaseID: p.KnowledgeBaseID, Query: p.Query})
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_knowledge_document",
		Description: "Get a single personal knowledge document by ID.",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			doc, err := database.GetKnowledgeDocument(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(doc)
		},
	})
	r.add(Tool{
		Name:        "search_knowledge",
		Description: "Search personal knowledge base chunks by query, optionally scoped to a knowledge_base_id.",
		Schema:      json.RawMessage(`{"type":"object","properties":{"query":{"type":"string"},"knowledge_base_id":{"type":"integer"},"limit":{"type":"integer"}},"required":["query"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Query           string `json:"query"`
				KnowledgeBaseID int64  `json:"knowledge_base_id"`
				Limit           int    `json:"limit"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			items, err := database.SearchKnowledge(db.KnowledgeSearchFilter{Query: p.Query, KnowledgeBaseID: p.KnowledgeBaseID, Limit: p.Limit})
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
		Description: "Add an interview review note. If application_id is provided, missing company and position are filled from the application.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"},"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"date":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"difficulty_points":{"type":"string"},"mood":{"type":"string"}}}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ApplicationID *int64 `json:"application_id"`
				Company       string `json:"company"`
				Position      string `json:"position"`
				Round         string `json:"round"`
			}
			_ = json.Unmarshal(args, &p)
			if p.Company == "" && p.ApplicationID != nil {
				return fmt.Sprintf("Add interview review for application #%d (%s)", *p.ApplicationID, p.Round)
			}
			return fmt.Sprintf("Add interview review: %s - %s (%s)", p.Company, p.Position, p.Round)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ApplicationID    *int64 `json:"application_id"`
				Company          string `json:"company"`
				Position         string `json:"position"`
				Round            string `json:"round"`
				Date             string `json:"date"`
				Questions        string `json:"questions"`
				SelfReflection   string `json:"self_reflection"`
				DifficultyPoints string `json:"difficulty_points"`
				Mood             string `json:"mood"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			appID, company, position, err := resolveToolNote(database, p.ApplicationID, p.Company, p.Position)
			if err != nil {
				return "", err
			}
			note := &db.InterviewNote{
				ApplicationID:    appID,
				Company:          company,
				Position:         position,
				Round:            p.Round,
				Date:             p.Date,
				Questions:        p.Questions,
				SelfReflection:   p.SelfReflection,
				DifficultyPoints: p.DifficultyPoints,
				Mood:             p.Mood,
			}
			if err := database.CreateInterviewNote(note); err != nil {
				return "", err
			}
			return jsonResult(note)
		},
	})
	r.add(Tool{
		Name:        "update_note",
		Description: "Update an existing interview review note by id. Omitted fields keep their current values.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"application_id":{"type":"integer"},"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"date":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"difficulty_points":{"type":"string"},"mood":{"type":"string"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Update interview review note #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID               int64  `json:"id"`
				ApplicationID    *int64 `json:"application_id"`
				Company          string `json:"company"`
				Position         string `json:"position"`
				Round            string `json:"round"`
				Date             string `json:"date"`
				Questions        string `json:"questions"`
				SelfReflection   string `json:"self_reflection"`
				DifficultyPoints string `json:"difficulty_points"`
				Mood             string `json:"mood"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			note, err := database.GetInterviewNote(p.ID)
			if err != nil {
				return "", err
			}
			if p.ApplicationID != nil {
				note.ApplicationID = p.ApplicationID
			}
			if p.Company != "" {
				note.Company = p.Company
			}
			if p.Position != "" {
				note.Position = p.Position
			}
			if p.Round != "" {
				note.Round = p.Round
			}
			if p.Date != "" {
				note.Date = p.Date
			}
			if p.Questions != "" {
				note.Questions = p.Questions
			}
			if p.SelfReflection != "" {
				note.SelfReflection = p.SelfReflection
			}
			if p.DifficultyPoints != "" {
				note.DifficultyPoints = p.DifficultyPoints
			}
			if p.Mood != "" {
				note.Mood = p.Mood
			}
			if err := database.UpdateInterviewNote(note); err != nil {
				return "", err
			}
			return jsonResult(note)
		},
	})
	r.add(Tool{
		Name:        "delete_note",
		Description: "Delete an interview review note by id.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Delete interview review note #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if _, err := database.GetInterviewNote(p.ID); err != nil {
				return "", err
			}
			if err := database.DeleteInterviewNote(p.ID); err != nil {
				return "", err
			}
			return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
		},
	})
	r.add(Tool{
		Name:        "create_knowledge_base",
		Description: "Create a personal knowledge base.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"name":{"type":"string"},"description":{"type":"string"}},"required":["name"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				Name string `json:"name"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Create knowledge base: %s", p.Name)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Name        string `json:"name"`
				Description string `json:"description"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			base := &db.KnowledgeBase{Name: p.Name, Description: p.Description}
			if err := database.CreateKnowledgeBase(base); err != nil {
				return "", err
			}
			return jsonResult(base)
		},
	})
	r.add(Tool{
		Name:        "update_knowledge_base",
		Description: "Update a personal knowledge base by id. Omitted fields keep their current values.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"name":{"type":"string"},"description":{"type":"string"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Update knowledge base #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID          int64   `json:"id"`
				Name        *string `json:"name"`
				Description *string `json:"description"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			base, err := database.GetKnowledgeBase(p.ID)
			if err != nil {
				return "", err
			}
			if p.Name != nil {
				base.Name = *p.Name
			}
			if p.Description != nil {
				base.Description = *p.Description
			}
			if err := database.UpdateKnowledgeBase(base); err != nil {
				return "", err
			}
			return jsonResult(base)
		},
	})
	r.add(Tool{
		Name:        "delete_knowledge_base",
		Description: "Delete a personal knowledge base by id.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Delete knowledge base #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if _, err := database.GetKnowledgeBase(p.ID); err != nil {
				return "", err
			}
			if err := database.DeleteKnowledgeBase(p.ID); err != nil {
				return "", err
			}
			return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
		},
	})
	r.add(Tool{
		Name:        "create_knowledge_document",
		Description: "Create a personal knowledge document.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"knowledge_base_id":{"type":"integer"},"title":{"type":"string"},"content":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["knowledge_base_id","title","content"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				KnowledgeBaseID int64  `json:"knowledge_base_id"`
				Title           string `json:"title"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Create knowledge document in base #%d: %s", p.KnowledgeBaseID, p.Title)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				KnowledgeBaseID int64    `json:"knowledge_base_id"`
				Title           string   `json:"title"`
				Content         string   `json:"content"`
				Tags            []string `json:"tags"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if _, err := database.GetKnowledgeBase(p.KnowledgeBaseID); err != nil {
				return "", err
			}
			doc := &db.KnowledgeDocument{
				KnowledgeBaseID: p.KnowledgeBaseID,
				Title:           p.Title,
				Content:         p.Content,
				Tags:            p.Tags,
			}
			if err := database.CreateKnowledgeDocument(doc); err != nil {
				return "", err
			}
			return jsonResult(doc)
		},
	})
	r.add(Tool{
		Name:        "update_knowledge_document",
		Description: "Update a personal knowledge document by id. Omitted fields keep their current values.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"knowledge_base_id":{"type":"integer"},"title":{"type":"string"},"content":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Update knowledge document #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID              int64     `json:"id"`
				KnowledgeBaseID *int64    `json:"knowledge_base_id"`
				Title           *string   `json:"title"`
				Content         *string   `json:"content"`
				Tags            *[]string `json:"tags"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			doc, err := database.GetKnowledgeDocument(p.ID)
			if err != nil {
				return "", err
			}
			if p.KnowledgeBaseID != nil {
				if _, err := database.GetKnowledgeBase(*p.KnowledgeBaseID); err != nil {
					return "", err
				}
				doc.KnowledgeBaseID = *p.KnowledgeBaseID
			}
			if p.Title != nil {
				doc.Title = *p.Title
			}
			if p.Content != nil {
				doc.Content = *p.Content
			}
			if p.Tags != nil {
				doc.Tags = *p.Tags
			}
			if err := database.UpdateKnowledgeDocument(doc); err != nil {
				return "", err
			}
			return jsonResult(doc)
		},
	})
	r.add(Tool{
		Name:        "delete_knowledge_document",
		Description: "Delete a personal knowledge document by id.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Delete knowledge document #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if _, err := database.GetKnowledgeDocument(p.ID); err != nil {
				return "", err
			}
			if err := database.DeleteKnowledgeDocument(p.ID); err != nil {
				return "", err
			}
			return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
		},
	})
	r.add(Tool{
		Name:        "create_event",
		Description: "Create a schedule event for an application.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"},"event_type":{"type":"string"},"round":{"type":"integer"},"scheduled_at":{"type":"string","description":"RFC3339 timestamp"},"duration_minutes":{"type":"integer"},"location":{"type":"string"},"notes":{"type":"string"}},"required":["application_id","event_type","scheduled_at","duration_minutes"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Create %s event for application #%d at %s for %d minutes", p.EventType, p.ApplicationID, p.ScheduledAt, p.DurationMinutes)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				Round           int    `json:"round"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
				Location        string `json:"location"`
				Notes           string `json:"notes"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if !validToolEventType(p.EventType) {
				return "", fmt.Errorf("invalid event_type %q", p.EventType)
			}
			scheduledAt, err := parseToolTime(p.ScheduledAt)
			if err != nil {
				return "", err
			}
			duration, err := durationString(p.DurationMinutes)
			if err != nil {
				return "", err
			}
			event := &db.Event{
				ApplicationID: p.ApplicationID,
				EventType:     p.EventType,
				Round:         p.Round,
				ScheduledAt:   scheduledAt,
				Duration:      duration,
				Location:      p.Location,
				Notes:         p.Notes,
			}
			if err := database.CreateEvent(event); err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
	r.add(Tool{
		Name:        "update_event",
		Description: "Update a schedule event.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"application_id":{"type":"integer"},"event_type":{"type":"string"},"round":{"type":"integer"},"scheduled_at":{"type":"string","description":"RFC3339 timestamp"},"duration_minutes":{"type":"integer"},"location":{"type":"string"},"notes":{"type":"string"}},"required":["id","application_id","event_type","scheduled_at","duration_minutes"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID              int64  `json:"id"`
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Update event #%d for application #%d to %s at %s for %d minutes", p.ID, p.ApplicationID, p.EventType, p.ScheduledAt, p.DurationMinutes)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID              int64  `json:"id"`
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				Round           int    `json:"round"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
				Location        string `json:"location"`
				Notes           string `json:"notes"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if !validToolEventType(p.EventType) {
				return "", fmt.Errorf("invalid event_type %q", p.EventType)
			}
			scheduledAt, err := parseToolTime(p.ScheduledAt)
			if err != nil {
				return "", err
			}
			duration, err := durationString(p.DurationMinutes)
			if err != nil {
				return "", err
			}
			event := &db.Event{
				ID:            p.ID,
				ApplicationID: p.ApplicationID,
				EventType:     p.EventType,
				Round:         p.Round,
				ScheduledAt:   scheduledAt,
				Duration:      duration,
				Location:      p.Location,
				Notes:         p.Notes,
			}
			if err := database.UpdateEvent(event); err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
	r.add(Tool{
		Name:        "delete_event",
		Description: "Delete a schedule event.",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID int64 `json:"id"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("Delete schedule event #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID int64 `json:"id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if err := database.DeleteEvent(p.ID); err != nil {
				return "", err
			}
			return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
		},
	})

	return r
}
