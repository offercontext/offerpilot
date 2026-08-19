from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Iterator, Literal, Protocol, TypedDict, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    ConfirmationRequired,
    ExecutionAuthorization,
    PreparedToolCall,
    ProviderToolContract,
    ReadyToExecute,
    ToolExecutionRecord,
    ToolFailure,
    ToolSpec,
)
from offerpilot.ai.tool_runtime.pipeline import Rejected, execute_prepared, prepare_call
from offerpilot.ai.tool_runtime.rendering import render_compatibility
from offerpilot.ai.tool_runtime.transport import project_transport_event
from offerpilot.ai.tool_runtime.validation import ArgumentValidationError, parse_arguments
from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.agent_runtime.events import ContextManifestInput
from offerpilot.agent_runtime.journal import EventInput, NullRunRecorder, RunRecorder

DEFAULT_MAX_ITERATIONS = 20
_DEFAULT_THREAD_ID = "conversation:ephemeral"
AgentEventSink = Callable[[dict[str, Any]], None]
AssistantDeltaSink = Callable[[str], None]
CancelCheck = Callable[[], bool]
_IN_MEMORY_CONFIRMATION_NAMESPACE = "offerpilot.ai.agent.in-memory"
_MAX_FALLBACK_CONFIRMATION_CLAIMS = 4096
ConfirmationLockKey = tuple[str, str]
FallbackConfirmationClaim = tuple[ConfirmationLockKey, str, str, str]


@dataclass
class _ConfirmationLockEntry:
    lock: Any
    users: int = 0


_CONFIRMATION_STATE_GUARD = Lock()
_CONFIRMATION_LOCKS: dict[ConfirmationLockKey, _ConfirmationLockEntry] = {}
_FALLBACK_CONFIRMATION_CLAIMS: OrderedDict[FallbackConfirmationClaim, None] = OrderedDict()


class ChatRunCancelled(RuntimeError):
    """Raised when a chat run is cancelled before another model/tool step."""


class StalePendingActionError(ValueError):
    """Raised when a confirmation does not match the persisted Pending Action."""


class PendingActionValidationError(ValueError):
    """Raised when confirmation arguments fail before a write handler is attempted."""


class ChatModel(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[ProviderToolContract],
        response_format: dict[str, Any] | None = None,
    ) -> Assistant: ...


class StreamingChatModel(Protocol):
    def stream_complete(
        self,
        messages: list[Message],
        tools: list[ProviderToolContract],
        on_delta: AssistantDeltaSink,
    ) -> Assistant: ...


@dataclass
class PendingAction:
    tool_call_id: str
    tool_name: str
    args: str
    human: str
    operation_id: str = ""


@dataclass(frozen=True)
class AgentTurnResult:
    added: list[Message]
    reply: str
    pending: PendingAction | None
    records: tuple[ToolExecutionRecord[Any, Any], ...] = ()
    failures: tuple[ToolFailure, ...] = ()

    def __iter__(self) -> Iterator[Any]:
        yield self.added
        yield self.reply
        yield self.pending


ConfirmationResultSink = Callable[
    [PendingAction, bool, Message, ToolExecutionRecord[Any, Any] | None],
    None,
]
ConfirmationAttemptSink = Callable[
    [PendingAction, PreparedToolCall[Any, Any] | None],
    ExecutionAuthorization | ToolFailure | None,
]
DeliveryFence = Callable[[], bool]


@contextmanager
def _confirmation_lock(lock_key: ConfirmationLockKey) -> Iterator[None]:
    with _CONFIRMATION_STATE_GUARD:
        entry = _CONFIRMATION_LOCKS.get(lock_key)
        if entry is None:
            entry = _ConfirmationLockEntry(lock=Lock())
            _CONFIRMATION_LOCKS[lock_key] = entry
        entry.users += 1
    entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        with _CONFIRMATION_STATE_GUARD:
            entry.users -= 1
            if entry.users == 0 and _CONFIRMATION_LOCKS.get(lock_key) is entry:
                del _CONFIRMATION_LOCKS[lock_key]


def _claim_fallback_confirmation(
    lock_key: ConfirmationLockKey,
    pending: PendingAction,
) -> bool:
    claim_key = (lock_key, pending.tool_call_id, pending.tool_name, pending.args)
    with _CONFIRMATION_STATE_GUARD:
        if claim_key in _FALLBACK_CONFIRMATION_CLAIMS:
            _FALLBACK_CONFIRMATION_CLAIMS.move_to_end(claim_key)
            return False
        _FALLBACK_CONFIRMATION_CLAIMS[claim_key] = None
        while len(_FALLBACK_CONFIRMATION_CLAIMS) > _MAX_FALLBACK_CONFIRMATION_CLAIMS:
            _FALLBACK_CONFIRMATION_CLAIMS.popitem(last=False)
    return True


class _GraphState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    added: list[dict[str, Any]]
    auto_approve: bool
    max_iter: int
    iterations: int
    status: str
    reply: str
    current_tool_call: dict[str, Any]
    current_tool_calls: list[dict[str, Any]]
    consumed_resume_id: str
    consumed_resume_attempt_id: str


