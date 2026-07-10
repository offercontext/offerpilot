import json

import pytest

from offerpilot.ai.agent import ChatRunCancelled, LangGraphAgentRunner, PendingAction, resume_after_confirm, run_turn
from offerpilot.ai.types import Assistant, ToolCall


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


class StreamingScriptedModel:
    def stream_complete(self, messages, tools, on_delta):
        on_delta("流式")
        on_delta("回复")
        return Assistant(content="流式回复")

    def complete(self, messages, tools):
        raise AssertionError("stream_complete should be preferred when available")


def test_write_tool_pauses_before_execution():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": 1, "status": "offer"}),
                    )
                ]
            )
        ]
    )

    added, reply, pending = run_turn(model, registry, [], auto_approve=False, max_iter=8)

    assert reply == ""
    assert isinstance(pending, PendingAction)
    assert pending.human == "change status"
    assert calls == []
    assert added[-1].tool_calls[0].name == "update_application_status"


def test_confirm_executes_pending_write():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or '{"ok":true}',
        }
    }
    model = ScriptedModel([Assistant(content="done")])
    pending = PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=json.dumps({"id": 1, "status": "offer"}),
        human="change status",
    )

    added, reply, new_pending = resume_after_confirm(
        model,
        registry,
        [],
        pending,
        approved=True,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == [json.dumps({"id": 1, "status": "offer"})]
    assert added[0].role == "tool"
    assert reply == "done"
    assert new_pending is None


def test_reject_does_not_execute_pending_write():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "handler": lambda args: calls.append(args) or '{"ok":true}',
        }
    }
    model = ScriptedModel([Assistant(content="cancelled")])
    pending = PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=json.dumps({"id": 1, "status": "offer"}),
        human="change status",
    )

    added, reply, new_pending = resume_after_confirm(
        model,
        registry,
        [],
        pending,
        approved=False,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == []
    assert "用户拒绝了该操作" in added[0].content
    assert reply == "cancelled"
    assert new_pending is None


def test_event_sink_emits_read_tool_call_and_result():
    events = []
    registry = {
        "list_applications": {
            "write": False,
            "description": "List job applications.",
            "handler": lambda args: '{"items":[]}',
        }
    }
    model = ScriptedModel(
        [
            Assistant(tool_calls=[ToolCall(id="r1", name="list_applications", args="{}")]),
            Assistant(content="done"),
        ]
    )

    added, reply, pending = run_turn(
        model,
        registry,
        [],
        auto_approve=False,
        max_iter=8,
        event_sink=events.append,
    )

    assert reply == "done"
    assert pending is None
    assert added[1].role == "tool"
    assert events == [
        {
            "event": "tool_call",
            "data": {
                "tool_call_id": "r1",
                "tool_name": "list_applications",
                "public_label": "List job applications.",
                "kind": "read",
                "confirm_mode": "none",
                "summary": "List job applications.",
                "args_summary": {},
            },
        },
        {
            "event": "tool_result",
            "data": {
                "tool_call_id": "r1",
                "tool_name": "list_applications",
                "status": "success",
                "summary": '{"items":[]}',
                "evidence": [],
                "affected_resources": [],
                "changed_entities": [],
            },
        },
    ]


def test_executes_multiple_read_only_tool_calls_from_one_assistant_turn():
    calls = []
    registry = {
        "list_applications": {
            "write": False,
            "description": "查看投递列表",
            "handler": lambda args: calls.append(("apps", args)) or "[]",
        },
        "list_notes": {
            "write": False,
            "description": "查看复盘记录",
            "handler": lambda args: calls.append(("notes", args)) or "[]",
        },
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(id="r1", name="list_applications", args="{}"),
                    ToolCall(id="r2", name="list_notes", args=json.dumps({"limit": 3})),
                ]
            ),
            Assistant(content="已汇总。"),
        ]
    )

    added, reply, pending = run_turn(model, registry, [], auto_approve=False, max_iter=8)

    assert reply == "已汇总。"
    assert pending is None
    assert [call[0] for call in calls] == ["apps", "notes"]
    assert added[0].role == "assistant"
    assert [tool.name for tool in added[0].tool_calls] == ["list_applications", "list_notes"]
    assert [message.tool_call_id for message in added if message.role == "tool"] == ["r1", "r2"]


def test_always_confirm_write_pauses_even_when_auto_approve_is_enabled():
    calls = []
    registry = {
        "delete_note": {
            "write": True,
            "always_confirm": True,
            "describe": lambda args: "删除复盘记录",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="d1",
                        name="delete_note",
                        args=json.dumps({"id": 1}),
                    )
                ]
            )
        ]
    )

    added, reply, pending = run_turn(model, registry, [], auto_approve=True, max_iter=8)

    assert reply == ""
    assert isinstance(pending, PendingAction)
    assert pending.tool_name == "delete_note"
    assert calls == []
    assert added[-1].tool_calls[0].name == "delete_note"


