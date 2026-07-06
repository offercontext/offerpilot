# OfferPilot

> **Open-source, self-hosted job search workbench.** Manage your entire job application lifecycle — locally.

[中文](#中文) | [English](#english)

---

<a id="中文"></a>

## 🇨🇳 中文

### ✨ 功能特点

- 📋 **投递管理** — 看板视图，管理所有求职投递（拖拽切换状态、统计）
- 🤖 **AI 赋能** — JD 智能分析、简历匹配度检查（自带 API Key）
- 📝 **面试复盘** — 按轮次记录面试问题、自我反思、薄弱点
- 🧠 **题库刷题** — 基于知识库或历史面试复盘用 AI 生成面试题库，配合间隔重复打卡（已刷 / 待复习 / 已掌握）。自动去重，重复生成不会产生重复题目。
- 💰 **Offer 谈薪** — 记录多个 offer、横向对比，并获得基于你自身求职数据的 AI 谈薪教练
- 💻 **命令行 + 网页** — 用 `oc` 命令行操作，或浏览器访问 `localhost:8080`
- 🔒 **完全本地** — 数据保存在本地（SQLite，无需联网）
- 🐳 **一键部署** — `docker run` 或 `uv run oc start`

### 🚀 快速开始

#### 方式一：Docker（推荐）

```bash
docker run -d -p 8080:8080 -v offerpilot-data:/data offercontext/offerpilot
```

浏览器打开 `http://localhost:8080`。

#### 方式二：Python 源码运行

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv sync
uv run oc start
```

#### 方式三：从源码安装 `oc` 命令

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv tool install --force .
oc start
```

#### 方式四：一键安装脚本

```bash
curl -sSL https://get.offerpilot.dev | sh
# 或从本地源码安装：
curl -sSL https://get.offerpilot.dev | sh -s -- --source .
```

### 📖 命令行用法

```bash
oc start                           # 启动本地 Web 服务
oc add --company "字节跳动" --position "后端开发"   # 添加投递
oc list                            # 列出所有投递
oc list --status interview         # 按状态筛选
oc analyze --jd "JD 文本…"         # AI 分析 JD（或 --jd-url https://…）
oc resume add --file resume.txt    # 保存简历文本
oc resume list                     # 列出已保存简历
oc resume match --resume 1 --jd "JD 文本…"   # 简历 #1 对 JD 做匹配度检查（AI）
oc note add --app 1 --round "一面" --date "2026-07-01"   # 添加面试复盘
oc note list --app 1               # 列出某投递的复盘
oc offer add --company "字节跳动" --position "后端开发" --base 35000 --months 16 --signing 50000   # 记录一个 offer
oc offer list                      # 列出所有 offer
oc offer compare 1,2               # 横向对比多个 offer
oc question generate --kb 1 --count 10       # 基于知识库 #1 用 AI 生成 10 道题
oc question generate --source notes          # 从面试复盘真题生成题目
oc question list --status new                # 列出题目（按刷题状态筛选）
oc config --api-key sk-xxx         # 设置 AI API Key
oc config                          # 查看当前配置
```

### 🔧 配置

首次运行 `oc config` 设置 API Key：

```json
// ~/.offerpilot/config.json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "local_port": 8080
}
```

兼容：OpenAI、Anthropic、DeepSeek、DashScope（阿里通义千问）等所有 OpenAI 兼容接口。

数据保存在 `~/.offerpilot` 目录（SQLite 数据库 + `config.json`）。可通过环境变量
`OFFERPILOT_DATA` 指定数据目录，Docker 或自定义部署时很有用。

### 🏗️ 技术栈

| 组件 | 技术 |
|---|---|
| 后端 | Python 3.10+ + FastAPI |
| 数据库 | SQLite（嵌入式，零配置） |
| 前端 | React 18 + Ant Design + Vite |
| 命令行 | Typer（`oc`） |
| AI | 用户自带 API Key（OpenAI 兼容 + Anthropic） |
| 部署 | Docker 多阶段构建 |

### 📊 数据模型

所有数据存储在本地 SQLite（`~/.offerpilot/data.db`）：

- **投递记录** — 公司、职位、状态、备注、时间线
- **事件** — 笔试、面试、测评时间
- **面试复盘** — 面试问题、自我反思、难点
- **Offer** — 底薪、薪数、签字费、期权、福利、截止日、谈判状态
- **简历** — 解析后的结构化数据（JSON，schema v5.0）

### 🗂️ 项目结构

```
offerpilot/
├── src/offerpilot/  # Python 后端、CLI、仓储、AI workflow
├── tests/           # pytest 契约测试
├── web/             # React 前端（Vite SPA）
├── scripts/         # install.sh 一键安装脚本
├── Dockerfile       # 多阶段构建
├── pyproject.toml   # Python 包配置
└── uv.lock
```

### 📄 开源协议

[MIT](LICENSE) — 自由使用、修改和分发。

### 🙏 致谢

本项目的 Offer 谈薪教练功能，其谈薪策略骨架（五阶段引导、四套话术、五种 HR 施压情景）灵感来源于开源项目 [Ssupercoder/Salary-Negotiation-Skill](https://github.com/Ssupercoder/Salary-Negotiation-Skill)。OfferPilot 将这些思路与本地求职数据（投递记录 / JD 分析 / 简历 / 面试复盘）深度结合，以「结构化 offer 记录 + 复用现有 AI 对话引擎」的方式独立重新实现，未直接复用其代码。

### 🌟 相关项目

- [OfferContext](https://hub.offercontext.cn) — 云端版本，含社区功能

---

<a id="english"></a>

## 🇬🇧 English

### ✨ Features

- 📋 **Application Tracking** — Kanban board for all your job applications (drag-to-update status, statistics)
- 🤖 **AI-Powered** — JD smart analysis + resume matching (bring your own API key)
- 📝 **Interview Retrospective** — Capture questions, self-reflection, weak points per round
- 🧠 **Question Bank & Practice** — AI-generate an interview question bank from your knowledge base or past retrospectives, then drill with spaced-repetition check-ins (done / due / mastered). Auto-dedupes so re-generating never repeats existing questions.
- 💰 **Offer & Salary Negotiation** — Track multiple offers, compare them side-by-side, and get an AI negotiation coach grounded in your own application data
- 💻 **CLI + Web** — Use `oc` command-line or browse to `localhost:8080`
- 🔒 **100% Local** — Your data stays on your machine (SQLite, no cloud)
- 🐳 **One-Command Deploy** — `docker run` or `uv run oc start`

### 🚀 Quick Start

#### Option 1: Docker (Recommended)

```bash
docker run -d -p 8080:8080 -v offerpilot-data:/data offercontext/offerpilot
```

Open `http://localhost:8080` in your browser.

#### Option 2: Python source checkout

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv sync
uv run oc start
```

#### Option 3: Install the `oc` CLI from source

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv tool install --force .
oc start
```

#### Option 4: One-line install script

```bash
curl -sSL https://get.offerpilot.dev | sh
# or install from a local checkout:
curl -sSL https://get.offerpilot.dev | sh -s -- --source .
```

### 📖 CLI Usage

```bash
oc start                           # Start local web server
oc add --company "ByteDance" --position "Backend"   # Add application
oc list                            # List all applications
oc list --status interview         # Filter by status
oc analyze --jd "JD text…"         # AI-analyze a JD (or --jd-url https://…)
oc resume add --file resume.txt    # Save a resume as text
oc resume list                     # List saved resumes
oc resume match --resume 1 --jd "JD text…"   # Match resume #1 against a JD (AI)
oc note add --app 1 --round "Round 1" --date "2026-07-01"   # Add interview retrospective
oc note list --app 1               # List notes for an application
oc offer add --company "ByteDance" --position "Backend" --base 35000 --months 16 --signing 50000   # Record an offer
oc offer list                      # List all offers
oc offer compare 1,2               # Compare offers side-by-side
oc question generate --kb 1 --count 10       # AI-generate 10 questions from knowledge base #1
oc question generate --source notes          # Generate from your interview retrospectives
oc question list --status new                # List questions (filter by practice status)
oc config --api-key sk-xxx         # Set your AI API key
oc config                         # Show current configuration
```

### 🔧 Configuration

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

Data lives in `~/.offerpilot` (SQLite database + `config.json`). Override the
data directory with the `OFFERPILOT_DATA` env var — handy for Docker or custom
installs.

### 🏗️ Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.10+ + FastAPI |
| Database | SQLite (embedded, zero config) |
| Frontend | React 18 + Ant Design + Vite |
| CLI | Typer (`oc`) |
| AI | User-supplied API key (OpenAI-compatible + Anthropic) |
| Deploy | Docker multi-stage build |

### 📊 Data Model

All data stored in local SQLite (`~/.offerpilot/data.db`):

- **Applications** — Company, position, status, notes, timeline
- **Events** — Written test, interview, assessment dates
- **Interview Notes** — Questions, self-reflection, difficulty points
- **Questions** — AI-generated/manual interview questions (category, difficulty, reference answer, tags, practice status, next-review schedule)
- **Question Reviews** — Practice check-in log (self-rating) driving spaced repetition
- **Offers** — Base salary, months/year, signing bonus, equity, perks, deadline, negotiation status
- **Resume** — Parsed data (JSON, schema v5.0)

### 🗂️ Project Structure

```
offerpilot/
├── src/offerpilot/  # Python backend, CLI, repositories, AI workflows
├── tests/           # pytest contract tests
├── web/             # React frontend (Vite SPA)
├── scripts/         # install.sh one-line installer
├── Dockerfile       # Multi-stage build
├── pyproject.toml   # Python package metadata
└── uv.lock
```

### 📄 License

[MIT](LICENSE) — Free to use, modify, and distribute.

### 🙏 Acknowledgements

The Offer & Salary-Negotiation coach feature is inspired by [Ssupercoder/Salary-Negotiation-Skill](https://github.com/Ssupercoder/Salary-Negotiation-Skill) — specifically its five-phase negotiation flow, four negotiation strategies, and five HR-pressure scenarios. OfferPilot reimplements these ideas independently, grounded in your local job-search data (applications / JD analysis / resume / interview retrospectives) via structured offer records + the existing AI chat engine, and does not reuse its source code.

### 🌟 Related

- [OfferContext](https://hub.offercontext.cn) — Cloud version with community features
