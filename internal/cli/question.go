package cli

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

var (
	questionSource string
	questionKBID   int64
	questionAppID  int64
	questionCount  int
	questionStatus string
)

func newQuestionCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "question",
		Short: "Manage the interview question bank and practice",
	}
	cmd.AddCommand(newQuestionGenerateCmd())
	cmd.AddCommand(newQuestionListCmd())
	return cmd
}

func newQuestionGenerateCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "generate",
		Short: "AI-generate questions from a knowledge base or interview notes",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runQuestionGenerate()
		},
	}
	cmd.Flags().StringVarP(&questionSource, "source", "s", "knowledge", "source: knowledge | notes")
	cmd.Flags().Int64Var(&questionKBID, "kb", 0, "knowledge base ID (required for --source knowledge)")
	cmd.Flags().Int64VarP(&questionAppID, "app", "a", 0, "application ID to scope interview notes (optional)")
	cmd.Flags().IntVarP(&questionCount, "count", "n", 8, "number of questions to generate")
	return cmd
}

func runQuestionGenerate() error {
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	var (
		label, contextText string
		sourceType         string
		kbID, appID        *int64
	)
	switch strings.TrimSpace(questionSource) {
	case "knowledge":
		if questionKBID <= 0 {
			return fmt.Errorf("--kb is required for --source knowledge")
		}
		label, contextText, err = ai.BuildKnowledgeContext(database, questionKBID)
		sourceType = ai.QuestionSourceKnowledge
		id := questionKBID
		kbID = &id
	case "notes":
		label, contextText, err = ai.BuildNotesContext(database, questionAppID)
		sourceType = ai.QuestionSourceNotes
		if questionAppID > 0 {
			id := questionAppID
			appID = &id
		}
	default:
		return fmt.Errorf("unsupported --source %q (use knowledge | notes)", questionSource)
	}
	if err != nil {
		return err
	}
	if strings.TrimSpace(contextText) == "" {
		return fmt.Errorf("selected source has no content to generate questions from")
	}

	cfg, err := config.Load(dataDir)
	if err != nil {
		return err
	}
	client, err := ai.New(cfg)
	if err != nil {
		return err
	}

	fmt.Printf("\n🤖 Generating %d questions from %s…\n", questionCount, label)
	existing, err := database.ListQuestionDigests()
	if err != nil {
		return err
	}
	existingStems := make([]string, 0, len(existing))
	for _, d := range existing {
		existingStems = append(existingStems, d.Question)
	}
	generated, err := ai.GenerateQuestions(context.Background(), client, label, contextText, questionCount, existingStems)
	if err != nil {
		return err
	}
	saved, skipped, err := ai.PersistGeneratedQuestions(database, kbID, appID, sourceType, generated, existing)
	if err != nil {
		return err
	}
	fmt.Printf("✅ Saved %d questions to the bank", len(saved))
	if skipped > 0 {
		fmt.Printf(" (skipped %d duplicates)", skipped)
	}
	fmt.Println(".")
	for _, q := range saved {
		fmt.Printf("  #%d [%s/%s] %s\n", q.ID, q.Category, q.Difficulty, truncate(q.Question, 60))
	}
	return nil
}

func newQuestionListCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List questions in the bank",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runQuestionList()
		},
	}
	cmd.Flags().StringVar(&questionStatus, "status", "", "filter by status: new | practicing | mastered")
	cmd.Flags().Int64Var(&questionKBID, "kb", 0, "filter by knowledge base ID")
	return cmd
}

func runQuestionList() error {
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	questions, err := database.ListQuestions(db.QuestionFilter{
		Status:          questionStatus,
		KnowledgeBaseID: questionKBID,
	})
	if err != nil {
		return err
	}
	if len(questions) == 0 {
		fmt.Println("\n📭 No questions yet. Try: oc question generate --kb <id>")
		return nil
	}
	fmt.Println("\n📚 Question Bank")
	fmt.Println("─────────────────────────────────────────────────────────────")
	for _, q := range questions {
		fmt.Printf("#%d [%s/%s] %s — 状态:%s 刷题:%d次\n",
			q.ID, q.Category, q.Difficulty, truncate(q.Question, 60), q.Status, q.PracticeCount)
	}
	fmt.Println()
	return nil
}