def test_auto_approved_write_still_runs_validation_before_execution():
    calls = []
    registry = {
        "create_application": {
            "write": True,
            "validate": lambda args: "create_application requires explicit user confirmation before adding a new position",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="create_application",
                        args=json.dumps({"company_name": "牛客网", "position_name": "测试工程师"}),
                    )
                ]
            ),
            Assistant(content="需要你先确认。"),
        ]
    )

    added, reply, pending = run_turn(model, registry, [], auto_approve=True, max_iter=8)

    assert reply == "需要你先确认。"
    assert pending is None
    assert calls == []
    assert added[1].role == "tool"
    assert "requires explicit user confirmation" in added[1].content


def test_cancelled_run_does_not_execute_auto_approved_write():
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "更新投递状态",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": 1, "status": "offer"}),
                    )
                ]
            )
        ]
    )
    checks = iter([False, True])

    with pytest.raises(ChatRunCancelled):
        run_turn(model, registry, [], auto_approve=True, max_iter=8, cancel_check=lambda: next(checks, True))

    assert calls == []


def test_event_sink_emits_assistant_delta_from_streaming_model():
    events = []

    added, reply, pending = run_turn(
        StreamingScriptedModel(),
        {},
        [],
        auto_approve=False,
        max_iter=8,
        event_sink=events.append,
    )

    assert reply == "流式回复"
    assert pending is None
    assert added[-1].content == "流式回复"
    assert events == [
        {"event": "assistant_delta", "data": {"delta": "流式"}},
        {"event": "assistant_delta", "data": {"delta": "回复"}},
    ]


def test_event_sink_emits_write_tool_call_before_pending_confirmation():
    calls = []
    events = []
    registry = {
        "update_application_status": {
            "write": True,
            "description": "Update application status.",
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or "{}",
        }
    }
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": 1, "status": "offer"}),
                    )
                ]
            )
        ]
    )

    added, reply, pending = run_turn(
        model,
        registry,
        [],
        auto_approve=False,
        max_iter=8,
        event_sink=events.append,
    )

    assert reply == ""
    assert isinstance(pending, PendingAction)
    assert calls == []
    assert added[-1].tool_calls[0].name == "update_application_status"
    assert events == [
        {
            "event": "tool_call",
            "data": {
                "tool_call_id": "w1",
                "tool_name": "update_application_status",
                "public_label": "Update application status.",
                "kind": "write",
                "confirm_mode": "hitl",
                "summary": "change status",
                "args_summary": {"id": 1, "status": "offer"},
            },
        }
    ]


def test_event_sink_emits_tool_events_when_confirm_resumes_without_checkpoint():
    calls = []
    events = []
    registry = {
        "update_application_status": {
            "write": True,
            "description": "Update application status.",
            "handler": lambda args: calls.append(args) or '{"ok":true}',
        }
    }
    pending = PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=json.dumps({"id": 1, "status": "offer"}),
        human="change status",
    )
    model = ScriptedModel([Assistant(content="done")])

    added, reply, new_pending = resume_after_confirm(
        model,
        registry,
        [],
        pending,
        approved=True,
        auto_approve=False,
        max_iter=8,
        event_sink=events.append,
    )

    assert calls == [json.dumps({"id": 1, "status": "offer"})]
    assert added[0].role == "tool"
    assert reply == "done"
    assert new_pending is None
    assert [event["event"] for event in events] == ["tool_call", "tool_result"]
    assert events[0]["data"]["confirm_mode"] == "approved"
    assert events[1]["data"]["status"] == "success"


def test_langgraph_runner_resumes_pending_write_from_sqlite_checkpoint(tmp_path):
    calls = []
    registry = {
        "update_application_status": {
            "write": True,
            "describe": lambda args: "change status",
            "handler": lambda args: calls.append(args) or '{"ok":true}',
        }
    }
    checkpoint_path = tmp_path / "agent_checkpoints.sqlite"
    thread_id = "conversation:1"

    first_runner = LangGraphAgentRunner(
        ScriptedModel(
            [
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="update_application_status",
                            args=json.dumps({"id": 1, "status": "offer"}),
                        )
                    ]
                )
            ]
        ),
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
    )

    added, reply, pending = first_runner.run_turn([], auto_approve=False, max_iter=8)

    assert reply == ""
    assert isinstance(pending, PendingAction)
    assert pending.tool_call_id == "w1"
    assert calls == []
    assert checkpoint_path.exists()

    second_runner = LangGraphAgentRunner(
        ScriptedModel([Assistant(content="done")]),
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
    )

    added_after_confirm, reply_after_confirm, new_pending = second_runner.resume_after_confirm(
        [],
        pending,
        approved=True,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == [json.dumps({"id": 1, "status": "offer"})]
    assert added_after_confirm[0].role == "tool"
    assert reply_after_confirm == "done"
    assert new_pending is None
