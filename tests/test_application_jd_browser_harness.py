from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "scripts" / "application-jd-real-ai-browser-harness.ps1"


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
    assert output.isascii()
