import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Barrier, Lock
from typing import Any, Callable, Literal, Mapping
from uuid import UUID

import pytest

import offerpilot.ai.agent as agent_module
from offerpilot.ai.agent import (
    ChatRunCancelled,
    LangGraphAgentRunner as ProductionLangGraphAgentRunner,
    PendingAction,
    PendingActionValidationError,
    StalePendingActionError,
    prepare_pending_action as production_prepare_pending_action,
    resume_after_confirm as production_resume_after_confirm,
    run_turn as production_run_turn,
)
from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    ExecutionAuthorization,
    ProviderToolContract,
    ToolExceptionMapping,
    ToolFailure,
    ToolSpec,
    WriteContract,
)
from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.agent_runtime.events import ContextManifestInput
from offerpilot.agent_runtime.journal import EventInput
from offerpilot.agent_runtime.journal import NullRunRecorder
from offerpilot.db import init_database
from offerpilot.repositories.application_events import ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationsRepository
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.notes import NotesRepository
from offerpilot.repositories.offers import OffersRepository
from offerpilot.repositories.resumes import ResumesRepository


_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="offerpilot-agent-tests-"))
_TEST_SESSIONS = init_database(_TEST_DATA_DIR / "agent.db")


@dataclass(frozen=True)
class _ToolDefinition:
    name: str
    kind: Literal["read", "write"] = "read"
    executor: Callable[[str], str] = lambda _args: "{}"
    description: str = ""
    parameters: Mapping[str, Any] | None = None
    validator: Callable[[str], str] | None = None
    confirmation_description: Callable[[str], str] | None = None
    editable_fields: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class _ToolSet:
    definitions: tuple[_ToolDefinition, ...] = ()

    def with_tool(self, definition: _ToolDefinition) -> "_ToolSet":
        return _ToolSet(
            tuple(item for item in self.definitions if item.name != definition.name) + (definition,)
        )

    def replace(self, name: str, **changes: Any) -> "_ToolSet":
        current = next(item for item in self.definitions if item.name == name)
        return self.with_tool(replace(current, **changes))


def _tool(
    name: str,
    *,
    write: bool = False,
    executor: Callable[[str], str] | None = None,
    description: str = "",
    parameters: Mapping[str, Any] | None = None,
    validator: Callable[[str], str] | None = None,
    confirmation_description: Callable[[str], str] | None = None,
    editable_fields: tuple[Mapping[str, Any], ...] = (),
) -> _ToolDefinition:
    return _ToolDefinition(
        name=name,
        kind="write" if write else "read",
        executor=executor or (lambda _args: "{}"),
        description=description,
        parameters=parameters,
        validator=validator,
        confirmation_description=confirmation_description,
        editable_fields=editable_fields,
    )


def _tools(*definitions: _ToolDefinition) -> _ToolSet:
    return _ToolSet(tuple(definitions))


def _test_runtime(tools: _ToolSet) -> tuple[ToolCatalog, ToolExecutionContext]:
    specs = []
    names = []
    for definition in tools.definitions:
        name = definition.name
        names.append(definition.name)
        schema = definition.parameters or {"type": "object", "properties": {}}
        description = definition.description or name
        contract = ProviderToolContract(
            payload={
                "type": "function",
                "function": {"name": name, "description": description, "parameters": schema},
            },
            name=name,
            description=description,
            parameters=schema,
        )
        executor_callable = definition.executor
        validator = definition.validator

        def decoder(values: Any) -> dict[str, Any]:
            return dict(values)

        def executor(
            args: dict[str, Any],
            context: Any,
            executor_callable: Callable[[str], str] = executor_callable,
        ) -> str:
            del context
            return str(
                executor_callable(json.dumps(args, ensure_ascii=False, separators=(",", ":")))
            )

        def preflight(
            args: dict[str, Any],
            context: Any,
            validator: Callable[[str], str] | None = validator,
        ) -> ToolFailure | None:
            del context
            if validator is None:
                return None
            try:
                detail = str(
                    validator(json.dumps(args, ensure_ascii=False, separators=(",", ":"))) or ""
                )
            except Exception:
                detail = "工具参数验证失败，请检查后重试。"
            return ToolFailure("validation_error", "test_validation", detail) if detail else None

        describe = definition.confirmation_description

        def confirmation_description(
            args: dict[str, Any], describe: Any = describe, name: str = name
        ) -> str:
            if not callable(describe):
                return ""
            return str(
                describe(json.dumps(args, ensure_ascii=False, separators=(",", ":"))) or name
            )

        is_write = definition.kind == "write"
        specs.append(
            ToolSpec(
                contract=contract,
                kind="write" if is_write else "read",
                decoder=decoder,
                executor=executor,
                confirmation_policy="required" if is_write else "none",
                editable_fields=definition.editable_fields,
                preflight=preflight if validator is not None else None,
                mutable_validator=preflight if validator is not None else None,
                declared_failure_categories=frozenset({"validation_error", "internal_error"}),
                exception_map=(
                    ToolExceptionMapping(Exception, "internal_error", "test_handler_error", str),
                ),
                success_renderer=lambda result: str(result),
                confirmation_description=confirmation_description,
                write_contract=WriteContract() if is_write else None,
            )
        )
    catalog = ToolCatalog(specs, expected_names=names)
    context = ToolExecutionContext(
        applications=ApplicationsRepository(_TEST_SESSIONS),
        capabilities=frozenset(ToolCapability),
        current_bindings={},
        events=ApplicationEventsRepository(_TEST_SESSIONS),
        jd_analyses=JDAnalysesRepository(_TEST_SESSIONS),
        notes=NotesRepository(_TEST_SESSIONS),
        offers=OffersRepository(_TEST_SESSIONS),
        resumes=ResumesRepository(_TEST_SESSIONS),
        run_recorder=NullRunRecorder(),
    )
    return catalog, context


