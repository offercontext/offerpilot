import json

from offerpilot.ai.agent import LangGraphAgentRunner, PendingAction, resume_after_confirm, run_turn
from offerpilot.ai.types import Assistant, ToolCall


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


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

