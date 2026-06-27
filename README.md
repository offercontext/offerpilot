# OfferPilot — 求职者的本地工作台

> **Open-source, self-hosted job search workbench.** Manage your entire job application lifecycle — locally.

## ✨ Features

- 📋 **Application Tracking** — Kanban board + calendar view for all your job applications
- 🤖 **AI-Powered** — JD analysis, resume matching (bring your own API key)
- 💻 **CLI + Web** — Use `oc` command-line or browse to `localhost:8080`
- 🔒 **100% Local** — Your data stays on your machine (SQLite, no cloud)
- 🐳 **One-Command Deploy** — `docker run` or `./oc start`

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
docker run -d -p 8080:8080 -v offerpilot-data:/data offercontext/offerpilot
```

Open `http://localhost:8080` in your browser.

### Option 2: Binary

```bash
# Download from GitHub Releases
chmod +x oc
./oc start
```

### Option 3: Build from Source

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
go build -o oc ./cmd/oc
./oc start
```

## 📖 CLI Usage

```bash
oc start                           # Start local web server
oc add --company "ByteDance" --position "Backend"   # Add application
oc list                            # List all applications
oc list --status interview         # Filter by status
oc analyze --jd "https://..."      # AI-analyze a JD
oc resume --match 1                # Match resume against job #1
oc event --app 1 --type interview --date "2026-07-01 14:00"  # Add interview event
oc config                          # Configure API key
```

## 🔧 Configuration

First run: `oc config` to set your API key.

```json
// ~/.offerpilot/config.json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "local_port": 8080
}
```

Compatible with: OpenAI, Anthropic, DeepSeek, DashScope (Aliyun Qwen), and any OpenAI-compatible API.

## 🏗️ Tech Stack

| Component | Technology |
|---|---|
| Backend | Go 1.22+ (single binary) |
| Database | SQLite (embedded, zero config) |
| Frontend | React 19 + Ant Design + Vite |
| CLI | Cobra |
| AI | User-supplied API key (OpenAI-compatible) |
| Deploy | Docker multi-stage build |

## 📊 Data Model

All data stored in local SQLite (`~/.offerpilot/data.db`):

- **Applications** — Company, position, status, notes, timeline
- **Events** — Written test, interview, assessment dates
- **Interview Notes** — Questions, self-reflection, difficulty points
- **Resume** — Parsed data (JSON, schema v5.0)

## 🗂️ Project Structure

```
offerpilot/
├── cmd/oc/          # CLI entry point
├── internal/
│   ├── api/         # HTTP REST API
│   ├── cli/         # CLI commands (cobra)
│   ├── db/          # SQLite + migrations
│   ├── models/      # Data models
│   └── ai/          # AI integration (provider-agnostic)
├── web/             # React frontend (Vite SPA)
├── Dockerfile       # Multi-stage build
└── go.mod
```

## 📄 License

[MIT](LICENSE) — Free to use, modify, and distribute.

## 🌟 Related

- [OfferContext](https://hub.offercontext.cn) — Cloud version with community features