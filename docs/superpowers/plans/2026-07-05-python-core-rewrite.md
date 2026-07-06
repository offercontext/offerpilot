# Python Core Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python backend core for OfferPilot while preserving the current Go contract for startup, config, SQLite, Applications, dashboard, CLI, and the minimum AI write-confirmation loop.

**Architecture:** Use FastAPI for HTTP, Typer for CLI, SQLAlchemy Core/ORM for SQLite, and Pydantic v2 for API and tool schemas. Keep compatibility code small and explicit: repositories own SQL behavior, services own business defaults, API/CLI layers only translate inputs and outputs.

**Tech Stack:** Python 3.10+, uv, FastAPI, Uvicorn, Typer, SQLAlchemy 2.0, Pydantic v2, pytest, httpx, ruff, mypy.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Python package metadata, dependencies, scripts, pytest/ruff/mypy config |
| `src/offerpilot/config.py` | Data-dir resolution and config JSON load/save |
| `src/offerpilot/db.py` | SQLite engine/session setup, foreign-key pragma, idempotent schema creation |
| `src/offerpilot/models.py` | SQLAlchemy models for core tables used in phases 2-4 |
| `src/offerpilot/schemas.py` | Pydantic API schemas with snake_case fields |
| `src/offerpilot/repositories/applications.py` | Applications persistence and dashboard grouping |
| `src/offerpilot/api.py` | FastAPI app factory and core routes |
| `src/offerpilot/cli.py` | Typer CLI: `start`, `add`, `list`, `config` |
| `src/offerpilot/ai/types.py` | Provider-neutral message/tool types |
| `src/offerpilot/ai/tools.py` | Minimal tool registry for application read/write tools |
| `src/offerpilot/ai/agent.py` | Tool loop and pending action semantics |
| `tests/` | Contract tests for config, DB, API, CLI, and AI loop |

## Task 1: Python Package Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/offerpilot/__init__.py`
- Create: `tests/test_health.py`
- Create: `src/offerpilot/api.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_health_returns_ok():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_health.py -q`
Expected: FAIL because the Python package and `create_app` do not exist yet.

- [ ] **Step 3: Add package metadata and minimal app**

Create `pyproject.toml` with FastAPI, Typer, SQLAlchemy, Pydantic, Uvicorn, pytest, httpx, ruff, and mypy. Create `src/offerpilot/api.py` with `create_app()` returning a FastAPI app and `/api/health`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_health.py -q`
Expected: PASS.

## Task 2: Config And Data Directory

**Files:**
- Create: `src/offerpilot/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write config tests**

```python
from pathlib import Path

from offerpilot.config import Config, load_config, resolve_data_dir, save_config


def test_resolve_data_dir_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path / "custom"))

    assert resolve_data_dir() == tmp_path / "custom"


def test_load_missing_config_returns_defaults(tmp_path):
    cfg = load_config(tmp_path)

    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.model == "gpt-4o"
    assert cfg.local_port == 8080
    assert cfg.chat_auto_approve_writes is False


def test_save_and_load_config_round_trip(tmp_path):
    cfg = Config(api_key="sk-test", base_url="https://example.test/v1", model="model", local_port=9999, chat_auto_approve_writes=True)

    save_config(tmp_path, cfg)
    loaded = load_config(tmp_path)

    assert loaded == cfg
    assert (tmp_path / "config.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL because `offerpilot.config` does not exist.

- [ ] **Step 3: Implement config module**

Implement `Config` as a Pydantic model with Go-compatible defaults. `resolve_data_dir()` must prefer `OFFERPILOT_DATA`; otherwise use `Path.home() / ".offerpilot"`. `save_config()` must create the data dir and write `config.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

## Task 3: Applications SQLite Contract

**Files:**
- Create: `src/offerpilot/db.py`
- Create: `src/offerpilot/models.py`
- Create: `src/offerpilot/repositories/__init__.py`
- Create: `src/offerpilot/repositories/applications.py`
- Create: `tests/test_applications_repository.py`

- [ ] **Step 1: Write repository tests**

```python
from datetime import datetime, timezone

from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def test_create_and_list_applications_ordered_by_applied_at(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)

    older = repo.create(ApplicationCreate(company_name="A", position_name="Backend", applied_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    newer = repo.create(ApplicationCreate(company_name="B", position_name="Frontend", applied_at=datetime(2026, 2, 1, tzinfo=timezone.utc)))

    apps = repo.list()

    assert [app.id for app in apps] == [newer.id, older.id]
    assert apps[0].status == "applied"
    assert apps[0].source == "cli"


def test_dashboard_groups_by_status(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)
    repo.create(ApplicationCreate(company_name="A", position_name="Backend", status="interview"))
    repo.create(ApplicationCreate(company_name="B", position_name="Frontend", status="offer"))

    dashboard = repo.dashboard()

    assert dashboard["total"] == 2
    assert len(dashboard["board"]["interview"]) == 1
    assert len(dashboard["board"]["offer"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_applications_repository.py -q`
