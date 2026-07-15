from pathlib import Path

import pytest
from typer.testing import CliRunner

from offerpilot.cli import app
from offerpilot.smoke import (
    SmokeStep,
    _run_real_ai_material_proposal_smoke,
    run_core_smoke,
    run_http_smoke,
)


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
        "chat_create_application_card",
        "chat_create_event_card",
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
        "http_unconfigured_chat",
        "http_health",
        "http_settings",
        "http_spa",
        "http_create_application",
        "http_list_applications",
        "http_resume_crud",
        "http_application_event_crud",
        "http_chat_pending",
        "http_confirm_action",
        "http_pending_cleared",
        "http_chat_create_application_card",
        "http_chat_create_event_card",
        "http_cleanup",
    ]


def test_real_ai_material_proposal_smoke_allows_empty_changes_and_hides_snapshot():
    class Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def __init__(self) -> None:
            self.deleted_resume_id: int | None = None

        def post(self, path: str, json: dict[str, object]) -> Response:
            if path == "/api/resumes":
                return Response(201, {"id": 42})
            if path.endswith("/material-kit/generate"):
                return Response(201, {"id": 7})
            if path.endswith("/material-revision-proposals"):
                return Response(
                    201,
                    {
                        "id": 8,
                        "application_id": 7,
                        "material_kit_id": 7,
                        "source_resume_id": 42,
                        "status": "draft",
                        "summary": "No safe changes.",
                        "proposal_sha256": "sha",
                        "result_resume_id": None,
                        "created_at": "2026-07-15T00:00:00Z",
                        "changes": [],
                        "accepted_change_ids": [],
                        "accepted_at": None,
                        "rejected_at": None,
                        "source": {
                            "application": {"id": 7, "company_name": "Smoke", "position_name": "QA"},
                            "material_kit": {"id": 7, "jd_excerpt": "QA"},
                            "resume": {"id": 42, "title": "Smoke Resume"},
                            "latest_evidence_bundle": None,
                            "user_assertions": [],
                        },
                    },
                )
            raise AssertionError(path)

        def delete(self, path: str) -> Response:
            self.deleted_resume_id = int(path.rsplit("/", 1)[-1])
            return Response(200, {})

    client = Client()
    steps: list[SmokeStep] = []

    _run_real_ai_material_proposal_smoke(client, steps, 7)

    assert [step.name for step in steps] == ["http_material_proposal"]
    assert client.deleted_resume_id == 42


def test_real_ai_material_proposal_smoke_rejects_renamed_snapshot_leak():
    class Response:
        status_code = 201

        def json(self) -> dict[str, object]:
            return {
                "id": 8,
                "status": "draft",
                "changes": [],
                "source": {"frozen_resume_payload": {"raw_text": "secret"}},
            }

    class Client:
        def post(self, path: str, json: dict[str, object]) -> Response:
            if path == "/api/resumes":
                return Response()
            if path.endswith("/material-kit/generate"):
                return Response()
            if path.endswith("/material-revision-proposals"):
                return Response()
            raise AssertionError(path)

        def delete(self, path: str) -> Response:
            response = Response()
            response.status_code = 200
            return response

    with pytest.raises(RuntimeError, match="leaked frozen source data"):
        _run_real_ai_material_proposal_smoke(Client(), [], 7)


def test_cli_verify_local_runs_http_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(app, ["verify", "--profile", "local", "--static-dir", str(_static_dir(tmp_path))])

    assert result.exit_code == 0
    assert "Verify local passed" in result.output
    assert "http_unconfigured_chat" in result.output
    assert "http_resume_crud" in result.output
    assert "http_application_event_crud" in result.output
    assert "http_health" in result.output
    assert "http_confirm_action" in result.output
