import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class JSONModel:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return Assistant(content=json.dumps(self.payload, ensure_ascii=False))


def test_question_crud_review_stats_and_delete(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    created_response = client.post(
        "/api/questions",
        json={
            "category": "系统设计",
            "difficulty": "hard",
            "question": "如何设计一个短链系统？",
            "reference_answer": "发号器 + 缓存",
            "tags": ["系统设计"],
        },
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["source_type"] == "manual"
    assert created["status"] == "new"

    listed = client.get("/api/questions").json()
    assert [item["id"] for item in listed] == [created["id"]]

    review_response = client.post(
        f"/api/questions/{created['id']}/reviews",
        json={"rating": 3, "note": "答得不错"},
    )
    assert review_response.status_code == 201
    reviewed = review_response.json()["question"]
    assert reviewed["status"] == "mastered"
    assert reviewed["practice_count"] == 1

    bad_rating = client.post(f"/api/questions/{created['id']}/reviews", json={"rating": 9})
    assert bad_rating.status_code == 400
    assert bad_rating.json() == {"error": "rating 需为 1(不会)、2(模糊) 或 3(掌握)"}

    stats = client.get("/api/questions/stats").json()
    assert stats["total"] == 1
    assert stats["mastered"] == 1
    assert stats["today_reviews"] == 1

    delete_response = client.delete(f"/api/questions/{created['id']}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""


def test_question_validation_and_generate_missing_source(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    empty = client.post("/api/questions", json={"question": "   "})
    assert empty.status_code == 400
    assert empty.json() == {"error": "题目内容不能为空"}

    missing_kb = client.post("/api/questions/generate", json={"source": "knowledge"})
    assert missing_kb.status_code == 400
    assert missing_kb.json() == {"error": "请选择知识库"}


def test_question_generate_from_knowledge_persists_questions(tmp_path):
    model = JSONModel(
        {
            "questions": [
                {
                    "category": "Go并发",
                    "difficulty": "hard",
                    "question": "如何解释 goroutine 调度？",
                    "reference_answer": "GMP 模型",
                    "tags": ["go", "scheduler"],
                },
                {
                    "category": "Go并发",
                    "difficulty": "困难",
                    "question": "如何解释 goroutine 调度？",
                    "reference_answer": "重复题",
                    "tags": [],
                },
            ]
        }
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    base = client.post("/api/knowledge-bases", json={"name": "Go notes"}).json()
    client.post(
        "/api/knowledge-documents",
        json={
            "knowledge_base_id": base["id"],
            "title": "Scheduler",
            "content": "goroutine scheduler GMP",
            "tags": [],
        },
    )

    response = client.post(
        "/api/questions/generate",
        json={"source": "knowledge", "knowledge_base_id": base["id"], "count": 2},
    )

    assert response.status_code == 201
    generated = response.json()
    assert generated["count"] == 1
    assert generated["skipped"] == 1
    assert generated["questions"][0]["source_type"] == "ai_knowledge"
    assert generated["questions"][0]["difficulty"] == "hard"
    assert client.get("/api/questions?knowledge_base_id=" + str(base["id"])).json()[0][
        "question"
    ] == "如何解释 goroutine 调度？"
