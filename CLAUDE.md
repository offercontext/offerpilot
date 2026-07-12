# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 与其他文档的优先级

- `AGENTS.md` 是跨 Agent 的施工协议 SSOT。Claude Code 必须先读 `AGENTS.md`，特别是 §5 代码改动规则、§6 领域红线、§7 验证与 Code Review、§10 最终汇报格式。
- `docs/architecture/documentation-rules.md` 是文档规范 SSOT。写/改任何 `.md` 前必读；触发 `.claude/hooks/pre-commit-doc-check.sh`。
- `docs/python-rewrite-contract.md` 是 REST/SQLite/CLI 行为兼容契约。改动 API、数据库 schema、CLI 输出前先查这份契约。
- `docs/p0-release-checklist.md` 是 v0.1 发布门禁清单。
- 飞书 wiki 是产品事实源（PRD / ADR / Check 表），入口见 `AGENTS.md` §4。
- `README.md` 是对外公开承诺，不是内部最新口径。除非安装/启动/命令行为变化，否则不要顺手改。

## 常用命令

### 环境与安装

```bash
uv sync                              # 安装 Python 依赖
cd web && npm install                # 安装前端依赖
uv tool install --force .            # 以工具方式安装 oc CLI
```

### 开发运行

```bash
uv run oc start                      # 启动后端 + 静态前端（默认 :8080）
uv run oc start --port 18765         # 指定端口
cd web && npm run dev                # 仅启前端 dev server（:5173，代理 /api → :8080）
```

### 测试 / Lint / 类型

```bash
uv run pytest                        # 全量测试
uv run pytest tests/test_chat_api.py # 单个测试文件
uv run pytest tests/test_chat_api.py::test_name   # 单个测试用例
uv run pytest -k keyword             # 按名匹配
uv run ruff check .                  # Python lint
uv run ruff check . --fix            # 自动修复
uv run mypy src                      # 严格类型检查（pyproject.toml 开启 strict）
cd web && npm test -- --run          # 前端 vitest 全量
cd web && npm test -- --run src/path/to/file.test.ts
cd web && npm run build              # tsc -b && vite build
```

### 发布门禁

```bash
scripts/release-gate.sh              # 完整非 Docker 门禁：pytest+ruff+mypy+npm test+npm build+local-smoke+oc verify
scripts/release-gate.sh --real-ai    # 追加真实 provider 验收
scripts/release-gate.sh --docker     # 追加 Docker smoke（需 Docker 可用）
scripts/release-gate.sh --install    # 追加 install-gate（验证 uv tool install 路径）
scripts/local-smoke.sh               # 仅本地 HTTP smoke：build → oc start → curl health → oc smoke
uv run oc verify --profile local --static-dir web/dist       # 真实 HTTP 接口验收
uv run oc verify --profile real-ai --static-dir web/dist     # 真实 AI provider 写确认流验收
uv run oc smoke --static-dir web/dist                        # 内置核心 smoke（health/SPA/投递/Pilot 确认流）
```

### CLI 快速参考（`oc` 是统一入口）

```bash
oc add --company "ByteDance" --position "Backend"   # 添加投递
oc list --status interview                          # 按 status 过滤
oc config --api-key sk-xxx --model gpt-4o           # 配置 AI provider
oc config --runtime-mode local --auth --log-level debug
oc skill add|trust|enable|list                      # Skill 注册/信任/启用
oc wakeup add|list|dispatch-due                     # 调度唤醒队列
oc resume|note|offer|question ...                   # 各子领域操作
```

## 高层架构

### 进程与数据流

```
oc CLI (Typer) ──┬─ start → uvicorn(FastAPI app) → /api/* + SPA fallback
                 ├─ smoke / verify → 启动真实 HTTP 服务跑验收
                 └─ 子命令 → 直接走 repository 层
```

- 单一 SQLite 数据库文件：`$OFFERPILOT_DATA/data.db`（默认 `~/.offerpilot/`）
- 配置：`$OFFERPILOT_DATA/config.json`（chmod 0600）
- 日志：`$OFFERPILOT_DATA/logs/offerpilot.log`（JSONL）
- 前端构建产物 `web/dist/` 由 FastAPI 在 `/` 直接serve（非 `/api` 路径回退到 SPA index.html）

### 后端分层（`src/offerpilot/`）

| 层 | 职责 | 关键文件 |
|---|---|---|
| CLI | 用户入口，Typer 子命令 | `cli.py` |
| API | 所有 HTTP 路由（89 个）+ CORS/auth middleware + SPA fallback | `api.py`（单文件 ~4000 行） |
| Repository | 每个领域一个，封装 SQLAlchemy 查询 | `repositories/*.py` |
| Model | SQLAlchemy ORM（`Base.metadata.create_all` + 启动时 `_ensure_column` 加列） | `models.py`, `db.py` |
| Schema | Pydantic 输入/输出模型 | `schemas.py` |
| AI Agent | LangGraph runtime + HITL pending/confirm + interrupt/resume | `ai/agent.py`, `ai/client.py`, `ai/tools.py`, `ai/workflows.py` |
| 配置 | provider profile / runtime_mode / auth / log_level | `config.py` |
| Skill | manifest 注册 + 信任模型（不执行包代码） | `skills.py` |
| Smoke | 内置 smoke harness（启动真实 HTTP 服务） | `smoke.py` |
| 诊断 | JSONL 日志写入/读取 | `diagnostics.py` |
| SSE | streaming chat 事件封装 | `sse.py` |

