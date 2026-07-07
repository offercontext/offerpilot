from typing import Any

from offerpilot.ai import client as ai_client
from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.types import Message
from offerpilot.config import Config


def test_legacy_anthropic_config_routes_through_litellm(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "需要确认"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = ConfiguredAIClient(
        Config(api_key="anthropic-key", base_url="https://api.anthropic.com", model="claude-test")
    )

    assistant = client.complete([Message(role="user", content="改状态")], [])

    assert captured["model"] == "anthropic/claude-test"
    assert captured["api_key"] == "anthropic-key"
    assert "api_base" not in captured
    assert assistant.content == "需要确认"
