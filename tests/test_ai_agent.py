import json

import pytest

import offerpilot.ai.agent as agent_module
from offerpilot.ai.agent import (
    ChatRunCancelled,
    LangGraphAgentRunner,
    PendingAction,
    prepare_pending_action,
    resume_after_confirm,
    run_turn,
)
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


class RecordingScriptedModel(ScriptedModel):
    def __init__(self, turns):
        super().__init__(turns)
        self.message_batches = []

    def complete(self, messages, tools):
        self.message_batches.append(list(messages))
        return super().complete(messages, tools)


def _editable_registry(calls=None, validate=None):
    calls = calls if calls is not None else []
    tool = {
        "write": True,
        "editable_fields": [
            {"field": "status", "type": "enum", "options": ["offer", "rejected"]},
            {"field": "title", "type": "string"},
            {"field": "note", "type": "long_text"},
            {"field": "score", "type": "number"},
            {"field": "active", "type": "boolean"},
            {"field": "scheduled_at", "type": "datetime"},
        ],
        "handler": lambda args: calls.append(args) or '{"ok":true}',
    }
    if validate is not None:
        tool["validate"] = validate
    return {"update_application_status": tool}


def _pending(args=None):
    return PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=json.dumps(args if args is not None else {"id": 7, "status": "offer"}),
        human="change status",
    )


def test_prepare_pending_action_merges_edited_status_and_preserves_id():
    pending = _pending({"id": 7, "status": "offer", "note": "old"})

    prepared = prepare_pending_action(pending, _editable_registry(), {"status": "rejected"})

    assert prepared is not pending
    assert prepared.tool_call_id == pending.tool_call_id
    assert prepared.tool_name == pending.tool_name
    assert prepared.human == pending.human
    assert prepared.args == '{"id":7,"status":"rejected","note":"old"}'
    assert json.loads(pending.args) == {"id": 7, "status": "offer", "note": "old"}


def test_prepare_pending_action_none_edits_leave_pending_unchanged():
    pending = _pending()

    assert prepare_pending_action(pending, {}, None) is pending


@pytest.mark.parametrize("edited", [["status"], "status", 1, True])
def test_prepare_pending_action_rejects_non_object_edits(edited):
    with pytest.raises(ValueError, match="object"):
        prepare_pending_action(_pending(), _editable_registry(), edited)


@pytest.mark.parametrize("edited_field", ["id", "application_id", "index", "unknown"])
def test_prepare_pending_action_rejects_non_editable_fields(edited_field):
    with pytest.raises(ValueError, match=edited_field):
        prepare_pending_action(_pending(), _editable_registry(), {edited_field: 99})


def test_prepare_pending_action_lists_all_non_editable_fields():
    with pytest.raises(ValueError) as exc_info:
        prepare_pending_action(_pending(), _editable_registry(), {"id": 1, "unknown": "x"})

    assert "id" in str(exc_info.value)
    assert "unknown" in str(exc_info.value)


def test_prepare_pending_action_rejects_unknown_tool():
    pending = PendingAction("w1", "missing", "{}", "missing")

    with pytest.raises(ValueError, match="missing"):
        prepare_pending_action(pending, _editable_registry(), {})


@pytest.mark.parametrize("raw_args", ["{", "[]", '"text"', "null", '{"score":NaN}'])
def test_prepare_pending_action_rejects_malformed_or_non_object_original_args(raw_args):
    pending = PendingAction("w1", "update_application_status", raw_args, "change status")

    with pytest.raises(ValueError, match="JSON object"):
        prepare_pending_action(pending, _editable_registry(), {})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", 3),
        ("note", 3),
        ("score", "3"),
        ("score", True),
        ("score", float("nan")),
        ("score", float("inf")),
        ("score", float("-inf")),
        ("active", 1),
        ("scheduled_at", 123),
        ("scheduled_at", ""),
        ("scheduled_at", "not-a-date"),
        ("status", 1),
        ("status", "waiting"),
    ],
)
def test_prepare_pending_action_rejects_invalid_edited_values(field, value):
    with pytest.raises(ValueError, match=field):
        prepare_pending_action(_pending(), _editable_registry(), {field: value})


def test_prepare_pending_action_accepts_all_supported_edited_types():
    prepared = prepare_pending_action(
        _pending(),
        _editable_registry(),
        {
            "status": "rejected",
            "title": "Backend Engineer",
            "note": "用户备注",
            "score": 3.5,
            "active": False,
            "scheduled_at": "2026-07-10T12:30:00Z",
        },
    )

    assert json.loads(prepared.args) == {
        "id": 7,
        "status": "rejected",
        "title": "Backend Engineer",
        "note": "用户备注",
        "score": 3.5,
        "active": False,
        "scheduled_at": "2026-07-10T12:30:00Z",
    }
    assert "用户备注" in prepared.args


def test_prepare_pending_action_rejects_unknown_descriptor_type():
    registry = _editable_registry()
    registry["update_application_status"]["editable_fields"] = [
        {"field": "status", "type": "object"}
    ]

    with pytest.raises(ValueError, match="unknown.*type|type.*unknown"):
        prepare_pending_action(_pending(), registry, {"status": "offer"})