class LangGraphAgentRunner:
    def __init__(
        self,
        model: ChatModel,
        catalog: ToolCatalog,
        tool_context: ToolExecutionContext,
        *,
        thread_id: str = _DEFAULT_THREAD_ID,
        event_sink: AgentEventSink | None = None,
        cancel_check: CancelCheck | None = None,
        confirmation_result_sink: ConfirmationResultSink | None = None,
        confirmation_attempt_sink: ConfirmationAttemptSink | None = None,
        run_recorder: RunRecorder | None = None,
        delivery_fence: DeliveryFence | None = None,
    ):
        self._model = model
        self._catalog = catalog
        self._tool_context = tool_context
        self._thread_id = thread_id
        self._event_sink = event_sink
        self._cancel_check = cancel_check
        self._confirmation_result_sink = confirmation_result_sink
        self._confirmation_attempt_sink = confirmation_attempt_sink
        self._run_recorder = run_recorder or NullRunRecorder()
        self._delivery_fence = delivery_fence
        self._memory_saver = InMemorySaver()
        self._records: list[ToolExecutionRecord[Any, Any]] = []
        self._failures: list[ToolFailure] = []

    def run_turn(
        self,
        messages: list[Message],
        auto_approve: bool,
        max_iter: int = DEFAULT_MAX_ITERATIONS,
    ) -> AgentTurnResult:
        self._records = []
        self._failures = []
        state: _GraphState = {
            "messages": [_message_to_dict(message) for message in messages],
            "added": [],
            "auto_approve": auto_approve,
            "max_iter": max_iter or DEFAULT_MAX_ITERATIONS,
            "iterations": 0,
        }
        with self._checkpointer() as checkpointer:
            graph = self._compile_graph(checkpointer)
            result = graph.invoke(state, self._config(max_iter))
        added, reply, pending = self._result_from_state(cast(dict[str, Any], result))
        return AgentTurnResult(added, reply, pending, tuple(self._records), tuple(self._failures))

    def resume_after_confirm(
        self,
        messages: list[Message],
        pending: PendingAction,
        approved: bool,
        auto_approve: bool,
        max_iter: int = DEFAULT_MAX_ITERATIONS,
        rejection_feedback: str = "",
    ) -> AgentTurnResult:
        approved = approved is True
        confirmation_lock_key = self._confirmation_lock_key()
        with _confirmation_lock(confirmation_lock_key):
            self._records = []
            self._failures = []
            return self._resume_without_checkpoint(
                messages,
                pending,
                approved,
                auto_approve,
                max_iter,
                rejection_feedback,
                confirmation_lock_key,
            )

    def _confirmation_lock_key(self) -> ConfirmationLockKey:
        return _IN_MEMORY_CONFIRMATION_NAMESPACE, self._thread_id

    def _compile_graph(self, checkpointer: Any) -> Any:
        graph = StateGraph(_GraphState)
        graph.add_node("call_model", self._call_model)
        graph.add_node("handle_tool", self._handle_tool)
        graph.add_edge(START, "call_model")
        graph.add_conditional_edges(
            "call_model",
            _next_after_model,
            {"tool": "handle_tool", "final": END},
        )
        graph.add_conditional_edges(
            "handle_tool",
            _next_after_tool,
            {"continue": "call_model", "final": END},
        )
        return graph.compile(checkpointer=checkpointer)

    def _call_model(self, state: _GraphState) -> _GraphState:
        self._raise_if_cancelled()
        iterations = int(state.get("iterations", 0))
        max_iter = int(state.get("max_iter", DEFAULT_MAX_ITERATIONS))
        if iterations >= max_iter:
            raise RuntimeError("AI 工具调用超过最大轮次")

        work = [_message_from_dict(message) for message in state.get("messages", [])]
        tools = list(self._catalog.provider_contracts())
        assistant = self._complete_model(work, tools, model_step=iterations + 1)
        selected_tool_calls = _select_tool_calls(assistant.tool_calls, self._catalog)
        assistant_message = Message(
            role="assistant",
            content=assistant.content,
            tool_calls=selected_tool_calls,
            provider_blocks=assistant.provider_blocks,
        )
        added = [*state.get("added", []), _message_to_dict(assistant_message)]
        messages = [*state.get("messages", []), _message_to_dict(assistant_message)]
        if not selected_tool_calls:
            return {
                "messages": messages,
                "added": added,
                "reply": assistant.content,
                "status": "final",
                "iterations": iterations + 1,
            }
        for tool_call in selected_tool_calls:
            self._emit_tool_call(tool_call, bool(state.get("auto_approve", False)))
        return {
            "messages": messages,
            "added": added,
            "current_tool_calls": [
                _tool_call_to_dict(tool_call) for tool_call in selected_tool_calls
            ],
            "status": "tool",
            "iterations": iterations + 1,
        }

    def _handle_tool(self, state: _GraphState) -> _GraphState:
        current_tool_calls = state.get("current_tool_calls") or [state["current_tool_call"]]
        messages = list(state.get("messages", []))
        added = list(state.get("added", []))
        consumed_resume_id = str(state.get("consumed_resume_id") or "")
        consumed_resume_attempt_id = str(state.get("consumed_resume_attempt_id") or "")
        for tool_call in current_tool_calls:
            confirmed_outcome: tuple[PendingAction, bool] | None = None
            self._raise_if_cancelled()
            tool_name = str(tool_call["name"])
            tool_args = str(tool_call.get("args") or "")
            tool_call_id = str(tool_call["id"])
            spec = self._catalog.resolve(tool_name)
            has_mapped_resume = False

            if spec is None:
                unknown_failure = ToolFailure(
                    "validation_error",
                    "unknown_tool",
                    f'未知工具 "{tool_name}"',
                )
                self._failures.append(unknown_failure)
                result = "错误：" + unknown_failure.compatibility_detail
            elif spec.kind == "write":
                initial_prepared = None
                if not has_mapped_resume:
                    initial_prepared = prepare_call(
                        self._catalog,
                        self._tool_context,
                        ToolCall(tool_call_id, tool_name, tool_args),
                        pending_identity=f"{tool_call_id}:{tool_name}",
                        pending_action_revision=_pending_action_revision(
                            tool_call_id, tool_name, tool_args
                        ),
                    )
                    self._raise_if_cancelled()
                    if isinstance(initial_prepared, Rejected):
                        self._failures.append(initial_prepared.failure)
                        result = render_compatibility(spec, initial_prepared.failure)
                        self._emit_tool_result(tool_call_id, tool_name, result, None)
                        tool_message = Message(
                            role="tool", content=result, tool_call_id=tool_call_id
                        )
                        messages.append(_message_to_dict(tool_message))
                        added.append(_message_to_dict(tool_message))
                        continue
                pending = {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "human": _spec_confirmation_description(spec, tool_args, tool_name),
                }
                if isinstance(initial_prepared, ConfirmationRequired) or has_mapped_resume:
                    raw_resume_value = interrupt(pending)
                    resume_value = raw_resume_value if isinstance(raw_resume_value, dict) else {}
                    self._raise_if_cancelled()
                    identity_error = _resume_identity_error(
                        resume_value,
                        tool_call_id,
                        tool_name,
                    )
                    if identity_error:
                        raise StalePendingActionError("stale pending action: " + identity_error)
                    if resume_value.get("approved") is True:
                        try:
                            effective_args = _validated_resumed_args(
                                tool_call_id,
                                tool_name,
                                tool_args,
                                resume_value.get("effective_args"),
                                self._catalog,
                            )
                        except ValueError as exc:
                            raise PendingActionValidationError(str(exc)) from exc
                        effective_pending = PendingAction(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            args=effective_args,
                            human=_spec_confirmation_description(
                                spec, effective_args, str(pending["human"])
                            ),
                            operation_id=str(resume_value.get("operation_id") or ""),
                        )
                        self._emit_pending_tool_call(
                            effective_pending,
                            "approved",
                        )
                        confirmed_outcome = (
                            effective_pending,
                            True,
                        )
                        self._raise_if_cancelled()
                        prepared_result = prepare_call(
                            self._catalog,
                            self._tool_context,
                            ToolCall(tool_call_id, tool_name, effective_args),
                            pending_identity=f"{tool_call_id}:{tool_name}",
                            pending_action_revision=_pending_action_revision(
                                tool_call_id, tool_name, tool_args
                            ),
                            record_proposal=False,
                        )
                        self._raise_if_cancelled()
                        if not isinstance(prepared_result, ConfirmationRequired):
                            if isinstance(prepared_result, Rejected):
                                self._failures.append(prepared_result.failure)
                                raise PendingActionValidationError(
                                    prepared_result.failure.compatibility_detail
                                    or prepared_result.failure.code
                                )
                            raise PendingActionValidationError(
                                "pending tool no longer requires confirmation"
                            )
                        else:

                            def claim(
                                prepared: PreparedToolCall[Any, Any],
                            ) -> ExecutionAuthorization | ToolFailure:
                                if self._confirmation_attempt_sink is not None:
                                    claimed = self._confirmation_attempt_sink(
                                        effective_pending,
                                        prepared,
                                    )
                                    if isinstance(claimed, (ExecutionAuthorization, ToolFailure)):
                                        return claimed
                                    return ToolFailure(
                                        "conflict",
                                        "confirmation_claim_failed",
                                    )
                                if not _claim_fallback_confirmation(
                                    self._confirmation_lock_key(),
                                    effective_pending,
                                ):
                                    return ToolFailure(
                                        "stale_state",
                                        "fallback_confirmation_consumed",
                                    )
                                return ExecutionAuthorization(
                                    pending_identity=prepared.pending_identity,
                                    pending_action_revision=cast(
                                        int, prepared.pending_action_revision
                                    ),
                                    tool_call_id=prepared.tool_call_id,
                                    tool_name=prepared.spec.name,
                                    arguments_digest=prepared.arguments_digest,
                                )

                            record = execute_prepared(
                                prepared_result.prepared,
                                self._tool_context,
                                confirmation_claimer=claim,
                            )
                            self._records.append(record)
                            if isinstance(record.outcome, ToolFailure) and record.outcome.code in {
                                "authorization_mismatch",
                                "confirmation_claim_failed",
                                "confirmation_claim_lost",
                                "fallback_confirmation_consumed",
                            }:
                                raise StalePendingActionError(
                                    "stale pending action: confirmation claim failed"
                                )
                            if not record.execution_started:
                                assert isinstance(record.outcome, ToolFailure)
                                raise PendingActionValidationError(
                                    record.outcome.compatibility_detail or record.outcome.code
                                )
                            result = render_compatibility(spec, record.outcome)
                    else:
                        if self._confirmation_attempt_sink is not None:
                            rejected_claim = self._confirmation_attempt_sink(
                                PendingAction(
                                    tool_call_id=tool_call_id,
                                    tool_name=tool_name,
                                    args=tool_args,
                                    human=str(pending["human"]),
                                ),
                                None,
                            )
                            if isinstance(rejected_claim, ToolFailure):
                                raise StalePendingActionError(
                                    "stale pending action: rejection claim failed"
                                )
                        elif not _claim_fallback_confirmation(
                            self._confirmation_lock_key(),
                            PendingAction(
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                args=tool_args,
                                human=str(pending["human"]),
                            ),
                        ):
                            raise StalePendingActionError(
                                "stale pending action: rejection was already consumed"
                            )
                        self._emit_pending_tool_call(
                            PendingAction(
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                args=tool_args,
                                human=str(pending["human"]),
                            ),
                            "rejected",
                        )
                        result = _rejection_result(resume_value.get("rejection_feedback"))
                        self._failures.append(
                            ToolFailure(
                                "confirmation_rejected",
                                "confirmation_rejected",
                                result,
                            )
                        )
                        confirmed_outcome = (
                            PendingAction(
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                args=tool_args,
                                human=str(pending["human"]),
                            ),
                            False,
                        )
                else:
                    result = "错误：确认操作状态不一致"
            else:
                self._raise_if_cancelled()
                prepared_result = prepare_call(
                    self._catalog,
                    self._tool_context,
                    ToolCall(tool_call_id, tool_name, tool_args),
                )
                self._raise_if_cancelled()
                if isinstance(prepared_result, Rejected):
                    self._failures.append(prepared_result.failure)
                    record = None
                    result = render_compatibility(spec, prepared_result.failure)
                elif isinstance(prepared_result, ReadyToExecute):
                    self._require_delivery_fence()
                    record = execute_prepared(prepared_result.prepared, self._tool_context)
                    self._require_delivery_fence()
                    self._records.append(record)
                    result = render_compatibility(spec, record.outcome)
                else:
                    record = None
                    result = "错误：只读工具不能请求确认"

            emitted_record = (
                record
                if spec is not None and spec.kind == "read"
                else (
                    self._records[-1]
                    if self._records and self._records[-1].prepared.tool_call_id == tool_call_id
                    else None
                )
            )
            self._emit_tool_result(tool_call_id, tool_name, result, emitted_record)
            tool_message = Message(role="tool", content=result, tool_call_id=tool_call_id)
            messages.append(_message_to_dict(tool_message))
            added.append(_message_to_dict(tool_message))
            if confirmed_outcome is not None and self._confirmation_result_sink is not None:
                effective_pending, confirmed_approved = confirmed_outcome
                self._confirmation_result_sink(
                    effective_pending,
                    confirmed_approved,
                    tool_message,
                    emitted_record,
                )
        return {
            "messages": messages,
            "added": added,
            "status": "continue",
            "consumed_resume_id": consumed_resume_id,
            "consumed_resume_attempt_id": consumed_resume_attempt_id,
        }

    def _checkpointer(self) -> AbstractContextManager[Any]:
        return nullcontext(self._memory_saver)

    def _config(self, max_iter: int) -> dict[str, Any]:
        resolved_max = max_iter or DEFAULT_MAX_ITERATIONS
        return {
            "configurable": {"thread_id": self._thread_id},
            "recursion_limit": resolved_max * 3 + 5,
        }

    def _result_from_state(
        self,
        state: dict[str, Any],
    ) -> tuple[list[Message], str, PendingAction | None]:
        added = [_message_from_dict(message) for message in state.get("added", [])]
        interrupts = state.get("__interrupt__") or []
        if interrupts:
            pending_payload = getattr(interrupts[0], "value")
            return (
                added,
                "",
                PendingAction(
                    tool_call_id=str(pending_payload["tool_call_id"]),
                    tool_name=str(pending_payload["tool_name"]),
                    args=str(pending_payload["args"]),
                    human=str(pending_payload["human"]),
                    operation_id=str(uuid4()),
                ),
            )
        return added, str(state.get("reply") or ""), None

    def _resume_without_checkpoint(
        self,
        messages: list[Message],
        pending: PendingAction,
        approved: bool,
        auto_approve: bool,
        max_iter: int,
        rejection_feedback: str,
        confirmation_lock_key: ConfirmationLockKey,
    ) -> AgentTurnResult:
        sink_pending = pending
        record: ToolExecutionRecord[Any, Any] | None = None
        if approved is True:
            spec = self._catalog.resolve(pending.tool_name)
            if spec is None:
                raise PendingActionValidationError(f'unknown pending tool "{pending.tool_name}"')
            try:
                parsed_args = _parse_json_object(
                    pending.args,
                    "pending arguments must be a valid JSON object",
                )
            except ValueError as exc:
                raise PendingActionValidationError(str(exc)) from exc
            effective_args = _encode_json_object(parsed_args)
            sink_pending = PendingAction(
                tool_call_id=pending.tool_call_id,
                tool_name=pending.tool_name,
                args=effective_args,
                human=pending.human,
                operation_id=pending.operation_id,
            )
            self._raise_if_cancelled()
            prepared_result = prepare_call(
                self._catalog,
                self._tool_context,
                ToolCall(pending.tool_call_id, pending.tool_name, effective_args),
                pending_identity=f"{pending.tool_call_id}:{pending.tool_name}",
                pending_action_revision=_pending_action_revision(
                    pending.tool_call_id, pending.tool_name, pending.args
                ),
                record_proposal=False,
            )
            self._raise_if_cancelled()
            if not isinstance(prepared_result, ConfirmationRequired):
                if isinstance(prepared_result, Rejected):
                    raise PendingActionValidationError(
                        prepared_result.failure.compatibility_detail or prepared_result.failure.code
                    )
                raise PendingActionValidationError("pending tool no longer requires confirmation")
            self._emit_pending_tool_call(sink_pending, "approved")

            def claim(prepared: Any) -> ExecutionAuthorization | ToolFailure:
                if self._confirmation_attempt_sink is not None:
                    claimed = self._confirmation_attempt_sink(sink_pending, prepared)
                    if isinstance(claimed, (ExecutionAuthorization, ToolFailure)):
                        return claimed
                    return ToolFailure("conflict", "confirmation_claim_failed")
                if not _claim_fallback_confirmation(confirmation_lock_key, pending):
                    return ToolFailure(
                        "stale_state",
                        "fallback_confirmation_consumed",
                        "stale pending action: fallback confirmation was already consumed",
                    )
                return ExecutionAuthorization(
                    pending_identity=prepared.pending_identity,
                    pending_action_revision=cast(int, prepared.pending_action_revision),
                    tool_call_id=prepared.tool_call_id,
                    tool_name=prepared.spec.name,
                    arguments_digest=prepared.arguments_digest,
                )

            record = execute_prepared(
                prepared_result.prepared,
                self._tool_context,
                confirmation_claimer=claim,
            )
            self._records.append(record)
            if isinstance(record.outcome, ToolFailure) and record.outcome.code in {
                "authorization_mismatch",
                "confirmation_claim_failed",
                "confirmation_claim_lost",
                "fallback_confirmation_consumed",
            }:
                raise StalePendingActionError(
                    "stale pending action: fallback confirmation was already consumed"
                )
            if not record.execution_started and not record.terminal_persisted:
                assert isinstance(record.outcome, ToolFailure)
                raise PendingActionValidationError(
                    record.outcome.compatibility_detail or record.outcome.code
                )
            if record.terminal_persisted:
                if record.persisted_visible_result is None:
                    raise RuntimeError("persisted operation result is missing")
                result = record.persisted_visible_result
            else:
                result = render_compatibility(spec, record.outcome)
        else:
            if self._confirmation_attempt_sink is not None:
                rejected_claim = self._confirmation_attempt_sink(pending, None)
                if isinstance(rejected_claim, ToolFailure):
                    raise StalePendingActionError("stale pending action: rejection claim failed")
            elif not _claim_fallback_confirmation(confirmation_lock_key, pending):
                raise StalePendingActionError(
                    "stale pending action: rejection was already consumed"
                )
            self._emit_pending_tool_call(pending, "rejected")
            result = _rejection_result(rejection_feedback)
            self._failures.append(
                ToolFailure(
                    "confirmation_rejected",
                    "confirmation_rejected",
                    result,
                )
            )
        self._emit_tool_result(pending.tool_call_id, pending.tool_name, result, record)

        tool_message = Message(role="tool", content=result, tool_call_id=pending.tool_call_id)
        added = [tool_message]
        if self._confirmation_result_sink is not None:
            self._confirmation_result_sink(sink_pending, approved, tool_message, record)
        first_records = tuple(self._records)
        first_failures = tuple(self._failures)
        continuation = self.run_turn(
            [*messages, tool_message],
            auto_approve=auto_approve,
            max_iter=max_iter,
        )
        added.extend(continuation.added)
        records = (*first_records, *continuation.records)
        failures = (*first_failures, *continuation.failures)
        self._records = list(records)
        self._failures = list(failures)
        return AgentTurnResult(added, continuation.reply, continuation.pending, records, failures)

    def _emit_tool_call(self, tool_call: Any, auto_approve: bool) -> None:
        del auto_approve
        tool_name = str(tool_call.name)
        spec = self._catalog.resolve(tool_name)
        is_write = spec is not None and spec.kind == "write"
        confirm_mode = "hitl" if is_write else "none"
        summary = _tool_call_summary(spec, str(tool_call.args or ""), tool_name)
        self._emit_event(
            "tool_call",
            {
                "tool_call_id": str(tool_call.id),
                "tool_name": tool_name,
                "public_label": _tool_public_label(spec, tool_name),
                "kind": "write" if is_write else "read",
                "confirm_mode": confirm_mode,
                "summary": summary,
                "args_summary": _args_summary(str(tool_call.args or "")),
            },
        )

    def _emit_pending_tool_call(self, pending: PendingAction, confirm_mode: str) -> None:
        spec = self._catalog.resolve(pending.tool_name)
        self._emit_event(
            "tool_call",
            {
                "tool_call_id": pending.tool_call_id,
                "tool_name": pending.tool_name,
                "public_label": _tool_public_label(spec, pending.tool_name),
                "kind": "write" if spec is not None and spec.kind == "write" else "read",
                "confirm_mode": confirm_mode,
                "summary": _spec_confirmation_description(spec, pending.args, pending.human),
                "args_summary": _args_summary(pending.args),
            },
        )

    def _emit_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        result: str,
        record: ToolExecutionRecord[Any, Any] | None,
    ) -> None:
        spec = self._catalog.resolve(tool_name)
        payload: dict[str, Any]
        if record is not None and record.terminal_persisted:
            if record.persisted_transport is None:
                raise RuntimeError("persisted operation transport is missing")
            payload = cast(dict[str, Any], dict(record.persisted_transport))
        elif spec is not None and record is not None:
            try:
                payload = project_transport_event(spec, record)
            except Exception:
                payload = _delivery_error_payload(tool_call_id, tool_name, result)
        else:
            payload = _delivery_error_payload(tool_call_id, tool_name, result)
        payload.setdefault("tool_call_id", tool_call_id)
        if record is not None and record.operation_id:
            payload.setdefault("operation_id", record.operation_id)
        self._emit_event("tool_result", cast(dict[str, Any], payload))

    def _complete_model(
        self,
        messages: list[Message],
        tools: list[ProviderToolContract],
        *,
        model_step: int,
    ) -> Assistant:
        model_call_id = str(uuid4())
        snapshot_id = self._capture_model_input(
            messages,
            tools,
            model_step=model_step,
            model_call_id=model_call_id,
        )
        stream_complete = getattr(self._model, "stream_complete", None)
        is_stream = callable(stream_complete)
        if snapshot_id is not None:
            provider_kind, model_id, supports_json_schema = _journal_model_metadata(self._model)
            model_id_fingerprint = self._fingerprint_model_id(model_id)
            self._append_journal_event(
                EventInput(
                    event_type="model.requested",
                    facts={
                        "snapshot_id": snapshot_id,
                        "provider_kind": provider_kind,
                        "model_id_fingerprint": model_id_fingerprint,
                        "supports_tools": True,
                        "supports_json_schema": supports_json_schema,
                        "stream": is_stream,
                        "tools_count": len(tools),
                        "response_format_kind": "text",
                    },
                    model_step=model_step,
                    model_call_id=model_call_id,
                    source_ref_type="context_snapshot",
                    source_ref_id=snapshot_id,
                )
            )
        try:
            self._require_delivery_fence()
            if is_stream:
                assistant = cast(StreamingChatModel, self._model).stream_complete(
                    messages,
                    tools,
                    self._emit_assistant_delta,
                )
            else:
                assistant = self._model.complete(messages, tools)
            self._require_delivery_fence()
        except Exception as exc:
            if snapshot_id is not None:
                failure_category, provider_outcome = _journal_model_failure(exc)
                self._append_journal_event(
                    EventInput(
                        event_type="model.failed",
                        facts={
                            "failure_category": failure_category,
                            "provider_outcome": provider_outcome,
                        },
                        model_step=model_step,
                        model_call_id=model_call_id,
                    )
                )
            raise
        if snapshot_id is not None:
            assistant_kind = _journal_assistant_kind(assistant)
            self._append_journal_event(
                EventInput(
                    event_type="model.completed",
                    facts={
                        "assistant_kind": assistant_kind,
                        "tool_call_count": len(assistant.tool_calls),
                        "finish_category": ("tool_calls" if assistant.tool_calls else "stop"),
                    },
                    model_step=model_step,
                    model_call_id=model_call_id,
                )
            )
        return assistant

    def _require_delivery_fence(self) -> None:
        if self._delivery_fence is not None and not self._delivery_fence():
            raise ChatRunCancelled("write operation delivery owner fenced")

    def _capture_model_input(
        self,
        messages: list[Message],
        tools: list[ProviderToolContract],
        *,
        model_step: int,
        model_call_id: str,
    ) -> str | None:
        try:
            return self._run_recorder.capture_context(
                _journal_model_input(messages, tools),
                ContextManifestInput(
                    conversation_message_ids=(),
                    tool_names=tuple(tool.name for tool in tools),
                    attachment_refs=(),
                    domain_source_refs=(),
                ),
                snapshot_kind="model_input",
                model_step=model_step,
                model_call_id=model_call_id,
            )
        except Exception:
            return None

    def _fingerprint_model_id(self, model_id: str) -> str | None:
        try:
            return self._run_recorder.fingerprint_model_id(model_id)
        except Exception:
            return None

    def _append_journal_event(self, event: EventInput) -> None:
        try:
            self._run_recorder.append_event(event)
        except Exception:
            return

    def _emit_assistant_delta(self, delta: str) -> None:
        if not delta:
            return
        self._emit_event("assistant_delta", {"delta": delta})

    def _emit_event(self, event: str, data: dict[str, Any]) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink({"event": event, "data": data})
        except Exception:
            return

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise ChatRunCancelled("chat run cancelled")


