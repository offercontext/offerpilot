from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver

from offerpilot.agent_runtime.journal import NullRunRecorder
from offerpilot.ai.agent import LangGraphAgentRunner
from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import ProviderToolContract, ToolSpec
from offerpilot.ai.types import Assistant, Message, ToolCall


class PendingWriteModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[Message], tools: list[ProviderToolContract]) -> Assistant:
        del messages, tools
        self.calls += 1
        if self.calls > 1:
            return Assistant(content="done")
        return Assistant(
            tool_calls=[ToolCall(id="write-1", name="write_one", args='{"id":1}')]
        )


class ReadThenFinishModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[Message], tools: list[ProviderToolContract]) -> Assistant:
        del messages, tools
        self.calls += 1
        if self.calls > 1:
            return Assistant(content="done")
        return Assistant(
            tool_calls=[ToolCall(id="read-1", name="read_one", args='{"id":1}')]
        )


def _runtime(checkpoint_path: Path) -> LangGraphAgentRunner:
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }
    contract = ProviderToolContract(
        payload={
            "type": "function",
            "function": {
                "name": "write_one",
                "description": "write",
                "parameters": parameters,
            },
        },
        name="write_one",
        description="write",
        parameters=parameters,
    )
    spec = ToolSpec(
        contract=contract,
        kind="write",
        decoder=lambda values: dict(values),
        executor=lambda args, context: args,
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_WRITE}),
        confirmation_policy="required",
    )
    catalog = ToolCatalog((spec,), expected_names=(spec.name,))
    dependency = cast(Any, object())
    context = ToolExecutionContext(
        applications=dependency,
        capabilities=frozenset({ToolCapability.APPLICATIONS_WRITE}),
        current_bindings={"application": 1},
        events=dependency,
        jd_analyses=dependency,
        notes=dependency,
        offers=dependency,
        resumes=dependency,
        run_recorder=NullRunRecorder(),
    )
    return LangGraphAgentRunner(
        PendingWriteModel(),
        catalog,
        context,
        checkpoint_path=checkpoint_path,
        thread_id="checkpoint-negative-gate",
    )


def _read_runtime(checkpoint_path: Path) -> LangGraphAgentRunner:
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }
    contract = ProviderToolContract(
        payload={
            "type": "function",
            "function": {
                "name": "read_one",
                "description": "read",
                "parameters": parameters,
            },
        },
        name="read_one",
        description="read",
        parameters=parameters,
    )
    spec = ToolSpec(
        contract=contract,
        kind="read",
        decoder=lambda values: dict(values),
        executor=lambda args, context: args,
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
    )
    catalog = ToolCatalog((spec,), expected_names=(spec.name,))
    dependency = cast(Any, object())
    context = ToolExecutionContext(
        applications=dependency,
        capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
        current_bindings={"application": 1},
        events=dependency,
        jd_analyses=dependency,
        notes=dependency,
        offers=dependency,
        resumes=dependency,
        run_recorder=NullRunRecorder(),
    )
    return LangGraphAgentRunner(
        ReadThenFinishModel(),
        catalog,
        context,
        checkpoint_path=checkpoint_path,
        thread_id="checkpoint-read-negative-gate",
    )


def _walk(value: object) -> list[object]:
    found = [value]
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_walk(key))
            found.extend(_walk(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.extend(_walk(item))
    elif hasattr(value, "__dict__"):
        found.extend(_walk(vars(value)))
    return found


def _assert_checkpoint_has_no_transient_runtime_values(
    checkpoint_path: Path,
    thread_id: str,
) -> None:
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        checkpoint = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    assert checkpoint is not None
    values = _walk(
        {
            "checkpoint": checkpoint.checkpoint,
            "metadata": checkpoint.metadata,
            "pending_writes": checkpoint.pending_writes,
        }
    )

    forbidden_keys = {
        "binding",
        "binding_audit",
        "capabilities",
        "outcome",
        "typed_args",
        "typed_result",
        "tool_catalog",
        "tool_execution_context",
        "tool_execution_record",
    }
    assert not (forbidden_keys & {value.lower() for value in values if isinstance(value, str)})
    assert all(
        not type(value).__module__.startswith("offerpilot.ai.tool_runtime")
        for value in values
    )
    assert all(not isinstance(value, BaseException) for value in values)


def test_checkpoint_contains_only_compatible_messages_and_control_state(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "agent-checkpoint.sqlite"
    result = _runtime(checkpoint_path).run_turn(
        [Message(role="user", content="write")],
        auto_approve=False,
    )
    assert result.pending is not None
    assert result.records == ()

    _assert_checkpoint_has_no_transient_runtime_values(
        checkpoint_path,
        "checkpoint-negative-gate",
    )


def test_checkpoint_after_read_execution_contains_no_transient_runtime_values(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "read-checkpoint.sqlite"
    result = _read_runtime(checkpoint_path).run_turn(
        [Message(role="user", content="read")],
        auto_approve=False,
    )

    assert result.pending is None
    assert len(result.records) == 1
    _assert_checkpoint_has_no_transient_runtime_values(
        checkpoint_path,
        "checkpoint-read-negative-gate",
    )


def test_checkpoint_after_confirmed_write_contains_no_transient_runtime_values(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "write-checkpoint.sqlite"
    runner = _runtime(checkpoint_path)
    initial = runner.run_turn(
        [Message(role="user", content="write")],
        auto_approve=False,
    )
    assert initial.pending is not None

    result = runner.resume_after_confirm(
        [Message(role="user", content="write")],
        initial.pending,
        approved=True,
        auto_approve=False,
    )

    assert len(result.records) == 1
    _assert_checkpoint_has_no_transient_runtime_values(
        checkpoint_path,
        "checkpoint-negative-gate",
    )
