from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import subprocess

import pytest


_AUDIT_PATH = Path(__file__).parents[1] / "scripts" / "browser-network-audit.py"
_HARNESS_PATH = Path(__file__).parents[1] / "scripts" / "interview-story-real-ai-browser-harness.ps1"
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


def test_story_browser_harness_validates_each_entrypoint_sequence_and_auditor_exit(tmp_path: Path) -> None:
    base_url = "http://127.0.0.1:9999"
    ui_context = {"entrypoint": "ui", "idempotency_key_sha256": "ui-key"}
    pilot_context = {"entrypoint": "pilot", "idempotency_key_sha256": "pilot-key"}
    audit_records = [
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-stories"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-story-sources"},
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": ui_context},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": ui_context, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 11},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals/11/confirm", "response_status": 201, "response_body_status": "captured", "response_story_id": 101, "response_story_version_id": 201},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories/101/versions/201", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-stories"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-story-sources?review_note_id=4"},
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": pilot_context},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": pilot_context, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 12},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals/12/confirm", "response_status": 201, "response_body_status": "captured", "response_story_id": 102, "response_story_version_id": 202},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories/102/versions/202", "response_status": 200, "response_body_status": "captured"},
    ]
    audit_path = tmp_path / "story-audit.jsonl"
    audit_path.write_text("\n".join(json.dumps(record) for record in audit_records) + "\n", encoding="utf-8")

    success = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_HARNESS_PATH),
            "-ValidateAudit",
            "-AuditPath",
            str(audit_path),
            "-ExpectedBaseUrl",
            base_url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert success.returncode == 0, success.stderr

    missing_pilot_source = [
        record for record in audit_records if not record["url"].startswith(f"{base_url}/api/interview-story-sources?")
    ]
    audit_path.write_text("\n".join(json.dumps(record) for record in missing_pilot_source) + "\n", encoding="utf-8")
    failure = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_HARNESS_PATH),
            "-ValidateAudit",
            "-AuditPath",
            str(audit_path),
            "-ExpectedBaseUrl",
            base_url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failure.returncode != 0
    assert "source picker" in (failure.stdout + failure.stderr)

    auditor_failure = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_HARNESS_PATH),
            "-ValidateAudit",
            "-AuditPath",
            str(audit_path),
            "-ExpectedBaseUrl",
            base_url,
            "-AuditorExitCode",
            "7",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert auditor_failure.returncode != 0
    assert "Browser auditor failed with exit code 7" in (auditor_failure.stdout + auditor_failure.stderr)