class LangGraphAgentRunner:
    def __init__(self, model: Any, tools: _ToolSet, **kwargs: Any) -> None:
        catalog, context = _test_runtime(tools)
        if kwargs.get("run_recorder") is not None:
            context = replace(context, run_recorder=kwargs["run_recorder"])
        self._inner = ProductionLangGraphAgentRunner(model, catalog, context, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_inner" or "_inner" not in self.__dict__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)


def run_turn(model: Any, tools: _ToolSet, *args: Any, **kwargs: Any) -> Any:
    catalog, context = _test_runtime(tools)
    if kwargs.get("run_recorder") is not None:
        context = replace(context, run_recorder=kwargs["run_recorder"])
    return production_run_turn(model, catalog, *args, tool_context=context, **kwargs)


def resume_after_confirm(model: Any, tools: _ToolSet, *args: Any, **kwargs: Any) -> Any:
    catalog, context = _test_runtime(tools)
    if kwargs.get("run_recorder") is not None:
        context = replace(context, run_recorder=kwargs["run_recorder"])
    return production_resume_after_confirm(model, catalog, *args, tool_context=context, **kwargs)


def prepare_pending_action(pending: PendingAction, tools: _ToolSet, edits: Any) -> PendingAction:
    catalog, _ = _test_runtime(tools)
    prepared = production_prepare_pending_action(pending, catalog, edits)
    definition = next(
        (item for item in tools.definitions if item.name == pending.tool_name),
        None,
    )
    validator = definition.validator if definition is not None else None
    if validator is not None:
        detail = str(validator(prepared.args) or "")
        if detail:
            raise ValueError(detail)
    return prepared


class RecordingRunRecorder:
    def __init__(self):
        self.run_id = "00000000-0000-0000-0000-000000000001"
        self.segment_id = "00000000-0000-0000-0000-000000000002"
        self.diagnostics = []
        self.actions = []

    def start_segment(self, command):
        self.actions.append(("segment.started", command))

    def attach_input_message(self, message_id):
        self.actions.append(("input.attached", message_id))

    def capture_context(
        self,
        logical_input,
        manifest: ContextManifestInput,
        *,
        snapshot_kind,
        model_step=None,
        model_call_id=None,
        estimated_token_count=None,
        token_estimator_name=None,
        token_estimator_version=None,
    ):
        del (
            logical_input,
            manifest,
            estimated_token_count,
            token_estimator_name,
            token_estimator_version,
        )
        snapshot_id = "00000000-0000-0000-0000-000000000003"
        self.actions.append(
            (
                "context.captured",
                {
                    "snapshot_id": snapshot_id,
                    "snapshot_kind": snapshot_kind,
                    "model_step": model_step,
                    "model_call_id": model_call_id,
                },
            )
        )
        return snapshot_id

    def append_event(self, event: EventInput):
        self.actions.append((event.event_type, event))

    def resume(self, command):
        self.actions.append(("run.resumed", command))

    def suspend(self, command):
        self.actions.append(("run.suspended", command))

    def abandon(self):
        self.actions.append(("segment.abandoned", None))

    def finish(self, command):
        self.actions.append(("run.finished", command))

    def fingerprint_model_id(self, value):
        del value
        return "a" * 64

    def fingerprint_pending_identity(self, value):
        del value
        return "b" * 64

    @property
    def event_types(self):
        return [name for name, _ in self.actions]

    @property
    def events(self):
        return [value for _, value in self.actions if isinstance(value, EventInput)]


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


class FailAfterPendingModel:
    def __init__(self, tool_call):
        self.tool_call = tool_call
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return Assistant(tool_calls=[self.tool_call])
        raise RuntimeError("provider failed after confirmed tool")


class CapturingToolsModel:
    def __init__(self):
        self.tools = []

    def complete(self, messages, tools):
        self.tools.append(tools)
        return Assistant(content="done")


def test_agent_exposes_only_tools_composed_into_typed_catalog():
    model = CapturingToolsModel()
    tools = _tools(
        _tool("list_applications"),
        _tool("update_application_status", write=True),
    )

    LangGraphAgentRunner(model, tools).run_turn(
        [Message(role="user", content="继续")],
        auto_approve=False,
    )

    assert [tool.name for tool in model.tools[0]] == [
        "list_applications",
        "update_application_status",
    ]


def _editable_tools(calls=None, validate=None):
    calls = calls if calls is not None else []
    return _tools(
        _tool(
            "update_application_status",
            write=True,
            editable_fields=(
                {"field": "status", "type": "enum", "options": ["offer", "rejected"]},
                {"field": "title", "type": "string"},
                {"field": "note", "type": "long_text"},
                {"field": "score", "type": "number"},
                {"field": "active", "type": "boolean"},
                {"field": "scheduled_at", "type": "datetime"},
                {
                    "field": "remind_at",
                    "type": "datetime",
                    "clearable": True,
                    "clear_value": "",
                },
                {"field": "round", "type": "number", "clearable": True, "clear_value": 0},
            ),
            executor=lambda args: calls.append(args) or '{"ok":true}',
            validator=validate,
        )
    )


def _pending(args=None):
    return PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=json.dumps(args if args is not None else {"id": 7, "status": "offer"}),
        human="change status",
    )


