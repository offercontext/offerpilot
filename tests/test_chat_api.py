import json
import time

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


class SlowModel:
    def complete(self, messages, tools):
        time.sleep(0.2)
        return Assistant(content="late reply")


def test_chat_returns_bad_gateway_when_model_fails(tmp_path):
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=FailingModel()),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "你好", "conversation_id": 0})

    assert response.status_code == 502
    assert response.json() == {"error": "AI provider request failed: provider unavailable"}


def test_chat_returns_recoverable_message_when_agent_times_out(tmp_path, monkeypatch):
    import offerpilot.api as api_module

    monkeypatch.setattr(api_module, "CHAT_AGENT_TIMEOUT_SECONDS", 0.01)
    client = TestClient(create_app(data_dir=tmp_path, chat_model=SlowModel()))

    response = client.post("/api/chat", json={"message": "帮我总结最近复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert response.json()["message"] == "这次处理时间过长，已停止。你可以重试或换一种问法。"
    stored = client.get(f"/api/chat/conversations/{response.json()['conversation_id']}").json()
    assert stored[-1]["role"] == "assistant"
    assert stored[-1]["content"] == "这次处理时间过长，已停止。你可以重试或换一种问法。"


def test_chat_provider_error_masks_configured_api_key(tmp_path):
    save_config(tmp_path, Config(api_key="sk-secret-value"))
    client = TestClient(
        create_app(data_dir=tmp_path, chat_model=SecretLeakingModel()),
        raise_server_exceptions=False,
    )

    response = client.post("/api/chat", json={"message": "你好", "conversation_id": 0})

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
    assert "one direct follow-up question" in system.content
    assert "After a successful write" in system.content


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


def test_chat_reply_hides_internal_tool_names(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                content=(
                    "下一步可通过 update_application_status 更新状态；"
                    "如有笔试安排，可使用 `create_application_event` 添加日程。"
                )
            )
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "下一步怎么办", "conversation_id": 0})

    assert response.status_code == 200
    message = response.json()["message"]
    assert "update_application_status" not in message
    assert "create_application_event" not in message
    assert "更新投递状态" in message
    assert "添加投递日程" in message
    stored = client.get(f"/api/chat/conversations/{response.json()['conversation_id']}").json()
    assistant_messages = [item["content"] for item in stored if item["role"] == "assistant"]
    assert assistant_messages == [message]


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
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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
        "title": "字节跳动",
        "meta": "后端工程师 · interview",
        "source": "pending_action",
    }
    assert response.json()["pending_action"]["proposed_changes"] == [
        {"field": "status", "before": "interview", "after": "offer"}
    ]
    assert response.json()["pending_action"]["evidence"] == [
        {
            "id": f"application-{application['id']}",
            "kind": "application",
            "title": "字节跳动",
            "meta": "后端工程师 · interview",
            "source": "pending_action",
        }
    ]
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "interview"


