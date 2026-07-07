# LangGraph Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-written chat loop internals with a LangGraph-backed runner while keeping the existing chat API, tool registry, HITL confirmation behavior, and persisted pending actions compatible.

**Architecture:** Add a focused LangGraph runner inside `src/offerpilot/ai/agent.py` behind the existing `run_turn` and `resume_after_confirm` functions. The graph has model, tool, pending-write interrupt, and final nodes, and uses a SQLite checkpointer path derived from the OfferPilot data directory when called from the API.

**Tech Stack:** Python, LangGraph, `langgraph-checkpoint-sqlite`, FastAPI, SQLAlchemy, pytest, Vitest.

---

### Task 1: Preserve Public Agent Contract With LangGraph Internals

**Files:**
- Modify: `src/offerpilot/ai/agent.py`
- Modify: `src/offerpilot/api.py`
- Test: `tests/test_ai_agent.py`
- Test: `tests/test_chat_api.py`

- [x] Add tests proving `run_turn` still returns assistant messages, tool messages, and `PendingAction` using the same public tuple contract.
- [x] Add a test proving a write tool pauses via a LangGraph interrupt payload instead of executing immediately.
- [x] Implement a `LangGraphAgentRunner` with a compiled `StateGraph`.
- [x] Keep `run_turn` as a compatibility wrapper around `LangGraphAgentRunner.run_turn`.
- [x] Keep `resume_after_confirm` as a compatibility wrapper around `LangGraphAgentRunner.resume_after_confirm`.

### Task 2: Add SQLite Checkpointer Wiring

**Files:**
- Modify: `src/offerpilot/ai/agent.py`
- Modify: `src/offerpilot/api.py`
- Test: `tests/test_chat_api.py`

- [x] Add a test proving chat confirmation can recover pending action state after app recreation and still execute the write.
- [x] Add `data_dir / "agent_checkpoints.sqlite"` checkpointer wiring in the API.
- [x] Pass stable thread ids such as `conversation:{conversation_id}` into LangGraph config.
- [x] Ensure checkpoint artifacts are local data files, not repository files.

### Task 3: Verify Compatibility and Release Gate

**Files:**
- Modify only if verification exposes bugs.

- [x] Run `uv run pytest -q`.
- [x] Run `uv run ruff check .`.
- [x] Run `uv run mypy src`.
- [x] Run `npm.cmd test`.
- [x] Run `npm.cmd run build`.
- [x] Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-smoke.ps1`.
- [x] Commit with `feat: AI add langgraph agent foundation`.
