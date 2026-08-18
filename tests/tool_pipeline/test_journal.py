from __future__ import annotations

from typing import Any, cast

from golden import load_golden

from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    ConfirmationRequired,
    ProviderToolContract,
    ReadyToExecute,
    ToolFailure,
    ToolSpec,
)
from offerpilot.ai.tool_runtime.pipeline import execute_prepared, prepare_call
from offerpilot.ai.types import ToolCall
from offerpilot.agent_runtime.journal import EventInput


class FailingStartedRecorder:
    def __init__(self, *, fail_started: bool = False) -> None:
        self.events: list[Any] = []
        self.fail_started = fail_started
        self.recording_status = "healthy"

    def append_event(self, event: Any) -> None:
        if self.fail_started and event.event_type == "tool.started":
            self.recording_status = "degraded"
            raise RuntimeError("journal unavailable")
        self.events.append(event)


def _runtime(recorder: FailingStartedRecorder, executor: Any) -> tuple[ToolCatalog, ToolExecutionContext, ToolSpec[Any, Any]]:
    parameters = {"properties": {"id": {"type": "integer"}}, "type": "object"}
    spec = ToolSpec(
        contract=ProviderToolContract(
            payload={
                "type": "function",
                "function": {
                    "description": "read",
                    "name": "list_applications",
                    "parameters": parameters,
                },
            },
            name="list_applications",
            description="read",
            parameters=parameters,
        ),
        decoder=lambda values: dict(values),
        executor=executor,
        kind="read",
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
        success_renderer=lambda result: '{"items":[]}',
    )
    dependency = cast(Any, object())
    context = ToolExecutionContext(
        applications=dependency,
        capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
        current_bindings={},
        events=dependency,
        jd_analyses=dependency,
        notes=dependency,
        offers=dependency,
        resumes=dependency,
        run_recorder=cast(Any, recorder),
    )
    return ToolCatalog([spec], expected_names=(spec.name,)), context, spec


def test_pipeline_journal_sequence_matches_first_phase_golden() -> None:
    recorder = FailingStartedRecorder()
    catalog, context, spec = _runtime(recorder, lambda args, runtime: {"items": []})
    prepared = prepare_call(
        catalog,
        context,
        ToolCall(id="read-1", name=spec.name, args="{}"),
    )
    assert isinstance(prepared, ReadyToExecute)

    execute_prepared(prepared.prepared, context)

    expected = load_golden("journal_sequences_30c944f.json")["cases"]["read_success"]
    assert [event.event_type for event in recorder.events] == [
        item["event_type"] for item in expected
    ]
    started = recorder.events[1]
    assert started.facts["result_contract"] == "legacy_string_v1"


def _assert_golden_case(case_name: str, events: list[EventInput]) -> None:
    expected = load_golden("journal_sequences_30c944f.json")["cases"][case_name]
    assert [
        {"event_type": event.event_type, "facts": dict(event.facts)} for event in events
    ] == expected


def _write_runtime(
    recorder: FailingStartedRecorder,
    executor: Any,
) -> tuple[ToolCatalog, ToolExecutionContext, ToolSpec[Any, Any]]:
    parameters = {
        "properties": {
            "id": {"type": "integer"},
            "status": {"type": "string"},
        },
        "required": ["id", "status"],
        "type": "object",
    }
    spec = ToolSpec(
        contract=ProviderToolContract(
            payload={
                "type": "function",
                "function": {
                    "description": "write",
                    "name": "update_application_status",
                    "parameters": parameters,
                },
            },
            name="update_application_status",
            description="write",
            parameters=parameters,
        ),
        decoder=lambda values: dict(values),
        executor=executor,
        kind="write",
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_WRITE}),
        confirmation_policy="required",
    )
    dependency = cast(Any, object())
    context = ToolExecutionContext(
        applications=dependency,
        capabilities=frozenset({ToolCapability.APPLICATIONS_WRITE}),
        current_bindings={},
        events=dependency,
        jd_analyses=dependency,
        notes=dependency,
        offers=dependency,
        resumes=dependency,
        run_recorder=cast(Any, recorder),
    )
    return ToolCatalog([spec], expected_names=(spec.name,)), context, spec


def _append_approval_requested(recorder: FailingStartedRecorder) -> None:
    recorder.events.append(
        EventInput(
            event_type="approval.requested",
            facts={
                "confirmation_mode": "required",
                "pending_identity_fingerprint": "b" * 64,
                "tool_call_id": "write-1",
            },
        )
    )


