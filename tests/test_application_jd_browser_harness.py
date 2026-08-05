from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "scripts" / "application-jd-real-ai-browser-harness.ps1"
AUDIT = ROOT / "scripts" / "browser-network-audit.py"


def _load_browser_audit():
    spec = importlib.util.spec_from_file_location("browser_network_audit", AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_application_jd_harness_parses_and_uses_explicit_stage_contract() -> None:
    command = (
        "$errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{HARNESS}', [ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { exit 1 }; Write-Output 'parse-ok'"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "parse-ok" in result.stdout
    assert result.stdout.isascii()


def test_application_jd_harness_fails_closed_without_browser_cdp() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HARNESS),
            "-Stage",
            "jd-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "APPLICATION_JD_CDP_URL" in output
    assert "Application JD browser acceptance failed." in output


def test_browser_audit_keeps_url_application_id_authoritative() -> None:
    module = _load_browser_audit()
    audit = module.BrowserAudit(None, Path("audit.jsonl"), Path("stop"))
    audit.target_sessions["target"] = "session"
    audit.handle = io.StringIO()
    message = {
        "sessionId": "session",
        "params": {
            "request": {
                "method": "POST",
                "url": "http://127.0.0.1:8000/api/applications/10/job-description/versions",
                "postData": json.dumps({"application_id": 11, "jd_text": "JD"}),
            }
        },
    }

    asyncio.run(audit.record_request(message))

    record = json.loads(audit.handle.getvalue())
    assert record["request_context"]["application_id"] == 10
    assert record["request_context"]["payload_application_id"] == 11
