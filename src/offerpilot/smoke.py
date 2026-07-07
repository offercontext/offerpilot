from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

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
        self._turn = 0

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        self._turn += 1
        if self._turn == 1:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="smoke-write-1",
                        name="update_application_status",
                        args=json.dumps({"id": self._application_id, "status": "offer"}),
                    )
                ]
            )
        return Assistant(content="smoke complete")


def run_core_smoke(data_dir: Path, static_dir: Path | None = None) -> SmokeReport:
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

    return SmokeReport(ok=True, steps=steps)


def _assert_status(actual: int, expected: int, step: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{step} returned status {actual}, expected {expected}")