@pytest.fixture(autouse=True)
def _clear_fallback_confirmation_claims():
    claims = getattr(agent_module, "_FALLBACK_CONFIRMATION_CLAIMS", None)
    guard = getattr(agent_module, "_CONFIRMATION_STATE_GUARD", None)
    if claims is not None and guard is not None:
        with guard:
            claims.clear()
    yield
    if claims is not None and guard is not None:
        with guard:
            claims.clear()


def test_prepare_pending_action_merges_edited_status_and_preserves_id():
    pending = _pending({"id": 7, "status": "offer", "note": "old"})

    prepared = prepare_pending_action(pending, _editable_tools(), {"status": "rejected"})

    assert prepared is not pending
    assert prepared.tool_call_id == pending.tool_call_id
    assert prepared.tool_name == pending.tool_name
    assert prepared.human == pending.human
    assert prepared.args == '{"id":7,"status":"rejected","note":"old"}'
    assert json.loads(pending.args) == {"id": 7, "status": "offer", "note": "old"}


def test_prepare_pending_action_none_edits_leave_pending_unchanged():
    pending = _pending()

    assert prepare_pending_action(pending, _tools(), None) is pending


@pytest.mark.parametrize("edited", [["status"], "status", 1, True])
def test_prepare_pending_action_rejects_non_object_edits(edited):
    with pytest.raises(ValueError, match="object"):
        prepare_pending_action(_pending(), _editable_tools(), edited)


@pytest.mark.parametrize("edited_field", ["id", "application_id", "index", "unknown"])
def test_prepare_pending_action_rejects_non_editable_fields(edited_field):
    with pytest.raises(ValueError, match=edited_field):
        prepare_pending_action(_pending(), _editable_tools(), {edited_field: 99})


def test_prepare_pending_action_lists_all_non_editable_fields():
    with pytest.raises(ValueError) as exc_info:
        prepare_pending_action(_pending(), _editable_tools(), {"id": 1, "unknown": "x"})

    assert "id" in str(exc_info.value)
    assert "unknown" in str(exc_info.value)


def test_prepare_pending_action_rejects_unknown_tool():
    pending = PendingAction("w1", "missing", "{}", "missing")

    with pytest.raises(ValueError, match="missing"):
        prepare_pending_action(pending, _editable_tools(), {})


@pytest.mark.parametrize(
    "raw_args",
    [
        "{",
        "[]",
        '"text"',
        "null",
        '{"score":NaN}',
        '{"score":Infinity}',
        '{"score":-Infinity}',
        '{"score":1e400}',
        '{"id":1,"id":2}',
    ],
)
def test_prepare_pending_action_rejects_malformed_or_non_object_original_args(raw_args):
    pending = PendingAction("w1", "update_application_status", raw_args, "change status")

    with pytest.raises(ValueError, match="JSON object"):
        prepare_pending_action(pending, _editable_tools(), {})


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
        prepare_pending_action(_pending(), _editable_tools(), {field: value})


def test_prepare_pending_action_accepts_all_supported_edited_types():
    prepared = prepare_pending_action(
        _pending(),
        _editable_tools(),
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


def test_prepare_pending_action_accepts_only_exact_declared_clear_sentinels():
    pending = _pending(
        {
            "id": 7,
            "status": "offer",
            "scheduled_at": "2026-07-10T12:30:00Z",
            "remind_at": "2026-07-10T11:30:00Z",
            "round": 2,
        }
    )

    prepared = prepare_pending_action(
        pending,
        _editable_tools(),
        {"remind_at": "", "round": 0},
    )

    assert json.loads(prepared.args) == {
        "id": 7,
        "status": "offer",
        "scheduled_at": "2026-07-10T12:30:00Z",
        "remind_at": "",
        "round": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scheduled_at", ""),
        ("remind_at", None),
        ("round", False),
    ],
)
def test_prepare_pending_action_rejects_undeclared_or_inexact_clear_values(field, value):
    with pytest.raises(ValueError, match=field):
        prepare_pending_action(_pending(), _editable_tools(), {field: value})


def test_prepare_pending_action_rejects_non_scalar_declared_clear_sentinel():
    registry = _editable_tools()
    registry = registry.replace(
        "update_application_status",
        editable_fields=(
            {
                "field": "scheduled_at",
                "type": "datetime",
                "clearable": True,
                "clear_value": {},
            },
        ),
    )

    with pytest.raises(ValueError, match="scheduled_at"):
        prepare_pending_action(_pending(), registry, {"scheduled_at": {}})


def test_prepare_pending_action_rejects_unknown_descriptor_type():
    registry = _editable_tools()
    registry = registry.replace(
        "update_application_status",
        editable_fields=({"field": "status", "type": "object"},),
    )

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
            _pending(), _editable_tools(validate=validate), {"status": "rejected"}
        )

    assert seen == [{"id": 7, "status": "rejected"}]


def test_in_memory_checkpoint_executes_effective_args():
    calls = []
    registry = _editable_tools(calls)
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


def test_mapped_confirmation_allows_chained_write_to_create_fresh_interrupt():
    calls = []
    registry = _editable_tools(calls)
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
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w2",
                            name="update_application_status",
                            args=json.dumps({"id": 7, "status": "rejected"}),
                        )
                    ]
                ),
                Assistant(content="both writes completed"),
            ]
        ),
        registry,
    )
    _, _, pending_w1 = runner.run_turn([], auto_approve=False, max_iter=8)
    assert pending_w1 is not None

    _, reply_w1, pending_w2 = runner.resume_after_confirm(
        [], pending_w1, approved=True, auto_approve=False, max_iter=8
    )

    assert calls == ['{"id":7,"status":"offer"}']
    assert reply_w1 == ""
    assert pending_w2 is not None
    assert pending_w2.tool_call_id == "w2"

    _, reply_w2, new_pending = runner.resume_after_confirm(
        [], pending_w2, approved=True, auto_approve=False, max_iter=8
    )

    assert calls == [
        '{"id":7,"status":"offer"}',
        '{"id":7,"status":"rejected"}',
    ]
    assert reply_w2 == "both writes completed"
    assert new_pending is None


