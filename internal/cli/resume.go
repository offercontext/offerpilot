package cli

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

func newResumeCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "resume",
		Short: "Manage resumes and match them against JDs",
	}
	cmd.AddCommand(newResumeAddCmd())
	cmd.AddCommand(newResumeListCmd())
	cmd.AddCommand(newResumeMatchCmd())
	return cmd
}

var resumeAddFile string
var resumeAddName string

func newResumeAddCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Add a resume from a local text/markdown file",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runResumeAdd(cmd)
		},
	}
	cmd.Flags().StringVarP(&resumeAddFile, "file", "f", "", "path to resume file (.txt/.md)")
	cmd.Flags().StringVarP(&resumeAddName, "name", "n", "", "optional name for this resume")
	cmd.MarkFlagRequired("file")
	return cmd
}

func runResumeAdd(cmd *cobra.Command) error {
	data, err := os.ReadFile(resumeAddFile)
	if err != nil {
		return fmt.Errorf("read resume file: %w", err)
	}
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	res := &db.Resume{
		Name:        resumeAddName,
		FilePath:    resumeAddFile,
		ParsedData:  string(data),
		ParseStatus: "text-ready",
	}
	if err := database.CreateResume(res); err != nil {
		return err
	}
	fmt.Printf("\n✅ Resume saved  (id: %d, name: %q, %d chars)\n", res.ID, res.Name, len(data))
	return nil
}

func newResumeListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List saved resumes",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runResumeList()
		},
	}
}

func runResumeList() error {
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	resumes, err := database.ListResumes()
	if err != nil {
		return err
	}
	if len(resumes) == 0 {
		fmt.Println("\n📭 No resumes yet. Use `oc resume add --file path/to/resume.txt`.")
		return nil
	}
	fmt.Println("\n📄 Resumes")
	fmt.Println("────────────────────────────────────────────────────────")
	fmt.Printf("%-4s %-20s %-12s %-12s\n", "ID", "Name", "Status", "Chars")
	for _, r := range resumes {
		name := r.Name
		if name == "" {
			name = "(unnamed)"
		}
		fmt.Printf("%-4d %-20s %-12s %-12d\n", r.ID, truncate(name, 20), r.ParseStatus, len(r.ParsedData))
	}
	return nil
}

var (
	matchResumeID int64
	matchJDText   string
	matchJDURL    string
	matchAppID    int64
)

func newResumeMatchCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "match",
		Short: "Match a saved resume against a JD (AI)",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runResumeMatch(cmd)
		},
	}
	cmd.Flags().Int64VarP(&matchResumeID, "resume", "r", 0, "resume ID (required)")
	cmd.Flags().StringVarP(&matchJDText, "jd", "j", "", "JD text (use '-' for stdin)")
	cmd.Flags().StringVarP(&matchJDURL, "jd-url", "u", "", "JD page URL")
	cmd.Flags().Int64VarP(&matchAppID, "app", "a", 0, "link match to an application ID")
	cmd.MarkFlagRequired("resume")
	return cmd
}

func runResumeMatch(cmd *cobra.Command) error {
	if matchJDText == "" && matchJDURL == "" {
		return fmt.Errorf("provide --jd \"<text>\" or --jd-url <url>")
	}
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	resume, err := database.GetResume(matchResumeID)
	if err != nil {
		return fmt.Errorf("resume not found: %w", err)
	}
	if resume.ParsedData == "" {
		return fmt.Errorf("resume has no text content")
	}

	// Resolve JD text.
	jdText := matchJDText
	if jdText == "-" {
		var sb strings.Builder
		buf := make([]byte, 4096)
		for {
			n, rerr := os.Stdin.Read(buf)
			if n > 0 {
				sb.Write(buf[:n])
			}
			if rerr != nil {
				break
			}
		}
		jdText = sb.String()
	}
	if matchJDText == "" && matchJDURL != "" {
		fetched, ferr := ai.FetchJDFromURL(matchJDURL)
		if ferr != nil {
			return ferr
		}
		jdText = fetched
	}
	if strings.TrimSpace(jdText) == "" {
		return fmt.Errorf("JD text is empty")
	}

	cfg, err := config.Load(dataDir)
	if err != nil {
		return err
	}
	client, err := ai.New(cfg)
	if err != nil {
		return err
	}

	result, err := ai.MatchResume(context.Background(), client, resume.ParsedData, jdText)
	if err != nil {
		return err
	}

	var appIDPtr *int64
	if matchAppID > 0 {
		id := matchAppID
		appIDPtr = &id
	}
	rec, err := ai.PersistResumeMatch(database, matchResumeID, appIDPtr, jdText, ai.MarshalMatch(result))
	if err != nil {
		return err
	}

	fmt.Printf("\n🤖 Resume Match  (id: %d, resume #%d)\n", rec.ID, matchResumeID)
	fmt.Println("────────────────────────────────────────────")
	fmt.Printf("匹配度: %d/100\n", result.MatchScore)
	fmt.Printf("总评: %s\n", result.Summary)
	if len(result.Matched) > 0 {
		fmt.Println("匹配点:")
		for _, m := range result.Matched {
			fmt.Printf("  + %s\n", m)
		}
	}
	if len(result.Gaps) > 0 {
		fmt.Println("差距:")
		for _, g := range result.Gaps {
			fmt.Printf("  - %s\n", g)
		}
	}
	if len(result.Suggestions) > 0 {
		fmt.Println("优化建议:")
		for i, s := range result.Suggestions {
			fmt.Printf("  %d. %s\n", i+1, s)
		}
	}
	return nil
}