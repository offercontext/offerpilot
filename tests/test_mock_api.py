import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class ScoringModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return Assistant(
            content=json.dumps(
                {
                    "score_overall": 78,
                    "score_communication": 80,
                    "score_depth": 72,
                    "score_structure": 75,
                    "score_confidence": 85,
                    "summary": "中等偏上",
                    "strengths": ["STAR清晰"],
                    "weaknesses": ["系统设计偏浅"],
                    "drills": [{"area": "系统设计", "action": "补练容量估算题", "link_question_ids": [12]}],
                },
                ensure_ascii=False,
            )
        )


def test_mock_session_create_get_list_and_delete(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, chat_model=ScoringModel()))

    created_response = client.post(
        "/api/mock/sessions",
        json={
            "role": "后端开发",
            "company": "字节跳动",
            "round_type": "technical",
            "difficulty": "hard",
            "question_count": 5,
            "duration_min": 30,
            "question_source": "bank",
        },
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["session"]["role"] == "后端开发"
    assert created["session"]["status"] == "in_progress"
    assert created["session"]["conversation_id"] == created["conversation_id"]
    assert created["conversation"]["mode"] == "mock_interview"

    fetched = client.get(f"/api/mock/sessions/{created['session']['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == []

    in_progress = client.get("/api/mock/sessions?status=in_progress").json()
    assert [session["id"] for session in in_progress] == [created["session"]["id"]]

    deleted = client.delete(f"/api/mock/sessions/{created['session']['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted"}
    assert client.get(f"/api/mock/sessions/{created['session']['id']}").status_code == 404


def test_mock_session_requires_role(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/mock/sessions", json={"company": "字节"})

    assert response.status_code == 400
    assert response.json() == {"error": "role is required"}


def test_mock_session_create_returns_conversation_context_label(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/mock/sessions", json={"role": "后端开发"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["conversation_id"] == payload["conversation"]["id"]
    assert payload["conversation"]["mode"] == "mock_interview"
    assert payload["conversation"]["context_type"] == "workspace"
    assert payload["conversation"]["context_ref"] == ""
    assert payload["conversation"]["context_label"] == "工作区"


def test_mock_session_end_scores_and_auto_saves_note(tmp_path):
    model = ScoringModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    app = client.post(
        "/api/applications",
        json={"company_name": "字节", "position_name": "后端", "status": "interview"},
    ).json()
    created = client.post(
        "/api/mock/sessions",
        json={"role": "后端", "round_type": "technical", "application_id": app["id"]},
    ).json()

    end_response = client.post(
        f"/api/mock/sessions/{created['session']['id']}/end",
        json={"auto_save_note": True},
    )

    assert end_response.status_code == 200
    ended = end_response.json()
    assert ended["session"]["status"] == "completed"
    assert ended["session"]["score_overall"] == 78
    assert ended["feedback"]["summary"] == "中等偏上"
    assert ended["saved_note_id"] > 0
    assert model.calls == 1

    saved_note = client.get(f"/api/applications/{app['id']}/notes").json()[0]
    assert saved_note["company"] == "字节"
    assert "系统设计偏浅" in saved_note["difficulty_points"]

    conflict = client.post(f"/api/mock/sessions/{created['session']['id']}/end", json={})
    assert conflict.status_code == 409
    assert conflict.json() == {"error": "session already ended"}


def test_mock_session_save_note_after_completion_reuses_feedback(tmp_path):
    model = ScoringModel()
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    created = client.post("/api/mock/sessions", json={"role": "算法"}).json()

    first = client.post(f"/api/mock/sessions/{created['session']['id']}/end", json={})
    assert first.status_code == 200

    second = client.post(
        f"/api/mock/sessions/{created['session']['id']}/end",
        json={"auto_save_note": True},
    )
    assert second.status_code == 200
    assert second.json()["saved_note_id"] > 0
    assert model.calls == 1
