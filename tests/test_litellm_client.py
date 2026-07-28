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


def test_client_streams_content_deltas_through_litellm(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="你"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="好"))]),
        ]

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(Config(api_key="sk-test", model="gpt-4o"))
    deltas: list[str] = []

    assistant = client.stream_complete([Message(role="user", content="hello")], [], deltas.append)

    assert captured["stream"] is True
    assert deltas == ["你", "好"]
    assert assistant.content == "你好"
    assert assistant.tool_calls == []


def test_client_streams_tool_calls_through_litellm(monkeypatch):
    def fake_completion(**kwargs: Any) -> Any:
        return [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "list_applications",
                                        "arguments": '{"status"',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "arguments": ':"offer"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        ]

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(Config(api_key="sk-test", model="gpt-4o"))
    deltas: list[str] = []

    assistant = client.stream_complete(
        [Message(role="user", content="hello")],
        [{"name": "list_applications", "schema": {"type": "object"}}],
        deltas.append,
    )

    assert deltas == []
    assert assistant.content == ""
    assert assistant.tool_calls[0].id == "call_1"
    assert assistant.tool_calls[0].name == "list_applications"
    assert assistant.tool_calls[0].args == '{"status":"offer"}'


def test_client_does_not_fallback_after_streaming_visible_delta(monkeypatch):
    calls: list[str] = []

    def fake_completion(**kwargs: Any) -> Any:
        calls.append(str(kwargs["api_key"]))
        if kwargs["api_key"] == "sk-primary":
            def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="半句"))])
                raise RuntimeError("stream failed")

            return chunks()
        return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="backup"))])]

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(
            active_provider_id="primary",
            fallback_provider_ids=["backup"],
            providers=[
                AIProviderProfile(id="primary", api_key="sk-primary", model="gpt-4o"),
                AIProviderProfile(id="backup", api_key="sk-backup", model="gpt-4o-mini"),
            ],
        )
    )
    deltas: list[str] = []

    with pytest.raises(RuntimeError, match="stream failed"):
        client.stream_complete([Message(role="user", content="hello")], [], deltas.append)

    assert deltas == ["半句"]
    assert calls == ["sk-primary"]


def test_client_falls_back_to_configured_provider_after_primary_failure(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs["api_key"] == "sk-primary":
            raise RuntimeError("primary provider unavailable")
        return {"choices": [{"message": {"content": "fallback ok"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(
            active_provider_id="primary",
            fallback_provider_ids=["backup"],
            providers=[
                AIProviderProfile(
                    id="primary",
                    label="Primary",
                    provider="openai",
                    api_key="sk-primary",
                    model="gpt-4o",
                ),
                AIProviderProfile(
                    id="backup",
                    label="Backup",
                    provider="openrouter",
                    api_key="sk-backup",
                    model="openai/gpt-4o-mini",
                ),
            ],
        )
    )

    assistant = client.complete([Message(role="user", content="hello")], [])

    assert assistant.content == "fallback ok"
    assert [call["api_key"] for call in calls] == ["sk-primary", "sk-backup"]
    assert calls[1]["model"] == "openai/gpt-4o-mini"


def test_client_emits_redacted_provider_failure_diagnostic(monkeypatch):
    events: list[tuple[str, str]] = []

    def fake_completion(**kwargs: Any) -> Any:
        raise TimeoutError("secret prompt and API key must not be logged")

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(api_key="sk-test", base_url="https://provider.example/v1", model="gpt-test"),
        on_provider_event=lambda level, message: events.append((level, message)),
    )

    with pytest.raises(ai_client.ProviderCallError) as caught:
        client.complete([Message(role="user", content="sensitive input")], [])

    assert caught.value.diagnostic["failure_category"] == "network_timeout"
    assert caught.value.diagnostic["http_status"] is None
    assert isinstance(caught.value.diagnostic["elapsed_ms"], int)
    assert caught.value.diagnostic["correlation_id"]
    assert len(events) == 1
    level, message = events[0]
    assert level == "WARNING"
    assert message.startswith("ai_provider_failure ")
    assert "secret prompt" not in message
    assert "sensitive input" not in message
    assert "sk-test" not in message


@pytest.mark.parametrize(
    ("error_factory", "expected_category", "expected_status"),
    [
        (lambda: type("Provider503Error", (RuntimeError,), {"status_code": 503})(), "provider_http_5xx", 503),
        (lambda: type("ProxyError", (RuntimeError,), {})(), "proxy_failure", None),
        (lambda: type("RemoteProtocolError", (RuntimeError,), {})(), "response_lost", None),
    ],
)
def test_client_classifies_provider_boundary_failures(
    monkeypatch, error_factory, expected_category, expected_status
):
    events: list[tuple[str, str]] = []

    def fake_completion(**kwargs: Any) -> Any:
        raise error_factory()

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(api_key="sk-test", base_url="https://provider.example/v1", model="gpt-test"),
        on_provider_event=lambda level, message: events.append((level, message)),
    )

    with pytest.raises(ai_client.ProviderCallError):
        client.complete([Message(role="user", content="sensitive input")], [])

    diagnostic = json.loads(events[0][1].removeprefix("ai_provider_failure "))
    assert diagnostic["failure_category"] == expected_category
    assert diagnostic["http_status"] == expected_status
    assert diagnostic["timeout"] is False
    assert diagnostic["elapsed_ms"] >= 0
    assert diagnostic["correlation_id"]
