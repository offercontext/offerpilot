# OfferPilot

Local-first, self-hosted job-search workbench with a Pilot assistant.

OfferPilot helps you manage applications, resumes, practice, interviews, offers, and local knowledge in one SQLite-backed workspace. AI features use your own API key and route through LiteLLM.

[中文](#中文) | [English](#english)

---

<a id="中文"></a>

## 中文

### 当前 v0.1 范围

- 模块化工作台：工作台、简历、练习、投递、面试、知识库、设置。
- 投递生命周期：`pending -> applied -> written_test -> interview -> offer -> closed`。
- Pilot 助手：桌面端常驻右侧栏，小屏使用抽屉；写操作先进入人工确认。
- 多模型接入：经 LiteLLM 统一路由 OpenAI、Anthropic、DeepSeek、DashScope、OpenRouter 和 OpenAI-compatible provider。
- 本地优先：SQLite 数据库、配置和日志默认写入 `~/.offerpilot`。
- 运行基础：`runtime_mode`、`auth_enabled`、`log_level`、`local_port`、`oc smoke`。

### 快速开始

#### Docker

```bash
docker run -d -p 8080:8080 -v offerpilot-data:/data offercontext/offerpilot
```

打开 `http://localhost:8080`。

#### 源码运行

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv sync
cd web && npm install && npm run build
cd ..
uv run oc start
```

#### 安装 CLI

```bash
uv tool install --force .
oc start
```

### 常用命令

```bash
oc start                                  # 启动本地 Web 服务
oc smoke                                  # 运行核心 smoke：health、SPA、投递、Pilot 确认流
oc config --api-key sk-xxx               # 设置 AI API key
oc config --model gpt-4o                 # 设置当前 provider 模型
oc config --runtime-mode local           # local 或 server
oc config --auth --log-level debug       # 打开 auth 开关并设置日志级别

oc add --company "ByteDance" --position "Backend"
oc list --status interview
oc resume add --file resume.txt
oc note add --app 1 --round "Round 1" --date "2026-07-01"
oc offer add --company "ByteDance" --position "Backend" --base 35000 --months 16
oc question generate --kb 1 --count 10
```

### 配置

配置文件默认位于 `~/.offerpilot/config.json`，可通过 `OFFERPILOT_DATA` 指定数据目录。

```json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "local_port": 8080,
  "runtime_mode": "local",
  "auth_enabled": false,
  "log_level": "INFO",
  "active_provider_id": "default",
  "providers": [
    {
      "id": "default",
      "label": "Default",
      "provider": "openai",
      "api_key": "sk-xxx",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "enabled": true
    }
  ]
}
```

### 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、Typer |
| 数据 | SQLite，本地文件存储 |
| 前端 | React 18、Ant Design、Vite |
| AI | LiteLLM、用户自带 API key、工具调用确认 |
| 部署 | Docker 多阶段构建 |

### 已完成的架构调整

- AGPLv3 开源协议对齐。
- 后端统一投递状态枚举，并兼容旧状态别名。
- 产品导航对齐模块 IA。
- Pilot 从纯抽屉升级为桌面常驻右栏。
- LiteLLM 统一模型 provider 路由。
- HITL pending actions 持久化，刷新后可恢复确认状态。
- 运行模式、日志级别、诊断日志 API 和 `oc smoke` 基础 smoke harness。

### 仍在路线图中

- Docker build/run 自动化 smoke。
- Skill 安装、信任和加载模型。
- 知识库 RAG：FTS5 + embedding + RRF + 来源 chunk 回指。
- LangGraph checkpoint / interrupt / scheduled wakeups。
- 日志 UI 面板和真实 auth middleware。
- 移动端与宽屏截图级 UI QA。

### 许可证

[AGPLv3](LICENSE)。如果你通过网络向用户提供修改后的 OfferPilot，也需要按 AGPLv3 向这些用户提供对应源代码。

---

<a id="english"></a>

## English

### Current v0.1 Scope

- Modular workspace: dashboard, resumes, practice, applications, interviews, knowledge base, settings.
- Application lifecycle: `pending -> applied -> written_test -> interview -> offer -> closed`.
- Pilot assistant: persistent desktop right rail, drawer on narrow screens, human confirmation for write tools.
- Multi-provider AI: LiteLLM routes OpenAI, Anthropic, DeepSeek, DashScope, OpenRouter, and OpenAI-compatible providers.
- Local-first storage: SQLite data, config, and diagnostics logs under `~/.offerpilot` by default.
- Runtime basics: `runtime_mode`, `auth_enabled`, `log_level`, `local_port`, and `oc smoke`.
- Skill registry: packages are registered untrusted by default and load only after explicit trust and enablement.
- Skill manifests: registry records manifest digest, entrypoint, source type, and provenance without executing package code.
- Knowledge RAG base: SQLite FTS5 chunk retrieval with lexical fallback, reciprocal-rank scoring, and source citations.
- Runtime diagnostics are visible in the settings module.
- Browser auth gate verifies `offerpilot.auth_token` before loading the app shell.
- Scheduled wakeups: durable SQLite queue with API and CLI dispatch for due follow-ups.
- Schema changes are tracked in `schema_migrations` before additive startup repairs run.

### Quick Start

#### Docker

```bash
docker run -d -p 8080:8080 -v offerpilot-data:/data offercontext/offerpilot
```

Open `http://localhost:8080`.

