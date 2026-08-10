from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from offerpilot.cli import app
from offerpilot.smoke import SmokeReport, SmokeStep, run_interview_story_smoke


def test_verify_interview_stories_cli_is_explicitly_isolated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))
    observed: dict[str, object] = {}

    def fake_verify(data_dir: Path, static_dir: Path | None, *, real_ai: bool) -> SmokeReport:
        observed.update({"data_dir": data_dir, "static_dir": static_dir, "real_ai": real_ai})
        return SmokeReport(ok=True, steps=[SmokeStep("story", "isolated flow")])

    monkeypatch.setattr("offerpilot.cli.run_interview_story_smoke", fake_verify)
    result = CliRunner().invoke(app, ["verify-interview-stories", "--profile", "local"])

    assert result.exit_code == 0
    assert observed["real_ai"] is False
    assert "Isolated Interview Story API verification" in result.output
    assert "does not replace full verify or browser/CDP evidence" in result.output


def test_local_interview_story_smoke_exercises_ui_and_pilot_without_chat_writes(tmp_path: Path) -> None:
    report = run_interview_story_smoke(tmp_path, real_ai=False)

    names = [step.name for step in report.steps]
    assert report.ok is True
    assert "story_manual_lifecycle" in names
    assert "story_ui_proposal_confirm" in names
    assert "story_pilot_proposal_confirm" in names
    assert "story_source_changed" in names
    assert "story_chat_isolation" in names
