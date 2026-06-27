package cli

import (
	"fmt"
	"log"
	"net/http"
	"os/exec"
	"path/filepath"
	"runtime"

	"github.com/offercontext/offerpilot/internal/api"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/spf13/cobra"
)

func newStartCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "start",
		Short: "Start the local web server",
		Long:  "Starts the OfferPilot local web server and opens it in your browser.",
		RunE: func(cmd *cobra.Command, args []string) error {
			return startServer(cmd)
		},
	}
	return cmd
}

func startServer(cmd *cobra.Command) error {
	dbPath := filepath.Join(dataDir, "data.db")
	database, err := db.Init(dbPath)
	if err != nil {
		return fmt.Errorf("failed to init database: %w", err)
	}
	defer database.Close()

	addr := fmt.Sprintf(":%d", serverPort)
	router := api.NewRouter(database, dataDir)

	fmt.Printf("\n🚀 OfferPilot is running at http://localhost:%d\n", serverPort)
	fmt.Printf("📂 Data directory: %s\n", dataDir)
	fmt.Println("Press Ctrl+C to stop.\n")

	// Try to open browser
	go openBrowser(fmt.Sprintf("http://localhost:%d", serverPort))

	return http.ListenAndServe(addr, router)
}

func openBrowser(url string) {
	var err error
	switch runtime.GOOS {
	case "darwin":
		err = exec.Command("open", url).Start()
	case "windows":
		err = exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	default:
		err = exec.Command("xdg-open", url).Start()
	}
	if err != nil {
		log.Printf("Warning: could not open browser: %v", err)
	}
}