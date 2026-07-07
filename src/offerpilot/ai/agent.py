from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from offerpilot.ai.types import Assistant, Message

DEFAULT_MAX_ITERATIONS = 20


class ChatModel(Protocol):
    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        ...


@dataclass
class PendingAction:
    tool_call_id: str
    tool_name: str
    args: str
    human: str


def run_turn(
    model: ChatModel,
    registry: dict[str, dict[str, Any]],
    messages: list[Message],
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
) -> tuple[list[Message], str, PendingAction | None]:
    added: list[Message] = []
    work = list(messages)
    tools = [{"name": name, **tool} for name, tool in registry.items()]

    for _ in range(max_iter or DEFAULT_MAX_ITERATIONS):
        assistant = model.complete(work, tools)
        if not assistant.tool_calls:
            message = Message(
                role="assistant",
                content=assistant.content,
                provider_blocks=assistant.provider_blocks,
            )
            added.append(message)
            return added, assistant.content, None

        tool_call = assistant.tool_calls[0]
        assistant_message = Message(
            role="assistant",
            content=assistant.content,
            tool_calls=[tool_call],
            provider_blocks=assistant.provider_blocks,
        )
        added.append(assistant_message)
        work.append(assistant_message)

        tool = registry.get(tool_call.name)
        if tool is None:
            result = f'错误：未知工具 "{tool_call.name}"'
            tool_message = Message(role="tool", content=result, tool_call_id=tool_call.id)
            added.append(tool_message)
            work.append(tool_message)
            continue

        if bool(tool.get("write")) and not auto_approve:
            describe = tool.get("describe")
            human = _describe_pending_action(describe, tool_call.args, tool_call.name)
            return added, "", PendingAction(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.args,
                human=human,
            )

        result = _execute_tool(tool, tool_call.args)
        tool_message = Message(role="tool", content=result, tool_call_id=tool_call.id)
        added.append(tool_message)
        work.append(tool_message)

    raise RuntimeError("AI 工具调用超过最大轮次")


def resume_after_confirm(
    model: ChatModel,
    registry: dict[str, dict[str, Any]],
    messages: list[Message],
    pending: PendingAction,
    approved: bool,
    auto_approve: bool,
    max_iter: int = DEFAULT_MAX_ITERATIONS,
) -> tuple[list[Message], str, PendingAction | None]:
    if approved:
        result = _execute_tool(registry[pending.tool_name], pending.args)
    else:
        result = "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"

    tool_message = Message(role="tool", content=result, tool_call_id=pending.tool_call_id)
    added = [tool_message]
    more, reply, new_pending = run_turn(
        model,
        registry,
        [*messages, tool_message],
        auto_approve=auto_approve,
        max_iter=max_iter,
    )
    added.extend(more)
    return added, reply, new_pending


def _describe_pending_action(describe: Any, args: str, fallback: str) -> str:
    if not callable(describe):
        return fallback
    try:
        human = describe(args)
    except Exception:
        return fallback
    return str(human or fallback)


def _execute_tool(tool: dict[str, Any], args: str) -> str:
    handler = tool["handler"]
    try:
        return str(handler(args))
    except Exception as exc:  # pragma: no cover - exercised through API adapters later.
        return "错误：" + str(exc)

