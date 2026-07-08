from __future__ import annotations

import json
from typing import Any

from litellm import completion

from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.config import AIProviderProfile, Config


class ConfiguredAIClient:
    def __init__(self, config: Config):
        self._providers = _ordered_providers(config)
        if not self._providers:
            raise ValueError("AI is not configured: run `oc config` to set your API key")

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                return _complete_with_provider(provider, messages, tools)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError("AI is not configured: run `oc config` to set your API key")


def _ordered_providers(config: Config) -> list[AIProviderProfile]:
    profiles = config.provider_profiles()
    by_id = {profile.id: profile for profile in profiles}
    ordered_ids = [config.active_provider().id, *config.fallback_provider_ids]
    ordered: list[AIProviderProfile] = []
    seen: set[str] = set()
    for provider_id in ordered_ids:
        profile = by_id.get(provider_id)
        if profile is None or profile.id in seen or not profile.enabled or not profile.api_key:
            continue
        ordered.append(profile)
        seen.add(profile.id)
    return ordered


def _complete_with_provider(
    provider: AIProviderProfile,
    messages: list[Message],
    tools: list[dict[str, Any]],
) -> Assistant:
    payload: dict[str, Any] = {
        "model": _litellm_model(provider),
        "messages": [_openai_message(message) for message in messages],
        "api_key": provider.api_key,
    }
    api_base = _litellm_api_base(provider)
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