def run_turn(
    model: ChatModel,
    catalog: ToolCatalog,
    messages: list[Message],
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
    *,
    thread_id: str = _DEFAULT_THREAD_ID,
    event_sink: AgentEventSink | None = None,
    cancel_check: CancelCheck | None = None,
    run_recorder: RunRecorder | None = None,
    delivery_fence: DeliveryFence | None = None,
    tool_context: ToolExecutionContext,
) -> AgentTurnResult:
    return LangGraphAgentRunner(
        model,
        catalog,
        tool_context,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
        run_recorder=run_recorder,
        delivery_fence=delivery_fence,
    ).run_turn(messages, auto_approve=auto_approve, max_iter=max_iter)


def resume_after_confirm(
    model: ChatModel,
    catalog: ToolCatalog,
    messages: list[Message],
    pending: PendingAction,
    approved: bool,
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
    rejection_feedback: str = "",
    *,
    thread_id: str = _DEFAULT_THREAD_ID,
    event_sink: AgentEventSink | None = None,
    cancel_check: CancelCheck | None = None,
    confirmation_result_sink: ConfirmationResultSink | None = None,
    confirmation_attempt_sink: ConfirmationAttemptSink | None = None,
    run_recorder: RunRecorder | None = None,
    delivery_fence: DeliveryFence | None = None,
    tool_context: ToolExecutionContext,
) -> AgentTurnResult:
    return LangGraphAgentRunner(
        model,
        catalog,
        tool_context,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
        confirmation_result_sink=confirmation_result_sink,
        confirmation_attempt_sink=confirmation_attempt_sink,
        run_recorder=run_recorder,
        delivery_fence=delivery_fence,
    ).resume_after_confirm(
        messages,
        pending,
        approved,
        auto_approve,
        max_iter,
        rejection_feedback,
    )