### AI Agent 关键约定

- `LangGraphAgentRunner` 用 SqliteSaver 持久化 checkpoint；pending 写操作通过 `interrupt()` 暂停，由 `/api/chat/confirm` 恢复
- 写工具必须保留 HITL 确认，除非 `chat_auto_approve_writes=true`（默认 false）
- Active provider 失败自动尝试 fallback provider（`fallback_provider_id`），事件写日志
- `provider_blocks` 字段保留 provider 特定块（如 reasoning content），不可丢弃
- AI tool schemas 必须暴露当前产品语言，不要留旧内部命名

### 前端结构（`web/src/`）

- `App.tsx` → `AuthGate` → `AppShell`（布局 + 视图切换）
- 模块导航 `layout/navigation.ts`：8 个一级模块（工作台 / 简历 / 练习 / 投递 / 面试 / 知识库 / Pilot / 设置），投递模块下设看板/列表/日历/Offer/提醒 5 个 tab
- 视图组件 `components/*.tsx`，按功能聚合（如 `ApplicationDetail.tsx`、`KanbanBoard.tsx`）
- `services/*.ts` 是 axios 客户端层，统一 `baseURL: /api`，请求拦截器注入 `X-OfferPilot-Token`（来自 localStorage `offerpilot.auth_token`）
- `features/<area>/` 用于较新的模块化视图（dashboard、onboarding、pipeline、reminders、MockStudio 等）
- React Query 做数据层；视图懒加载（`lazy()` + ErrorBoundary）
- 路径别名 `@/*` → `src/*`

### 领域状态机

- 投递生命周期（`application_status.py`）：`pending → applied → written_test → interview → offer → closed`
- 旧状态别名自动归一：`assessment → written_test`、`eliminated/rejected → closed`
- 事件类型（`ai/tools.py`）：`written_test | interview | offer_step | deadline | custom`；`assessment` 不是一级 event_type
- 对话上下文（`repositories/chat.py`）：`context_type ∈ {workspace, application, global}` + `context_ref`，不再使用旧 `offer_id`

### Schema 演进策略

- 无 Alembic；启动时 `Base.metadata.create_all` + `_ensure_column` 做加法迁移
- 每次加列记录到 `schema_migrations` 表
- 不兼容的 v0.1 表（旧 `events`、旧 `knowledge_bases` 关联表、旧 `resumes` 二进制模型）由 `_reset_incompatible_v01_tables` 在启动时清表重建——本地开发数据可破坏性迁移，但必须在最终汇报中说明

### Docker

多阶段构建（`Dockerfile`）：node:20-alpine 构建 `web/dist` → python:3.12-slim 运行时，`OFFERPILOT_DATA=/data`，暴露 8080 端口和 `/data` volume。

## 项目特定约束

### 必读红线（详见 `AGENTS.md` §6）

- 事件表/API 语义是 `application_events`，不要重新引入旧 `events` 作为兼容层
- `event_type + subtype + tags` 是事件语义契约；`assessment` 不是一级 `event_type`
- 对话上下文用 `context_type/context_ref`，不要扩展旧 `offer_id` 字段
- 投递场景用 `context_type=application, context_ref=<application_id>`
- v0.1/v0.2/v0.3 各自范围边界见 `AGENTS.md` §6，不要把未来版本能力承诺到当前版本

### 测试约定

- 后端测试位于 `tests/`，每个 API/领域一个文件，文件名 `test_<area>_api.py` 或 `test_<area>_repository.py`
- 前端测试与源码同目录，文件名 `*.test.ts(x)`
- 测试使用真实 SQLite（临时目录），不 mock repository
- `oc smoke` 和 `oc verify --profile local` 是发版必跑

### 文档规范触发

写/改文档前必须读 `docs/architecture/documentation-rules.md`。核心约束：

- 根 `AGENTS.md` ≤ 300 行；`docs/` 下非 ADR 文档 ≤ 300 行；ADR ≤ 800 行
- 每个事实只能在一处定义（SSOT）
- 新增 ADR 必填段：Context / Decision / Consequences / Alternatives Considered（≥ 2 个备选）
- 不要新建 `docs/<random>/` 目录，统一放 `docs/architecture/` 或 `docs/superpowers/`
- 不留 placeholder（`TODO`、`待补充`）

### 分支命名（详见 `AGENTS.md` §3）

`<type>/<yyyymmdd>-<name>`，type ∈ {feat, fix, docs, chore, refactor, test}。分支名不含 Agent 名。

### 飞书文档操作

涉及飞书 wiki / docs / whiteboard 时，先 `lark-cli skills read lark-doc` 读对应 skill；str_replace 雷区、画板跨文档复用、Mermaid subgraph ID 等约束见 `AGENTS.md` §9。

## 最终汇报要求

实现类任务完成时（见 `AGENTS.md` §10）必须包含：改了什么 / 破坏性变化 / 剩余风险 / 验证结果。测试没跑或跑不了要说明原因。
