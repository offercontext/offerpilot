package cli

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

var (
	offerCompany  string
	offerPosition string
	offerAppID    int64
	offerBase     int64
	offerMonths   int64
	offerSigning  int64
	offerEquity   string
	offerPerks    string
	offerDeadline string
	offerNotes    string
	offerStatusSet string
)

func newOfferCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "offer",
		Short: "Manage compensation offers",
	}
	cmd.AddCommand(newOfferAddCmd())
	cmd.AddCommand(newOfferListCmd())
	cmd.AddCommand(newOfferUpdateCmd())
	cmd.AddCommand(newOfferDeleteCmd())
	cmd.AddCommand(newOfferCompareCmd())
	return cmd
}

func openCLIDB() (*db.Database, error) {
	return db.Init(filepath.Join(dataDir, "data.db"))
}

func newOfferAddCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Add a compensation offer",
		RunE: func(cmd *cobra.Command, args []string) error {
			database, err := openCLIDB()
			if err != nil {
				return fmt.Errorf("init database: %w", err)
			}
			defer database.Close()

			if offerMonths == 0 {
				offerMonths = 12
			}
			if offerBase < 0 || offerSigning < 0 {
				return fmt.Errorf("--base and --signing must be non-negative")
			}
			if offerMonths < 1 {
				return fmt.Errorf("--months must be at least 1")
			}
			o := &db.Offer{
				CompanyName: offerCompany, PositionName: offerPosition,
				Status: "pending", BaseMonthly: offerBase, MonthsPerYear: offerMonths,
				SigningBonus: offerSigning, Equity: offerEquity, Perks: offerPerks,
				Deadline: offerDeadline, Notes: offerNotes,
			}
			if offerAppID > 0 {
				o.ApplicationID = &offerAppID
				if app, err := database.GetApplication(offerAppID); err == nil {
					if o.CompanyName == "" {
						o.CompanyName = app.CompanyName
					}
					if o.PositionName == "" {
						o.PositionName = app.PositionName
					}
				}
			}
			if o.CompanyName == "" || o.PositionName == "" {
				return fmt.Errorf("--company and --position are required")
			}
			if err := database.CreateOffer(o); err != nil {
				return fmt.Errorf("create offer: %w", err)
			}
			fmt.Printf("\n✅ Offer added: %s — %s (%d×%d + %d, total %d)\n",
				o.CompanyName, o.PositionName, o.BaseMonthly, o.MonthsPerYear, o.SigningBonus, o.TotalCash)
			return nil
		},
	}
	cmd.Flags().StringVarP(&offerCompany, "company", "c", "", "company name")
	cmd.Flags().StringVar(&offerPosition, "position", "", "position name")
	cmd.Flags().Int64VarP(&offerAppID, "app", "a", 0, "linked application ID")
	cmd.Flags().Int64Var(&offerBase, "base", 0, "monthly base salary")
	cmd.Flags().Int64Var(&offerMonths, "months", 12, "months per year (e.g. 12/13/16)")
	cmd.Flags().Int64Var(&offerSigning, "signing", 0, "signing bonus (one-time)")
	cmd.Flags().StringVar(&offerEquity, "equity", "", "equity description")
	cmd.Flags().StringVar(&offerPerks, "perks", "", "perks description")
	cmd.Flags().StringVar(&offerDeadline, "deadline", "", "offer deadline, e.g. 2026-07-08")
	cmd.Flags().StringVarP(&offerNotes, "notes", "n", "", "notes")
	return cmd
}

func newOfferListCmd() *cobra.Command {
	var statusFilter string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List offers",
		RunE: func(cmd *cobra.Command, args []string) error {
			database, err := openCLIDB()
			if err != nil {
				return fmt.Errorf("init database: %w", err)
			}
			defer database.Close()
			offers, err := database.ListOffers(statusFilter)
			if err != nil {
				return fmt.Errorf("list offers: %w", err)
			}
			if len(offers) == 0 {
				fmt.Println("\n📭 No offers found. Use 'oc offer add' to add one.")
				return nil
			}
			fmt.Println("\n💼 Offers")
			fmt.Println("──────────────────────────────────────────────────────────────")
			fmt.Printf("%-4s %-16s %-14s %-12s %-10s %-10s\n", "ID", "Company", "Position", "Status", "Base×M", "Total")
			fmt.Println("──────────────────────────────────────────────────────────────")
			for _, o := range offers {
				fmt.Printf("%-4s %-16s %-14s %-12s %-10s %-10d\n",
					strconv.FormatInt(o.ID, 10),
					truncate(o.CompanyName, 16),
					truncate(o.PositionName, 14),
					o.Status,
					fmt.Sprintf("%d×%d", o.BaseMonthly, o.MonthsPerYear),
					o.TotalCash,
				)
			}
			fmt.Printf("\nTotal: %d offers\n", len(offers))
			return nil
		},
	}
	cmd.Flags().StringVarP(&statusFilter, "status", "s", "", "filter by status")
	return cmd
}

func newOfferUpdateCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "update [id]",
		Short: "Update an offer's fields/status",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid offer id: %s", args[0])
			}
			database, err := openCLIDB()
			if err != nil {
				return fmt.Errorf("init database: %w", err)
			}
			defer database.Close()
			o, err := database.GetOffer(id)
			if err != nil {
				return fmt.Errorf("offer not found: %w", err)
			}
			if cmd.Flags().Changed("status") {
				o.Status = offerStatusSet
			}
			if cmd.Flags().Changed("base") {
				o.BaseMonthly = offerBase
			}
			if cmd.Flags().Changed("months") {
				o.MonthsPerYear = offerMonths
			}
			if cmd.Flags().Changed("signing") {
				o.SigningBonus = offerSigning
			}
			if o.MonthsPerYear < 1 {
				return fmt.Errorf("months must be at least 1")
			}
			if err := database.UpdateOffer(o); err != nil {
				return fmt.Errorf("update offer: %w", err)
			}
			fmt.Printf("\n✅ Offer #%d updated (status %s, total %d)\n", o.ID, o.Status, o.TotalCash)
			return nil
		},
	}
	cmd.Flags().StringVar(&offerStatusSet, "status", "", "new status")
	cmd.Flags().Int64Var(&offerBase, "base", 0, "monthly base salary")
	cmd.Flags().Int64Var(&offerMonths, "months", 12, "months per year")
	cmd.Flags().Int64Var(&offerSigning, "signing", 0, "signing bonus")
	return cmd
}

func newOfferDeleteCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "delete [id]",
		Short: "Delete an offer",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := strconv.ParseInt(args[0], 10, 64)
			if err != nil {
				return fmt.Errorf("invalid offer id: %s", args[0])
			}
			database, err := openCLIDB()
			if err != nil {
				return fmt.Errorf("init database: %w", err)
			}
			defer database.Close()
			if err := database.DeleteOffer(id); err != nil {
				return fmt.Errorf("delete offer: %w", err)
			}
			fmt.Printf("\n🗑️  Offer #%d deleted\n", id)
			return nil
		},
	}
}

func newOfferCompareCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "compare [id1,id2,...]",
		Short: "Compare offers side by side",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			database, err := openCLIDB()
			if err != nil {
				return fmt.Errorf("init database: %w", err)
			}
			defer database.Close()
			var offers []db.Offer
			for _, part := range strings.Split(args[0], ",") {
				part = strings.TrimSpace(part)
				if part == "" {
					continue
				}
				id, err := strconv.ParseInt(part, 10, 64)
				if err != nil {
					return fmt.Errorf("invalid id: %s", part)
				}
				o, err := database.GetOffer(id)
				if err != nil {
					continue
				}
				offers = append(offers, *o)
			}
			if len(offers) == 0 {
				fmt.Println("\n📭 No offers matched those IDs.")
				return nil
			}
			fmt.Println("\n📊 Offer Comparison")
			fmt.Printf("%-16s", "Field")
			for _, o := range offers {
				fmt.Printf("%-16s", truncate(o.CompanyName, 16))
			}
			fmt.Println()
			printRow := func(label string, val func(db.Offer) string) {
				fmt.Printf("%-16s", label)
				for _, o := range offers {
					fmt.Printf("%-16s", val(o))
				}
				fmt.Println()
			}
			printRow("Position", func(o db.Offer) string { return truncate(o.PositionName, 16) })
			printRow("Status", func(o db.Offer) string { return o.Status })
			printRow("Base×Months", func(o db.Offer) string { return fmt.Sprintf("%d×%d", o.BaseMonthly, o.MonthsPerYear) })
			printRow("Signing", func(o db.Offer) string { return strconv.FormatInt(o.SigningBonus, 10) })
			printRow("Total Cash", func(o db.Offer) string { return strconv.FormatInt(o.TotalCash, 10) })
			printRow("Deadline", func(o db.Offer) string { return truncate(o.Deadline, 16) })
			return nil
		},
	}
}