def prepare_pending_action(
    pending: PendingAction,
    catalog: ToolCatalog,
    edited_args: dict[str, Any] | None,
) -> PendingAction:
    if edited_args is None:
        return pending
    if not isinstance(edited_args, dict):
        raise ValueError("edited arguments must be a JSON object")

    spec = catalog.resolve(pending.tool_name)
    if spec is None:
        raise ValueError(f'unknown pending tool "{pending.tool_name}"')

    original_args = _parse_json_object(
        pending.args,
        "pending arguments must be a valid JSON object",
    )

    editable_fields = {
        descriptor.get("field"): descriptor
        for descriptor in spec.editable_fields
        if isinstance(descriptor.get("field"), str)
    }
    non_editable = [str(field) for field in edited_args if field not in editable_fields]
    if non_editable:
        raise ValueError("non-editable fields: " + ", ".join(sorted(non_editable)))

    for field, value in edited_args.items():
        _validate_edited_value(str(field), value, editable_fields[field])

    effective_args = {**original_args, **edited_args}
    encoded_args = _encode_json_object(effective_args)
    return PendingAction(
        tool_call_id=pending.tool_call_id,
        tool_name=pending.tool_name,
        args=encoded_args,
        human=_spec_confirmation_description(spec, encoded_args, pending.human),
        operation_id=pending.operation_id,
    )