def test_chat_create_event_confirmation_includes_schedule_details(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="create_application_event",
                        args=json.dumps(
                            {
                                "application_id": application["id"],
                                "event_type": "written_test",
                                "subtype": "assessment",
                                "scheduled_at": "2026-07-10T19:00:00+08:00",
                                "duration_minutes": 30,
                                "notes": "牛客网 agent开发笔试",
                            }
                        ),
                    )
                ]
            )
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post(
        "/api/chat",
        json={"message": "为这个投递创建一个笔试日程，明晚7点，30分钟", "conversation_id": 0},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    pending = response.json()["pending_action"]
    assert pending["human"] == "新建日程：笔试 · 2026-07-10 19:00 · 30 分钟"
    assert pending["target"] == {
        "id": f"application-event-draft-{application['id']}",
        "kind": "application_event",
        "title": "笔试",
        "meta": "2026-07-10 19:00 · 30 分钟",
        "source": "pending_action",
        "snippet": "牛客网 agent开发笔试",
    }
    assert pending["proposed_changes"] == [
        {"field": "event_type", "before": "", "after": "written_test"},
        {"field": "subtype", "before": "", "after": "assessment"},
        {"field": "scheduled_at", "before": "", "after": "2026-07-10T19:00:00+08:00"},
        {"field": "duration_minutes", "before": "", "after": 30},
        {"field": "notes", "before": "", "after": "牛客网 agent开发笔试"},
    ]
    assert pending["evidence"] == [
        {
            "id": f"application-{application['id']}",
            "kind": "application",
            "title": "牛客网",
            "meta": "agent开发 · applied",
            "source": "pending_action",
        }
    ]


def test_chat_note_missing_company_asks_for_required_info_without_pending(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                content="没有找到对应的申请记录。我先帮你创建一份完整的面试复盘笔记。",
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="add_note",
                        args=json.dumps({"position": "软件测试工程师", "round": "技术面", "questions": "测试流程"}),
                    )
                ],
            ),
            Assistant(content="保存复盘前还需要公司名称，补充后我再帮你保存。"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "帮我保存面试复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert response.json()["message"] == "保存复盘前还需要公司名称，补充后我再帮你保存。"
    assert client.get("/api/chat/conversations").json()[0]["pending_action"] is None
    stored = client.get(f"/api/chat/conversations/{response.json()['conversation_id']}").json()
    assert any(item["role"] == "tool" and "add_note requires company" in item["content"] for item in stored)


def test_chat_create_application_confirmation_includes_record_details(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                content="我先为你创建新的申请记录。",
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="create_application",
                        args=json.dumps(
                            {
                                "company_name": "牛客网",
                                "position_name": "软件测试工程师",
                                "status": "interview",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            )
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "帮我保存牛客网软件测试工程师复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    pending = response.json()["pending_action"]
    assert pending["human"] == "新建投递：牛客网 - 软件测试工程师"
    assert pending["target"] == {
        "id": "application-draft-牛客网-软件测试工程师",
        "kind": "application",
        "title": "牛客网",
        "meta": "软件测试工程师 · interview",
        "source": "pending_action",
    }
    assert pending["proposed_changes"] == [
        {"field": "company_name", "before": "", "after": "牛客网"},
        {"field": "position_name", "before": "", "after": "软件测试工程师"},
        {"field": "status", "before": "", "after": "interview"},
    ]
    assert pending["workflow"] == {
        "current_step": 1,
        "total_steps": 2,
        "current_label": "新建投递",
        "next_label": "保存面试复盘",
        "description": "确认后我会继续保存这次面试复盘。",
    }


def test_chat_create_application_for_existing_company_requires_user_confirmation(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    app_client.post(
        "/api/applications",
        json={"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
    )
    model = ScriptedModel(
        [
            Assistant(
                content="我先为这次面试创建申请记录。",
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="create_application",
                        args=json.dumps(
                            {
                                "company_name": "牛客网",
                                "position_name": "软件测试工程师",
                                "status": "interview",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            ),
            Assistant(content="系统里已有牛客网的 agent开发 记录。要为软件测试工程师新建一条投递吗？"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "帮我保存牛客网软件测试工程师复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert response.json()["message"] == "系统里已有牛客网的 agent开发 记录。要为软件测试工程师新建一条投递吗？"
    assert client.get("/api/chat/conversations").json()[0]["pending_action"] is None
    stored = client.get(f"/api/chat/conversations/{response.json()['conversation_id']}").json()
    assert any(
        item["role"] == "tool" and "requires explicit user confirmation" in item["content"]
        for item in stored
    )


def test_chat_add_note_confirmation_includes_review_details(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="add_note",
                        args=json.dumps(
                            {
                                "company": "腾讯",
                                "position": "软件测试工程师",
                                "round": "技术面",
                                "date": "2026-07-09",
                                "questions": "测试流程和缺陷生命周期",
                                "difficulty_points": "自动化测试经验不足",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            )
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "帮我保存面试复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    pending = response.json()["pending_action"]
    assert pending["human"] == "新增复盘：腾讯 · 软件测试工程师 · 技术面"
    assert pending["target"] == {
        "id": "note-draft-腾讯-软件测试工程师",
        "kind": "note",
        "title": "腾讯",
        "meta": "软件测试工程师 · 技术面 · 2026-07-09",
        "source": "pending_action",
        "snippet": "测试流程和缺陷生命周期",
    }
    assert pending["proposed_changes"] == [
        {"field": "company", "before": "", "after": "腾讯"},
        {"field": "position", "before": "", "after": "软件测试工程师"},
        {"field": "round", "before": "", "after": "技术面"},
        {"field": "date", "before": "", "after": "2026-07-09"},
        {"field": "questions", "before": "", "after": "测试流程和缺陷生命周期"},
        {"field": "difficulty_points", "before": "", "after": "自动化测试经验不足"},
    ]
    assert pending["risk_hint"] == "基于本轮对话整理，请确认结构化内容无误。"
    assert pending["workflow"] == {
        "current_step": 2,
        "total_steps": 2,
        "current_label": "保存面试复盘",
        "description": "这是本次连续写入的最后一步。",
    }


def test_chat_add_note_placeholder_date_asks_before_confirmation(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                content="我先保存复盘。",
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="add_note",
                        args=json.dumps(
                            {
                                "company": "牛客网",
                                "position": "软件测试工程师",
                                "round": "技术一面",
                                "date": "2026年XX月XX日",
                                "questions": "测试流程",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            ),
            Assistant(content="面试日期还不明确。请补充具体日期，或告诉我以“日期待定”保存。"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post("/api/chat", json={"message": "帮我保存牛客网面试复盘", "conversation_id": 0})

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    assert response.json()["message"] == "面试日期还不明确。请补充具体日期，或告诉我以“日期待定”保存。"
    assert client.get("/api/chat/conversations").json()[0]["pending_action"] is None
    stored = client.get(f"/api/chat/conversations/{response.json()['conversation_id']}").json()
    assert any(item["role"] == "tool" and "date is unclear" in item["content"] for item in stored)


def test_chat_confirm_executes_pending_write(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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


def test_chat_cancel_pending_write_returns_short_local_message(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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
            )
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "改成 offer", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "type": "message",
        "conversation_id": pending["conversation_id"],
        "message": "已取消本次写入。你可以修改信息后让我重新整理。",
    }
    assert len(model.calls) == 1
    assert client.get("/api/chat/conversations").json()[0]["pending_action"] is None
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "interview"


def test_chat_confirm_add_note_returns_saved_record_summary(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="add_note",
                        args=json.dumps(
                            {
                                "company": "牛客网",
                                "position": "软件测试工程师",
                                "round": "技术一面",
                                "date": "2026-07-09",
                                "questions": "测试流程",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            ),
            Assistant(content="后续可以继续补充面试官追问。"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "保存复盘", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "message"
    message = response.json()["message"]
    assert "保存成功：复盘记录 #1 已保存（牛客网 · 软件测试工程师 · 技术一面）。" in message
    assert "后续可以继续补充面试官追问。" in message


def test_chat_confirm_create_application_continues_to_review_note_card(tmp_path):
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="create_application",
                        args=json.dumps(
                            {
                                "company_name": "牛客网",
                                "position_name": "软件测试工程师",
                                "status": "interview",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            ),
            Assistant(
                content="投递已创建，继续保存复盘。",
                tool_calls=[
                    ToolCall(
                        id="w2",
                        name="add_note",
                        args=json.dumps(
                            {
                                "application_id": 1,
                                "round": "技术一面",
                                "date": "2026-07-09",
                                "questions": "测试流程",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            ),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "保存牛客网面试复盘", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    next_pending = response.json()["pending_action"]
    assert next_pending["tool_name"] == "add_note"
    assert next_pending["target"]["title"] == "牛客网"
    assert next_pending["target"]["meta"] == "软件测试工程师 · 技术一面 · 2026-07-09"
    assert next_pending["workflow"] == {
        "current_step": 2,
        "total_steps": 2,
        "current_label": "保存面试复盘",
        "description": "这是本次连续写入的最后一步。",
    }


def test_chat_confirm_replays_reasoning_content_for_pending_tool(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
    ).json()
    model = CapturingScriptedModel(
        [
            Assistant(
                provider_blocks={"reasoning_content": "已选择目标投递"},
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": application["id"], "status": "offer"}),
                    )
                ],
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
    replayed_assistant = next(
        message for message in model.calls[1] if message.role == "assistant" and message.tool_calls
    )
    assert replayed_assistant.provider_blocks == {
        "reasoning_content": "已选择目标投递"
    }


def test_chat_confirm_keeps_application_context_for_model(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "启明智能", "position_name": "算法工程师", "status": "interview"},
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
            Assistant(content="已结合上下文更新。"),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post(
        "/api/chat",
        json={
            "message": "把这条投递改成 offer",
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
    assert "启明智能" in model.calls[1][1].content


def test_chat_confirm_resumes_pending_write_from_langgraph_checkpoint(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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

    pending = client.post("/api/chat", json={"message": "改成 offer", "conversation_id": 0}).json()

    assert pending["type"] == "confirmation_required"
    assert (tmp_path / "agent_checkpoints.sqlite").exists()

    second_model = ScriptedModel([Assistant(content="已更新")])
    reloaded_client = TestClient(create_app(data_dir=tmp_path, chat_model=second_model))
    response = reloaded_client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "已更新"
    assert app_client.get(f"/api/applications/{application['id']}").json()["status"] == "offer"


def test_chat_conversation_exposes_pending_action_for_reload(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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
    assert conversations[0]["pending_action"]["target"]["title"] == "字节跳动"


def test_chat_confirm_clears_persisted_pending_action(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    application = app_client.post(
        "/api/applications",
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
    ).json()
    second = app_client.post(
        "/api/applications",
        json={"company_name": "启明智能", "position_name": "产品经理", "status": "applied"},
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
        json={"company_name": "字节跳动", "position_name": "后端工程师", "status": "interview"},
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
    created = client.post("/api/chat", json={"message": "你好", "conversation_id": 0}).json()

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
            "company_name": "启明智能",
            "position_name": "算法工程师",
            "status": "interview",
            "notes": "重点准备智能体评测。",
        },
    ).json()
    model = CapturingScriptedModel([Assistant(content="我已读取投递上下文。")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    response = client.post(
        "/api/chat",
        json={
            "message": "我应该准备什么？",
            "conversation_id": 0,
            "context_type": "application",
            "context_ref": str(application["id"]),
        },
    )

    assert response.status_code == 200
    injected = model.calls[0][1]
    assert injected.role == "system"
    assert "Current conversation context" in injected.content
    assert "启明智能" in injected.content
    assert "算法工程师" in injected.content
    assert "interview" in injected.content
    assert "重点准备智能体评测。" in injected.content


def test_chat_without_context_defaults_to_workspace(tmp_path):
    model = ScriptedModel([Assistant(content="你好")])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))

    created = client.post("/api/chat", json={"message": "你好", "conversation_id": 0}).json()
    conversation = client.get("/api/chat/conversations").json()[0]

    assert conversation["id"] == created["conversation_id"]
    assert conversation["context_type"] == "workspace"
    assert conversation["context_ref"] == ""


def test_chat_without_configured_ai_returns_503(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/chat", json={"message": "你好", "conversation_id": 0})

    assert response.status_code == 503
    assert response.json() == {"error": "AI is not configured: run `oc config` to set your API key"}