def test_prepare_pending_action_runs_tool_validator_on_effective_args():
    seen = []

    def validate(args):
        seen.append(json.loads(args))
        return (
            "status transition is not allowed" if json.loads(args)["status"] == "rejected" else ""
        )

    with pytest.raises(ValueError, match="status transition is not allowed"):
        prepare_pending_action(
            _pending(), _editable_registry(validate=validate), {"status": "rejected"}
        )

    assert seen == [{"id": 7, "status": "rejected"}]


def test_in_memory_checkpoint_executes_effective_args():
    calls = []
    registry = _editable_registry(calls)
    runner = LangGraphAgentRunner(
        ScriptedModel(
            [
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="update_application_status",
                            args=json.dumps({"id": 7, "status": "offer"}),
                        )
                    ]
                ),
                Assistant(content="done"),
            ]
        ),
        registry,
    )
    _, _, pending = runner.run_turn([], auto_approve=False, max_iter=8)
    assert pending is not None
    effective_pending = prepare_pending_action(pending, registry, {"status": "rejected"})

    _, reply, new_pending = runner.resume_after_confirm(
        [], effective_pending, approved=True, auto_approve=False, max_iter=8
    )

    assert calls == ['{"id":7,"status":"rejected"}']
    assert reply == "done"
    assert new_pending is None


def test_missing_checkpoint_fallback_executes_effective_args():
    calls = []
    registry = _editable_registry(calls)
    effective_pending = prepare_pending_action(_pending(), registry, {"status": "rejected"})

    _, reply, new_pending = resume_after_confirm(
        ScriptedModel([Assistant(content="done")]),
        registry,
        [],
        effective_pending,
        approved=True,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == ['{"id":7,"status":"rejected"}']
    assert reply == "done"
    assert new_pending is None


@pytest.mark.parametrize(
    "effective_args",
    [
        None,
        {"id": 7, "status": "rejected"},
        '{"id":999,"status":"offer"}',
        '{"id":7.0,"status":"offer"}',
    ],
)
def test_approved_resume_rejects_missing_or_non_string_effective_args(monkeypatch, effective_args):
    calls = []
    registry = _editable_registry(calls)
    runner = LangGraphAgentRunner(ScriptedModel([]), registry)
    resume_payload = {"approved": True}
    if effective_args is not None:
        resume_payload["effective_args"] = effective_args
    monkeypatch.setattr(agent_module, "interrupt", lambda pending: resume_payload)

    result = runner._handle_tool(
        {
            "messages": [],
            "added": [],
            "auto_approve": False,
            "current_tool_calls": [
                {
                    "id": "w1",
                    "name": "update_application_status",
                    "args": json.dumps({"id": 7, "status": "offer"}),
                }
            ],
        }
    )

    assert calls == []
    assert result["added"][0]["content"].startswith("错误：")


def test_resume_does_not_treat_non_boolean_approval_as_approved(monkeypatch):
    calls = []
    registry = _editable_registry(calls)
    runner = LangGraphAgentRunner(ScriptedModel([]), registry)
    monkeypatch.setattr(
        agent_module,
        "interrupt",
        lambda pending: {"approved": "true", "effective_args": pending["args"]},
    )

    result = runner._handle_tool(
        {
            "messages": [],
            "added": [],
            "auto_approve": False,
            "current_tool_calls": [
                {
                    "id": "w1",
                    "name": "update_application_status",
                    "args": json.dumps({"id": 7, "status": "offer"}),
                }
            ],
        }
    )

    assert calls == []
    assert result["added"][0]["content"].startswith("用户拒绝")


def test_missing_checkpoint_validates_effective_args_before_handler_execution():
    calls = []
    registry = _editable_registry(calls, validate=lambda args: "blocked effective arguments")

    added, reply, new_pending = resume_after_confirm(
        ScriptedModel([Assistant(content="not executed")]),
        registry,
        [],
        _pending(),
        approved=True,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == []
    assert added[0].content == "错误：blocked effective arguments"
    assert reply == "not executed"
    assert new_pending is None


def test_missing_checkpoint_does_not_treat_non_boolean_approval_as_approved():
    calls = []

    added, _, _ = resume_after_confirm(
        ScriptedModel([Assistant(content="not executed")]),
        _editable_registry(calls),
        [],
        _pending(),
        approved="false",
        auto_approve=False,
        max_iter=8,
    )

    assert calls == []
    assert added[0].content.startswith("用户拒绝")


def test_rejection_feedback_reaches_next_model_turn_without_handler_execution():
    calls = []
    model = RecordingScriptedModel([Assistant(content="understood")])

    added, reply, new_pending = resume_after_confirm(
        model,
        _editable_registry(calls),
        [],
        _pending(),
        approved=False,
        auto_approve=False,
        max_iter=8,
        rejection_feedback="  Keep it in offer status.  ",
    )

    assert calls == []
    assert reply == "understood"
    assert new_pending is None
    assert "用户拒绝" in added[0].content
    assert "Keep it in offer status." in added[0].content
    assert "Keep it in offer status." in model.message_batches[0][-1].content


def test_empty_rejection_feedback_keeps_generic_rejection_message():
    calls = []
    model = RecordingScriptedModel([Assistant(content="cancelled")])

    added, _, _ = resume_after_confirm(
        model,
        _editable_registry(calls),
        [],
        _pending(),
        approved=False,
        auto_approve=False,
        rejection_feedback="   ",
    )

    assert calls == []
    assert added[0].content == "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"


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
