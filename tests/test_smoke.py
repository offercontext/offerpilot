from pathlib import Path

from typer.testing import CliRunner

from offerpilot.cli import app
from offerpilot.smoke import run_core_smoke


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