#### Docker Smoke

```bash
scripts/docker-smoke.sh
```

On Windows PowerShell:

```powershell
.\scripts\docker-smoke.ps1
```

Both `scripts/docker-smoke.sh` and `scripts/docker-smoke.ps1` build a local image and run `oc smoke --static-dir /app/web/dist` inside the container.

#### Local Release Smoke

```bash
scripts/local-smoke.sh
```

```powershell
.\scripts\local-smoke.ps1
```

Both `scripts/local-smoke.sh` and `scripts/local-smoke.ps1` build `web/dist`, start `uv run oc start` on a temporary data directory, verify `/api/health` and the SPA fallback route, then run the core `oc smoke` flow.

The current non-Docker P0 gate is tracked in [`docs/p0-release-checklist.md`](docs/p0-release-checklist.md).

#### Source Checkout

```bash
git clone https://github.com/offercontext/offerpilot.git
cd offerpilot
uv sync
cd web && npm install && npm run build
cd ..
uv run oc start
```

#### Install CLI From Source

```bash
uv tool install --force .
oc start
```

### CLI

```bash
oc start
oc smoke
oc config --api-key sk-xxx
oc config --model gpt-4o
oc config --runtime-mode local
oc config --auth --log-level debug
oc config --auth-token local-secret
oc skill add --manifest ./skill.json --source file:///skills/resume-coach
oc skill add --id resume-coach --label "Resume Coach" --source file:///skills/resume-coach
oc skill trust resume-coach
oc skill enable resume-coach
oc skill list
oc wakeup add --kind follow_up --due-at 2026-07-08T09:30:00Z --payload-json '{"application_id":7}'
oc wakeup dispatch-due

oc add --company "ByteDance" --position "Backend"
oc list --status interview
oc resume add --file resume.txt
oc note add --app 1 --round "Round 1" --date "2026-07-01"
oc offer add --company "ByteDance" --position "Backend" --base 35000 --months 16
oc question generate --kb 1 --count 10
```

### Configuration

Config lives at `~/.offerpilot/config.json` by default. Override the data directory with `OFFERPILOT_DATA`.
When API auth is enabled in the browser, the frontend sends `X-OfferPilot-Token` from local storage key `offerpilot.auth_token`.

```json
{
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "local_port": 8080,
  "runtime_mode": "local",
  "auth_enabled": false,
  "auth_token": "local-secret",
  "log_level": "INFO",
  "skills": [
    {
      "id": "resume-coach",
      "label": "Resume Coach",
      "version": "0.1.0",
      "source": "file:///skills/resume-coach",
      "trusted": true,
      "enabled": true
    }
  ],
  "active_provider_id": "default",
  "providers": [
    {
      "id": "default",
      "label": "Default",
      "provider": "openai",
      "api_key": "sk-xxx",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "enabled": true
    }
  ]
}
```

### Stack

| Component | Technology |
| --- | --- |
| Backend | Python 3.10+, FastAPI, Typer |
| Data | SQLite, local file storage |
| Frontend | React 18, Ant Design, Vite |
| AI | LiteLLM, bring-your-own API key, confirmed write tools |
| Deploy | Docker multi-stage build |

### Roadmap

- Skill execution sandbox, manifest validation, and package provenance.
- Skill execution sandbox and trust policy enforcement.
- Embedding rerankers for knowledge search.
- LangGraph checkpoint / interrupt workflows.
- Background wakeup scheduler.
- Auth token rotation.
- Screenshot-level responsive UI QA.

### License

[AGPLv3](LICENSE). If you provide a modified OfferPilot over a network, AGPLv3 requires making the corresponding source available to those users.
