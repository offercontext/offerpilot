package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/offercontext/offerpilot/internal/cli"
)

func main() {
	// Data directory: prefer OFFERPILOT_DATA env (handy for Docker / custom
	// installs), otherwise default to ~/.offerpilot.
	dataDir := os.Getenv("OFFERPILOT_DATA")
	if dataDir == "" {
		homeDir, err := os.UserHomeDir()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: cannot determine home directory: %v\n", err)
			os.Exit(1)
		}
		dataDir = filepath.Join(homeDir, ".offerpilot")
	}
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error: cannot create data directory %s: %v\n", dataDir, err)
		os.Exit(1)
	}

	// Execute CLI
	if err := cli.Execute(dataDir); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}