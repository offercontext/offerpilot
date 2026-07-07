from typing import Any

from offerpilot.ai import client as ai_client
from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.types import Message, ToolCall
from offerpilot.config import Config


def test_legacy_anthropic_config_routes_through_litellm(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "needs confirmation"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(api_key="anthropic-key", base_url="https://api.anthropic.com", model="claude-test")
    )

    assistant = client.complete([Message(role="user", content="change status")], [])

    assert captured["model"] == "anthropic/claude-test"
    assert captured["api_key"] == "anthropic-key"
    assert "api_base" not in captured
    assert assistant.content == "needs confirmation"


def test_reasoning_content_round_trips_for_thinking_models(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "looked up the application",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "list_applications",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(Config(api_key="sk-test", model="deepseek-reasoner"))

    assistant = client.complete(
        [
            Message(
                role="assistant",
                content="",
                provider_blocks={"reasoning_content": "previous thinking"},
                tool_calls=[ToolCall(id="previous", name="list_applications", args="{}")],
            )
        ],
        [],
    )

    assert captured["messages"][0]["reasoning_content"] == "previous thinking"
    assert assistant.provider_blocks == {"reasoning_content": "looked up the application"}
