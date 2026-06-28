package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

var (
	analyzeJDText string
	analyzeJDURL  string
	analyzeAppID  int64
)

func newAnalyzeCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "analyze",
		Short: "AI-analyze a job description (JD)",
		Long:  "Run an AI analysis on a JD supplied as text or a URL, and save the result locally.",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runAnalyze(cmd)
		},
	}
	cmd.Flags().StringVarP(&analyzeJDText, "jd", "j", "", "JD text to analyze (use '-' to read from stdin)")
	cmd.Flags().StringVarP(&analyzeJDURL, "jd-url", "u", "", "JD page URL to fetch then analyze")
	cmd.Flags().Int64VarP(&analyzeAppID, "app", "a", 0, "link analysis to an application ID")
	return cmd
}

func runAnalyze(cmd *cobra.Command) error {
	// Validate input: at least one of --jd / --jd-url, but not both.
	hasText := cmd.Flags().Changed("jd")
	hasURL := cmd.Flags().Changed("jd-url")
	if !hasText && !hasURL {
		return fmt.Errorf("provide --jd \"<text>\" or --jd-url <url>")
	}
	if hasText && hasURL {
		return fmt.Errorf("use only one of --jd / --jd-url")
	}

	// Resolve JD text.
	jdText := analyzeJDText
	source := "text"
	if jdText == "-" {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			return fmt.Errorf("read stdin: %w", err)
		}
		jdText = string(data)
	}
	if hasURL {
		fetched, err := ai.FetchJDFromURL(analyzeJDURL)
		if err != nil {
			return err
		}
		jdText = fetched
		source = "url"
	}
	if strings.TrimSpace(jdText) == "" {
		return fmt.Errorf("JD text is empty")
	}

	// Load config + build AI client.
	cfg, err := config.Load(dataDir)
	if err != nil {
		return err
	}
	client, err := ai.New(cfg)
	if err != nil {
		return err
	}

	result, err := ai.AnalyzeJD(context.Background(), client, jdText)
	if err != nil {
		return err
	}

	// Persist to SQLite, optionally linked to an application.
	database, err := db.Init(filepath.Join(dataDir, "data.db"))
	if err != nil {
		return fmt.Errorf("init database: %w", err)
	}
	defer database.Close()

	var appIDPtr *int64
	if analyzeAppID > 0 {
		id := analyzeAppID
		appIDPtr = &id
	}
	resultJSON, _ := json.Marshal(result)
	rec, err := ai.PersistJDAnalysis(database, appIDPtr, source, jdText, string(resultJSON))
	if err != nil {
		return err
	}

	// Print summary.
	fmt.Printf("\n🤖 JD Analysis  (id: %d, source: %s)\n", rec.ID, source)
	fmt.Println("────────────────────────────────────────────")
	fmt.Printf("摘要: %s\n", result.Summary)
	fmt.Printf("年限要求: %s | 学历: %s\n", result.ExperienceYears, result.Education)
	if len(result.TechStack) > 0 {
		fmt.Printf("技术栈: %s\n", strings.Join(result.TechStack, ", "))
	}
	if len(result.Requirements) > 0 {
		fmt.Println("关键要求:")
		for i, req := range result.Requirements {
			fmt.Printf("  %d. %s\n", i+1, req)
		}
	}
	if len(result.Highlights) > 0 {
		fmt.Println("亮点:")
		for _, h := range result.Highlights {
			fmt.Printf("  - %s\n", h)
		}
	}
	if len(result.Suggestions) > 0 {
		fmt.Println("准备建议:")
		for i, s := range result.Suggestions {
			fmt.Printf("  %d. %s\n", i+1, s)
		}
	}
	return nil
}