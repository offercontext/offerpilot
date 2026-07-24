from __future__ import annotations

import json

from fastapi.testclient import TestClient

from offerpilot.ai.interview_preparation_proposals import safe_empty_interview_preparation_proposal
from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class FakeModel:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Assistant(
            content=json.dumps(safe_empty_interview_preparation_proposal(), ensure_ascii=False)
        )


def _context(client: TestClient) -> tuple[dict, dict, dict]:
    application = client.post(
        "/api/applications", json={"company_name": "Acme", "position_name": "Backend"}
    ).json()
    resume = client.post(
        "/api/resumes",
        json={
            "title": "Backend Resume",
            "text": "Built reliable API services",
            "content_json": {"raw_text": "Built reliable API services"},
        },
    ).json()
    event = client.post(
        "/api/application-events",
        json={
            "application_id": application["id"],
            "event_type": "interview",
            "scheduled_at": "2026-07-24T10:00:00Z",
            "duration_minutes": 45,
        },
    ).json()
    return application, resume, event


def _payload(resume_id: int, event_id: int, key: str = "attempt-00000001") -> dict:
    return {
        "event_id": event_id,
        "resume_id": resume_id,
        "jd_text": "Build reliable services with Python.",
        "knowledge_selections": [],
        "user_assertions": ["I led a migration."],
        "idempotency_key": key,
    }


def test_missing_required_input_returns_422_without_provider_call(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)

    missing_jd = _payload(resume["id"], event["id"])
    missing_jd["jd_text"] = ""
    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=missing_jd,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_preparation_jd_required"
    assert model.calls == 0


def test_invalid_idempotency_key_returns_422_without_provider_call(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    payload = _payload(resume["id"], event["id"], "too-short")
    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_preparation_invalid_request"
    assert model.calls == 0


def test_input_limits_return_422_without_provider_call(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    payload = _payload(resume["id"], event["id"])
    payload["user_assertions"] = [f"assertion-{index}" for index in range(11)]
    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_preparation_input_too_large"
    assert model.calls == 0


def test_unknown_request_fields_and_forged_source_fields_are_rejected(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    payload = _payload(resume["id"], event["id"])
    payload["job_url"] = "https://jobs.example.invalid/should-not-fetch"
    payload["current_jd_hash"] = "forged"

    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_preparation_invalid_request"
    assert model.calls == 0


def test_forged_knowledge_selection_is_rejected_before_provider_call(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    payload = _payload(resume["id"], event["id"])
    payload["knowledge_selections"] = [{"note_version_id": 999, "evidence_ids": ["ev-forged"]}]

    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_preparation_knowledge_selection_invalid"
    assert model.calls == 0


def test_create_returns_201_then_same_key_returns_200_without_provider_resolution(tmp_path) -> None:
    model = FakeModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    url = f"/api/applications/{application['id']}/interview-preparation-proposals"

    first = client.post(url, json=_payload(resume["id"], event["id"]))
    assert first.status_code == 201
    assert first.json()["source_states"]["jd"] == "not_checked"
    assert first.json()["proposal_status"] == "safe_empty"

    replay = client.post(url, json=_payload(resume["id"], event["id"]))
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert model.calls == 1


def test_same_key_provider_unknown_returns_202_without_second_provider_call(tmp_path) -> None:
    model = FakeModel(error=TimeoutError("provider secret"))
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application, resume, event = _context(client)
    url = f"/api/applications/{application['id']}/interview-preparation-proposals"

    first = client.post(url, json=_payload(resume["id"], event["id"], "unknown-000000001"))
    second = client.post(url, json=_payload(resume["id"], event["id"], "unknown-000000001"))

    assert first.status_code == 502
    assert first.json()["error_code"] == "interview_preparation_provider_error"
    assert second.status_code == 202
    assert second.json()["attempt_status"] == "provider_unknown"
    assert model.calls == 1
    assert "provider secret" not in second.text


def test_history_marks_deleted_event_and_soft_deleted_application_is_404(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, chat_model=FakeModel()))
    application, resume, event = _context(client)
    url = f"/api/applications/{application['id']}/interview-preparation-proposals"
    created = client.post(url, json=_payload(resume["id"], event["id"])).json()
    assert client.delete(f"/api/application-events/{event['id']}").status_code == 200

    history = client.get(url)
    assert history.status_code == 200
    assert history.json()[0]["source_states"]["event"] == "source_changed"

    assert client.delete(f"/api/applications/{application['id']}").status_code == 200
    hidden = client.get(url)
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "interview_preparation_application_not_found"
    assert created["proposal_status"] == "safe_empty"


def test_unconfigured_provider_has_stable_safe_error(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    application, resume, event = _context(client)
    response = client.post(
        f"/api/applications/{application['id']}/interview-preparation-proposals",
        json=_payload(resume["id"], event["id"]),
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": "AI 服务暂不可用，请稍后重试。",
        "error_code": "interview_preparation_provider_error",
    }
