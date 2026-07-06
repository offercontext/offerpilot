from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: str


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""


@dataclass
class Assistant:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

