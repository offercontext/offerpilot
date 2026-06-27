package cli

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"
)

var (
	dataDir    string
	serverPort int
)

// Execute runs the root CLI command
func Execute(dir string) error {
	dataDir = dir

	rootCmd := &cobra.Command{
		Use:   "oc",
		Short: "OfferPilot — your local job search workbench",
		Long: "OfferPilot is an open-source, self-hosted job application management tool.\n" +
			"Manage your entire job search lifecycle from the terminal or browser.",
	}

	// Global flags
	rootCmd.PersistentFlags().IntVarP(&serverPort, "port", "p", 8080, "local server port")

	// Register subcommands
	rootCmd.AddCommand(newStartCmd())
	rootCmd.AddCommand(newAddCmd())
	rootCmd.AddCommand(newListCmd())
	rootCmd.AddCommand(newConfigCmd())

	return rootCmd.Execute()
}

// newConfigCmd creates the config subcommand
func newConfigCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "config",
		Short: "Configure API key and settings",
		RunE: func(cmd *cobra.Command, args []string) error {
			return interactiveConfig(cmd)
		},
	}
}

// interactiveConfig guides the user through API key configuration
func interactiveConfig(cmd *cobra.Command) error {
	fmt.Println("\n🔧 OfferPilot Configuration")
	fmt.Println("───────────────────────────")
	fmt.Printf("Config directory: %s\n\n", dataDir)

	// For now, just create a default config
	configPath := filepath.Join(dataDir, "config.json")
	fmt.Printf("Config file: %s\n", configPath)
	fmt.Println("\nEdit this file to set your API key:")
	fmt.Println(`{
  "api_key": "your-api-key",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "local_port": 8080
}`)
	fmt.Println("\nCompatible with: OpenAI, Anthropic, DeepSeek, DashScope")

	return nil
}