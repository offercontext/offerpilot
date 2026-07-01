package api

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/offercontext/offerpilot/internal/db"
)

// NewRouter creates the HTTP router with API + embedded frontend
func NewRouter(database *db.Database, dataDir string) http.Handler {
	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(corsMiddleware)

	// API routes
	r.Route("/api", func(r chi.Router) {
		r.Get("/applications", listApplications(database))
		r.Post("/applications", createApplication(database))
		r.Get("/applications/{id}", getApplication(database))
		r.Put("/applications/{id}", updateApplication(database))
		r.Delete("/applications/{id}", deleteApplication(database))
		r.Get("/dashboard", getDashboard(database))

		// Schedule events
		registerEventRoutes(r, database)

		// JD analysis (AI)
		registerJDRoutes(r, database, dataDir)

		// Resumes + matching (AI)
		registerResumeRoutes(r, database, dataDir)

		// Interview retrospective notes
		registerNoteRoutes(r, database)

		// Knowledge bases, documents, imports, and search
		registerKnowledgeRoutes(r, database)

		// Offer negotiation
		registerOfferRoutes(r, database)

		// Calendar aggregation (interviews + applied dates)
		r.Get("/calendar", getCalendarHandler(database))

		// AI chat assistant
		registerChatRoutes(r, database, dataDir)
		// Chat-related settings (no API key exposure)
		registerSettingsRoutes(r, dataDir)
	})

	// Serve React frontend (or fallback to dev proxy)
	r.Get("/*", serveFrontend(dataDir))

	return r
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func respondJSON(w http.ResponseWriter, code int, payload interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(payload)
}

func respondError(w http.ResponseWriter, code int, msg string) {
	respondJSON(w, code, map[string]string{"error": msg})
}

// serveFrontend serves the built React app if dist exists, otherwise a placeholder
func serveFrontend(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Try to serve from web/dist
		distDir := findDistDir()
		if distDir != "" {
			filePath := filepath.Join(distDir, strings.TrimPrefix(r.URL.Path, "/"))
			if _, err := os.Stat(filePath); err == nil {
				http.ServeFile(w, r, filePath)
				return
			}
			// SPA fallback: serve index.html
			indexPath := filepath.Join(distDir, "index.html")
			if _, err := os.Stat(indexPath); err == nil {
				http.ServeFile(w, r, indexPath)
				return
			}
		}

		// Dev mode: no frontend built yet
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(devPlaceholderHTML))
	}
}

// findDistDir locates the frontend dist directory
func findDistDir() string {
	// Check relative paths (development)
	candidates := []string{
		"web/dist",
		"../web/dist",
		"./web/dist",
	}
	for _, p := range candidates {
		if _, err := os.Stat(filepath.Join(p, "index.html")); err == nil {
			return p
		}
	}
	return ""
}

const devPlaceholderHTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OfferPilot</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f0f4f8;color:#1a1a1a}
.container{text-align:center;padding:2rem}
h1{font-size:2rem;margin-bottom:1rem;color:#059669}
p{color:#6b7280;max-width:400px;margin:0.5rem auto}
code{background:#e4e4e7;padding:2px 8px;border-radius:4px;font-size:0.9rem}
</style>
</head>
<body>
<div class="container">
<h1>🚀 OfferPilot is running</h1>
<p>The backend is ready. To see the full UI, build the frontend:</p>
<p><code>cd web && npm install && npm run build</code></p>
<p>Then restart <code>oc start</code> and refresh this page.</p>
<p>Or use the CLI: <code>oc add --company "Test" --position "Engineer"</code></p>
</div>
</body>
</html>`