def _validated_resumed_args(
    tool_call_id: str,
    tool_name: str,
    original_encoded_args: str,
    effective_encoded_args: Any,
    catalog: ToolCatalog,
) -> str:
    if not isinstance(effective_encoded_args, str):
        raise ValueError("approved resume requires validated effective arguments")
    try:
        original_args = _parse_json_object(
            original_encoded_args,
            "effective arguments must be a valid JSON object",
        )
        effective_args = _parse_json_object(
            effective_encoded_args,
            "effective arguments must be a valid JSON object",
        )
    except ValueError as exc:
        raise ValueError("effective arguments must be a valid JSON object") from exc

    missing_fields = [str(field) for field in original_args if field not in effective_args]
    if missing_fields:
        raise ValueError(
            "effective arguments removed original fields: " + ", ".join(missing_fields)
        )
    edited_args = {
        field: value
        for field, value in effective_args.items()
        if field not in original_args or not _same_json_value(original_args[field], value)
    }
    prepared = prepare_pending_action(
        PendingAction(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=original_encoded_args,
            human=tool_name,
        ),
        catalog,
        edited_args,
    )
    return prepared.args


def _resume_identity_error(
    resume_value: dict[str, Any],
    tool_call_id: str,
    tool_name: str,
) -> str:
    if resume_value.get("tool_call_id") != tool_call_id:
        return "confirmation does not match the pending tool call"
    if resume_value.get("tool_name") != tool_name:
        return "confirmation does not match the pending tool"
    return ""


