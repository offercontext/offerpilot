import json
from types import SimpleNamespace
from typing import Any

import pytest

from offerpilot.ai import client as ai_client
from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.types import Message
from offerpilot.config import AIProviderProfile, Config


def test_client_routes_openai_compatible_calls_through_litellm(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "update_application_status",
                                    "arguments": json.dumps({"id": 1}),
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(api_key="sk-test", base_url="http://localhost:4000/v1", model="gpt-4o")
    )

    assistant = client.complete(
        [Message(role="user", content="hello")],
        [{"name": "update_application_status", "schema": {"type": "object"}}],
    )

    assert captured["model"] == "openai/gpt-4o"
    assert captured["api_key"] == "sk-test"
    assert captured["api_base"] == "http://localhost:4000/v1"
    assert captured["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["tools"][0]["function"]["name"] == "update_application_status"
    assert captured["tool_choice"] == "auto"
    assert assistant.content == "ok"
    assert assistant.tool_calls[0].name == "update_application_status"
    assert assistant.tool_calls[0].args == json.dumps({"id": 1})


def test_client_uses_active_provider_profile(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done"))])

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(
            active_provider_id="anthropic",
            providers=[
                AIProviderProfile(
                    id="openai",
                    label="OpenAI",
                    provider="openai",
                    api_key="sk-openai",
                    model="gpt-4o",
                ),
                AIProviderProfile(
                    id="anthropic",
                    label="Anthropic",
                    provider="anthropic",
                    api_key="sk-anthropic",
                    model="claude-sonnet-4",
                ),
            ],
        )
    )

    assistant = client.complete([Message(role="user", content="hello")], [])

    assert captured["model"] == "anthropic/claude-sonnet-4"
    assert captured["api_key"] == "sk-anthropic"
    assert "api_base" not in captured
    assert assistant.content == "done"


def test_client_requires_active_provider_key():
    with pytest.raises(ValueError, match="AI is not configured"):
        ConfiguredAIClient(Config(providers=[AIProviderProfile(id="default", api_key="")]))


def test_client_falls_back_to_configured_provider_order(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs["api_key"] == "sk-openai":
            raise RuntimeError("primary down")
        return {"choices": [{"message": {"content": "fallback ok"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(
            active_provider_id="openai",
            fallback_provider_ids=["deepseek"],
            providers=[
                AIProviderProfile(
                    id="openai",
                    label="OpenAI",
                    provider="openai",
                    api_key="sk-openai",
                    model="gpt-4o",
                ),
                AIProviderProfile(
                    id="deepseek",
                    label="DeepSeek",
                    provider="openai_compatible",
                    api_key="sk-deepseek",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                ),
            ],
        )
    )

    assistant = client.complete([Message(role="user", content="hello")], [])

    assert assistant.content == "fallback ok"
    assert [call["api_key"] for call in calls] == ["sk-openai", "sk-deepseek"]
    assert calls[1]["model"] == "openai/deepseek-chat"
    assert calls[1]["api_base"] == "https://api.deepseek.com/v1"