def _append_approval_decided(recorder: FailingStartedRecorder, decision: str) -> None:
    recorder.events.append(
        EventInput(
            event_type="approval.decided",
            facts={
                "confirmation_attempt_id": "00000000-0000-0000-0000-000000000005",
                "decided_input_fingerprint": "c" * 64,
                "decision": decision,
                "original_input_fingerprint": "c" * 64,
                "tool_call_id": "write-1",
            },
        )
    )


def test_executor_exception_journal_sequence_matches_first_phase_golden() -> None:
    recorder = FailingStartedRecorder()

    def fail(args: Any, context: ToolExecutionContext) -> Any:
        del args, context
        raise RuntimeError("private executor detail")

    catalog, context, spec = _runtime(recorder, fail)
    prepared = prepare_call(
        catalog,
        context,
        ToolCall(id="read-1", name=spec.name, args="{}"),
    )
    assert isinstance(prepared, ReadyToExecute)

    execute_prepared(prepared.prepared, context)

    _assert_golden_case("executor_exception", recorder.events)


def test_write_waiting_and_rejection_sequences_match_first_phase_golden() -> None:
    recorder = FailingStartedRecorder()
    catalog, context, spec = _write_runtime(recorder, lambda args, runtime: args)
    prepared = prepare_call(
        catalog,
        context,
        ToolCall(
            id="write-1",
            name=spec.name,
            args='{"id":1,"status":"offer"}',
        ),
        pending_identity="write-1:update_application_status",
        pending_action_revision=1,
    )
    assert isinstance(prepared, ConfirmationRequired)
    _append_approval_requested(recorder)

    _assert_golden_case("write_waiting_confirmation", recorder.events)

    _append_approval_decided(recorder, "rejected")
    _assert_golden_case("confirmation_rejected", recorder.events)
    assert not any(
        event.event_type in {"tool.started", "tool.completed", "tool.failed"}
        for event in recorder.events
    )


def test_pre_execution_stale_claim_sequence_matches_first_phase_golden() -> None:
    recorder = FailingStartedRecorder()
    catalog, context, spec = _write_runtime(recorder, lambda args, runtime: args)
    prepared = prepare_call(
        catalog,
        context,
        ToolCall(
            id="write-1",
            name=spec.name,
            args='{"id":1,"status":"offer"}',
        ),
        pending_identity="write-1:update_application_status",
        pending_action_revision=1,
    )
    assert isinstance(prepared, ConfirmationRequired)
    _append_approval_requested(recorder)
    _append_approval_decided(recorder, "approved")

    record = execute_prepared(
        prepared.prepared,
        context,
        confirmation_claimer=lambda call: ToolFailure(
            "stale_state",
            "confirmation_claim_lost",
        ),
    )

    assert record.execution_started is False
    _assert_golden_case("pre_execution_stale_claim", recorder.events)


def test_pre_execution_validation_sequence_matches_first_phase_golden() -> None:
    recorder = FailingStartedRecorder()
    parameters = {
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
        "type": "object",
    }
    spec = ToolSpec(
        contract=ProviderToolContract(
            payload={
                "type": "function",
                "function": {
                    "description": "read",
                    "name": "get_application",
                    "parameters": parameters,
                },
            },
            name="get_application",
            description="read",
            parameters=parameters,
        ),
        decoder=lambda values: dict(values),
        executor=lambda args, runtime: args,
        kind="read",
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
    )
    dependency = cast(Any, object())
    context = ToolExecutionContext(
        applications=dependency,
        capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
        current_bindings={},
        events=dependency,
        jd_analyses=dependency,
        notes=dependency,
        offers=dependency,
        resumes=dependency,
        run_recorder=cast(Any, recorder),
    )
    catalog = ToolCatalog([spec], expected_names=(spec.name,))

    rejected = prepare_call(
        catalog,
        context,
        ToolCall(id="read-1", name=spec.name, args="not-json"),
    )

    assert not isinstance(rejected, ReadyToExecute)
    _assert_golden_case("pre_execution_validation_failure", recorder.events)


def test_started_projection_failure_degrades_and_suppresses_terminal_event() -> None:
    calls = 0

    def executor(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
        nonlocal calls
        del context
        calls += 1
        return args

    recorder = FailingStartedRecorder(fail_started=True)
    catalog, context, spec = _runtime(recorder, executor)
    prepared = prepare_call(
        catalog,
        context,
        ToolCall(id="read-1", name=spec.name, args='{"id":1}'),
    )
    assert isinstance(prepared, ReadyToExecute)

    record = execute_prepared(prepared.prepared, context)

    assert calls == 1
    assert record.execution_started is True
    assert [event.event_type for event in recorder.events] == ["tool.proposed"]