def _parse_json_object(raw: str, error_message: str) -> dict[str, Any]:
    try:
        parsed = parse_arguments(raw)
    except ArgumentValidationError as exc:
        raise ValueError(error_message) from exc
    return cast(dict[str, Any], parsed)


def _encode_json_object(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _pending_action_revision(tool_call_id: str, tool_name: str, raw_args: str) -> int:
    try:
        normalized_args = _encode_json_object(
            _parse_json_object(raw_args, "pending arguments must be a valid JSON object")
        )
    except ValueError:
        normalized_args = raw_args
    canonical = json.dumps(
        {
            "args": normalized_args,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(canonical).digest()[:8], "big") & ((1 << 63) - 1)


def _validate_finite_json_numbers(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite_json_numbers(item)
    elif isinstance(value, list):
        for item in value:
            _validate_finite_json_numbers(item)


def _same_json_value(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(left_value, right_value)
            for left_value, right_value in zip(left, right, strict=True)
        )
    return bool(left == right)


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f'non-JSON numeric constant "{value}"')


def _is_json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _validate_edited_value(field: str, value: Any, descriptor: Mapping[str, Any]) -> None:
    if (
        descriptor.get("clearable") is True
        and "clear_value" in descriptor
        and _is_json_scalar(descriptor["clear_value"])
        and _same_json_value(value, descriptor["clear_value"])
    ):
        return
    field_type = descriptor.get("type")
    if field_type in {"string", "long_text"}:
        if not isinstance(value, str):
            raise ValueError(f'edited field "{field}" must be a string')
        return
    if field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'edited field "{field}" must be a finite number')
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f'edited field "{field}" must be a finite number')
        return
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f'edited field "{field}" must be a boolean')
        return
    if field_type == "enum":
        options = descriptor.get("options")
        if not isinstance(value, str) or not isinstance(options, list) or value not in options:
            raise ValueError(f'edited field "{field}" must be one of the configured options')
        return
    if field_type == "datetime":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'edited field "{field}" must be an ISO/RFC3339 datetime string')
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f'edited field "{field}" must be an ISO/RFC3339 datetime string'
            ) from exc
        return
    raise ValueError(f'edited field "{field}" has unknown descriptor type "{field_type}"')


