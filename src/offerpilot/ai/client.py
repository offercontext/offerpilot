from __future__ import annotations

import json
from typing import Any

from litellm import completion

from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.config import AIProviderProfile, Config


class ConfiguredAIClient:
    def __init__(self, config: Config):
        self._provider = config.active_provider()
        if not self._provider.api_key:
            raise ValueError("AI is not configured: run `oc config` to set your API key")

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        payload: dict[str, Any] = {
            "model": _litellm_model(self._provider),
            "messages": [_openai_message(message) for message in messages],
            "api_key": self._provider.api_key,
        }
        api_base = _litellm_api_base(self._provider)
        if api_base:
            payload["api_base"] = api_base
        if tools:
            payload["tools"] = [_openai_tool(tool) for tool in tools]
            payload["tool_choice"] = "auto"

        response = completion(**payload)
        message = _first_choice_message(response)
        calls = []
        for call in _get(message, "tool_calls") or []:
            function = _get(call, "function") or {}
            calls.append(
                ToolCall(
                    id=str(_get(call, "id") or ""),
                    name=str(_get(function, "name") or ""),
                    args=str(_get(function, "arguments") or "{}"),
                )
            )
        return Assistant(
            content=str(_get(message, "content") or ""),
            tool_calls=calls,
            provider_blocks=_provider_blocks(message),
        )


def _litellm_model(provider: AIProviderProfile) -> str:
    if "/" in provider.model:
        return provider.model
    if provider.provider in {"openai", "openai_compatible", "litellm_proxy"}:
        return f"openai/{provider.model}"
    if provider.provider:
        return f"{provider.provider}/{provider.model}"
    return provider.model


def _litellm_api_base(provider: AIProviderProfile) -> str:
    if provider.provider == "anthropic":
        return ""
    return provider.base_url.rstrip("/")


def _first_choice_message(response: Any) -> Any:
    choices = _get(response, "choices") or []
    if not choices:
        return {}
    return _get(choices[0], "message") or {}


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _openai_message(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "assistant":
        reasoning_content = message.provider_blocks.get("reasoning_content")
        if reasoning_content is not None:
            out["reasoning_content"] = reasoning_content
    if message.tool_call_id:
        out["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.args},
            }
            for call in message.tool_calls
        ]
    return out


def _provider_blocks(message: Any) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    reasoning_content = _get(message, "reasoning_content")
    if reasoning_content is not None:
        blocks["reasoning_content"] = reasoning_content
    return blocks


def _openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("schema") or {"type": "object", "properties": {}}
    if isinstance(schema, str):
        schema = json.loads(schema)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        },
    }
