from pathlib import Path

from typer.testing import CliRunner

from offerpilot.cli import app
from offerpilot.smoke import run_core_smoke, run_http_smoke


def _static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><div id='root'></div></html>", encoding="utf-8")
    return static_dir


def test_core_smoke_runs_spa_api_and_hitl_loop(tmp_path):
    report = run_core_smoke(data_dir=tmp_path / "data", static_dir=_static_dir(tmp_path))

    assert report.ok is True
    assert [step.name for step in report.steps] == [
        "health",
        "spa",
        "create_application",
        "chat_pending",
        "confirm_action",
        "pending_cleared",
    ]


def test_cli_smoke_prints_checked_steps(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(app, ["smoke", "--static-dir", str(_static_dir(tmp_path))])

    assert result.exit_code == 0
    assert "Smoke passed" in result.output
    assert "confirm_action" in result.output


def test_http_smoke_uses_real_http_and_cleans_test_application(tmp_path):
    report = run_http_smoke(data_dir=tmp_path / "data", static_dir=_static_dir(tmp_path), real_ai=False)

    assert report.ok is True
    assert [step.name for step in report.steps] == [
        "http_health",
        "http_settings",
        "http_spa",
        "http_create_application",
        "http_list_applications",
        "http_chat_pending",
        "http_confirm_action",
        "http_pending_cleared",
        "http_cleanup",
    ]


def test_cli_verify_local_runs_http_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(app, ["verify", "--profile", "local", "--static-dir", str(_static_dir(tmp_path))])

    assert result.exit_code == 0
    assert "Verify local passed" in result.output
    assert "http_health" in result.output
    assert "http_confirm_action" in result.output
