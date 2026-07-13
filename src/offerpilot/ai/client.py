from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from litellm import completion

from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.config import AIProviderProfile, Config


class ConfiguredAIClient:
    def __init__(self, config: Config, on_provider_event: Callable[[str, str], None] | None = None):
        self._providers = config.ordered_provider_profiles()
        self._on_provider_event = on_provider_event
        if not any(provider.api_key for provider in self._providers):
            raise ValueError("AI is not configured: run `oc config` to set your API key")

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        last_error: Exception | None = None
        providers = self._candidate_providers()
        for index, provider in enumerate(providers):
            if not provider.api_key:
                continue
            try:
                assistant = self._complete_with_provider(provider, messages, tools)
                if index > 0:
                    self._emit("INFO", f"AI fallback provider {provider.id} succeeded")
                return assistant
            except Exception as exc:
                last_error = exc
                if index + 1 < len(providers):
                    self._emit(
                        "WARNING",
                        f"AI provider {provider.id} failed; trying fallback {providers[index + 1].id}",
                    )
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise ValueError("AI is not configured: run `oc config` to set your API key")

    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_delta: Callable[[str], None],
    ) -> Assistant:
        last_error: Exception | None = None
        providers = self._candidate_providers()
        for index, provider in enumerate(providers):
            if not provider.api_key:
                continue
            emitted_delta = False

            def emit_delta(text: str) -> None:
                nonlocal emitted_delta
                emitted_delta = True
                on_delta(text)

            try:
                assistant = self._stream_with_provider(provider, messages, tools, emit_delta)
                if index > 0:
                    self._emit("INFO", f"AI fallback provider {provider.id} succeeded")
                return assistant
            except Exception as exc:
                last_error = exc
                if emitted_delta:
                    raise
                if index + 1 < len(providers):
                    self._emit(
                        "WARNING",
                        f"AI provider {provider.id} failed; trying fallback {providers[index + 1].id}",
                    )
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise ValueError("AI is not configured: run `oc config` to set your API key")

    def _candidate_providers(self) -> list[AIProviderProfile]:
        return [provider for provider in self._providers if provider.enabled]

    def _complete_with_provider(
        self,
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

    def _stream_with_provider(
        self,
        provider: AIProviderProfile,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_delta: Callable[[str], None],
    ) -> Assistant:
        payload: dict[str, Any] = {
            "model": _litellm_model(provider),
            "messages": [_openai_message(message) for message in messages],
            "api_key": provider.api_key,
            "stream": True,
        }
        api_base = _litellm_api_base(provider)
        if api_base:
            payload["api_base"] = api_base
        if tools:
            payload["tools"] = [_openai_tool(tool) for tool in tools]
            payload["tool_choice"] = "auto"

        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        provider_blocks: dict[str, Any] = {}
        for chunk in completion(**payload):
            delta = _first_choice_delta(chunk)
            piece = _get(delta, "content")
            if piece:
                text = str(piece)
                content_parts.append(text)
                on_delta(text)
            reasoning_content = _get(delta, "reasoning_content")
            if reasoning_content:
                provider_blocks["reasoning_content"] = str(provider_blocks.get("reasoning_content") or "") + str(
                    reasoning_content
                )
            for raw_call in _get(delta, "tool_calls") or []:
                index = int(_get(raw_call, "index") or 0)
                current = tool_calls.setdefault(index, {"id": "", "name": "", "args": ""})
                call_id = _get(raw_call, "id")
                if call_id:
                    current["id"] = str(call_id)
                function = _get(raw_call, "function") or {}
                name = _get(function, "name")
                if name:
                    current["name"] = str(name)
                arguments = _get(function, "arguments")
                if arguments:
                    current["args"] = str(current["args"]) + str(arguments)

        calls = [
            ToolCall(
                id=str(raw["id"]),
                name=str(raw["name"]),
                args=str(raw["args"] or "{}"),
            )
            for _, raw in sorted(tool_calls.items())
            if raw.get("name")
        ]
        return Assistant(
            content="".join(content_parts),
            tool_calls=calls,
            provider_blocks=provider_blocks,
        )

    def _emit(self, level: str, message: str) -> None:
        if self._on_provider_event is not None:
            self._on_provider_event(level, message)


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


def _first_choice_delta(response: Any) -> Any:
    choices = _get(response, "choices") or []
    if not choices:
        return {}
    return _get(choices[0], "delta") or {}


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