def test_checkpoint_validator_exception_fails_before_claim_without_leaking_details():
    calls = []
    validation_count = 0

    def validate(args):
        nonlocal validation_count
        validation_count += 1
        if validation_count == 1:
            return ""
        raise Exception()

    registry = _editable_tools(calls, validate=validate)
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
                Assistant(content="validation failed"),
            ]
        ),
        registry,
    )
    _, _, pending = runner.run_turn([], auto_approve=False, max_iter=8)
    assert pending is not None

    with pytest.raises(PendingActionValidationError, match="工具参数验证失败"):
        runner.resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == []


@pytest.mark.parametrize(
    ("effective_args", "expected_args"),
    [
        (' { "id" : 7, "status" : "rejected" } ', '{"id":7,"status":"rejected"}'),
    ],
)
def test_checkpoint_executes_only_canonical_effective_args(effective_args, expected_args):
    calls = []
    registry = _editable_tools(calls)
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
    effective_pending = PendingAction(
        tool_call_id=pending.tool_call_id,
        tool_name=pending.tool_name,
        args=effective_args,
        human=pending.human,
    )

    runner.resume_after_confirm(
        [], effective_pending, approved=True, auto_approve=False, max_iter=8
    )

    assert calls == [expected_args]


def test_checkpoint_rejects_duplicate_effective_argument_keys_before_claim():
    calls = []
    outcomes = []
    registry = _editable_tools(calls)
    runner = LangGraphAgentRunner(
        ScriptedModel(
            [
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="update_application_status",
                            args='{"id":7,"status":"offer"}',
                        )
                    ]
                ),
                Assistant(content="must not run"),
            ]
        ),
        registry,
        confirmation_result_sink=lambda *args: outcomes.append(args),
    )
    _, _, pending = runner.run_turn([], auto_approve=False, max_iter=8)

    assert pending is not None
    duplicate = PendingAction(
        pending.tool_call_id,
        pending.tool_name,
        '{"id":7,"status":"offer","status":"rejected"}',
        pending.human,
    )
    with pytest.raises(PendingActionValidationError, match="valid JSON object"):
        runner.resume_after_confirm(
            [],
            duplicate,
            approved=True,
            auto_approve=False,
            max_iter=8,
        )

    assert calls == []
    assert outcomes == []


@pytest.mark.parametrize("overflow_source", ["original", "effective"])
def test_checkpoint_rejects_non_finite_overflow_args(overflow_source):
    calls = []
    registry = _editable_tools(calls)
    original_args = (
        '{"id":7,"status":"offer","score":1e400}'
        if overflow_source == "original"
        else '{"id":7,"status":"offer"}'
    )
    runner = LangGraphAgentRunner(
        ScriptedModel(
            [
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="update_application_status",
                            args=original_args,
                        )
                    ]
                ),
                Assistant(content="overflow rejected"),
            ]
        ),
        registry,
    )
    added, _, pending = runner.run_turn([], auto_approve=False, max_iter=8)
    if overflow_source == "original":
        assert pending is None
        assert any(message.role == "tool" for message in added)
        assert calls == []
        return
    assert pending is not None
    if overflow_source == "effective":
        pending = PendingAction(
            tool_call_id=pending.tool_call_id,
            tool_name=pending.tool_name,
            args='{"id":7,"status":"offer","score":1e400}',
            human=pending.human,
        )

    with pytest.raises(ValueError, match="valid JSON object"):
        runner.resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == []


def test_missing_checkpoint_fallback_executes_effective_args():
    calls = []
    registry = _editable_tools(calls)
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


def test_concurrent_fallback_confirmations_execute_handler_at_most_once():
    calls = []
    calls_lock = Lock()

    def handler(args):
        with calls_lock:
            calls.append(args)
        return '{"ok":true}'

    registry = _editable_tools()
    registry = registry.replace("update_application_status", executor=handler)
    pending = _pending()
    thread_id = "conversation:concurrent-fallback"
    runners = [
        LangGraphAgentRunner(
            ScriptedModel([Assistant(content=f"done-{index}")]),
            registry,
            thread_id=thread_id,
        )
        for index in range(2)
    ]
    start = Barrier(3)

    def confirm(runner):
        start.wait(timeout=5)
        try:
            runner.resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)
        except StalePendingActionError:
            return "stale"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm, runner) for runner in runners]
        start.wait(timeout=5)
        outcomes = [future.result(timeout=10) for future in futures]

    assert calls == ['{"id":7,"status":"offer"}']
    assert sorted(outcomes) == ["stale", "success"]


