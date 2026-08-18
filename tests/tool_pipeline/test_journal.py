from __future__ import annotations

from typing import Any, cast

from golden import load_golden

from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import ProviderToolContract, ReadyToExecute, ToolSpec
from offerpilot.ai.tool_runtime.pipeline import execute_prepared, prepare_call
from offerpilot.ai.types import ToolCall


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
    parameters = {"properties": {"id": {"type": "integer"}}, "required": ["id"], "type": "object"}
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
        ToolCall(id="read-1", name=spec.name, args='{"id":1}'),
    )
    assert isinstance(prepared, ReadyToExecute)

    execute_prepared(prepared.prepared, context)

    expected = load_golden("journal_sequences_30c944f.json")["cases"]["read_success"]
    assert [event.event_type for event in recorder.events] == [
        item["event_type"] for item in expected
    ]
    started = recorder.events[1]
    assert started.facts["result_contract"] == "legacy_string_v1"


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