def _rejection_result(rejection_feedback: Any) -> str:
    feedback = rejection_feedback.strip() if isinstance(rejection_feedback, str) else ""
    if not feedback:
        return "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"
    return f"用户拒绝了该操作，请勿执行。用户反馈：{feedback}请将这条反馈作为用户指导继续正常回应。"


def _spec_confirmation_description(
    spec: ToolSpec[Any, Any] | None,
    args: str,
    fallback: str,
) -> str:
    if spec is None or spec.confirmation_description is None:
        return fallback
    try:
        parsed = parse_arguments(args)
        human = spec.confirmation_description(spec.decoder(parsed))
    except Exception:
        return fallback
    return str(human or fallback)


def _journal_model_input(
    messages: list[Message],
    tools: list[ProviderToolContract],
) -> dict[str, object]:
    return {
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "tool_call_id": message.tool_call_id,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "args": call.args}
                    for call in message.tool_calls
                ],
            }
            for message in messages
        ],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            }
            for tool in tools
        ],
    }


def _journal_model_metadata(model: ChatModel) -> tuple[str, str, bool]:
    provider_kind = "openai_compatible"
    model_id = f"{type(model).__module__}.{type(model).__qualname__}"
    supports_json_schema = getattr(model, "supports_json_schema", False) is True
    providers = getattr(model, "_providers", None)
    if isinstance(providers, list) and providers:
        profile = providers[0]
        raw_provider = str(getattr(profile, "provider", "") or "")
        provider_kind = (
            raw_provider
            if raw_provider in {"openai", "openai_compatible", "litellm_proxy", "anthropic"}
            else "openai_compatible"
        )
        model_id = str(getattr(profile, "model", "") or model_id)
    else:
        raw_provider = str(getattr(model, "provider_kind", "") or "")
        if raw_provider in {"openai", "openai_compatible", "litellm_proxy", "anthropic"}:
            provider_kind = raw_provider
        model_id = str(getattr(model, "model", "") or model_id)
    return provider_kind, model_id, supports_json_schema


