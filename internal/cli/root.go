package cli

import (
	"fmt"
	"path/filepath"

	"github.com/offercontext/offerpilot/internal/config"
	"github.com/spf13/cobra"
)

var (
	dataDir    string
	serverPort int

	// config flags
	cfgAPIKey  string
	cfgBaseURL string
	cfgModel   string
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
	rootCmd.AddCommand(newAnalyzeCmd())
	rootCmd.AddCommand(newResumeCmd())
	rootCmd.AddCommand(newNoteCmd())

	return rootCmd.Execute()
}

// newConfigCmd creates the config subcommand. Supports:
//   oc config                      (show current config)
//   oc config --api-key sk-xxx     (set API key)
//   oc config --base-url https://… --model gpt-4o  (set endpoint/model)
func newConfigCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config",
		Short: "Configure API key and settings",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runConfig(cmd)
		},
	}
	cmd.Flags().StringVar(&cfgAPIKey, "api-key", "", "set API key for the OpenAI-compatible endpoint")
	cmd.Flags().StringVar(&cfgBaseURL, "base-url", "", "set base_url (e.g. https://api.deepseek.com/v1)")
	cmd.Flags().StringVar(&cfgModel, "model", "", "set model name (e.g. deepseek-chat)")
	return cmd
}

// runConfig shows the current config, and writes changes when any --api-key /
// --base-url / --model flag is provided.
func runConfig(cmd *cobra.Command) error {
	cfg, err := config.Load(dataDir)
	if err != nil {
		return err
	}

	changed := false
	if cmd.Flags().Changed("api-key") {
		cfg.APIKey = cfgAPIKey
		changed = true
	}
	if cmd.Flags().Changed("base-url") {
		cfg.BaseURL = cfgBaseURL
		changed = true
	}
	if cmd.Flags().Changed("model") {
		cfg.Model = cfgModel
		changed = true
	}

	if changed {
		if err := config.Save(dataDir, cfg); err != nil {
			return err
		}
		fmt.Println("✅ Config saved to", filepath.Join(dataDir, "config.json"))
	}

	configPath := filepath.Join(dataDir, "config.json")
	fmt.Println("\n🔧 OfferPilot Configuration")
	fmt.Println("───────────────────────────")
	fmt.Printf("Config file: %s\n", configPath)
	fmt.Printf("  base_url : %s\n", cfg.BaseURL)
	fmt.Printf("  model    : %s\n", cfg.Model)
	if cfg.APIKey == "" {
		fmt.Println("  api_key  : (not set — AI features will return an error)")
	} else {
		fmt.Printf("  api_key  : %s…(hidden)\n", maskKey(cfg.APIKey))
	}
	fmt.Printf("  local_port: %d\n", cfg.LocalPort)
	fmt.Println("\nCompatible with: OpenAI, DeepSeek, DashScope, Ollama (any OpenAI-compatible /v1/chat/completions endpoint).")
	if cfg.APIKey == "" {
		fmt.Println("\nSet your key:  oc config --api-key sk-xxx")
	}
	return nil
}

func maskKey(k string) string {
	if len(k) <= 6 {
		return "******"
	}
	return k[:4] + "****" + k[len(k)-2:]
}