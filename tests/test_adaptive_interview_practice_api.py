from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import Application, ApplicationEvent, InterviewNote, InterviewReviewProposal
from offerpilot.repositories.json_contract import canonical_json, sha256_text


class ForbiddenModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise AssertionError("adaptive practice must not call a provider")


def _seed(data_dir) -> int:
    session_factory = session_factory_for_data_dir(data_dir)
    with session_factory() as session:
        app = Application(company_name="云栖智能", position_name="后端工程师", source="web")
        session.add(app)
        session.flush()
        event = ApplicationEvent(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
            duration_minutes=60,
            status="done",
        )
        session.add(event)
        session.flush()
        note = InterviewNote(
            application_id=app.id,
            application_event_id=event.id,
            company=app.company_name,
            position=app.position_name,
            questions="请说明一次线上延迟排查。",
            self_reflection="回答时先讲了过程，没有先给结论。",
            difficulty_points="被追问影响范围时卡住了。",
            mood="有些紧张",
        )
        session.add(note)
        session.flush()
        proposal = {
            "summary": {"text": "有一项练习。", "evidence_refs": []},
            "observations": [],
            "clarifications": [],
            "practice_focuses": [
                {
                    "id": "focus-1",
                    "text": "拆解影响范围追问。",
                    "evidence_refs": [
                        {
                            "source": "interview_note",
                            "path": "/difficulty_points",
                            "excerpt": note.difficulty_points,
                        }
                    ],
                }
            ],
            "next_questions": [],
        }
        snapshot = {"event": {"id": event.id}, "note": {"difficulty_points": note.difficulty_points}}
        row = InterviewReviewProposal(
            note_id=note.id,
            application_event_id=event.id,
            idempotency_key="review-key",
            input_snapshot_json=canonical_json(snapshot),
            source_fingerprint=sha256_text(canonical_json(snapshot)),
            proposal_json=canonical_json(proposal),
            proposal_hash=sha256_text(canonical_json(proposal)),
        )
        session.add(row)
        session.commit()
        return row.id


def test_adaptive_practice_api_runs_without_provider_and_is_idempotent(tmp_path) -> None:
    model = ForbiddenModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    proposal_id = _seed(tmp_path)

    recommendations = client.get("/api/interview-practice/recommendations")
    assert recommendations.status_code == 200
    recommendation = recommendations.json()[0]
    assert recommendation["proposal_id"] == proposal_id

    body = {
        "proposal_id": proposal_id,
        "focus_id": "focus-1",
        "expected_source_fingerprint": recommendation["source_fingerprint"],
        "idempotency_key": "practice-start-api-1",
    }
    started = client.post("/api/interview-practice/plans", json=body)
    replay = client.post("/api/interview-practice/plans", json=body)
    assert started.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == started.json()["id"]

    completed_body = {
        "expected_revision": 1,
        "response_text": "先说明影响范围，再描述定位过程和恢复结果。",
        "reflection_text": "下一次先给结论。",
        "self_assessment": "clearer",
        "idempotency_key": "practice-complete-api-1",
    }
    completed = client.post(
        f"/api/interview-practice/plans/{started.json()['id']}/complete",
        json=completed_body,
    )
    completed_replay = client.post(
        f"/api/interview-practice/plans/{started.json()['id']}/complete",
        json=completed_body,
    )
    assert completed.status_code == 200
    assert completed_replay.status_code == 200
    assert client.get("/api/interview-practice/plans").json()[0]["status"] == "completed"
    assert model.calls == 0


def test_adaptive_practice_api_returns_stable_validation_and_conflict_codes(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, chat_model=ForbiddenModel()))
    proposal_id = _seed(tmp_path)
    recommendation = client.get("/api/interview-practice/recommendations").json()[0]

    invalid = client.post("/api/interview-practice/plans", json={"proposal_id": proposal_id})
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "adaptive_practice_invalid_payload"

    for malformed in (None, [], "not-an-object"):
        invalid_start = (
            client.post("/api/interview-practice/plans")
            if malformed is None
            else client.post("/api/interview-practice/plans", json=malformed)
        )
        assert invalid_start.status_code == 422
        assert invalid_start.json()["error_code"] == "adaptive_practice_invalid_payload"

        invalid_complete = (
            client.post("/api/interview-practice/plans/1/complete")
            if malformed is None
            else client.post(
                "/api/interview-practice/plans/1/complete",
                json=malformed,
            )
        )
        assert invalid_complete.status_code == 422
        assert invalid_complete.json()["error_code"] == "adaptive_practice_invalid_payload"

    stale = client.post(
        "/api/interview-practice/plans",
        json={
            "proposal_id": proposal_id,
            "focus_id": "focus-1",
            "expected_source_fingerprint": recommendation["source_fingerprint"] + "stale",
            "idempotency_key": "practice-start-api-stale",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "adaptive_practice_source_conflict"

    missing = client.post(
        "/api/interview-practice/plans/999/complete",
        json={
            "expected_revision": 1,
            "response_text": "有效回答",
            "reflection_text": "",
            "self_assessment": "clearer",
            "idempotency_key": "practice-complete-missing",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "adaptive_practice_not_found"
