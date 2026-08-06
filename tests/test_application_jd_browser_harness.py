from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "scripts" / "application-jd-real-ai-browser-harness.ps1"
AUDIT = ROOT / "scripts" / "browser-network-audit.py"
ALLOWLIST_FILE_ENV = "OFFERPILOT_APPLICATION_JD_ALLOWLIST_FILE"


def _changed_paths_since(root: Path, baseline: str) -> set[str]:
    changed: set[str] = set()
    for args in (
        [baseline, "--name-only"],
        [f"{baseline}..HEAD", "--name-only"],
    ):
        result = subprocess.run(
            ["git", "diff", *args], cwd=root, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        changed.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert staged.returncode == 0, staged.stderr
    changed.update(line.strip().replace("\\", "/") for line in staged.stdout.splitlines() if line.strip())
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert untracked.returncode == 0, untracked.stderr
    changed.update(line.strip().replace("\\", "/") for line in untracked.stdout.splitlines() if line.strip())
    return changed


def _approved_allowlist_from_environment() -> frozenset[str]:
    allowlist_file = os.environ.get(ALLOWLIST_FILE_ENV)
    if not allowlist_file:
        pytest.fail(f"release gate must supply {ALLOWLIST_FILE_ENV}")
    paths = tuple(
        line.strip().replace("\\", "/")
        for line in Path(allowlist_file).read_text(encoding="ascii").splitlines()
        if line.strip()
    )
    assert paths and len(paths) == len(set(paths)), "recorded implementation allowlist is invalid"
    return frozenset(paths)


def assert_application_jd_implementation_scope(root: Path, baseline: str) -> None:
    changed = _changed_paths_since(root, baseline)
    unexpected = sorted(changed - _approved_allowlist_from_environment())
    assert not unexpected, f"application JD implementation changed paths outside the tracked allowlist: {unexpected}"


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


def test_application_jd_harness_self_starts_and_cleans_temporary_browser() -> None:
    script = HARNESS.read_text(encoding="utf-8")
    assert "Start-TemporaryBrowser 'about:blank'" in script
    assert "--remote-debugging-port=$browserCdpPort" in script
    assert "--user-data-dir=$browserProfile" in script
    assert "Stop-Tree $browser" in script
    assert "APPLICATION_JD_CDP_URL" in script
    assert "browser-diagnostic.json" in script
    assert "RedirectStandardError" in script
    assert "Wait-AuditorExit" in script


def test_application_jd_harness_fails_closed_on_auditor_disconnect() -> None:
    script = HARNESS.read_text(encoding="utf-8")
    assert "Assert-BrowserAuditorHealthy" in script
    assert "failure_category" in script
    assert "Browser auditor did not exit cleanly" in script
    assert "successful Pilot confirmation response" in script


def test_application_jd_implementation_scope_is_machine_checked() -> None:
    baseline_file = os.environ.get("OFFERPILOT_APPLICATION_JD_BASELINE_FILE")
    if not baseline_file:
        pytest.fail("release gate must supply OFFERPILOT_APPLICATION_JD_BASELINE_FILE")
    baseline = Path(baseline_file).read_text(encoding="ascii").strip()
    assert baseline
    assert_application_jd_implementation_scope(ROOT, baseline)


def test_release_report_uses_all_consumer_harness_stage() -> None:
    report = (ROOT / "docs" / "reports" / "2026-08-05-application-jd-versions-release-verification.md").read_text(
        encoding="utf-8"
    )
    assert "application-jd-real-ai-browser-harness.ps1 -Stage all" in report
    assert "application-jd-real-ai-browser-harness.ps1 -Stage jd-only" not in report


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


def test_browser_audit_extracts_consumer_jd_version_from_direct_response_payload() -> None:
    module = _load_browser_audit()
    record: dict[str, object] = {}

    module.record_response_payload_metadata(
        record,
        {
            "stage": "triage",
            "jd_version_id": 23,
            "stage_status": "ready",
        },
    )

    assert record["response_jd_version_id"] == 23
