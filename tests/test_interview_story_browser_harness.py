from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path

import pytest


_AUDIT_PATH = Path(__file__).parents[1] / "scripts" / "browser-network-audit.py"
_SPEC = importlib.util.spec_from_file_location("browser_network_audit", _AUDIT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BrowserAudit = _MODULE.BrowserAudit


class _WebSocket:
    async def send(self, message: str) -> None:
        del message


class _ScriptedWebSocket:
    def __init__(self, *, attach_target: str | None = "story-target", reject_network: bool = False) -> None:
        self.attach_target = attach_target
        self.reject_network = reject_network
        self.messages: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

    async def send(self, message: str) -> None:
        command = json.loads(message)
        command_id = command["id"]
        method = command["method"]
        if method == "Target.createTarget":
            if self.attach_target is not None:
                await self.messages.put({
                    "method": "Target.attachedToTarget",
                    "params": {
                        "sessionId": "story-session",
                        "targetInfo": {"targetId": self.attach_target, "type": "page"},
                    },
                })
            await self.messages.put({"id": command_id, "result": {"targetId": "story-target"}})
            return
        if method == "Network.enable" and self.reject_network:
            await self.messages.put({"id": command_id, "error": {"message": "rejected"}})
            return
        await self.messages.put({"id": command_id, "result": {}})

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        message = await self.messages.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)


def _request(url: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "sessionId": "story-session",
        "params": {
            "requestId": "request-1",
            "request": {"method": "POST", "url": url, "postData": json.dumps(payload)},
        },
    }


def test_browser_audit_derives_story_entrypoint_and_hashes_retry_tokens(tmp_path: Path) -> None:
    async def run() -> list[dict[str, object]]:
        audit = BrowserAudit(_WebSocket(), tmp_path / "audit.jsonl", tmp_path / "stop")
        audit.target_sessions["story-target"] = "story-session"
        handle = io.StringIO()
        audit.handle = handle
        await audit.record_request(
            _request(
                "http://127.0.0.1:9999/api/interview-story-proposals",
                {"idempotency_key": "story-ui-audit-key-0001"},
            )
        )
        await audit.record_request(
            _request(
                "http://127.0.0.1:9999/api/pilot/interview-story-proposals",
                {"idempotency_key": "story-pilot-audit-key-01"},
            )
        )
        await audit.record_request(
            _request(
                "http://127.0.0.1:9999/api/interview-story-proposals/8/confirm",
                {"confirmation_token": "story-confirm-audit-01"},
            )
        )
        return [json.loads(line) for line in handle.getvalue().splitlines()]

    records = asyncio.run(run())

    assert records[0]["request_context"]["entrypoint"] == "ui"
    assert records[1]["request_context"]["entrypoint"] == "pilot"
    assert "idempotency_key_sha256" in records[0]["request_context"]
    assert "confirmation_token_sha256" in records[2]["request_context"]


def test_browser_audit_waits_for_loading_finished_before_capturing_workflow_response(tmp_path: Path) -> None:
    async def run() -> list[dict[str, object]]:
        audit = BrowserAudit(_WebSocket(), tmp_path / "audit.jsonl", tmp_path / "stop")
        audit.target_sessions["story-target"] = "story-session"
        handle = io.StringIO()
        audit.handle = handle
        await audit.record_request(
            _request(
                "http://127.0.0.1:9999/api/interview-story-proposals",
                {"idempotency_key": "story-ui-audit-key-0001"},
            )
        )
        sent = asyncio.Event()

        async def response_body(*_args, **_kwargs):
            sent.set()
            return {"result": {"body": json.dumps({"id": 8, "attempt_status": "ready"})}}

        audit.send = response_body  # type: ignore[method-assign]
        response = {
            "sessionId": "story-session",
            "params": {"requestId": "request-1", "response": {"status": 201}},
        }
        audit.response_finished[("story-session", "request-1")] = asyncio.Event()
        task = asyncio.create_task(audit.record_response(response))
        await asyncio.sleep(0)
        assert not sent.is_set()
        audit.response_finished[("story-session", "request-1")].set()
        await task
        return [json.loads(line) for line in handle.getvalue().splitlines()]

    records = asyncio.run(run())

    assert records[-1]["response_body_status"] == "captured"
    assert records[-1]["response_proposal_id"] == 8


def test_browser_audit_requires_the_dedicated_target_to_finish_network_enable(tmp_path: Path) -> None:
    async def run() -> None:
        websocket = _ScriptedWebSocket(attach_target="unowned-target")
        audit = BrowserAudit(websocket, tmp_path / "audit.jsonl", tmp_path / "stop")
        with pytest.raises(RuntimeError, match="dedicated browser target did not complete Network.enable"):
            await asyncio.wait_for(
                audit.run("http://127.0.0.1:9999", tmp_path / "ready", 0.05),
                timeout=1,
            )

    asyncio.run(run())


def test_browser_audit_fails_closed_when_network_enable_is_rejected(tmp_path: Path) -> None:
    async def run() -> None:
        websocket = _ScriptedWebSocket(reject_network=True)
        audit = BrowserAudit(websocket, tmp_path / "audit.jsonl", tmp_path / "stop")
        with pytest.raises(RuntimeError, match="Network.enable"):
            await asyncio.wait_for(
                audit.run("http://127.0.0.1:9999", tmp_path / "ready", 0.5),
                timeout=1,
            )

    asyncio.run(run())
