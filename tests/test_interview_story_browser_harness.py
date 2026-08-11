from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import zlib

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


def _run_harness(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_HARNESS_PATH),
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )


def _write_gray_png(path: Path, *, width: int = 1455, height: int = 1200) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    scanlines = (b"\x00" + b"\xff" * width) * height
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + chunk(b"IEND", b"")
    )


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


def test_browser_audit_never_reads_non_api_response_bodies(tmp_path: Path) -> None:
    async def run() -> tuple[list[str], list[dict[str, object]]]:
        audit = BrowserAudit(_WebSocket(), tmp_path / "audit.jsonl", tmp_path / "stop")
        audit.target_sessions["story-target"] = "story-session"
        handle = io.StringIO()
        audit.handle = handle
        await audit.record_request(
            _request("http://127.0.0.1:9999/assets/application.js", {})
        )
        calls: list[str] = []

        async def send(method: str, *_args, **_kwargs):
            calls.append(method)
            return {"result": {"body": "{}"}}

        audit.send = send  # type: ignore[method-assign]
        audit.response_finished[("story-session", "request-1")] = asyncio.Event()
        audit.response_finished[("story-session", "request-1")].set()
        await audit.record_response(
            {
                "sessionId": "story-session",
                "params": {"requestId": "request-1", "response": {"status": 200}},
            }
        )
        return calls, [json.loads(line) for line in handle.getvalue().splitlines()]

    calls, records = asyncio.run(run())

    assert calls == []
    assert records[-1]["response_body_status"] == "not_requested"


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
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-stories?status=active&query="},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories?status=active&query=", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-story-sources"},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-story-sources", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": ui_context},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": ui_context, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 11},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals/11/confirm", "response_status": 201, "response_body_status": "captured", "response_story_id": 101, "response_story_version_id": 201},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories/101/versions/201", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-stories?status=active&query="},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories?status=active&query=", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "GET", "url": f"{base_url}/api/interview-story-sources?review_note_id=4"},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-story-sources?review_note_id=4", "response_status": 200, "response_body_status": "captured"},
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": pilot_context},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": pilot_context, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 12},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals/12/confirm", "response_status": 201, "response_body_status": "captured", "response_story_id": 102, "response_story_version_id": 202},
        {"kind": "browser_response", "method": "GET", "url": f"{base_url}/api/interview-stories/102/versions/202", "response_status": 200, "response_body_status": "captured"},
    ]
    for index, record in enumerate(audit_records, 1):
        record["observed_at_ns"] = 1_000_000 + index * 1_000
    audit_path = tmp_path / "story-audit.jsonl"
    audit_path.write_text("\n".join(json.dumps(record) for record in audit_records) + "\n", encoding="utf-8")

    success = _run_harness("-ValidateAudit", "-AuditPath", str(audit_path), "-ExpectedBaseUrl", base_url)
    assert success.returncode == 0, success.stderr

    missing_pilot_source = [
        record for record in audit_records if not record["url"].startswith(f"{base_url}/api/interview-story-sources?")
    ]
    audit_path.write_text("\n".join(json.dumps(record) for record in missing_pilot_source) + "\n", encoding="utf-8")
    failure = _run_harness("-ValidateAudit", "-AuditPath", str(audit_path), "-ExpectedBaseUrl", base_url)
    assert failure.returncode != 0
    assert "source picker" in (failure.stdout + failure.stderr)

    failed_source_response = [dict(record) for record in audit_records]
    pilot_source_response = next(
        record for record in failed_source_response
        if record["kind"] == "browser_response" and record["url"].startswith(f"{base_url}/api/interview-story-sources?")
    )
    pilot_source_response["response_status"] = 500
    audit_path.write_text("\n".join(json.dumps(record) for record in failed_source_response) + "\n", encoding="utf-8")
    failed_read = _run_harness("-ValidateAudit", "-AuditPath", str(audit_path), "-ExpectedBaseUrl", base_url)
    assert failed_read.returncode != 0
    assert "source picker" in (failed_read.stdout + failed_read.stderr)

    auditor_failure = _run_harness(
        "-ValidateAudit", "-AuditPath", str(audit_path), "-ExpectedBaseUrl", base_url, "-AuditorExitCode", "7"
    )
    assert auditor_failure.returncode != 0
    assert "Browser auditor failed with exit code 7" in (auditor_failure.stdout + auditor_failure.stderr)

    chat_write = [*audit_records, {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/chat"}]
    audit_path.write_text("\n".join(json.dumps(record) for record in chat_write) + "\n", encoding="utf-8")
    chat_failure = _run_harness("-ValidateAudit", "-AuditPath", str(audit_path), "-ExpectedBaseUrl", base_url)
    assert chat_failure.returncode != 0
    assert "chat writes" in (chat_failure.stdout + chat_failure.stderr)


def test_story_browser_harness_allows_one_bounded_repair_per_entrypoint_and_rejects_more(tmp_path: Path) -> None:
    audit = tmp_path / "provider-audit.jsonl"
    browser_audit = tmp_path / "browser-audit.jsonl"
    allowlist = tmp_path / "providers.json"
    allowlist.write_text(json.dumps([{"Tuple": "https://provider.example:443"}]), encoding="utf-8")
    base_url = "http://127.0.0.1:9999"
    browser_records = [
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": {"entrypoint": "ui"}, "observed_at_ns": 1_000},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/interview-story-proposals", "request_context": {"entrypoint": "ui"}, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 11, "observed_at_ns": 2_000},
        {"kind": "browser_request", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": {"entrypoint": "pilot"}, "observed_at_ns": 3_000},
        {"kind": "browser_response", "method": "POST", "url": f"{base_url}/api/pilot/interview-story-proposals", "request_context": {"entrypoint": "pilot"}, "response_status": 201, "response_body_status": "captured", "response_proposal_id": 12, "observed_at_ns": 4_000},
    ]
    browser_audit.write_text("\n".join(json.dumps(record) for record in browser_records) + "\n", encoding="utf-8")
    normal_and_repaired = [
        {"kind": "provider_proxy_connect", "scheme": "https", "host": "provider.example", "port": 443, "status": "connected", "observed_at_ns": timestamp}
        for timestamp in (1_200, 1_800, 3_200, 3_800)
    ]
    audit.write_text("\n".join(json.dumps(record) for record in normal_and_repaired) + "\n", encoding="utf-8")

    accepted = _run_harness(
        "-ValidateProviderEgress", "-ProviderAuditPath", str(audit), "-ProviderAllowlistPath", str(allowlist),
        "-BrowserAuditPath", str(browser_audit), "-ExpectedBaseUrl", base_url,
    )
    assert accepted.returncode == 0, accepted.stderr

    audit.write_text("\n".join(json.dumps(record) for record in [*normal_and_repaired, normal_and_repaired[0]]) + "\n", encoding="utf-8")
    rejected = _run_harness(
        "-ValidateProviderEgress", "-ProviderAuditPath", str(audit), "-ProviderAllowlistPath", str(allowlist),
        "-BrowserAuditPath", str(browser_audit), "-ExpectedBaseUrl", base_url,
    )
    assert rejected.returncode != 0
    assert "two to four" in (rejected.stdout + rejected.stderr)

    ui_overflow = [
        {"kind": "provider_proxy_connect", "scheme": "https", "host": "provider.example", "port": 443, "status": "connected", "observed_at_ns": timestamp}
        for timestamp in (1_100, 1_500, 1_900, 3_500)
    ]
    audit.write_text("\n".join(json.dumps(record) for record in ui_overflow) + "\n", encoding="utf-8")
    unbalanced = _run_harness(
        "-ValidateProviderEgress", "-ProviderAuditPath", str(audit), "-ProviderAllowlistPath", str(allowlist),
        "-BrowserAuditPath", str(browser_audit), "-ExpectedBaseUrl", base_url,
    )
    assert unbalanced.returncode != 0
    assert "Story ui flow" in (unbalanced.stdout + unbalanced.stderr)


def test_story_browser_harness_records_a_single_viewport_screenshot_matrix(tmp_path: Path) -> None:
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    names = [
        "01-story-library.png", "02-source-picker.png", "03-source-preview.png", "04-generated-draft.png",
        "05-confirmation.png", "06-history.png", "07-source-changed.png", "08-pilot-entry.png",
        "09-pilot-source-choice.png", "10-pilot-history.png",
    ]
    for name in names:
        _write_gray_png(screenshots / name)
    manifest = tmp_path / "matrix.json"

    result = _run_harness(
        "-ValidateScreenshotMatrix", "-ScreenshotDirectory", str(screenshots), "-ScreenshotManifestPath", str(manifest)
    )

    assert result.returncode == 0, result.stderr
    matrix = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(matrix) == 10
    assert all(item["width"] == 1455 and item["height"] == 1200 and len(item["sha256"]) == 64 for item in matrix)


def test_story_browser_harness_starts_audited_chromium_before_honoring_completion_signal(tmp_path: Path) -> None:
    source_data = tmp_path / "configured-data"
    source_data.mkdir()
    (source_data / "config.json").write_text(
        json.dumps(
            {
                "active_provider_id": "browser-harness-stub",
                "providers": [
                    {
                        "id": "browser-harness-stub",
                        "enabled": True,
                        "base_url": "https://provider.example",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    completion_signal = tmp_path / "complete.signal"
    completion_signal.touch()
    session_state = tmp_path / "story-browser-session.json"
    environment = dict(os.environ)
    environment["OFFERPILOT_DATA"] = str(source_data)

    result = _run_harness(
        "-CompletionSignalPath", str(completion_signal), "-SessionStatePath", str(session_state), env=environment,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Dedicated browser target is ready" in output
    assert "Browser did not execute exactly one UI and one Pilot Story proposal sequence" in output
    state = json.loads(session_state.read_text(encoding="utf-8"))
    assert state["base_url"].startswith("http://127.0.0.1:")
    assert state["cdp_url"].startswith("http://127.0.0.1:")
