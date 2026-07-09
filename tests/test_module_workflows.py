import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class JSONModel:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return Assistant(content=json.dumps(self.payload, ensure_ascii=False))


def test_knowledge_to_practice_generation_review_workflow(tmp_path):
    model = JSONModel(
        {
            "questions": [
                {
                    "category": "系统设计",
                    "difficulty": "hard",
                    "question": "如何设计一个高并发短链系统？",
                    "reference_answer": "发号器、缓存、限流、异步写入。",
                    "tags": ["缓存", "限流"],
                }
            ]
        }
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    doc = client.post(
        "/api/knowledge-documents",
        json={
            "title": "短链系统设计",
            "content": "短链系统需要发号器、缓存、限流和异步写入。",
            "tags": ["系统设计"],
        },
    ).json()
    generated = client.post(
        "/api/questions/generate",
        json={"source": "knowledge", "topic": "system-design", "count": 1},
    )

    assert generated.status_code == 201
    question = generated.json()["questions"][0]
    assert question["question"] == "如何设计一个高并发短链系统？"
    assert question["source_type"] == "ai_knowledge"
    assert client.get("/api/knowledge/search?q=短链").json()[0]["document_id"] == doc["id"]
    assert client.get("/api/questions/due").json()[0]["id"] == question["id"]

    reviewed = client.post(f"/api/questions/{question['id']}/reviews", json={"rating": 3})

    assert reviewed.status_code == 201
    stats = client.get("/api/questions/stats").json()
    assert stats["total"] == 1
    assert stats["mastered"] == 1
    assert stats["due"] == 0
    assert stats["today_reviews"] == 1


def test_interview_mock_completion_can_save_review_note_for_application(tmp_path):
    model = JSONModel(
        {
            "score_overall": 82,
            "score_communication": 84,
            "score_depth": 78,
            "score_structure": 80,
            "score_confidence": 86,
            "summary": "表达稳定，项目追问仍需加深",
            "strengths": ["回答结构清晰"],
            "weaknesses": ["性能测试案例不足"],
            "drills": [{"area": "性能测试", "action": "补练压测指标复盘", "link_question_ids": []}],
        }
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    application = client.post(
        "/api/applications",
        json={"company_name": "牛客网", "position_name": "软件测试工程师", "status": "interview"},
    ).json()

    created = client.post(
        "/api/mock/sessions",
        json={
            "role": "软件测试工程师",
            "company": "牛客网",
            "round_type": "technical",
            "application_id": application["id"],
            "question_source": "mixed",
        },
    ).json()
    ended = client.post(
        f"/api/mock/sessions/{created['session']['id']}/end",
        json={"auto_save_note": True},
    )

    assert ended.status_code == 200
    body = ended.json()
    assert body["session"]["status"] == "completed"
    assert body["feedback"]["summary"] == "表达稳定，项目追问仍需加深"
    assert body["saved_note_id"] > 0

    notes = client.get(f"/api/applications/{application['id']}/notes").json()
    assert len(notes) == 1
    assert notes[0]["company"] == "牛客网"
    assert notes[0]["position"] == "软件测试工程师"
    assert "性能测试案例不足" in notes[0]["difficulty_points"]
