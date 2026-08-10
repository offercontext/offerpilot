from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path


_AUDIT_PATH = Path(__file__).parents[1] / "scripts" / "browser-network-audit.py"
_SPEC = importlib.util.spec_from_file_location("browser_network_audit", _AUDIT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BrowserAudit = _MODULE.BrowserAudit


class _WebSocket:
    async def send(self, message: str) -> None:
        del message


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
