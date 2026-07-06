import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant, ToolCall
from offerpilot.api import create_app
from offerpilot.config import Config, save_config


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


def test_chat_write_tool_requires_confirmation_before_mutating(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": application["id"], "status": "offer"}),
                    )
                ]
            )
        ]
    )
    chat_client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = chat_client.post("/api/chat", json={"message": "帮我把这条改成 offer", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    assert response.json()["pending_action"]["tool_name"] == "update_application_status"
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "interview"


def test_chat_confirm_executes_pending_write(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": application["id"], "status": "offer"}),
                    )
                ]
            ),
            Assistant(content="已更新"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "改成 offer", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "type": "message",
        "conversation_id": pending["conversation_id"],
        "message": "已更新",
    }
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "offer"


def test_chat_auto_approve_executes_write_without_pending(tmp_path):
    save_config(tmp_path, Config(api_key="sk-test", chat_auto_approve_writes=True))
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": application["id"], "status": "offer"}),
                    )
                ]
            ),
            Assistant(content="已更新"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "改成 offer", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "offer"


def test_chat_conversations_detail_and_delete(tmp_path):
    model = ScriptedModel([Assistant(content="你好")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    created = client.post("/api/chat", json={"message": "hello", "conversation_id": 0}).json()

    conversations = client.get("/api/chat/conversations").json()
    messages = client.get(f"/api/chat/conversations/{created['conversation_id']}").json()
    deleted = client.delete(f"/api/chat/conversations/{created['conversation_id']}")

    assert conversations[0]["id"] == created["conversation_id"]
    assert messages[0]["role"] == "user"
    assert deleted.status_code == 200
    assert client.get("/api/chat/conversations").json() == []


def test_chat_offer_id_creates_nego_conversation(tmp_path):
    model = ScriptedModel([Assistant(content="开始谈薪")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    created = client.post(
        "/api/chat",
        json={"message": "帮我谈这个 offer", "conversation_id": 0, "offer_id": 42},
    ).json()
    conversation = client.get("/api/chat/conversations").json()[0]

    assert conversation["id"] == created["conversation_id"]
    assert conversation["mode"] == "nego_coach"
    assert conversation["offer_id"] == 42


def test_chat_without_configured_ai_returns_503(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})

    assert response.status_code == 503
    assert response.json() == {"error": "AI is not configured: run `oc config` to set your API key"}
