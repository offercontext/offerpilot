package db

var ApplicationStatuses = []string{
	"applied",
	"assessment",
	"written_test",
	"interview",
	"offer",
	"eliminated",
	"rejected",
}

var OfferStatuses = []string{
	"pending",
	"negotiating",
	"accepted",
	"declined",
	"expired",
}

var QuestionDifficulties = []string{
	"easy",
	"medium",
	"hard",
}

var QuestionStatuses = []string{
	"new",
	"practicing",
	"mastered",
}

var QuestionSources = []string{
	"ai_knowledge",
	"ai_notes",
	"manual",
}
