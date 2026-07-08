import json

import pytest
from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant, ToolCall
from offerpilot.api import create_app
from offerpilot.config import Config, save_config


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


class CapturingScriptedModel(ScriptedModel):
    def __init__(self, turns):
        super().__init__(turns)
        self.calls = []
        self.tools = []

    def complete(self, messages, tools):
        self.calls.append(messages)
        self.tools.append(tools)
        return super().complete(messages, tools)


class FailingModel:
    def complete(self, messages, tools):
        raise RuntimeError("provider unavailable")


class SecretLeakingModel:
    def complete(self, messages, tools):
        raise RuntimeError("provider rejected API key sk-secret-value")


def test_chat_returns_bad_gateway_when_model_fails(tmp_path):
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=FailingModel()),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})

    assert response.status_code == 502
    assert response.json() == {"error": "AI provider request failed: provider unavailable"}


def test_chat_provider_error_masks_configured_api_key(tmp_path):
    save_config(tmp_path, Config(api_key="sk-secret-value"))
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=SecretLeakingModel()),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})

    assert response.status_code == 502
    assert "sk-secret-value" not in response.text
    assert response.json() == {"error": "AI provider request failed: provider rejected API key ***"}


def test_chat_exposes_module_tools_to_model(tmp_path):
    model = CapturingScriptedModel([Assistant(content="ok")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "what context can you inspect?", "conversation_id": 0})

    assert response.status_code == 200
    captured_tools = {tool["name"] for tool in model.tools[0]}
    assert {"list_applications", "list_notes", "list_application_events", "list_offers"}.issubset(captured_tools)
    assert {"list_resumes", "list_jd_analyses", "list_knowledge_documents", "search_knowledge"}.issubset(
        captured_tools
    )


def test_chat_injects_response_structure_prompt(tmp_path):
    model = CapturingScriptedModel([Assistant(content="ok")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "what should I do next?", "conversation_id": 0})

    assert response.status_code == 200
    system = model.calls[0][0]
    assert system.role == "system"
    assert "Conclusion" in system.content
    assert "Evidence" in system.content
    assert "Next steps" in system.content


def test_chat_allows_wide_read_only_tool_summaries(tmp_path):
    model = ScriptedModel(
        [
            Assistant(tool_calls=[ToolCall(id="r1", name="list_applications", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r2", name="list_offers", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r3", name="list_notes", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r4", name="list_application_events", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r5", name="list_resumes", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r6", name="list_jd_analyses", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r7", name="list_knowledge_documents", args="{}")]),
            Assistant(tool_calls=[ToolCall(id="r8", name="search_knowledge", args=json.dumps({"query": "Java"}))]),
            Assistant(tool_calls=[ToolCall(id="r9", name="compare_offers", args=json.dumps({"ids": []}))]),
            Assistant(tool_calls=[ToolCall(id="r10", name="list_resume_matches", args=json.dumps({"resume_id": 1}))]),
            Assistant(tool_calls=[ToolCall(id="r11", name="get_application_event", args=json.dumps({"id": 1}))]),
            Assistant(tool_calls=[ToolCall(id="r12", name="get_knowledge_document", args=json.dumps({"id": 1}))]),
            Assistant(content="summary complete"),
        ]
    )
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=model),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "summarize everything", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert response.json()["message"] == "summary complete"


@pytest.mark.parametrize("args", ["{bad", "[]"])
def test_chat_pending_write_tolerates_invalid_args(tmp_path, args):
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=args,
                    )
                ]
            )
        ]
    )
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=model),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "update", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    assert response.json()["pending_action"] == {
        "tool_name": "update_application_status",
        "human": "update_application_status",
        "args": {},
    }


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
    assert response.json()["pending_action"]["args"] == {
        "id": application["id"],
        "status": "offer",
    }
    assert response.json()["pending_action"]["target"] == {
        "id": f"application-{application['id']}",
        "kind": "application",
        "title": "ByteDance",
        "meta": "Backend · interview",
        "source": "pending_action",
    }
    assert response.json()["pending_action"]["proposed_changes"] == [
        {"field": "status", "before": "interview", "after": "offer"}
    ]
    assert response.json()["pending_action"]["evidence"] == [
        {
            "id": f"application-{application['id']}",
            "kind": "application",
            "title": "ByteDance",
            "meta": "Backend · interview",
            "source": "pending_action",
        }
    ]
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


