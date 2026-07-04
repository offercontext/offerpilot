package mock

import (
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

const DefaultSessionTitle = "模拟面试"

type SessionConfig struct {
	Title   string
	Role    string
	Company string
}

type ReviewNoteInput struct {
	Session     db.MockSession
	Application *db.Application
	Summary     string
	Weaknesses  []string
	Today       string
}

func TitleForSessionConfig(cfg SessionConfig) string {
	if cfg.Title != "" {
		return cfg.Title
	}
	name := cfg.Role
	if name == "" {
		name = DefaultSessionTitle
	}
	if cfg.Company != "" {
		name = cfg.Company + " · " + name
	}
	return name
}

func BuildReviewNote(input ReviewNoteInput) *db.InterviewNote {
	company := input.Session.Company
	position := input.Session.Role
	if input.Application != nil {
		if company == "" {
			company = input.Application.CompanyName
		}
		if position == "" {
			position = input.Application.PositionName
		}
	}
	if position == "" {
		position = DefaultSessionTitle
	}
	return &db.InterviewNote{
		ApplicationID:    input.Session.ApplicationID,
		Company:          company,
		Position:         position,
		Round:            DefaultSessionTitle + "·" + input.Session.RoundType,
		Date:             input.Today,
		SelfReflection:   input.Summary,
		DifficultyPoints: joinWeaknesses(input.Weaknesses),
	}
}

func joinWeaknesses(ws []string) string {
	if len(ws) == 0 {
		return ""
	}
	return "待加强：" + strings.Join(ws, "；")
}