def _journal_model_failure(error: Exception) -> tuple[str, str]:
    if isinstance(error, TimeoutError):
        return "timeout", "timeout"
    if isinstance(error, ConnectionError):
        return "network_error", "network_error"
    return "provider_error", "error"


def _journal_assistant_kind(assistant: Assistant) -> str:
    if assistant.content and assistant.tool_calls:
        return "mixed"
    if assistant.tool_calls:
        return "tool_calls"
    if assistant.content:
        return "text"
    return "empty"


def _select_tool_calls(tool_calls: list[Any], catalog: ToolCatalog) -> list[Any]:
    if not tool_calls:
        return []
    if all(
        (spec := catalog.resolve(str(call.name))) is None or spec.kind == "read"
        for call in tool_calls
    ):
        return tool_calls
    return tool_calls[:1]


def _tool_public_label(spec: ToolSpec[Any, Any] | None, fallback: str) -> str:
    description = spec.contract.description.strip() if spec is not None else ""
    return description or fallback


def _tool_call_summary(spec: ToolSpec[Any, Any] | None, args: str, fallback: str) -> str:
    if spec is not None and spec.kind == "write":
        return _spec_confirmation_description(spec, args, fallback)
    return _tool_public_label(spec, fallback)


def _args_summary(args: str) -> Any:
    try:
        parsed = json.loads(args) if args else {}
    except json.JSONDecodeError:
        return {}
    return _scrub_sensitive(parsed)


def _delivery_error_payload(tool_call_id: str, tool_name: str, result: str) -> dict[str, Any]:
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "status": "error",
        "summary": _summarize_tool_result(result),
        "evidence": [],
        "affected_resources": [],
        "changed_entities": [],
    }


def _summarize_tool_result(result: str) -> str:
    compact = " ".join(result.split())
    return compact[:500]


def _scrub_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in ("key", "token", "secret", "password")):
                result[key] = "***"
            else:
                result[key] = _scrub_sensitive(item)
        return result
    if isinstance(value, list):
        return [_scrub_sensitive(item) for item in value]
    return value


def _next_after_model(state: _GraphState) -> Literal["tool", "final"]:
    return "tool" if state.get("status") == "tool" else "final"


def _next_after_tool(state: _GraphState) -> Literal["continue", "final"]:
    return "continue" if state.get("status") == "continue" else "final"


def _tool_call_to_dict(tool_call: Any) -> dict[str, Any]:
    return {"id": tool_call.id, "name": tool_call.name, "args": tool_call.args}


def _tool_call_from_dict(raw: dict[str, Any]) -> Any:
    from offerpilot.ai.types import ToolCall

    return ToolCall(id=str(raw["id"]), name=str(raw["name"]), args=str(raw.get("args") or ""))


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [_tool_call_to_dict(tool_call) for tool_call in message.tool_calls],
        "tool_call_id": message.tool_call_id,
        "provider_blocks": dict(message.provider_blocks),
    }


def _message_from_dict(raw: dict[str, Any]) -> Message:
    return Message(
        role=str(raw["role"]),
        content=str(raw.get("content") or ""),
        tool_calls=[_tool_call_from_dict(tool_call) for tool_call in raw.get("tool_calls", [])],
        tool_call_id=str(raw.get("tool_call_id") or ""),
        provider_blocks=cast(dict[str, Any], raw.get("provider_blocks") or {}),
    )