def test_chat_confirm_replays_reasoning_content_for_pending_tool(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    model = CapturingScriptedModel(
        [
            Assistant(
                provider_blocks={"reasoning_content": "selected target application"},
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": application["id"], "status": "offer"}),
                    )
                ],
            ),
            Assistant(content="updated"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "move it to offer", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    replayed_assistant = next(
        message for message in model.calls[1] if message.role == "assistant" and message.tool_calls
    )
    assert replayed_assistant.provider_blocks == {
        "reasoning_content": "selected target application"
    }


def test_chat_confirm_keeps_application_context_for_model(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "OpenAI", "position_name": "Research Engineer", "status": "interview"},
    ).json()
    model = CapturingScriptedModel(
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
            Assistant(content="Updated with context."),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post(
        "/api/chat",
        json={
            "message": "Move this to offer",
            "conversation_id": 0,
            "context_type": "application",
            "context_ref": str(application["id"]),
        },
    ).json()
    (tmp_path / "agent_checkpoints.sqlite").unlink()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert model.calls[1][1].role == "system"
    assert "Current conversation context" in model.calls[1][1].content
    assert "OpenAI" in model.calls[1][1].content


def test_chat_confirm_resumes_pending_write_from_langgraph_checkpoint(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    first_model = ScriptedModel(
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
    client = TestClient(create_app(data_dir=tmp_path, chat_model=first_model))

    pending = client.post("/api/chat", json={"message": "move it to offer", "conversation_id": 0}).json()

    assert pending["type"] == "confirmation_required"
    assert (tmp_path / "agent_checkpoints.sqlite").exists()

    second_model = ScriptedModel([Assistant(content="updated")])
    reloaded_client = TestClient(create_app(data_dir=tmp_path, chat_model=second_model))
    response = reloaded_client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "updated"
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "offer"


def test_chat_conversation_exposes_pending_action_for_reload(tmp_path):
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
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "改成 offer", "conversation_id": 0}).json()

    conversations = client.get("/api/chat/conversations").json()

    assert conversations[0]["id"] == pending["conversation_id"]
    assert conversations[0]["pending_action"] == pending["pending_action"]
    assert conversations[0]["pending_action"]["target"]["title"] == "ByteDance"


def test_chat_confirm_clears_persisted_pending_action(tmp_path):
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
    assert client.get("/api/chat/conversations").json()[0]["pending_action"] is None


def test_chat_confirm_returns_args_for_chained_pending_write(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    first = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    second = app_client.post(
        "/api/applications",
        json={"company_name": "OpenAI", "position_name": "Product", "status": "applied"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": first["id"], "status": "offer"}),
                    )
                ]
            ),
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w2",
                        name="update_application_status",
                        args=json.dumps({"id": second["id"], "status": "interview"}),
                    )
                ]
            ),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "update two", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    assert response.json()["pending_action"]["tool_name"] == "update_application_status"
    assert response.json()["pending_action"]["args"] == {
        "id": second["id"],
        "status": "interview",
    }


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


def test_chat_context_creates_application_scoped_conversation(tmp_path):
    model = ScriptedModel([Assistant(content="已读取投递上下文")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    created = client.post(
        "/api/chat",
        json={
            "message": "看看这条投递",
            "conversation_id": 0,
            "context_type": "application",
            "context_ref": "42",
        },
    ).json()
    conversation = client.get("/api/chat/conversations").json()[0]

    assert conversation["id"] == created["conversation_id"]
    assert conversation["mode"] == "general"
    assert conversation["context_type"] == "application"
    assert conversation["context_ref"] == "42"
    assert "offer_id" not in conversation


def test_chat_injects_application_context_for_model(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={
            "company_name": "OpenAI",
            "position_name": "Research Engineer",
            "status": "interview",
            "notes": "Focus on agent evals.",
        },
    ).json()
    model = CapturingScriptedModel([Assistant(content="I have the application context.")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post(
        "/api/chat",
        json={
            "message": "What should I prepare?",
            "conversation_id": 0,
            "context_type": "application",
            "context_ref": str(application["id"]),
        },
    )

    assert response.status_code == 200
    injected = model.calls[0][1]
    assert injected.role == "system"
    assert "Current conversation context" in injected.content
    assert "OpenAI" in injected.content
    assert "Research Engineer" in injected.content
    assert "interview" in injected.content
    assert "Focus on agent evals." in injected.content


def test_chat_without_context_defaults_to_workspace(tmp_path):
    model = ScriptedModel([Assistant(content="你好")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    created = client.post("/api/chat", json={"message": "hello", "conversation_id": 0}).json()
    conversation = client.get("/api/chat/conversations").json()[0]

    assert conversation["id"] == created["conversation_id"]
    assert conversation["context_type"] == "workspace"
    assert conversation["context_ref"] == ""


def test_chat_without_configured_ai_returns_503(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})

    assert response.status_code == 503
    assert response.json() == {"error": "AI is not configured: run `oc config` to set your API key"}
