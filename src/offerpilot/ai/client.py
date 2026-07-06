from __future__ import annotations

import json
from typing import Any

import httpx

from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.config import Config


class ConfiguredAIClient:
    def __init__(self, config: Config):
        if not config.api_key:
            raise ValueError("AI is not configured: run `oc config` to set your API key")
        self._config = config

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        if "anthropic" in self._config.base_url:
            return self._complete_anthropic(messages, tools)
        return self._complete_openai(messages, tools)

    def _complete_openai(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [_openai_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_openai_tool(tool) for tool in tools]
            payload["tool_choice"] = "auto"

        response = httpx.post(
            self._config.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self._config.api_key}"},
            json=payload,
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(response.text)
        message = response.json()["choices"][0]["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            calls.append(
                ToolCall(
                    id=str(call.get("id", "")),
                    name=str(call.get("function", {}).get("name", "")),
                    args=str(call.get("function", {}).get("arguments") or "{}"),
                )
            )
        return Assistant(content=message.get("content") or "", tool_calls=calls)

    def _complete_anthropic(self, messages: list[Message], tools: list[dict[str, Any]]) -> Assistant:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [],
            "max_tokens": 4096,
        }
        system_parts: list[str] = []
        for message in messages:
            if message.role == "system":
                system_parts.append(message.content)
                continue
            if message.role == "user":
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": message.content}],
                    }
                )
                continue
            if message.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": _json_object(call.args),
                        }
                    )
                payload["messages"].append({"role": "assistant", "content": blocks})
                continue
            if message.role == "tool":
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if tools:
            payload["tools"] = [_anthropic_tool(tool) for tool in tools]

        response = httpx.post(
            self._config.base_url.rstrip("/") + "/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._config.api_key,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(response.text)
        assistant = Assistant()
        for block in response.json().get("content") or []:
            block_type = block.get("type")
            if block_type in {"text", ""}:
                assistant.content += str(block.get("text") or "")
            elif block_type == "tool_use":
                assistant.tool_calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        args=json.dumps(block.get("input") or {}, ensure_ascii=False),
                    )
                )
        return assistant


def _openai_message(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
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


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("schema") or {"type": "object", "properties": {}}
    if isinstance(schema, str):
        schema = json.loads(schema)
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": schema,
    }


def _json_object(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}