def test_rejected_fallback_claims_rejection_and_blocks_later_execution():
    calls = []
    registry = _editable_tools(calls)
    pending = _pending()
    thread_id = "conversation:rejected-fallback"

    LangGraphAgentRunner(
        ScriptedModel([Assistant(content="rejected")]),
        registry,
        thread_id=thread_id,
    ).resume_after_confirm([], pending, approved=False, auto_approve=False, max_iter=8)
    with pytest.raises(StalePendingActionError):
        LangGraphAgentRunner(
            ScriptedModel([Assistant(content="approved later")]),
            registry,
            thread_id=thread_id,
        ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == []


def test_fallback_handler_error_remains_claimed_against_replay():
    calls = []

    def handler(args):
        calls.append(args)
        raise RuntimeError("failed after side effect")

    registry = _editable_tools()
    registry = registry.replace("update_application_status", executor=handler)
    pending = _pending()
    thread_id = "conversation:fallback-handler-error"

    added, _, _ = LangGraphAgentRunner(
        ScriptedModel([Assistant(content="write may have completed")]),
        registry,
        thread_id=thread_id,
    ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)
    assert added[0].content.startswith("错误：")

    with pytest.raises(StalePendingActionError, match="already consumed"):
        LangGraphAgentRunner(
            ScriptedModel([Assistant(content="must not retry")]),
            registry,
            thread_id=thread_id,
        ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == ['{"id":7,"status":"offer"}']


def test_fallback_validation_error_remains_retryable_without_approval_or_sink():
    calls = []
    events = []
    outcomes = []
    registry = _editable_tools(calls, validate=lambda args: "blocked arguments")
    pending = _pending()
    thread_id = "conversation:fallback-validation-error"

    for _ in range(2):
        with pytest.raises(ValueError, match="blocked arguments"):
            LangGraphAgentRunner(
                ScriptedModel([Assistant(content="must not run")]),
                registry,
                thread_id=thread_id,
                event_sink=events.append,
                confirmation_result_sink=lambda *args: outcomes.append(args),
            ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == []
    assert outcomes == []
    assert not any(
        event["event"] == "tool_call" and event["data"].get("confirm_mode") == "approved"
        for event in events
    )


def test_mutable_validation_failure_never_claims_or_persists_confirmation_result():
    calls = []
    attempts = []
    outcomes = []
    checks = 0

    def validate(args):
        nonlocal checks
        checks += 1
        return "state changed before execution" if checks > 1 else ""

    with pytest.raises(ValueError, match="state changed before execution"):
        LangGraphAgentRunner(
            ScriptedModel([Assistant(content="must not run")]),
            _editable_tools(calls, validate=validate),
            thread_id="conversation:mutable-validation",
            confirmation_attempt_sink=lambda *args: attempts.append(args),
            confirmation_result_sink=lambda *args: outcomes.append(args),
        ).resume_after_confirm(
            [],
            _pending(),
            approved=True,
            auto_approve=False,
            max_iter=8,
        )

    assert calls == []
    assert attempts == []
    assert outcomes == []


def test_fallback_parse_error_remains_retryable_without_consuming_claim():
    pending = PendingAction("bad-json", "update_application_status", "{", "change status")
    outcomes = []
    calls = []
    registry = _editable_tools(calls)
    thread_id = "conversation:fallback-parse-error"

    for _ in range(2):
        with pytest.raises(ValueError, match="valid JSON object"):
            LangGraphAgentRunner(
                ScriptedModel([Assistant(content="must not run")]),
                registry,
                thread_id=thread_id,
                confirmation_result_sink=lambda *args: outcomes.append(args),
            ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert outcomes == []
    valid_pending = PendingAction(
        pending.tool_call_id,
        pending.tool_name,
        json.dumps({"id": 7, "status": "offer"}),
        pending.human,
    )
    LangGraphAgentRunner(
        ScriptedModel([Assistant(content="done")]),
        registry,
        thread_id=thread_id,
    ).resume_after_confirm([], valid_pending, approved=True, auto_approve=False, max_iter=8)
    assert calls == ['{"id":7,"status":"offer"}']


def test_fallback_duplicate_argument_key_remains_retryable_without_consuming_claim():
    pending = PendingAction(
        "duplicate-json",
        "update_application_status",
        '{"id":1,"id":2,"status":"offer"}',
        "change status",
    )
    outcomes = []
    calls = []

    for _ in range(2):
        with pytest.raises(ValueError, match="valid JSON object"):
            LangGraphAgentRunner(
                ScriptedModel([Assistant(content="must not run")]),
                _editable_tools(calls),
                thread_id="conversation:duplicate-json",
                confirmation_result_sink=lambda *args: outcomes.append(args),
            ).resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    assert calls == []
    assert outcomes == []


def test_confirmation_locks_are_scoped_by_thread_id():
    calls = []
    calls_lock = Lock()
    handlers_entered = Barrier(2)

    def handler(args):
        handlers_entered.wait(timeout=5)
        with calls_lock:
            calls.append(args)
        return '{"ok":true}'

    registry = _editable_tools()
    registry = registry.replace("update_application_status", executor=handler)
    pending_actions = [
        PendingAction(
            tool_call_id=f"write-{index}",
            tool_name="update_application_status",
            args=json.dumps({"id": index, "status": "offer"}),
            human="change status",
        )
        for index in (1, 2)
    ]
    runners = [
        LangGraphAgentRunner(
            ScriptedModel([Assistant(content=f"done-{index}")]),
            registry,
            thread_id=f"conversation:parallel-{index}",
        )
        for index in (1, 2)
    ]
    start = Barrier(3)

    def confirm(runner, pending):
        start.wait(timeout=5)
        runner.resume_after_confirm([], pending, approved=True, auto_approve=False, max_iter=8)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, runner, pending)
            for runner, pending in zip(runners, pending_actions, strict=True)
        ]
        start.wait(timeout=5)
        for future in futures:
            future.result(timeout=10)

    assert sorted(json.loads(args)["id"] for args in calls) == [1, 2]


@pytest.mark.parametrize(
    "effective_args",
    [
        ' { "id" : 7, "status" : "rejected" } ',
    ],
)
def test_missing_checkpoint_executes_only_canonical_effective_args(effective_args):
    calls = []
    pending = PendingAction(
        tool_call_id="w1",
        tool_name="update_application_status",
        args=effective_args,
        human="change status",
    )

    resume_after_confirm(
        ScriptedModel([Assistant(content="done")]),
        _editable_tools(calls),
        [],
        pending,
        approved=True,
        auto_approve=False,
        max_iter=8,
    )

    assert calls == ['{"id":7,"status":"rejected"}']


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
    registry = _editable_tools(calls)
    runner = LangGraphAgentRunner(ScriptedModel([]), registry)
    resume_payload = {
        "approved": True,
        "tool_call_id": "w1",
        "tool_name": "update_application_status",
    }
    if effective_args is not None:
        resume_payload["effective_args"] = effective_args
    monkeypatch.setattr(agent_module, "interrupt", lambda pending: resume_payload)

    with pytest.raises(ValueError):
        runner._handle_tool(
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


def test_resume_does_not_treat_non_boolean_approval_as_approved(monkeypatch):
    calls = []
    registry = _editable_tools(calls)
    runner = LangGraphAgentRunner(ScriptedModel([]), registry)
    monkeypatch.setattr(
        agent_module,
        "interrupt",
        lambda pending: {
            "approved": "true",
            "effective_args": pending["args"],
            "tool_call_id": pending["tool_call_id"],
            "tool_name": pending["tool_name"],
        },
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
    registry = _editable_tools(calls, validate=lambda args: "blocked effective arguments")

    with pytest.raises(ValueError, match="blocked effective arguments"):
        resume_after_confirm(
            ScriptedModel([Assistant(content="not executed")]),
            registry,
            [],
            _pending(),
            approved=True,
            auto_approve=False,
            max_iter=8,
        )

    assert calls == []


def test_missing_checkpoint_validator_exception_fails_closed_without_leaking_details():
    calls = []

    def validate(args):
        raise Exception("database password leaked")

    with pytest.raises(ValueError) as exc_info:
        resume_after_confirm(
            ScriptedModel([Assistant(content="not executed")]),
            _editable_tools(calls, validate=validate),
            [],
            _pending(),
            approved=True,
            auto_approve=False,
            max_iter=8,
        )

    assert calls == []
    assert str(exc_info.value) == "工具参数验证失败，请检查后重试。"
    assert "password" not in str(exc_info.value)


@pytest.mark.parametrize(
    "raw_args",
    [
        '{"id":7,"status":"offer","score":NaN}',
        '{"id":7,"status":"offer","score":Infinity}',
        '{"id":7,"status":"offer","score":-Infinity}',
        '{"id":7,"status":"offer","score":1e400}',
        '{"id":7,"status":"offer","nested":{"scores":[1,1e400]}}',
    ],
)
def test_missing_checkpoint_rejects_non_finite_effective_args(raw_args):
    calls = []
    pending = PendingAction("w1", "update_application_status", raw_args, "change status")

    with pytest.raises(ValueError, match="valid JSON object"):
        resume_after_confirm(
            ScriptedModel([Assistant(content="not executed")]),
            _editable_tools(calls),
            [],
            pending,
            approved=True,
            auto_approve=False,
            max_iter=8,
        )

    assert calls == []


def test_missing_checkpoint_does_not_treat_non_boolean_approval_as_approved():
    calls = []

    added, _, _ = resume_after_confirm(
        ScriptedModel([Assistant(content="not executed")]),
        _editable_tools(calls),
        [],
        _pending(),
        approved="false",
        auto_approve=False,
        max_iter=8,
    )

    assert calls == []
    assert added[0].content.startswith("用户拒绝")


def test_rejection_feedback_is_provider_free_and_does_not_run_handler():
    calls = []
    model = RecordingScriptedModel([Assistant(content="understood")])

    added, reply, new_pending = resume_after_confirm(
        model,
        _editable_tools(calls),
        [],
        _pending(),
        approved=False,
        auto_approve=False,
        max_iter=8,
        rejection_feedback="  Keep it in offer status.  ",
    )

    assert calls == []
    assert "保持不变" in reply
    assert new_pending is None
    assert "用户拒绝" in added[0].content
    assert "Keep it in offer status." in added[0].content
    assert model.message_batches == []


def test_empty_rejection_feedback_keeps_generic_rejection_message():
    calls = []
    model = RecordingScriptedModel([Assistant(content="cancelled")])

    added, _, _ = resume_after_confirm(
        model,
        _editable_tools(calls),
        [],
        _pending(),
        approved=False,
        auto_approve=False,
        rejection_feedback="   ",
    )

    assert calls == []
    assert added[0].content == "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"


def test_confirmation_result_sink_records_approved_tool_error():
    outcomes = []
    registry = _editable_tools()
    registry = registry.replace(
        "update_application_status",
        executor=lambda args: "错误：write failed",
    )

    added, _, _ = resume_after_confirm(
        ScriptedModel([Assistant(content="handled")]),
        registry,
        [],
        _pending(),
        approved=True,
        auto_approve=False,
        confirmation_result_sink=lambda effective, approved, message, record: outcomes.append(
            (effective, approved, message, record)
        ),
    )

    assert len(outcomes) == 1
    effective, approved, message, record = outcomes[0]
    assert effective.tool_call_id == _pending().tool_call_id
    assert effective.tool_name == _pending().tool_name
    assert json.loads(effective.args) == json.loads(_pending().args)
    assert approved is True
    assert message.content == "错误：write failed"
    assert added[0] == message
    assert record is not None


def test_confirmation_attempt_sink_runs_immediately_before_handler():
    attempts = []
    calls = []
    pending = _pending()

    def handler(args):
        assert attempts == [pending.tool_call_id]
        calls.append(args)
        return '{"ok":true}'

    registry = _editable_tools()
    registry = registry.replace(pending.tool_name, executor=handler)
    model = ScriptedModel([Assistant(content="done")])

    def claim(action, prepared):
        attempts.append(action.tool_call_id)
        assert prepared is not None
        return ExecutionAuthorization(
            pending_identity=prepared.pending_identity,
            pending_action_revision=prepared.pending_action_revision,
            tool_call_id=prepared.tool_call_id,
            tool_name=prepared.spec.name,
            arguments_digest=prepared.arguments_digest,
        )

    resume_after_confirm(
        model,
        registry,
        [],
        pending,
        approved=True,
        auto_approve=False,
        confirmation_attempt_sink=claim,
    )

    assert attempts == [pending.tool_call_id]
    assert calls == ['{"id":7,"status":"offer"}']


def test_write_tool_pauses_before_execution():
    calls = []
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            confirmation_description=lambda args: "change status",
            executor=lambda args: calls.append(args) or "{}",
        )
    )
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
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            confirmation_description=lambda args: "change status",
            executor=lambda args: calls.append(args) or '{"ok":true}',
        )
    )
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

    assert calls == ['{"id":1,"status":"offer"}']
    assert added[0].role == "tool"
    assert reply == "done"
    assert new_pending is None


