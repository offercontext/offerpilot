from __future__ import annotations

import json
import math
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, TypedDict, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from offerpilot.ai.types import Assistant, Message

DEFAULT_MAX_ITERATIONS = 20
_DEFAULT_THREAD_ID = "conversation:ephemeral"
AgentEventSink = Callable[[dict[str, Any]], None]
AssistantDeltaSink = Callable[[str], None]
CancelCheck = Callable[[], bool]


class ChatRunCancelled(RuntimeError):
    """Raised when a chat run is cancelled before another model/tool step."""


class ChatModel(Protocol):
    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        ...


class StreamingChatModel(Protocol):
    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_delta: AssistantDeltaSink,
    ) -> Assistant:
        ...


@dataclass
class PendingAction:
    tool_call_id: str
    tool_name: str
    args: str
    human: str


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
    ):
        self._model = model
        self._registry = registry
        self._checkpoint_path = checkpoint_path
        self._thread_id = thread_id
        self._event_sink = event_sink
        self._cancel_check = cancel_check
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
        self._emit_pending_tool_call(pending, "approved" if approved else "rejected")
        checkpoint_missing = self._checkpoint_path is None or not self._checkpoint_path.exists()
        if checkpoint_missing and not self._has_pending_checkpoint:
            return self._resume_without_checkpoint(
                messages,
                pending,
                approved,
                auto_approve,
                max_iter,
                rejection_feedback,
            )

        with self._checkpointer() as checkpointer:
            graph = self._compile_graph(checkpointer)
            result = graph.invoke(
                Command(
                    update={"added": []},
                    resume={
                        "approved": approved,
                        "effective_args": pending.args,
                        "rejection_feedback": rejection_feedback,
                    },
                ),
                self._config(max_iter),
            )
        added, reply, new_pending = self._result_from_state(cast(dict[str, Any], result))
        if new_pending is not None:
            self._has_pending_checkpoint = True
        return added, reply, new_pending

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
        tools = [{"name": name, **tool} for name, tool in self._registry.items()]
        assistant = self._complete_model(work, tools)
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
            "current_tool_calls": [_tool_call_to_dict(tool_call) for tool_call in selected_tool_calls],
            "status": "tool",
            "iterations": iterations + 1,
        }

    def _handle_tool(self, state: _GraphState) -> _GraphState:
        current_tool_calls = state.get("current_tool_calls") or [state["current_tool_call"]]
        messages = list(state.get("messages", []))
        added = list(state.get("added", []))
        for tool_call in current_tool_calls:
            self._raise_if_cancelled()
            tool_name = str(tool_call["name"])
            tool_args = str(tool_call.get("args") or "")
            tool_call_id = str(tool_call["id"])
            tool = self._registry.get(tool_name)

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
                            result = "错误：" + str(exc)
                        else:
                            result = _execute_tool(tool, effective_args)
                    else:
                        result = _rejection_result(resume_value.get("rejection_feedback"))
                else:
                    self._raise_if_cancelled()
                    result = _execute_tool(tool, tool_args)
            else:
                self._raise_if_cancelled()
                result = _execute_tool(tool, tool_args)

            self._emit_tool_result(tool_call_id, tool_name, result)
            tool_message = Message(role="tool", content=result, tool_call_id=tool_call_id)
            messages.append(_message_to_dict(tool_message))
            added.append(_message_to_dict(tool_message))
        return {
            "messages": messages,
            "added": added,
            "status": "continue",
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
            return added, "", PendingAction(
                tool_call_id=str(pending_payload["tool_call_id"]),
                tool_name=str(pending_payload["tool_name"]),
                args=str(pending_payload["args"]),
                human=str(pending_payload["human"]),
            )
        return added, str(state.get("reply") or ""), None

    def _resume_without_checkpoint(
        self,
        messages: list[Message],
        pending: PendingAction,
        approved: bool,
        auto_approve: bool,
        max_iter: int,
        rejection_feedback: str = "",
    ) -> tuple[list[Message], str, PendingAction | None]:
        if approved is True:
            tool = self._registry[pending.tool_name]
            validation_error = _validate_pending_action(tool.get("validate"), pending.args)
            if validation_error:
                result = "错误：" + validation_error
            else:
                result = _execute_tool(tool, pending.args)
        else:
            result = _rejection_result(rejection_feedback)
        self._emit_tool_result(pending.tool_call_id, pending.tool_name, result)

        tool_message = Message(role="tool", content=result, tool_call_id=pending.tool_call_id)
        added = [tool_message]
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
        confirm_mode = "hitl" if _requires_confirmation(tool, auto_approve) else "auto" if is_write else "none"
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
                "summary": pending.human,
                "args_summary": _args_summary(pending.args),
            },
        )

    def _emit_tool_result(self, tool_call_id: str, tool_name: str, result: str) -> None:
        self._emit_event("tool_result", _tool_result_payload(tool_call_id, tool_name, result))

    def _complete_model(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        stream_complete = getattr(self._model, "stream_complete", None)
        if callable(stream_complete):
            return cast(StreamingChatModel, self._model).stream_complete(
                messages,
                tools,
                self._emit_assistant_delta,
            )
        return self._model.complete(messages, tools)

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
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
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
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
        cancel_check=cancel_check,
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

    try:
        original_args = json.loads(pending.args, parse_constant=_reject_non_json_constant)
    except (ValueError, TypeError) as exc:
        raise ValueError("pending arguments must be a valid JSON object") from exc
    if not isinstance(original_args, dict):
        raise ValueError("pending arguments must be a valid JSON object")

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
    encoded_args = json.dumps(effective_args, ensure_ascii=False, separators=(",", ":"))
    validation_error = _validate_pending_action(tool.get("validate"), encoded_args)
    if validation_error:
        raise ValueError(validation_error)
    return PendingAction(
        tool_call_id=pending.tool_call_id,
        tool_name=pending.tool_name,
        args=encoded_args,
        human=pending.human,
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
        original_args = json.loads(
            original_encoded_args,
            parse_constant=_reject_non_json_constant,
        )
        effective_args = json.loads(
            effective_encoded_args,
            parse_constant=_reject_non_json_constant,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("effective arguments must be a valid JSON object") from exc
    if not isinstance(original_args, dict) or not isinstance(effective_args, dict):
        raise ValueError("effective arguments must be a valid JSON object")

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
    prepare_pending_action(
        PendingAction(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args=original_encoded_args,
            human=tool_name,
        ),
        registry,
        edited_args,
    )
    return effective_encoded_args


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


def _validate_edited_value(field: str, value: Any, descriptor: dict[str, Any]) -> None:
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
    except Exception as exc:
        return str(exc)
    return str(error or "")


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


def _requires_confirmation(tool: dict[str, Any], auto_approve: bool) -> bool:
    if not bool(tool.get("write")):
        return False
    return not auto_approve or bool(tool.get("always_confirm"))


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
