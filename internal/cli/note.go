package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

var (
	noteAppID       int64
	noteRound       string
	noteDate        string
	noteQuestions   string
	noteReflection  string
	noteDifficulty  string
	noteMood        string
	noteCompany     string
	notePosition    string
)

func newNoteCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "note",
		Short: "Manage interview retrospective notes",
	}
	cmd.AddCommand(newNoteAddCmd())
	cmd.AddCommand(newNoteListCmd())
	return cmd
}

func newNoteAddCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Add an interview retrospective note",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runNoteAdd(cmd)
		},
	}
	cmd.Flags().Int64VarP(&noteAppID, "app", "a", 0, "application ID to link (recommended)")
	cmd.Flags().StringVar(&noteCompany, "company", "", "company name (auto-filled from --app when omitted)")
	cmd.Flags().StringVar(&notePosition, "position", "", "position name (auto-filled from --app when omitted)")
	cmd.Flags().StringVarP(&noteRound, "round", "r", "", "interview round, e.g. 一面")
	cmd.Flags().StringVar(&noteDate, "date", "", "interview date, e.g. 2026-07-01")
	cmd.Flags().StringVarP(&noteQuestions, "questions", "q", "", "interview questions (use '-' to read from stdin)")
	cmd.Flags().StringVarP(&noteReflection, "reflection", "f", "", "self reflection")
	cmd.Flags().StringVar(&noteDifficulty, "difficulty", "", "difficult points / areas to improve")
	cmd.Flags().StringVar(&noteMood, "mood", "", "mood, e.g. 好/一般/差")
	cmd.MarkFlagRequired("app")
	return cmd
}

func runNoteAdd(cmd *cobra.Command) error {
	if noteAppID <= 0 {
		return fmt.Errorf("--app is required")
	}
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	// Backfill company/position from the application when omitted.
	company := noteCompany
	position := notePosition
	if company == "" || position == "" {
		app, aerr := database.GetApplication(noteAppID)
		if aerr != nil {
			return fmt.Errorf("application #%d not found: %w", noteAppID, aerr)
		}
		if company == "" {
			company = app.CompanyName
		}
		if position == "" {
			position = app.PositionName
		}
	}
	if company == "" {
		return fmt.Errorf("company could not be resolved (pass --company)")
	}

	questions := noteQuestions
	if questions == "-" {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return fmt.Errorf("read stdin: %w", err)
		}
		questions = string(data)
	}

	appID := noteAppID
	n := &db.InterviewNote{
		ApplicationID:    &appID,
		Company:          company,
		Position:         position,
		Round:            noteRound,
		Date:             noteDate,
		Questions:        questions,
		SelfReflection:   noteReflection,
		DifficultyPoints: noteDifficulty,
		Mood:             noteMood,
	}
	if err := database.CreateInterviewNote(n); err != nil {
		return err
	}
	fmt.Printf("\n✅ Note saved  (id: %d, %s — %s — %s)\n", n.ID, company, position, noteRound)
	return nil
}

func newNoteListCmd() *cobra.Command {
	var appID int64
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List interview notes",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runNoteList(appID)
		},
	}
	cmd.Flags().Int64VarP(&appID, "app", "a", 0, "filter by application ID")
	return cmd
}

func runNoteList(appID int64) error {
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	notes, err := database.ListInterviewNotes(appID)
	if err != nil {
		return err
	}
	if len(notes) == 0 {
		fmt.Println("\n📭 No interview notes.")
		return nil
	}
	fmt.Println("\n📝 Interview Notes")
	fmt.Println("─────────────────────────────────────────────────────────────")
	for _, n := range notes {
		fmt.Printf("#%d  %s — %s — %s — %s — 心情:%s\n",
			n.ID, n.Company, n.Position, n.Round, n.Date, n.Mood)
		if n.Questions != "" {
			fmt.Printf("   问题: %s\n", truncate(n.Questions, 60))
		}
		if n.SelfReflection != "" {
			fmt.Printf("   反思: %s\n", truncate(n.SelfReflection, 60))
		}
		if n.DifficultyPoints != "" {
			fmt.Printf("   难点: %s\n", truncate(n.DifficultyPoints, 60))
		}
		fmt.Println()
	}
	return nil
}