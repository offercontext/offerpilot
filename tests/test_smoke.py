from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from offerpilot.cli import app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import (
    Application,
    ApplicationMaterialKit,
    MaterialRevisionProposal,
    OpportunityFitReview,
    Resume,
)
from offerpilot.smoke import (
    SmokeStep,
    SmokeReport,
    _assert_real_ai_smoke_data_clean,
    _cleanup_real_ai_browser_records,
    _cleanup_real_ai_smoke_records,
    _run_real_ai_interview_review_smoke,
    _run_real_ai_material_proposal_smoke,
    _run_real_ai_opportunity_fit_smoke,
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
            self.created_resume_ids: list[int] = []
            self.deleted_resume_ids: list[int] = []

        def post(self, path: str, json: dict[str, object]) -> Response:
            if path == "/api/resumes":
                resume_id = 41 if not self.created_resume_ids else 42
                self.created_resume_ids.append(resume_id)
                return Response(201, {"id": resume_id})
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
            self.deleted_resume_ids.append(int(path.rsplit("/", 1)[-1]))
            return Response(200, {})

    client = Client()
    steps: list[SmokeStep] = []
    resume_ids: list[int] = []

    _run_real_ai_material_proposal_smoke(client, steps, 7, resume_ids)

    assert [step.name for step in steps] == ["http_material_proposal"]
    assert client.created_resume_ids == [41, 42]
    assert resume_ids == [41, 42]


def test_real_ai_http_smoke_isolates_config_and_removes_temporary_data(monkeypatch, tmp_path):
    import offerpilot.smoke as smoke

    source_data = tmp_path / "user-data"
    source_data.mkdir()
    config_text = '{"api_key":"not-for-output","model":"configured"}\n'
    (source_data / "config.json").write_text(config_text, encoding="utf-8")
    observed: dict[str, Path] = {}

    def fake_http_smoke(data_dir: Path, static_dir: Path | None, *, real_ai: bool) -> SmokeReport:
        observed["data_dir"] = data_dir
        assert real_ai is True
        assert data_dir != source_data
        assert (data_dir / "config.json").read_text(encoding="utf-8") == config_text
        return SmokeReport(ok=True, steps=[])

    monkeypatch.setattr(smoke, "_run_http_smoke", fake_http_smoke)

    report = run_http_smoke(source_data, real_ai=True)

    assert report.ok is True
    assert not observed["data_dir"].exists()


def test_real_ai_smoke_cleanup_removes_material_records_and_active_resume(tmp_path):
    data_dir = tmp_path / "isolated"
    session_factory = session_factory_for_data_dir(data_dir)
    with session_factory() as session:
        application = Application(company_name="Smoke", position_name="QA")
        session.add(application)
        session.flush()
        resume = Resume(
            title="Smoke Resume",
            is_master=True,
            content_json="{}",
            deleted_at=datetime.now(timezone.utc),
        )
        session.add(resume)
        session.flush()
        material_kit = ApplicationMaterialKit(
            application_id=application.id,
            resume_id=resume.id,
            content_json="{}",
        )
        session.add(material_kit)
        session.flush()
        session.add(
            MaterialRevisionProposal(
                application_id=application.id,
                material_kit_id=material_kit.id,
                source_resume_id=resume.id,
                source_fingerprint_sha256="source",
                source_snapshot_json="{}",
                proposal_json="{}",
                proposal_sha256="proposal",
            )
        )
        session.add(
            OpportunityFitReview(
                application_id=application.id,
                resume_id=resume.id,
                idempotency_key="f36f6d0b-1d1e-4e9a-aec1-9fef6b2f3b90",
                source_fingerprint_sha256="source",
                source_snapshot_json="{}",
                triage_json="{}",
                triage_sha256="triage",
            )
        )
        session.commit()
    bind = session_factory.kw.get("bind")
    if bind is not None:
        bind.dispose()

    _cleanup_real_ai_smoke_records(data_dir, application.id, [resume.id])
    _assert_real_ai_smoke_data_clean(data_dir)


def test_real_ai_browser_cleanup_is_scoped_to_temp_data(tmp_path):
    source_data = tmp_path / "source"
    temp_data = tmp_path / "temp"
    records: dict[str, tuple[int, int]] = {}
    for name, data_dir in (("source", source_data), ("temp", temp_data)):
        session_factory = session_factory_for_data_dir(data_dir)
        with session_factory() as session:
            application = Application(company_name=f"{name} company", position_name="QA")
            resume = Resume(title=f"{name} resume", content_json="{}")
            session.add_all([application, resume])
            session.commit()
            records[name] = (application.id, resume.id)
        bind = session_factory.kw.get("bind")
        if bind is not None:
            bind.dispose()

    _cleanup_real_ai_browser_records(temp_data, records["temp"][0], [records["temp"][1]])
    _assert_real_ai_smoke_data_clean(temp_data)

    source_factory = session_factory_for_data_dir(source_data)
    with source_factory() as session:
        assert session.get(Application, records["source"][0]) is not None
        assert session.get(Resume, records["source"][1]) is not None
    bind = source_factory.kw.get("bind")
    if bind is not None:
        bind.dispose()


def test_real_ai_browser_harness_isolated_and_uses_base_url():
    harness = Path(__file__).parents[1] / "scripts" / "pilot-real-ai-browser-harness.ps1"
    source = harness.read_text(encoding="utf-8")
    assert "OFFERPILOT_DATA" in source
    assert "Copy-Item" in source
    assert "Get-NetTCPConnection" in source
    assert "Get-TreeIds" in source
    assert "http://127.0.0.1:$port" in source
    assert "/api/application-events" in source
    assert "evidence-gated interview review proposal" in source
    assert "/applications/" not in source
    assert "_cleanup_real_ai_browser_records" in source
    assert "if ($LASTEXITCODE -ne 0)" in source
    assert source.count("if ($LASTEXITCODE -ne 0)") >= 2


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


def test_real_ai_opportunity_fit_smoke_requires_verified_triage_without_snapshot_leak():
    class Response:
        status_code = 201

        def __init__(self, payload: dict[str, object] | None = None) -> None:
            self._payload = payload or {}

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def post(self, path: str, json: dict[str, object] | None = None) -> Response:
            if path == "/api/resumes":
                return Response({"id": 41})
            if path.endswith("opportunity-fit-reviews"):
                return Response({"id": 8, "triage": {"summary": {"text": "safe", "evidence_refs": []}}})
            if path.endswith("deep-review"):
                return Response({"deep_review": {"recommended_path": "clarify_first"}})
            raise AssertionError(path)

        def delete(self, path: str) -> Response:
            response = Response()
            response.status_code = 200
            return response

    steps: list[SmokeStep] = []
    _run_real_ai_opportunity_fit_smoke(Client(), steps, 7)
    assert [step.name for step in steps] == [
        "http_opportunity_fit_review",
        "http_opportunity_fit_deep_review",
    ]


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


def test_real_ai_interview_review_smoke_allows_empty_changes_without_snapshot_leak():
    class Response:
        status_code = 201

        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def post(self, path: str, json: dict[str, object]) -> Response:
            if path == "/api/application-events":
                assert json["event_type"] == "interview"
                return Response({"id": 31, "application_id": 7, "event_type": "interview"})
            if path == "/api/applications/7/notes":
                assert json["application_event_id"] == 31
                return Response({"id": 32, "application_event_id": 31})
            if path == "/api/notes/32/interview-review-proposals":
                assert set(json) == {"idempotency_key"}
                return Response(
                    {
                        "id": 33,
                        "note_id": 32,
                        "application_event_id": 31,
                        "source_status": "current",
                        "proposal": {
                            "summary": {
                                "text": "本次复盘记录不足以形成有依据的表现判断，请先补充待澄清问题。",
                                "evidence_refs": [],
                            },
                            "observations": [],
                            "clarifications": [],
                            "practice_focuses": [],
                            "next_questions": [],
                        },
                        "proposal_hash": "hash",
                        "source_fingerprint": "fingerprint",
                        "created_at": "2026-07-22T00:00:00Z",
                    }
                )
            raise AssertionError(path)

    steps: list[SmokeStep] = []
    _run_real_ai_interview_review_smoke(Client(), steps, 7)

    assert [step.name for step in steps] == ["http_interview_review_proposal"]