def test_reject_does_not_execute_pending_write():
    calls = []
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            executor=lambda args: calls.append(args) or '{"ok":true}',
        )
    )
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
    assert "已取消这次操作" in reply
    assert new_pending is None


def test_event_sink_emits_read_tool_call_and_result():
    events = []
    registry = _tools(
        _tool(
            "list_applications",
            description="List job applications.",
            executor=lambda args: '{"items":[]}',
        )
    )
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


def test_journal_records_one_model_answer_lifecycle():
    recorder = RecordingRunRecorder()

    added, reply, pending = run_turn(
        ScriptedModel([Assistant(content="done")]),
        _tools(),
        [Message(role="user", content="hello")],
        auto_approve=False,
        run_recorder=recorder,
    )

    assert [message.role for message in added] == ["assistant"]
    assert reply == "done"
    assert pending is None
    assert recorder.event_types == [
        "context.captured",
        "model.requested",
        "model.completed",
    ]
    requested, completed = recorder.events
    assert requested.model_step == completed.model_step == 1
    assert requested.model_call_id == completed.model_call_id
    assert requested.model_call_id is not None
    UUID(requested.model_call_id)


def test_journal_records_read_tool_loop_and_increments_model_step():
    recorder = RecordingRunRecorder()
    model = ScriptedModel(
        [
            Assistant(tool_calls=[ToolCall(id="r1", name="list_applications", args="{}")]),
            Assistant(content="done"),
        ]
    )

    _, reply, pending = run_turn(
        model,
        _tools(
            _tool(
                "list_applications",
                executor=lambda _args: '{"items":[]}',
            )
        ),
        [],
        auto_approve=False,
        run_recorder=recorder,
    )

    assert reply == "done"
    assert pending is None
    assert recorder.event_types == [
        "context.captured",
        "model.requested",
        "model.completed",
        "tool.proposed",
        "tool.started",
        "tool.completed",
        "context.captured",
        "model.requested",
        "model.completed",
    ]
    model_events = [event for event in recorder.events if event.event_type.startswith("model.")]
    assert [event.model_step for event in model_events] == [1, 1, 2, 2]
    assert model_events[0].model_call_id == model_events[1].model_call_id
    assert model_events[2].model_call_id == model_events[3].model_call_id
    assert model_events[0].model_call_id != model_events[2].model_call_id


