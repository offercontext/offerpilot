import json

import httpx

from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.types import Message, ToolCall
from offerpilot.config import Config


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "content": [
                {"type": "text", "text": "需要确认"},
                {"type": "tool_use", "id": "toolu_1", "name": "update_application_status", "input": {"id": 1}},
            ]
        }


def test_anthropic_client_posts_messages_and_parses_tool_use(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ConfiguredAIClient(
        Config(api_key="anthropic-key", base_url="https://api.anthropic.com", model="claude-test")
    )

    assistant = client.complete(
        [
            Message(role="system", content="系统提示"),
            Message(role="user", content="改状态"),
            Message(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="toolu_old",
                        name="update_application_status",
                        args=json.dumps({"id": 1, "status": "offer"}),
                    )
                ],
            ),
            Message(role="tool", content='{"ok":true}', tool_call_id="toolu_old"),
        ],
        [
            {
                "name": "update_application_status",
                "description": "update status",
                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
            }
        ],
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "anthropic-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["system"] == "系统提示"
    assert captured["json"]["messages"][0]["content"][0] == {"type": "text", "text": "改状态"}
    assert captured["json"]["messages"][1]["content"][0]["type"] == "tool_use"
    assert captured["json"]["messages"][2]["content"][0]["type"] == "tool_result"
    assert captured["json"]["tools"][0]["input_schema"]["type"] == "object"
    assert assistant.content == "需要确认"
    assert assistant.tool_calls == [
        ToolCall(id="toolu_1", name="update_application_status", args=json.dumps({"id": 1}, ensure_ascii=False))
    ]
