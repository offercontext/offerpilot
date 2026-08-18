from __future__ import annotations

import hashlib
import json
import math
import os
from collections import OrderedDict
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterator, Literal, Protocol, TypedDict, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Interrupt, interrupt

from offerpilot.ai.types import Assistant, Message
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
    """Raised when a confirmation does not match the checkpoint interrupt."""


class PendingActionValidationError(ValueError):
    """Raised when confirmation arguments fail before a write handler is attempted."""


class ChatModel(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> Assistant: ...


class StreamingChatModel(Protocol):
    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_delta: AssistantDeltaSink,
    ) -> Assistant: ...


@dataclass
class PendingAction:
    tool_call_id: str
    tool_name: str
    args: str
    human: str


ConfirmationResultSink = Callable[[PendingAction, bool, Message], None]
ConfirmationAttemptSink = Callable[[PendingAction], None]


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
        registry: dict[str, dict[str, Any]],
        *,
        checkpoint_path: Path | None = None,
        thread_id: str = _DEFAULT_THREAD_ID,
        event_sink: AgentEventSink | None = None,
        cancel_check: CancelCheck | None = None,
        confirmation_result_sink: ConfirmationResultSink | None = None,
        confirmation_attempt_sink: ConfirmationAttemptSink | None = None,
        run_recorder: RunRecorder | None = None,
    ):
        self._model = model
        self._registry = registry
        self._checkpoint_path = checkpoint_path
        self._thread_id = thread_id
        self._event_sink = event_sink
        self._cancel_check = cancel_check
        self._confirmation_result_sink = confirmation_result_sink
        self._confirmation_attempt_sink = confirmation_attempt_sink
        self._run_recorder = run_recorder or NullRunRecorder()
        self._memory_saver = InMemorySaver()
        self._has_pending_checkpoint = False

    def run_turn(
        self,
        messages: list[Message],
        auto_approve: bool,
        max_iter: int = DEFAULT_MAX_ITERATIONS,
    ) -> tuple[list[Message], str, PendingAction | None]:
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
        if pending is not None:
            self._has_pending_checkpoint = True
        return added, reply, pending

    def resume_after_confirm(
        self,
        messages: list[Message],
        pending: PendingAction,
        approved: bool,
        auto_approve: bool,
        max_iter: int = DEFAULT_MAX_ITERATIONS,
        rejection_feedback: str = "",
    ) -> tuple[list[Message], str, PendingAction | None]:
        approved = approved is True
        confirmation_lock_key = self._confirmation_lock_key()
        with _confirmation_lock(confirmation_lock_key):
            return self._resume_after_confirm_locked(
                messages,
                pending,
                approved,
                auto_approve,
                max_iter,
                rejection_feedback,
                confirmation_lock_key,
            )

    def _resume_after_confirm_locked(
        self,
        messages: list[Message],
        pending: PendingAction,
        approved: bool,
        auto_approve: bool,
        max_iter: int,
        rejection_feedback: str,
        confirmation_lock_key: ConfirmationLockKey,
    ) -> tuple[list[Message], str, PendingAction | None]:
        checkpoint_missing = self._checkpoint_path is None or not self._checkpoint_path.exists()
        if checkpoint_missing and not self._has_pending_checkpoint:
            return self._resume_without_checkpoint(
                messages,
                pending,
                approved,
                auto_approve,
                max_iter,
                rejection_feedback,
                confirmation_lock_key,
            )

        with self._checkpointer() as checkpointer:
            graph = self._compile_graph(checkpointer)
            config = self._config(max_iter)
            interrupt_id = _assert_pending_checkpoint_identity(graph, config, pending)
            resume_attempt_id = uuid4().hex
            resume_payload = {
                "approved": approved,
                "tool_call_id": pending.tool_call_id,
                "tool_name": pending.tool_name,
                "effective_args": pending.args,
                "rejection_feedback": rejection_feedback,
                "resume_attempt_id": resume_attempt_id,
            }
            result = graph.invoke(
                Command(
                    resume={interrupt_id: resume_payload},
                ),
                config,
            )
        result_state = cast(dict[str, Any], result)
        if (
            result_state.get("consumed_resume_id") != interrupt_id
            or result_state.get("consumed_resume_attempt_id") != resume_attempt_id
        ):
            raise StalePendingActionError(
                "stale pending action: confirmation resume was not consumed"
            )
        added, reply, new_pending = self._result_from_state(result_state)
        if new_pending is not None:
            self._has_pending_checkpoint = True
        return added, reply, new_pending

    def _confirmation_lock_key(self) -> ConfirmationLockKey:
        if self._checkpoint_path is None:
            checkpoint_identity = _IN_MEMORY_CONFIRMATION_NAMESPACE
        else:
            checkpoint_identity = os.path.normcase(
                str(self._checkpoint_path.expanduser().resolve())
            )
        return checkpoint_identity, self._thread_id

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
        tools = _model_visible_tools(self._registry)
        assistant = self._complete_model(work, tools, model_step=iterations + 1)
        selected_tool_calls = _select_tool_calls(assistant.tool_calls, self._registry)
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
            tool = self._registry.get(tool_name)
            has_mapped_resume, mapped_resume, mapped_interrupt_id = _mapped_resume_payload()
            if not has_mapped_resume:
                self._record_tool_proposed(
                    tool_call_id,
                    tool_name,
                    tool_args,
                    tool,
                    auto_approve=bool(state.get("auto_approve", False)),
                )
            if has_mapped_resume:
                mapped_identity_error = _resume_identity_error(
                    mapped_resume,
                    tool_call_id,
                    tool_name,
                )
                if mapped_identity_error:
                    raise StalePendingActionError("stale pending action: " + mapped_identity_error)
                mapped_attempt_id = mapped_resume.get("resume_attempt_id")
                if not isinstance(mapped_attempt_id, str) or not mapped_attempt_id:
                    raise StalePendingActionError(
                        "stale pending action: confirmation resume identity is missing"
                    )
                consumed_resume_id = mapped_interrupt_id
                consumed_resume_attempt_id = mapped_attempt_id
                added = []

            if tool is None:
                result = f'错误：未知工具 "{tool_name}"'
            elif bool(tool.get("write")):
                validation_error = _validate_pending_action(tool.get("validate"), tool_args)
                if validation_error:
                    result = "错误：" + validation_error
                elif _requires_confirmation(tool, bool(state.get("auto_approve", False))):
                    describe = tool.get("describe")
                    pending = {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "human": _describe_pending_action(describe, tool_args, tool_name),
                    }
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
                                self._registry,
                            )
                        except ValueError as exc:
                            raise PendingActionValidationError(str(exc)) from exc
                        effective_pending = PendingAction(
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            args=effective_args,
                            human=_describe_pending_action(
                                describe, effective_args, str(pending["human"])
                            ),
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
                        if self._confirmation_attempt_sink is not None:
                            self._confirmation_attempt_sink(effective_pending)
                        result = self._execute_tool_recorded(
                            tool_call_id,
                            tool_name,
                            tool,
                            effective_args,
                        )
                    else:
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
                    self._raise_if_cancelled()
                    result = self._execute_tool_recorded(
                        tool_call_id,
                        tool_name,
                        tool,
                        tool_args,
                    )
            else:
                self._raise_if_cancelled()
                result = self._execute_tool_recorded(
                    tool_call_id,
                    tool_name,
                    tool,
                    tool_args,
                )

            self._emit_tool_result(tool_call_id, tool_name, result)
            tool_message = Message(role="tool", content=result, tool_call_id=tool_call_id)
            messages.append(_message_to_dict(tool_message))
            added.append(_message_to_dict(tool_message))
            if confirmed_outcome is not None and self._confirmation_result_sink is not None:
                effective_pending, confirmed_approved = confirmed_outcome
                self._confirmation_result_sink(
                    effective_pending,
                    confirmed_approved,
                    tool_message,
                )
        return {
            "messages": messages,
            "added": added,
            "status": "continue",
            "consumed_resume_id": consumed_resume_id,
            "consumed_resume_attempt_id": consumed_resume_attempt_id,
        }

    def _checkpointer(self) -> AbstractContextManager[Any]:
        if self._checkpoint_path is None:
            return nullcontext(self._memory_saver)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteSaver.from_conn_string(str(self._checkpoint_path))

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
    ) -> tuple[list[Message], str, PendingAction | None]:
        sink_pending = pending
        if approved is True:
            tool = self._registry[pending.tool_name]
            try:
                parsed_args = _parse_json_object(
                    pending.args,
                    "pending arguments must be a valid JSON object",
                )
            except ValueError as exc:
                raise PendingActionValidationError(str(exc)) from exc
            effective_args = _encode_json_object(parsed_args)
            validation_error = _validate_pending_action(tool.get("validate"), effective_args)
            if validation_error:
                raise PendingActionValidationError(validation_error)
            sink_pending = PendingAction(
                tool_call_id=pending.tool_call_id,
                tool_name=pending.tool_name,
                args=effective_args,
                human=pending.human,
            )
            self._emit_pending_tool_call(sink_pending, "approved")
            self._raise_if_cancelled()
            if self._confirmation_attempt_sink is not None:
                self._confirmation_attempt_sink(sink_pending)
            if not _claim_fallback_confirmation(
                confirmation_lock_key,
                pending,
            ):
                raise StalePendingActionError(
                    "stale pending action: fallback confirmation was already consumed"
                )
            result = self._execute_tool_recorded(
                pending.tool_call_id,
                pending.tool_name,
                tool,
                effective_args,
            )
        else:
            self._emit_pending_tool_call(pending, "rejected")
            result = _rejection_result(rejection_feedback)
        self._emit_tool_result(pending.tool_call_id, pending.tool_name, result)

        tool_message = Message(role="tool", content=result, tool_call_id=pending.tool_call_id)
        added = [tool_message]
        if self._confirmation_result_sink is not None:
            self._confirmation_result_sink(sink_pending, approved, tool_message)
        more, reply, new_pending = self.run_turn(
            [*messages, tool_message],
            auto_approve=auto_approve,
            max_iter=max_iter,
        )
        added.extend(more)
        return added, reply, new_pending

    def _emit_tool_call(self, tool_call: Any, auto_approve: bool) -> None:
        tool_name = str(tool_call.name)
        tool = self._registry.get(tool_name) or {}
        is_write = bool(tool.get("write"))
        confirm_mode = (
            "hitl" if _requires_confirmation(tool, auto_approve) else "auto" if is_write else "none"
        )
        summary = _tool_call_summary(tool, str(tool_call.args or ""), tool_name)
        self._emit_event(
            "tool_call",
            {
                "tool_call_id": str(tool_call.id),
                "tool_name": tool_name,
                "public_label": _tool_public_label(tool, tool_name),
                "kind": "write" if is_write else "read",
                "confirm_mode": confirm_mode,
                "summary": summary,
                "args_summary": _args_summary(str(tool_call.args or "")),
            },
        )

    def _emit_pending_tool_call(self, pending: PendingAction, confirm_mode: str) -> None:
        tool = self._registry.get(pending.tool_name) or {}
        self._emit_event(
            "tool_call",
            {
                "tool_call_id": pending.tool_call_id,
                "tool_name": pending.tool_name,
                "public_label": _tool_public_label(tool, pending.tool_name),
                "kind": "write" if bool(tool.get("write")) else "read",
                "confirm_mode": confirm_mode,
                "summary": _describe_pending_action(
                    tool.get("describe"), pending.args, pending.human
                ),
                "args_summary": _args_summary(pending.args),
            },
        )

    def _emit_tool_result(self, tool_call_id: str, tool_name: str, result: str) -> None:
        self._emit_event("tool_result", _tool_result_payload(tool_call_id, tool_name, result))

    def _complete_model(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
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
            provider_kind, model_id, supports_json_schema = _journal_model_metadata(
                self._model
            )
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
            if is_stream:
                assistant = cast(StreamingChatModel, self._model).stream_complete(
                    messages,
                    tools,
                    self._emit_assistant_delta,
                )
            else:
                assistant = self._model.complete(messages, tools)
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
                        "finish_category": (
                            "tool_calls" if assistant.tool_calls else "stop"
                        ),
                    },
                    model_step=model_step,
                    model_call_id=model_call_id,
                )
            )
        return assistant

    def _capture_model_input(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        model_step: int,
        model_call_id: str,
    ) -> str | None:
        try:
            return self._run_recorder.capture_context(
                _journal_model_input(messages, tools),
                ContextManifestInput(
                    conversation_message_ids=(),
                    tool_names=tuple(str(tool.get("name") or "") for tool in tools),
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

    def _record_tool_proposed(
        self,
        tool_call_id: str,
        tool_name: str,
        tool_args: str,
        tool: dict[str, Any] | None,
        *,
        auto_approve: bool,
    ) -> None:
        tool_definition = tool or {}
        requires_confirmation = bool(tool_definition.get("write")) and _requires_confirmation(
            tool_definition,
            auto_approve,
        )
        self._append_journal_event(
            EventInput(
                event_type="tool.proposed",
                facts={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "tool_kind": "write" if bool(tool_definition.get("write")) else "read",
                    "args_shape_digest": _journal_shape_digest(tool_args),
                    "proposal_outcome": (
                        "confirmation_required"
                        if requires_confirmation
                        else "execution_allowed"
                    ),
                },
                source_ref_type="tool_call",
                source_ref_id=tool_call_id,
            )
        )

    def _execute_tool_recorded(
        self,
        tool_call_id: str,
        tool_name: str,
        tool: dict[str, Any],
        args: str,
    ) -> str:
        self._append_journal_event(
            EventInput(
                event_type="tool.started",
                facts={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "result_contract": "legacy_string_v1",
                },
                source_ref_type="tool_call",
                source_ref_id=tool_call_id,
            )
        )
        result = _execute_tool(tool, args)
        if result.startswith("错误："):
            event = EventInput(
                event_type="tool.failed",
                facts={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "failure_category": "tool_error",
                },
                source_ref_type="tool_call",
                source_ref_id=tool_call_id,
            )
        else:
            event = EventInput(
                event_type="tool.completed",
                facts={
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "outcome": "completed",
                    "result_shape_digest": _journal_shape_digest(result),
                },
                source_ref_type="tool_call",
                source_ref_id=tool_call_id,
            )
        self._append_journal_event(event)
        return result

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
    registry: dict[str, dict[str, Any]],
    messages: list[Message],
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
    *,
    checkpoint_path: Path | None = None,
    thread_id: str = _DEFAULT_THREAD_ID,
    event_sink: AgentEventSink | None = None,
    cancel_check: CancelCheck | None = None,
    run_recorder: RunRecorder | None = None,
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
        run_recorder=run_recorder,
    ).run_turn(messages, auto_approve=auto_approve, max_iter=max_iter)


def resume_after_confirm(
    model: ChatModel,
    registry: dict[str, dict[str, Any]],
    messages: list[Message],
    pending: PendingAction,
    approved: bool,
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
    rejection_feedback: str = "",
    *,
    checkpoint_path: Path | None = None,
    thread_id: str = _DEFAULT_THREAD_ID,
    event_sink: AgentEventSink | None = None,
    cancel_check: CancelCheck | None = None,
    confirmation_result_sink: ConfirmationResultSink | None = None,
    confirmation_attempt_sink: ConfirmationAttemptSink | None = None,
    run_recorder: RunRecorder | None = None,
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
        confirmation_result_sink=confirmation_result_sink,
        confirmation_attempt_sink=confirmation_attempt_sink,
        run_recorder=run_recorder,
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
    registry: dict[str, dict[str, Any]],
    edited_args: dict[str, Any] | None,
) -> PendingAction:
    if edited_args is None:
        return pending
    if not isinstance(edited_args, dict):
        raise ValueError("edited arguments must be a JSON object")

    tool = registry.get(pending.tool_name)
    if tool is None:
        raise ValueError(f'unknown pending tool "{pending.tool_name}"')

    original_args = _parse_json_object(
        pending.args,
        "pending arguments must be a valid JSON object",
    )

    descriptors = tool.get("editable_fields")
    editable_fields = (
        {
            descriptor.get("field"): descriptor
            for descriptor in descriptors
            if isinstance(descriptor, dict) and isinstance(descriptor.get("field"), str)
        }
        if isinstance(descriptors, list)
        else {}
    )
    non_editable = [str(field) for field in edited_args if field not in editable_fields]
    if non_editable:
        raise ValueError("non-editable fields: " + ", ".join(sorted(non_editable)))

    for field, value in edited_args.items():
        _validate_edited_value(str(field), value, editable_fields[field])

    effective_args = {**original_args, **edited_args}
    encoded_args = _encode_json_object(effective_args)
    validation_error = _validate_pending_action(tool.get("validate"), encoded_args)
    if validation_error:
        raise ValueError(validation_error)
    return PendingAction(
        tool_call_id=pending.tool_call_id,
        tool_name=pending.tool_name,
        args=encoded_args,
        human=_describe_pending_action(tool.get("describe"), encoded_args, pending.human),
    )


def _validated_resumed_args(
    tool_call_id: str,
    tool_name: str,
    original_encoded_args: str,
    effective_encoded_args: Any,
    registry: dict[str, dict[str, Any]],
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
        registry,
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


def _assert_pending_checkpoint_identity(
    graph: Any,
    config: dict[str, Any],
    pending: PendingAction,
) -> str:
    try:
        snapshot = graph.get_state(config)
    except Exception as exc:
        raise StalePendingActionError(
            "stale pending action: unable to read the current checkpoint"
        ) from exc
    interrupts = getattr(snapshot, "interrupts", ())
    if not isinstance(interrupts, tuple) or len(interrupts) != 1:
        raise StalePendingActionError("stale pending action: no current checkpoint interrupt")
    current_interrupt = interrupts[0]
    current = getattr(current_interrupt, "value", None)
    if not isinstance(current, dict):
        raise StalePendingActionError("stale pending action: invalid checkpoint interrupt")
    if (
        current.get("tool_call_id") != pending.tool_call_id
        or current.get("tool_name") != pending.tool_name
    ):
        raise StalePendingActionError(
            "stale pending action: confirmation does not match the current checkpoint"
        )
    interrupt_id = getattr(current_interrupt, "id", None)
    if not isinstance(interrupt_id, str) or not interrupt_id:
        raise StalePendingActionError("stale pending action: invalid checkpoint interrupt identity")
    return interrupt_id


def _mapped_resume_payload() -> tuple[bool, dict[str, Any], str]:
    try:
        configurable = get_config().get("configurable", {})
    except RuntimeError:
        return False, {}, ""
    if "__pregel_resume_map" not in configurable:
        return False, {}, ""
    resume_map = configurable.get("__pregel_resume_map")
    checkpoint_ns = configurable.get("checkpoint_ns")
    if not isinstance(resume_map, dict) or not isinstance(checkpoint_ns, str):
        return True, {}, ""
    current_interrupt_id = Interrupt.from_ns(value=None, ns=checkpoint_ns).id
    if current_interrupt_id not in resume_map:
        return False, {}, ""
    payload = resume_map[current_interrupt_id]
    return True, payload if isinstance(payload, dict) else {}, current_interrupt_id


def _parse_json_object(raw: str, error_message: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw, parse_constant=_reject_non_json_constant)
        _validate_finite_json_numbers(parsed)
    except (ValueError, TypeError) as exc:
        raise ValueError(error_message) from exc
    if not isinstance(parsed, dict):
        raise ValueError(error_message)
    return parsed


def _encode_json_object(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


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


def _validate_edited_value(field: str, value: Any, descriptor: dict[str, Any]) -> None:
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


def _describe_pending_action(describe: Any, args: str, fallback: str) -> str:
    if not callable(describe):
        return fallback
    try:
        human = describe(args)
    except Exception:
        return fallback
    return str(human or fallback)


def _validate_pending_action(validate: Any, args: str) -> str:
    if not callable(validate):
        return ""
    try:
        error = validate(args)
        return str(error or "")
    except Exception:
        return "工具参数验证失败，请检查后重试。"


def _journal_model_input(
    messages: list[Message],
    tools: list[dict[str, Any]],
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
                "name": str(tool.get("name") or ""),
                "description": str(tool.get("description") or ""),
                "parameters": tool.get("schema") or {},
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


def _journal_shape_digest(raw: str) -> str:
    if len(raw) > 65_536:
        value: object = {"type": "oversized"}
    else:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw
    shape = _journal_value_shape(value)
    encoded = json.dumps(shape, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _journal_value_shape(value: object, *, depth: int = 0) -> object:
    if depth >= 16:
        return {"type": "truncated"}
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if len(mapping) > 64:
            return {"type": "object", "field_count": len(mapping), "truncated": True}
        return {
            "type": "object",
            "fields": {
                str(key): _journal_value_shape(item, depth=depth + 1)
                for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0]))
            },
        }
    if type(value) is list:
        sequence = cast(list[object], value)
        return {
            "type": "array",
            "length": len(sequence),
            "items": [_journal_value_shape(item, depth=depth + 1) for item in sequence[:16]],
        }
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) in {int, float}:
        return {"type": "number"}
    if type(value) is str:
        return {"type": "string"}
    return {"type": "unsupported"}


def _execute_tool(tool: dict[str, Any], args: str) -> str:
    handler = tool["handler"]
    try:
        return str(handler(args))
    except Exception as exc:  # pragma: no cover - exercised through API adapters later.
        return "错误：" + str(exc)


def _select_tool_calls(tool_calls: list[Any], registry: dict[str, dict[str, Any]]) -> list[Any]:
    if not tool_calls:
        return []
    if all(not bool((registry.get(str(call.name)) or {}).get("write")) for call in tool_calls):
        return tool_calls
    return tool_calls[:1]


def _model_visible_tools(registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": name, **tool}
        for name, tool in registry.items()
        if tool.get("model_visible", True) is not False
    ]


def _requires_confirmation(tool: dict[str, Any], auto_approve: bool) -> bool:
    if not bool(tool.get("write")):
        return False
    return True


def _tool_public_label(tool: dict[str, Any], fallback: str) -> str:
    description = str(tool.get("description") or "").strip()
    return description or fallback


def _tool_call_summary(tool: dict[str, Any], args: str, fallback: str) -> str:
    if bool(tool.get("write")):
        return _describe_pending_action(tool.get("describe"), args, fallback)
    return _tool_public_label(tool, fallback)


def _args_summary(args: str) -> Any:
    try:
        parsed = json.loads(args) if args else {}
    except json.JSONDecodeError:
        return {}
    return _scrub_sensitive(parsed)


def _tool_result_payload(tool_call_id: str, tool_name: str, result: str) -> dict[str, Any]:
    structured = _json_object(result)
    status = "error" if result.startswith("错误：") else "success"
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "status": status,
        "summary": _summarize_tool_result(result),
        "evidence": _list_field(structured, "evidence"),
        "affected_resources": _list_field(structured, "affected_resources"),
        "changed_entities": _list_field(structured, "changed_entities"),
    }


def _summarize_tool_result(result: str) -> str:
    compact = " ".join(result.split())
    return compact[:500]


def _json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _list_field(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


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
