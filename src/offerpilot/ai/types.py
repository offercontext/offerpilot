from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    provider_blocks: dict[str, Any] = field(default_factory=dict)


@dataclass
class Assistant:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_blocks: dict[str, Any] = field(default_factory=dict)

