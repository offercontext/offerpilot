from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from offerpilot.api import create_app


def _client(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    application = client.post(
        "/api/applications",
        json={"company_name": "Acme", "position_name": "Engineer", "status": "interview"},
    ).json()
    event = client.post(
        "/api/application-events",
        json={
            "application_id": application["id"],
            "event_type": "interview",
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "duration_minutes": 30,
        },
    ).json()
    resume = client.post(
        "/api/resumes",
        json={"title": "Resume", "text": "Python engineer"},
    ).json()
    return client, application["id"], event["id"], resume["id"]


def test_start_requires_selected_resume_and_nonempty_jd(tmp_path):
    client, app_id, event_id, resume_id = _client(tmp_path)
    path = f"/api/applications/{app_id}/events/{event_id}/mock-interview/attempts"

    missing_resume = client.post(path, json={"jd_text": "JD", "attempt_idempotency_key": "a", "initial_question_idempotency_key": "q"})
    empty_jd = client.post(path, json={"resume_id": resume_id, "jd_text": " ", "attempt_idempotency_key": "b", "initial_question_idempotency_key": "q"})

    assert missing_resume.status_code == 422
    assert empty_jd.status_code == 422


def test_start_and_same_key_replay_are_idempotent(tmp_path):
    client, app_id, event_id, resume_id = _client(tmp_path)
    path = f"/api/applications/{app_id}/events/{event_id}/mock-interview/attempts"
    payload = {
        "resume_id": resume_id,
        "jd_text": "需要 Python",
        "attempt_idempotency_key": "attempt-1",
        "initial_question_idempotency_key": "question-1",
    }

    first = client.post(path, json=payload)
    replay = client.post(path, json=payload)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["attempt_id"] == replay.json()["attempt_id"]


def test_start_rejects_cross_application_event(tmp_path):
    client, app_id, event_id, resume_id = _client(tmp_path)
    second = client.post(
        "/api/applications",
        json={"company_name": "Other", "position_name": "Other", "status": "interview"},
    ).json()
    path = f"/api/applications/{second['id']}/events/{event_id}/mock-interview/attempts"

    response = client.post(
        path,
        json={
            "resume_id": resume_id,
            "jd_text": "JD",
            "attempt_idempotency_key": "attempt-1",
            "initial_question_idempotency_key": "question-1",
        },
    )

    assert response.status_code == 422


def test_submit_answer_and_finish_persist_safe_empty_feedback(tmp_path):
    client, app_id, event_id, resume_id = _client(tmp_path)
    base = f"/api/applications/{app_id}/events/{event_id}/mock-interview/attempts"
    started = client.post(
        base,
        json={
            "resume_id": resume_id,
            "jd_text": "需要 Python",
            "attempt_idempotency_key": "attempt-1",
            "initial_question_idempotency_key": "question-1",
        },
    ).json()
    attempt_id = started["attempt_id"]

    answered = client.post(
        f"{base}/{attempt_id}/turns",
        json={"turn_no": 1, "answer_text": "我做过 Python 服务", "turn_idempotency_key": "answer-1"},
    )
    finished = client.post(
        f"{base}/{attempt_id}/finish",
        json={"feedback_idempotency_key": "feedback-1"},
    )

    assert answered.status_code == 200
    assert finished.status_code == 201
    assert finished.json()["proposal"]["proposal_status"] == "safe_empty"