Expected: FAIL because DB/repository modules do not exist.

- [ ] **Step 3: Implement DB and repository**

Implement SQLite with SQLAlchemy, `PRAGMA foreign_keys=ON`, and `pool_size` compatible with a single SQLite writer. Create at least the `applications` table with Go-compatible columns and `idx_applications_status`. Repository methods: `create`, `list`, `get`, `update_full`, `delete`, `dashboard`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_applications_repository.py -q`
Expected: PASS.

## Task 4: Applications And Dashboard API

**Files:**
- Modify: `src/offerpilot/api.py`
- Create: `src/offerpilot/schemas.py`
- Create: `tests/test_applications_api.py`

- [ ] **Step 1: Write API contract tests**

```python
from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_create_application_defaults_and_list(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    created = client.post("/api/applications", json={"company_name": "ByteDance", "position_name": "Backend"}).json()
    listed = client.get("/api/applications").json()

    assert created["status"] == "applied"
    assert created["source"] == "web"
    assert listed[0]["company_name"] == "ByteDance"


def test_dashboard_groups_by_status(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    client.post("/api/applications", json={"company_name": "A", "position_name": "Backend", "status": "interview"})
    client.post("/api/applications", json={"company_name": "B", "position_name": "Frontend", "status": "offer"})

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["board"]["interview"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_applications_api.py -q`
Expected: FAIL because API routes are not implemented.

- [ ] **Step 3: Implement API routes**

Implement `/api/applications`, `/api/applications/{id}`, and `/api/dashboard` with Go-compatible status codes and error shape `{"error": string}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_applications_api.py -q`
Expected: PASS.

## Task 5: Core Typer CLI

**Files:**
- Create: `src/offerpilot/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI tests**

```python
from typer.testing import CliRunner

from offerpilot.cli import app


def test_add_and_list_application(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))
    runner = CliRunner()

    add_result = runner.invoke(app, ["add", "--company", "ByteDance", "--position", "Backend"])
    list_result = runner.invoke(app, ["list"])

    assert add_result.exit_code == 0
    assert "Added: ByteDance" in add_result.output
    assert list_result.exit_code == 0
    assert "ByteDance" in list_result.output


def test_config_masks_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["config", "--api-key", "sk-abcdef"])

    assert result.exit_code == 0
    assert "sk-a****ef" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL because CLI is not implemented.

- [ ] **Step 3: Implement CLI**

Implement Typer commands `add`, `list`, `config`, and `start`. `start` must initialize DB and run Uvicorn against the FastAPI app factory.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS.

## Task 6: AI Minimum Tool Loop

**Files:**
- Create: `src/offerpilot/ai/__init__.py`
- Create: `src/offerpilot/ai/types.py`
- Create: `src/offerpilot/ai/tools.py`
- Create: `src/offerpilot/ai/agent.py`
- Create: `tests/test_ai_agent.py`

- [ ] **Step 1: Write AI loop tests**

```python
import json

from offerpilot.ai.agent import PendingAction, run_turn, resume_after_confirm
from offerpilot.ai.types import Assistant, ToolCall


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


def test_write_tool_pauses_before_execution():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel([Assistant(tool_calls=[ToolCall(id="w1", name="update_application_status", args=json.dumps({"id": 1, "status": "offer"}))])])

    added, reply, pending = run_turn(model, registry, [], auto_approve=False, max_iter=8)

    assert reply == ""
    assert isinstance(pending, PendingAction)
    assert calls == []
    assert added[-1].tool_calls[0].name == "update_application_status"


def test_confirm_executes_pending_write():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or '{"ok":true}',
        }
    }
    model = ScriptedModel([Assistant(content="done")])
    pending = PendingAction(tool_call_id="w1", tool_name="update_application_status", args=json.dumps({"id": 1, "status": "offer"}), human="change status")

    added, reply, new_pending = resume_after_confirm(model, registry, [], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == [json.dumps({"id": 1, "status": "offer"})]
    assert reply == "done"
    assert new_pending is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_agent.py -q`
Expected: FAIL because AI modules are not implemented.

- [ ] **Step 3: Implement minimum AI loop**

Implement provider-neutral dataclasses/Pydantic models for `ToolCall`, `Message`, `Assistant`, `PendingAction`. Implement `run_turn` and `resume_after_confirm` with Go-compatible semantics: max 8, first tool only, write pause, auto-approve, unknown tool result, reject text.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_agent.py -q`
Expected: PASS.

## Final Verification For This Plan

- [ ] Run `uv run pytest -q`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run mypy src`.
- [ ] Run Go baseline again with `go test ./...`.
- [ ] Run frontend baseline again with `npm test` and `npm run build` in `web/`.