def test_journal_write_tool_stops_at_proposal_before_confirmation():
    recorder = RecordingRunRecorder()
    calls = []

    _, reply, pending = run_turn(
        ScriptedModel(
            [
                Assistant(
                    tool_calls=[
                        ToolCall(
                            id="w1",
                            name="update_application_status",
                            args='{"id":1,"status":"offer"}',
                        )
                    ]
                )
            ]
        ),
        _tools(
            _tool(
                "update_application_status",
                write=True,
                executor=lambda args: calls.append(args) or "{}",
            )
        ),
        [],
        auto_approve=False,
        run_recorder=recorder,
    )

    assert reply == ""
    assert pending is not None
    assert calls == []
    assert recorder.event_types == [
        "context.captured",
        "model.requested",
        "model.completed",
        "tool.proposed",
    ]


def test_journal_records_provider_failure_and_preserves_exception():
    class FailingProvider:
        def complete(self, messages, tools):
            del messages, tools
            raise RuntimeError("sensitive provider detail")

    recorder = RecordingRunRecorder()

    with pytest.raises(RuntimeError, match="sensitive provider detail"):
        run_turn(
            FailingProvider(),
            _tools(),
            [],
            auto_approve=False,
            run_recorder=recorder,
        )

    assert recorder.event_types == [
        "context.captured",
        "model.requested",
        "model.failed",
    ]
    requested, failed = recorder.events
    assert requested.model_step == failed.model_step == 1
    assert requested.model_call_id == failed.model_call_id
    assert "sensitive provider detail" not in repr(failed)


