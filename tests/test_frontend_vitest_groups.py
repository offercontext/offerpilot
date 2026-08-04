from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "windows-vitest-groups.ps1"
GROUPS = (
    "components-core",
    "components-chat",
    "components-interview",
    "components-offer",
    "components-support",
    "features",
    "layout",
    "lib",
    "services",
    "theme",
)


def _powershell_available() -> bool:
    return shutil.which("powershell.exe") is not None


def _run_gate(result_dir: Path, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
            "-ResultDir",
            str(result_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _fake_npm_environment(tmp_path: Path, manifest_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_runner = fake_bin / "fake-vitest.ps1"
    fake_runner.write_text(
        """
param()
$allArguments = @($args)
$outputArgument = $allArguments | Where-Object { $_ -like '--outputFile=*' } | Select-Object -First 1
$outputPath = $outputArgument.Substring('--outputFile='.Length)
if ($env:FAKE_VITEST_FAIL -eq '1') { exit 17 }
$manifest = Get-Content $env:FAKE_VITEST_MANIFEST -Raw -Encoding utf8 | ConvertFrom-Json
$files = @($manifest.groups | ForEach-Object { $_.PSObject.Properties[$env:FAKE_VITEST_GROUP].Value })
if ($env:FAKE_VITEST_OMIT_FILE -eq '1') { $files = @() }
$results = @($files | ForEach-Object {
    @{
        name = Join-Path $env:FAKE_VITEST_WEB_ROOT $_
        assertionResults = @(@{ fullName = 'fake passes'; status = 'passed' })
    }
})
@{
    success = $true
    numPendingTests = 0
    numTodoTests = 0
    numTotalTests = $results.Count
    testResults = $results
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding utf8
""".strip(),
        encoding="utf-8",
    )
    (fake_bin / "npm.cmd").write_text(
        '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0fake-vitest.ps1" %*\r\nexit /b %ERRORLEVEL%\r\n',
        encoding="ascii",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["FAKE_VITEST_MANIFEST"] = str(manifest_path)
    environment["FAKE_VITEST_WEB_ROOT"] = str(ROOT / "web")
    return environment


def _run_all_fake_groups(result_dir: Path, environment: dict[str, str]) -> None:
    for group in GROUPS:
        environment["FAKE_VITEST_GROUP"] = group
        run = _run_gate(result_dir, "-Group", group, env=environment)
        assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_group_rejects_missing_expected_file(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    collected = _run_gate(result_dir, "-Collect")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    environment = _fake_npm_environment(tmp_path, result_dir / "frontend-manifest.json")
    environment["FAKE_VITEST_GROUP"] = "theme"
    environment["FAKE_VITEST_OMIT_FILE"] = "1"

    run = _run_gate(result_dir, "-Group", "theme", env=environment)

    assert run.returncode != 0


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_aggregate_removes_stale_success_before_validation(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    aggregate = result_dir / "frontend.aggregate.json"
    aggregate.write_text('{"status":"completed"}', encoding="utf-8")

    run = _run_gate(result_dir, "-Aggregate")

    assert run.returncode != 0
    assert not aggregate.exists()


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_aggregate_rejects_results_from_previous_manifest(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    collected = _run_gate(result_dir, "-Collect")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    manifest_path = result_dir / "frontend-manifest.json"
    environment = _fake_npm_environment(tmp_path, manifest_path)

    for group in GROUPS:
        environment["FAKE_VITEST_GROUP"] = group
        run = _run_gate(result_dir, "-Group", group, env=environment)
        assert run.returncode == 0, run.stdout + run.stderr

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["source_hash"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    aggregate = _run_gate(result_dir, "-Aggregate", env=environment)

    assert aggregate.returncode != 0


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_group_does_not_reuse_old_result_after_failed_run(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    collected = _run_gate(result_dir, "-Collect")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    environment = _fake_npm_environment(tmp_path, result_dir / "frontend-manifest.json")
    environment["FAKE_VITEST_GROUP"] = "theme"

    first = _run_gate(result_dir, "-Group", "theme", env=environment)
    assert first.returncode == 0, first.stdout + first.stderr
    assert (result_dir / "theme.results.json").exists()
    assert (result_dir / "theme.complete.json").exists()

    environment["FAKE_VITEST_FAIL"] = "1"
    second = _run_gate(result_dir, "-Group", "theme", env=environment)

    assert second.returncode != 0
    assert not (result_dir / "theme.results.json").exists()
    assert not (result_dir / "theme.complete.json").exists()


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_aggregate_rejects_new_test_file_after_group_runs(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    collected = _run_gate(result_dir, "-Collect")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    environment = _fake_npm_environment(tmp_path, result_dir / "frontend-manifest.json")
    _run_all_fake_groups(result_dir, environment)

    added_test = ROOT / "web" / "src" / "__frontend_gate_probe__.test.ts"
    try:
        added_test.write_text("it('probe', () => expect(true).toBe(true));\n", encoding="utf-8")
        aggregate = _run_gate(result_dir, "-Aggregate", env=environment)
        assert aggregate.returncode != 0
    finally:
        added_test.unlink(missing_ok=True)


@pytest.mark.skipif(not _powershell_available(), reason="Windows PowerShell is required")
def test_frontend_aggregate_rejects_production_source_change_after_group_runs(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    collected = _run_gate(result_dir, "-Collect")
    assert collected.returncode == 0, collected.stdout + collected.stderr
    environment = _fake_npm_environment(tmp_path, result_dir / "frontend-manifest.json")
    _run_all_fake_groups(result_dir, environment)

    production_source = ROOT / "web" / "src" / "main.tsx"
    original = production_source.read_bytes()
    try:
        production_source.write_bytes(original + b"\n// temporary frontend gate probe\n")
        aggregate = _run_gate(result_dir, "-Aggregate", env=environment)
        assert aggregate.returncode != 0
    finally:
        production_source.write_bytes(original)
