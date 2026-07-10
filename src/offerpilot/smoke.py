from __future__ import annotations

from contextlib import contextmanager
import gc
import json
from dataclasses import dataclass
from pathlib import Path
import socket
import tempfile
import threading
import time
from typing import Any

import httpx
import uvicorn

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.api import create_app


@dataclass(frozen=True)
class SmokeStep:
    name: str
    detail: str


@dataclass(frozen=True)
class SmokeReport:
    ok: bool
    steps: list[SmokeStep]


class _SmokeChatModel(ChatModel):
    def __init__(self, application_id: int):
        self._application_id = application_id

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        if messages and messages[-1].role == "tool":
            return Assistant(content="smoke complete")
        user_message = _latest_user_message(messages)
        if "create application card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="smoke-create-application-card",
                        name="create_application",
                        args=json.dumps(
                            {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        if "create event card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="smoke-create-event-card",
                        name="create_application_event",
                        args=json.dumps(
                            {
                                "application_id": self._application_id,
                                "event_type": "written_test",
                                "subtype": "assessment",
                                "scheduled_at": "2026-07-10T19:00:00+08:00",
                                "duration_minutes": 30,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        return Assistant(
            tool_calls=[
                ToolCall(
                    id="smoke-write-1",
                    name="update_application_status",
                    args=json.dumps({"id": self._application_id, "status": "offer"}),
                )
            ]
        )


class _MutableSmokeChatModel(ChatModel):
    def __init__(self) -> None:
        self.application_id: int | None = None

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        if self.application_id is None:
            raise RuntimeError("smoke application id was not initialized")
        if messages and messages[-1].role == "tool":
            return Assistant(content="http smoke complete")
        user_message = _latest_user_message(messages)
        if "create application card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="http-smoke-create-application-card",
                        name="create_application",
                        args=json.dumps(
                            {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        if "create event card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="http-smoke-create-event-card",
                        name="create_application_event",
                        args=json.dumps(
                            {
                                "application_id": self.application_id,
                                "event_type": "written_test",
                                "subtype": "assessment",
                                "scheduled_at": "2026-07-10T19:00:00+08:00",
                                "duration_minutes": 30,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        return Assistant(
            tool_calls=[
                ToolCall(
                    id="http-smoke-write-1",
                    name="update_application_status",
                    args=json.dumps({"id": self.application_id, "status": "offer"}),
                )
            ]
        )


def _latest_user_message(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _assert_create_application_card(pending_body: dict[str, Any]) -> None:
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("create application card smoke did not request confirmation")
    action = pending_body.get("pending_action", {})
    if action.get("tool_name") != "create_application":
        raise RuntimeError("create application card smoke requested the wrong tool")
    if action.get("human") != "新建投递：牛客网 - agent开发":
        raise RuntimeError("create application card smoke lost the human-readable title")
    expected_args = {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"}
    if action.get("args") != expected_args:
        raise RuntimeError("create application card smoke lost the proposed application fields")
    if action.get("target") != {
        "id": "application-draft-牛客网-agent开发",
        "kind": "application",
        "title": "牛客网",
        "meta": "agent开发 · applied",
        "source": "pending_action",
    }:
        raise RuntimeError("create application card smoke lost target record details")
    if action.get("proposed_changes") != [
        {"field": "company_name", "before": "", "after": "牛客网"},
        {"field": "position_name", "before": "", "after": "agent开发"},
        {"field": "status", "before": "", "after": "applied"},
    ]:
        raise RuntimeError("create application card smoke lost proposed record changes")


def _assert_create_event_card(pending_body: dict[str, Any], application_id: int) -> None:
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("create event card smoke did not request confirmation")
    action = pending_body.get("pending_action", {})
    if action.get("tool_name") != "create_application_event":
        raise RuntimeError("create event card smoke requested the wrong tool")
    if action.get("human") != "新建日程：笔试 · 2026-07-10 19:00 · 30 分钟":
        raise RuntimeError("create event card smoke lost the human-readable schedule title")
    if action.get("target") != {
        "id": f"application-event-draft-{application_id}",
        "kind": "application_event",
        "title": "笔试",
        "meta": "2026-07-10 19:00 · 30 分钟",
        "source": "pending_action",
    }:
        raise RuntimeError("create event card smoke lost target schedule details")
    if action.get("proposed_changes") != [
        {"field": "event_type", "before": "", "after": "written_test"},
        {"field": "subtype", "before": "", "after": "assessment"},
        {"field": "scheduled_at", "before": "", "after": "2026-07-10T19:00:00+08:00"},
        {"field": "duration_minutes", "before": "", "after": 30},
    ]:
        raise RuntimeError("create event card smoke lost proposed schedule changes")
    evidence = action.get("evidence") or []
    if not evidence or evidence[0].get("id") != f"application-{application_id}":
        raise RuntimeError("create event card smoke lost application evidence")


def _reject_pending_chat_action(client: Any, pending_body: dict[str, Any], step: str) -> None:
    rejected = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending_body["conversation_id"], "approved": False},
    )
    _assert_status(rejected.status_code, 200, step)


def run_core_smoke(data_dir: Path, static_dir: Path | None = None) -> SmokeReport:
    from fastapi.testclient import TestClient

    steps: list[SmokeStep] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    health = client.get("/api/health")
    _assert_status(health.status_code, 200, "health")
    steps.append(SmokeStep("health", "api health returned ok"))

    if static_dir is not None:
        spa = client.get("/applications/smoke")
        _assert_status(spa.status_code, 200, "spa")
        if "root" not in spa.text:
            raise RuntimeError("spa fallback did not serve index.html")
        steps.append(SmokeStep("spa", "spa fallback served index.html"))

    created = client.post(
        "/api/applications",
        json={"company_name": "Smoke Co", "position_name": "Backend", "status": "applied"},
    )
    _assert_status(created.status_code, 201, "create_application")
    application = created.json()
    application_id = int(application["id"])
    steps.append(SmokeStep("create_application", f"created application #{application_id}"))

    chat_client = TestClient(
        create_app(
            data_dir=data_dir,
            static_dir=static_dir,
            chat_model=_SmokeChatModel(application_id),
        )
    )
    pending = chat_client.post("/api/chat", json={"message": "move to offer", "conversation_id": 0})
    _assert_status(pending.status_code, 200, "chat_pending")
    pending_body = pending.json()
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("chat did not request confirmation")
    before_confirm = client.get(f"/api/applications/{application_id}").json()
    if before_confirm["status"] != "applied":
        raise RuntimeError("write tool mutated before confirmation")
    steps.append(SmokeStep("chat_pending", "write action paused for confirmation"))

    confirmed = chat_client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending_body["conversation_id"], "approved": True},
    )
    _assert_status(confirmed.status_code, 200, "confirm_action")
    after_confirm = client.get(f"/api/applications/{application_id}").json()
    if after_confirm["status"] != "offer":
        raise RuntimeError("confirmed write did not update application")
    steps.append(SmokeStep("confirm_action", "confirmed write updated application"))

    conversations = chat_client.get("/api/chat/conversations").json()
    if conversations[0]["pending_action"] is not None:
        raise RuntimeError("pending action was not cleared")
    steps.append(SmokeStep("pending_cleared", "pending action cleared after confirmation"))

    _run_chat_card_regression_smoke(chat_client, steps, application_id)

    return SmokeReport(ok=True, steps=steps)


def run_http_smoke(
    data_dir: Path,
    static_dir: Path | None = None,
    *,
    real_ai: bool = False,
) -> SmokeReport:
    steps: list[SmokeStep] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    _run_unconfigured_chat_smoke(static_dir, steps)

    local_model = None if real_ai else _MutableSmokeChatModel()
    app = create_app(data_dir=data_dir, static_dir=static_dir, chat_model=local_model)
    with _running_server(app) as base_url:
        with httpx.Client(base_url=base_url, timeout=60.0) as client:
            health = client.get("/api/health")
            _assert_status(health.status_code, 200, "http_health")
            steps.append(SmokeStep("http_health", "GET /api/health returned ok"))

            settings = client.get("/api/settings")
            _assert_status(settings.status_code, 200, "http_settings")
            settings_body = settings.json()
            if real_ai and not bool(settings_body.get("has_api_key")):
                raise RuntimeError("real-ai profile requires a configured API key")
            steps.append(SmokeStep("http_settings", "GET /api/settings returned current AI settings"))

            if static_dir is not None:
                spa = client.get("/applications/smoke")
                _assert_status(spa.status_code, 200, "http_spa")
                if "root" not in spa.text:
                    raise RuntimeError("http_spa did not serve index.html")
                steps.append(SmokeStep("http_spa", "GET /applications/smoke served the SPA fallback"))

            marker = str(int(time.time() * 1000))
            company = f"AI HTTP Smoke {marker}"
            created = client.post(
                "/api/applications",
                json={
                    "company_name": company,
                    "position_name": "Verification Engineer",
                    "status": "applied",
                    "source": "smoke",
                },
            )
            _assert_status(created.status_code, 201, "http_create_application")
            application_id = int(created.json()["id"])
            if local_model is not None:
                local_model.application_id = application_id
            steps.append(SmokeStep("http_create_application", f"POST /api/applications created #{application_id}"))

            try:
                listed = client.get("/api/applications", params={"status": "applied"})
                _assert_status(listed.status_code, 200, "http_list_applications")
                if not any(item.get("id") == application_id for item in listed.json()):
                    raise RuntimeError("created application was not returned by list endpoint")
                steps.append(SmokeStep("http_list_applications", "GET /api/applications returned created record"))

                _run_resume_http_smoke(client, steps)
                _run_application_event_http_smoke(client, steps, application_id)

                if real_ai:
                    _run_real_ai_write_smoke(client, steps, company, application_id)
                else:
                    _run_deterministic_chat_smoke(client, steps, application_id)
                    _run_chat_card_regression_smoke(client, steps, application_id, step_prefix="http_")
            finally:
                cleanup = client.delete(f"/api/applications/{application_id}")
                _assert_status(cleanup.status_code, 200, "http_cleanup")
                steps.append(SmokeStep("http_cleanup", f"deleted smoke application #{application_id}"))

    return SmokeReport(ok=True, steps=steps)


def _run_unconfigured_chat_smoke(static_dir: Path | None, steps: list[SmokeStep]) -> None:
    with tempfile.TemporaryDirectory(prefix="offerpilot-smoke-unconfigured-", ignore_cleanup_errors=True) as temp_dir:
        app = create_app(data_dir=Path(temp_dir), static_dir=static_dir)
        with _running_server(app) as base_url:
            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})
                _assert_status(response.status_code, 503, "http_unconfigured_chat")
                if "AI is not configured" not in response.json().get("error", ""):
                    raise RuntimeError("unconfigured chat did not return a clear AI setup error")
                steps.append(SmokeStep("http_unconfigured_chat", "POST /api/chat returned setup guidance without API key"))
        del app
        gc.collect()


def _run_resume_http_smoke(client: httpx.Client, steps: list[SmokeStep]) -> None:
    empty_content = {
        "career_intent": {"target_roles": [], "target_locations": []},
        "contact": {},
        "education": [],
        "experience": [],
        "projects": [],
        "skills": [],
        "raw_text": "",
    }
    created = client.post(
        "/api/resumes",
        json={"title": "HTTP Smoke Resume Draft", "source": "dialog", "content_json": empty_content},
    )
    _assert_status(created.status_code, 201, "http_resume_crud")
    resume_id = int(created.json()["id"])
    try:
        updated = client.patch(f"/api/resumes/{resume_id}", json={"title": "HTTP Smoke Resume Draft Updated"})
        _assert_status(updated.status_code, 200, "http_resume_crud")
        fetched = client.get(f"/api/resumes/{resume_id}")
        _assert_status(fetched.status_code, 200, "http_resume_crud")
        if fetched.json()["title"] != "HTTP Smoke Resume Draft Updated":
            raise RuntimeError("resume update was not reflected by get endpoint")
        listed = client.get("/api/resumes")
        _assert_status(listed.status_code, 200, "http_resume_crud")
        if not any(item.get("id") == resume_id for item in listed.json()):
            raise RuntimeError("created resume was not returned by list endpoint")
    finally:
        deleted = client.delete(f"/api/resumes/{resume_id}")
        _assert_status(deleted.status_code, 200, "http_resume_crud")
    steps.append(SmokeStep("http_resume_crud", "resume create, update, read, list, and delete endpoints worked"))


def _run_application_event_http_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    created = client.post(
        "/api/application-events",
        json={
            "application_id": application_id,
            "event_type": "interview",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 30,
            "notes": "http smoke",
        },
    )
    _assert_status(created.status_code, 201, "http_application_event_crud")
    event_id = int(created.json()["id"])
    try:
        updated = client.put(
            f"/api/application-events/{event_id}",
            json={
                "application_id": application_id,
                "event_type": "interview",
                "scheduled_at": "2026-07-11T10:00:00Z",
                "duration_minutes": 45,
                "notes": "http smoke updated",
            },
        )
        _assert_status(updated.status_code, 200, "http_application_event_crud")
        fetched = client.get(f"/api/application-events/{event_id}")
        _assert_status(fetched.status_code, 200, "http_application_event_crud")
        if fetched.json()["duration_minutes"] != 45:
            raise RuntimeError("application event update was not reflected by get endpoint")
        listed = client.get("/api/application-events", params={"application_id": application_id})
        _assert_status(listed.status_code, 200, "http_application_event_crud")
        if not any(item.get("id") == event_id for item in listed.json()):
            raise RuntimeError("created application event was not returned by list endpoint")
    finally:
        deleted = client.delete(f"/api/application-events/{event_id}")
        _assert_status(deleted.status_code, 200, "http_application_event_crud")
    steps.append(
        SmokeStep(
            "http_application_event_crud",
            "application event create, update, read, list, and delete endpoints worked",
        )
    )


def _run_chat_card_regression_smoke(
    client: Any,
    steps: list[SmokeStep],
    application_id: int,
    *,
    step_prefix: str = "",
) -> None:
    create_application_step = f"{step_prefix}chat_create_application_card"
    create_application_pending = client.post(
        "/api/chat",
        json={"message": "create application card regression", "conversation_id": 0},
    )
    _assert_status(create_application_pending.status_code, 200, create_application_step)
    _assert_create_application_card(create_application_pending.json())
    _reject_pending_chat_action(client, create_application_pending.json(), create_application_step)
    steps.append(SmokeStep(create_application_step, "create application confirmation card kept key fields"))

    create_event_step = f"{step_prefix}chat_create_event_card"
    create_event_pending = client.post(
        "/api/chat",
        json={"message": "create event card regression", "conversation_id": 0},
    )
    _assert_status(create_event_pending.status_code, 200, create_event_step)
    _assert_create_event_card(create_event_pending.json(), application_id)
    _reject_pending_chat_action(client, create_event_pending.json(), create_event_step)
    steps.append(SmokeStep(create_event_step, "create event confirmation card kept schedule details"))


def _run_deterministic_chat_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    pending = client.post("/api/chat", json={"message": "move to offer", "conversation_id": 0})
    _assert_status(pending.status_code, 200, "http_chat_pending")
    pending_body = pending.json()
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("http chat did not request confirmation")
    before_confirm = client.get(f"/api/applications/{application_id}").json()
    if before_confirm["status"] != "applied":
        raise RuntimeError("http write tool mutated before confirmation")
    steps.append(SmokeStep("http_chat_pending", "POST /api/chat paused write action for confirmation"))

    confirmed = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending_body["conversation_id"], "approved": True},
    )
    _assert_status(confirmed.status_code, 200, "http_confirm_action")
    after_confirm = client.get(f"/api/applications/{application_id}").json()
    if after_confirm["status"] != "offer":
        raise RuntimeError("http confirmed write did not update application")
    steps.append(SmokeStep("http_confirm_action", "POST /api/chat/confirm updated application"))

    conversations = client.get("/api/chat/conversations")
    _assert_status(conversations.status_code, 200, "http_pending_cleared")
    if conversations.json()[0]["pending_action"] is not None:
        raise RuntimeError("http pending action was not cleared")
    steps.append(SmokeStep("http_pending_cleared", "pending action cleared after confirmation"))


def _run_real_ai_write_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    company: str,
    application_id: int,
) -> None:
    prompt = (
        "Verification smoke: use the update_application_status tool to change the existing "
        f"application for {company} with id {application_id} to status offer. "
        "Do not create any other records."
    )
    pending = client.post("/api/chat", json={"message": prompt, "conversation_id": 0})
    _assert_status(pending.status_code, 200, "http_chat_pending")
    pending_body = pending.json()
    conversation_id = int(pending_body["conversation_id"])
    if pending_body.get("type") == "confirmation_required":
        if pending_body.get("pending_action", {}).get("tool_name") != "update_application_status":
            raise RuntimeError("real-ai smoke requested an unexpected pending tool")
        steps.append(SmokeStep("http_chat_pending", "real AI requested write confirmation"))
        confirmed = client.post(
            "/api/chat/confirm",
            json={"conversation_id": conversation_id, "approved": True},
        )
        _assert_status(confirmed.status_code, 200, "http_confirm_action")
    else:
        steps.append(SmokeStep("http_chat_pending", "real AI completed without pending confirmation"))

    updated = client.get(f"/api/applications/{application_id}")
    _assert_status(updated.status_code, 200, "http_confirm_action")
    if updated.json()["status"] != "offer":
        raise RuntimeError("real-ai smoke did not update the application to offer")
    steps.append(SmokeStep("http_confirm_action", "real AI write updated application"))

    conversations = client.get("/api/chat/conversations")
    _assert_status(conversations.status_code, 200, "http_pending_cleared")
    match = next((item for item in conversations.json() if item["id"] == conversation_id), None)
    if match is None:
        raise RuntimeError("real-ai smoke conversation was not listed")
    if match["pending_action"] is not None:
        raise RuntimeError("real-ai smoke pending action was not cleared")
    steps.append(SmokeStep("http_pending_cleared", "real AI conversation has no pending action"))


@contextmanager
def _running_server(app: Any) -> Any:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("http smoke server did not become ready")
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_status(actual: int, expected: int, step: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{step} returned status {actual}, expected {expected}")
