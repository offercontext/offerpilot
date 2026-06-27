package cli

import (
	"fmt"
	"path/filepath"
	"strconv"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

var (
	addCompany  string
	addPosition string
	addURL      string
	addNotes    string
)

func newAddCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Add a new job application",
		Long:  "Add a new job application to your tracking board.",
		RunE: func(cmd *cobra.Command, args []string) error {
			return addApplication(cmd)
		},
	}
	cmd.Flags().StringVarP(&addCompany, "company", "c", "", "company name (required)")
	cmd.Flags().StringVarP(&addPosition, "position", "", "", "position/job title (required)")
	cmd.Flags().StringVarP(&addURL, "url", "u", "", "job posting URL")
	cmd.Flags().StringVarP(&addNotes, "notes", "n", "", "notes about this application")
	cmd.MarkFlagRequired("company")
	cmd.MarkFlagRequired("position")
	return cmd
}

func addApplication(cmd *cobra.Command) error {
	dbPath := filepath.Join(dataDir, "data.db")
	database, err := db.Init(dbPath)
	if err != nil {
		return fmt.Errorf("failed to init database: %w", err)
	}
	defer database.Close()

	app := &db.Application{
		CompanyName:  addCompany,
		PositionName: addPosition,
		JobURL:       addURL,
		Status:       "applied",
		Source:       "cli",
		Notes:        addNotes,
		AppliedAt:    time.Now(),
	}

	if err := database.CreateApplication(app); err != nil {
		return fmt.Errorf("failed to create application: %w", err)
	}

	fmt.Printf("\n✅ Added: %s — %s\n", app.CompanyName, app.PositionName)
	fmt.Printf("   ID: %d  Status: %s\n", app.ID, app.Status)
	return nil
}

func newListCmd() *cobra.Command {
	var statusFilter string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List all job applications",
		Long:  "Display all job applications in a compact table format.",
		RunE: func(cmd *cobra.Command, args []string) error {
			return listApplications(statusFilter)
		},
	}
	cmd.Flags().StringVarP(&statusFilter, "status", "s", "", "filter by status (applied/interview/offer/etc)")
	return cmd
}

func listApplications(statusFilter string) error {
	dbPath := filepath.Join(dataDir, "data.db")
	database, err := db.Init(dbPath)
	if err != nil {
		return fmt.Errorf("failed to init database: %w", err)
	}
	defer database.Close()

	apps, err := database.ListApplications(statusFilter)
	if err != nil {
		return fmt.Errorf("failed to list applications: %w", err)
	}

	if len(apps) == 0 {
		fmt.Println("\n📭 No applications found. Use 'oc add' to add one.")
		return nil
	}

	fmt.Println("\n📋 Job Applications")
	fmt.Println("─────────────────────────────────────────────────────────────")
	fmt.Printf("%-4s %-20s %-20s %-12s %-12s\n", "ID", "Company", "Position", "Status", "Applied")
	fmt.Println("─────────────────────────────────────────────────────────────")
	for _, app := range apps {
		fmt.Printf("%-4s %-20s %-20s %-12s %-12s\n",
			strconv.FormatInt(app.ID, 10),
			truncate(app.CompanyName, 20),
			truncate(app.PositionName, 20),
			app.Status,
			app.AppliedAt.Format("2006-01-02"),
		)
	}
	fmt.Printf("\nTotal: %d applications\n", len(apps))
	return nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n-1] + "…"
	}
	return s
}