def test_journal_records_typed_tool_error_without_changing_agent_result():
    recorder = RecordingRunRecorder()
    model = RecordingScriptedModel(
        [
            Assistant(tool_calls=[ToolCall(id="r1", name="list_applications", args="{}")]),
            Assistant(content="recovered"),
        ]
    )

    _, reply, pending = run_turn(
        model,
        _tools(
            _tool(
                "list_applications",
                executor=lambda _args: (_ for _ in ()).throw(ValueError("typed failure")),
            )
        ),
        [],
        auto_approve=False,
        run_recorder=recorder,
    )

    assert reply == "recovered"
    assert pending is None
    assert model.message_batches[1][-1].content == "错误：typed failure"
    assert recorder.event_types[3:6] == [
        "tool.proposed",
        "tool.started",
        "tool.failed",
    ]
    assert "typed failure" not in repr(recorder.events)


def test_executes_multiple_read_only_tool_calls_from_one_assistant_turn():
    calls = []
    registry = _tools(
        _tool(
            "list_applications",
            description="查看投递列表",
            executor=lambda args: calls.append(("apps", args)) or "[]",
        ),
        _tool(
            "list_notes",
            description="查看复盘记录",
            executor=lambda args: calls.append(("notes", args)) or "[]",
        ),
    )
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


@pytest.mark.parametrize(
    ("kinds", "expected_calls", "expected_tool_call_ids", "expects_pending"),
    [
        (("read", "read"), ["first", "second"], ["first", "second"], False),
        (("write", "read"), [], ["first"], True),
        (("read", "write"), ["first"], ["first"], False),
        (("write", "write"), [], ["first"], True),
    ],
)
def test_multi_tool_call_selection_matches_baseline_matrix(
    kinds,
    expected_calls,
    expected_tool_call_ids,
    expects_pending,
):
    calls = []
    tools = _tools(
        *(
            _tool(
                f"{kind}_tool_{index}",
                write=kind == "write",
                executor=lambda _args, label=label: calls.append(label) or "{}",
            )
            for index, (kind, label) in enumerate(
                zip(kinds, ("first", "second"), strict=True),
                start=1,
            )
        )
    )
    tool_calls = [
        ToolCall(id=label, name=definition.name, args="{}")
        for label, definition in zip(("first", "second"), tools.definitions, strict=True)
    ]
    model = ScriptedModel([Assistant(tool_calls=tool_calls), Assistant(content="done")])

    added, reply, pending = run_turn(
        model,
        tools,
        [],
        auto_approve=False,
        max_iter=8,
    )

    assert calls == expected_calls
    assert [call.id for call in added[0].tool_calls] == expected_tool_call_ids
    assert (pending is not None) is expects_pending
    assert reply == ("" if expects_pending else "done")


def test_failed_first_read_does_not_block_second_read_in_same_turn():
    calls = []

    def fail_first(_args):
        calls.append("first")
        raise ValueError("private read failure")

    tools = _tools(
        _tool("first_read", executor=fail_first),
        _tool(
            "second_read",
            executor=lambda _args: calls.append("second") or "{}",
        ),
    )
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(id="first", name="first_read", args="{}"),
                    ToolCall(id="second", name="second_read", args="{}"),
                ]
            ),
            Assistant(content="done"),
        ]
    )

    added, reply, pending = run_turn(
        model,
        tools,
        [],
        auto_approve=False,
        max_iter=8,
    )

    assert calls == ["first", "second"]
    assert [message.tool_call_id for message in added if message.role == "tool"] == [
        "first",
        "second",
    ]
    assert reply == "done"
    assert pending is None


def test_always_confirm_write_pauses_even_when_auto_approve_is_enabled():
    calls = []
    registry = _tools(
        _tool(
            "delete_note",
            write=True,
            confirmation_description=lambda args: "删除复盘记录",
            executor=lambda args: calls.append(args) or "{}",
        )
    )
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


def test_every_write_pauses_even_when_auto_approve_is_enabled():
    calls: list[str] = []
    registry = _tools(
        _tool(
            "write_tool",
            write=True,
            executor=lambda args: calls.append(args) or "written",
            validator=lambda args: "",
            confirmation_description=lambda args: "写入测试数据",
        )
    )
    model = ScriptedModel(
        [Assistant(tool_calls=[ToolCall(id="write-1", name="write_tool", args="{}")])]
    )

    added, reply, pending = run_turn(model, registry, [], auto_approve=True, max_iter=8)

    assert added
    assert reply == ""
    assert pending is not None
    assert calls == []


def test_auto_approved_write_still_runs_validation_before_execution():
    calls = []
    registry = _tools(
        _tool(
            "create_application",
            write=True,
            validator=lambda args: (
                "create_application requires explicit user confirmation before adding a new position"
            ),
            executor=lambda args: calls.append(args) or "{}",
        )
    )
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
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            confirmation_description=lambda args: "更新投递状态",
            executor=lambda args: calls.append(args) or "{}",
        )
    )
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
        run_turn(
            model,
            registry,
            [],
            auto_approve=True,
            max_iter=8,
            cancel_check=lambda: next(checks, True),
        )

    assert calls == []


def test_event_sink_emits_assistant_delta_from_streaming_model():
    events = []

    added, reply, pending = run_turn(
        StreamingScriptedModel(),
        _tools(),
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
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            description="Update application status.",
            confirmation_description=lambda args: "change status",
            executor=lambda args: calls.append(args) or "{}",
        )
    )
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
    registry = _tools(
        _tool(
            "update_application_status",
            write=True,
            description="Update application status.",
            executor=lambda args: calls.append(args) or '{"ok":true}',
        )
    )
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

    assert calls == ['{"id":1,"status":"offer"}']
    assert added[0].role == "tool"
    assert reply == "done"
    assert new_pending is None
    assert [event["event"] for event in events] == ["tool_call", "tool_result"]
    assert events[0]["data"]["confirm_mode"] == "approved"
    assert events[1]["data"]["status"] == "success"
