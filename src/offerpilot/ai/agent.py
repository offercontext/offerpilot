from __future__ import annotations

import json
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
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


class LangGraphAgentRunner:
    def __init__(
        self,
        model: ChatModel,
        registry: dict[str, dict[str, Any]],
        *,
        checkpoint_path: Path | None = None,
        thread_id: str = _DEFAULT_THREAD_ID,
        event_sink: AgentEventSink | None = None,
    ):
        self._model = model
        self._registry = registry
        self._checkpoint_path = checkpoint_path
        self._thread_id = thread_id
        self._event_sink = event_sink
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
    ) -> tuple[list[Message], str, PendingAction | None]:
        self._emit_pending_tool_call(pending, "approved" if approved else "rejected")
        checkpoint_missing = self._checkpoint_path is None or not self._checkpoint_path.exists()
        if checkpoint_missing and not self._has_pending_checkpoint:
            return self._resume_without_checkpoint(messages, pending, approved, auto_approve, max_iter)

        with self._checkpointer() as checkpointer:
            graph = self._compile_graph(checkpointer)
            result = graph.invoke(
                Command(update={"added": []}, resume={"approved": approved}),
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
        iterations = int(state.get("iterations", 0))
        max_iter = int(state.get("max_iter", DEFAULT_MAX_ITERATIONS))
        if iterations >= max_iter:
            raise RuntimeError("AI 工具调用超过最大轮次")

        work = [_message_from_dict(message) for message in state.get("messages", [])]
        tools = [{"name": name, **tool} for name, tool in self._registry.items()]
        assistant = self._complete_model(work, tools)
        assistant_message = Message(
            role="assistant",
            content=assistant.content,
            tool_calls=assistant.tool_calls[:1],
            provider_blocks=assistant.provider_blocks,
        )
        added = [*state.get("added", []), _message_to_dict(assistant_message)]
        messages = [*state.get("messages", []), _message_to_dict(assistant_message)]
        if not assistant.tool_calls:
            return {
                "messages": messages,
                "added": added,
                "reply": assistant.content,
                "status": "final",
                "iterations": iterations + 1,
            }
        self._emit_tool_call(assistant.tool_calls[0], bool(state.get("auto_approve", False)))
        return {
            "messages": messages,
            "added": added,
            "current_tool_call": _tool_call_to_dict(assistant.tool_calls[0]),
            "status": "tool",
            "iterations": iterations + 1,
        }

    def _handle_tool(self, state: _GraphState) -> _GraphState:
        tool_call = state["current_tool_call"]
        tool_name = str(tool_call["name"])
        tool_args = str(tool_call.get("args") or "")
        tool_call_id = str(tool_call["id"])
        tool = self._registry.get(tool_name)

        if tool is None:
            result = f'错误：未知工具 "{tool_name}"'
        elif bool(tool.get("write")) and not bool(state.get("auto_approve", False)):
            validation_error = _validate_pending_action(tool.get("validate"), tool_args)
            if validation_error:
                result = "错误：" + validation_error
            else:
                describe = tool.get("describe")
                pending = {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "human": _describe_pending_action(describe, tool_args, tool_name),
                }
                resume_value = cast(dict[str, Any], interrupt(pending))
                if bool(resume_value.get("approved")):
                    result = _execute_tool(tool, tool_args)
                else:
                    result = "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"
        else:
            result = _execute_tool(tool, tool_args)

        self._emit_tool_result(tool_call_id, tool_name, result)
        tool_message = Message(role="tool", content=result, tool_call_id=tool_call_id)
        return {
            "messages": [*state.get("messages", []), _message_to_dict(tool_message)],
            "added": [*state.get("added", []), _message_to_dict(tool_message)],
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
    ) -> tuple[list[Message], str, PendingAction | None]:
        if approved:
            result = _execute_tool(self._registry[pending.tool_name], pending.args)
        else:
            result = "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"
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
        confirm_mode = "auto" if is_write and auto_approve else "hitl" if is_write else "none"
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
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
    ).run_turn(messages, auto_approve=auto_approve, max_iter=max_iter)


def resume_after_confirm(
    model: ChatModel,
    registry: dict[str, dict[str, Any]],
    messages: list[Message],
    pending: PendingAction,
    approved: bool,
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
    *,
    checkpoint_path: Path | None = None,
    thread_id: str = _DEFAULT_THREAD_ID,
    event_sink: AgentEventSink | None = None,
) -> tuple[list[Message], str, PendingAction | None]:
    return LangGraphAgentRunner(
        model,
        registry,
        checkpoint_path=checkpoint_path,
        thread_id=thread_id,
        event_sink=event_sink,
    ).resume_after_confirm(messages, pending, approved, auto_approve, max_iter)


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
