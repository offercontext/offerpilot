import json
from pathlib import Path

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app
from offerpilot.db import init_database
from offerpilot.models import Resume


class _QuickPracticeModel:
    supports_json_schema = False

    def complete(self, messages, tools, **kwargs):
        if any("mock-interview-feedback-v1" in message.content for message in messages):
            return Assistant(
                content=json.dumps(
                    {
                        "schema_version": "mock-interview-feedback-v1",
                        "proposal_status": "safe_empty",
                        "strengths": [],
                        "practice_points": [],
                        "follow_up_questions": [],
                        "next_practice_steps": [],
                    }
                )
            )
        return Assistant(
            content=json.dumps(
                {
                    "question": "请结合 Python 经验说明你的推进方式。",
                    "evidence_refs": [
                        {"source": "jd", "path": "/jd/text", "excerpt": "Python"}
                    ],
                }
            )
        )


def _seed_resume(data_dir: Path) -> int:
    factory = init_database(data_dir / "data.db")
    with factory() as session:
        resume = Resume(
            title="筱哲简历",
            parsed_data="Python FastAPI",
            content_json=json.dumps({"summary": "后端工程师", "skills": ["Python"]}),
        )
        session.add(resume)
        session.commit()
        return resume.id


def test_quick_practice_case_api_has_idempotent_safe_snapshot_and_archive(tmp_path):
    resume_id = _seed_resume(tmp_path)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        payload = {
            "idempotency_key": "case-api-001",
            "position_name": "后端工程师",
            "jd_text": "负责 Python 服务。",
            "resume_id": resume_id,
        }
        created = client.post("/api/interview-practice-cases", json=payload)
        replay = client.post("/api/interview-practice-cases", json=payload)
        conflict = client.post(
            "/api/interview-practice-cases",
            json={**payload, "jd_text": "另一份岗位资料。"},
        )

        assert created.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["id"] == created.json()["id"]
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "interview_practice_case_idempotency_conflict"
        assert "provider" not in json.dumps(created.json(), ensure_ascii=False).lower()

        case_id = created.json()["id"]
        listed = client.get("/api/interview-practice-cases").json()
        assert listed["items"][0]["position_name_snapshot"] == "后端工程师"
        archived = client.post(f"/api/interview-practice-cases/{case_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"


def test_quick_practice_case_api_rejects_boolean_resume_id(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        response = client.post(
            "/api/interview-practice-cases",
            json={
                "idempotency_key": "case-api-bool-resume",
                "position_name": "后端工程师",
                "jd_text": "负责 Python 服务",
                "resume_id": True,
            },
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_practice_case_invalid_payload"


def test_quick_practice_finish_uses_last_confirmed_answer(tmp_path):
    resume_id = _seed_resume(tmp_path)
    with TestClient(create_app(data_dir=tmp_path, chat_model=_QuickPracticeModel())) as client:
        case = client.post(
            "/api/interview-practice-cases",
            json={
                "idempotency_key": "case-api-finish-001",
                "position_name": "后端工程师",
                "jd_text": "负责 Python 服务",
                "resume_id": resume_id,
            },
        ).json()
        base = f"/api/interview-practice-cases/{case['id']}/mock-interview"
        started = client.post(
            f"{base}/attempts",
            json={
                "attempt_idempotency_key": "quick-finish-attempt-001",
                "initial_question_idempotency_key": "quick-finish-question-001",
            },
        )
        attempt_id = started.json()["attempt_id"]
        client.post(
            f"{base}/attempts/{attempt_id}/turns",
            json={
                "turn_no": 1,
                "answer_text": "我会先拆解接口，再用指标验证稳定性。",
                "turn_idempotency_key": "quick-finish-answer-001",
            },
        )
        next_question = client.post(
            f"{base}/attempts/{attempt_id}/turns/2/question",
            json={"question_idempotency_key": "quick-finish-question-002"},
        )
        assert next_question.status_code == 201

        finished = client.post(
            f"{base}/attempts/{attempt_id}/finish",
            json={"feedback_idempotency_key": "quick-finish-feedback-001"},
        )

    assert finished.status_code == 201
    assert finished.json()["context_kind"] == "quick_practice"
    assert finished.json()["practice_case_id"] == case["id"]
