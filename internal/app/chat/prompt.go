package chat

import (
	"strings"

	"github.com/offercontext/offerpilot/internal/ai"
	mockapp "github.com/offercontext/offerpilot/internal/app/mock"
	"github.com/offercontext/offerpilot/internal/db"
)

// SystemPromptFor picks the model system prompt for the conversation mode.
func SystemPromptFor(database *db.Database, conv *db.Conversation) string {
	if conv == nil || database == nil {
		return ai.ChatSystemPrompt
	}
	switch conv.Mode {
	case "nego_coach":
		if conv.OfferID == nil {
			return ai.ChatSystemPrompt
		}
		offer, err := database.GetOffer(*conv.OfferID)
		if err != nil {
			return ai.ChatSystemPrompt
		}
		return ai.NegoCoachPrompt(offer, buildOfferContext(database, offer))
	case "mock_interview":
		sess, err := database.GetMockSessionByConversation(conv.ID)
		if err != nil || sess == nil {
			return ai.MockInterviewerPromptFallback
		}
		return ai.MockInterviewerPrompt(sess, mockapp.BuildContext(database, sess))
	default:
		return ai.ChatSystemPrompt
	}
}

func buildOfferContext(database *db.Database, offer *db.Offer) string {
	if offer.ApplicationID == nil {
		return ""
	}
	var b strings.Builder
	app, err := database.GetApplication(*offer.ApplicationID)
	if err == nil && app != nil && app.Notes != "" {
		b.WriteString("投递备注：" + app.Notes + "\n")
	}
	notes, err := database.ListInterviewNotes(*offer.ApplicationID)
	if err == nil {
		for _, n := range notes {
			if n.DifficultyPoints != "" || n.SelfReflection != "" {
				b.WriteString("面试复盘（" + n.Round + "）：" + n.SelfReflection + " " + n.DifficultyPoints + "\n")
			}
		}
	}
	return strings.TrimSpace(b.String())
}
