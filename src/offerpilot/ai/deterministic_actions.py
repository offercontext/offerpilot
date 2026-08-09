from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from offerpilot.ai.agent import PendingAction


MAX_JD_UTF8_BYTES = 60_000
_ACTION_KEYS = {"type", "jdText", "sourceUrl"}
_CANCEL_MESSAGES = frozenset({"取消", "算了", "先不用", "不用了", "不保存", "不要保存"})
_JD_TARGET = r"(?:JD|jd|岗位描述|职位描述|岗位资料)"
_JD_COMMAND_PREFIX = r"(?:给\s*)?(?:当前\s*)?(?:投递\s*)?"
_JD_COMMAND_HEAD = re.compile(
    rf"^\s*{_JD_COMMAND_PREFIX}(?:保存|更新|补充|录入)\s*"
    rf"(?:当前\s*)?(?:投递\s*)?{_JD_TARGET}\s*$"
)
_JD_COMMAND_WITH_BODY = re.compile(
    rf"^\s*{_JD_COMMAND_PREFIX}(?:保存|更新|补充|录入)\s*"
    rf"(?:当前\s*)?(?:投递\s*)?{_JD_TARGET}"
    rf"(?:[ \t]*(?::|：)|\r?\n)([\s\S]+)$"
)
_ASCII_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True)
class PilotAction:
    jd_text: str | None
    source_url: str | None


@dataclass(frozen=True)
class PilotActionDecision:
    kind: Literal["normal_agent", "collecting_jd", "pending_confirmation", "cancelled"]
    jd_text: str | None = None
    source_url: str | None = None
    question: str = ""


def parse_pilot_action(payload: Any) -> PilotAction:
    if not isinstance(payload, dict):
        raise ValueError("pilot_action must be an object")
    if set(payload) - _ACTION_KEYS or payload.get("type") != "application_jd_save":
        raise ValueError("unsupported pilot_action")
    source_url = payload.get("sourceUrl")
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("sourceUrl must be a string or null")
    jd_text = payload.get("jdText")
    if jd_text is None:
        return PilotAction(jd_text=None, source_url=source_url)
    if not isinstance(jd_text, str):
        raise ValueError("jdText is required")
    if not jd_text.strip():
        return PilotAction(jd_text=None, source_url=source_url)
    if len(jd_text.encode("utf-8")) > MAX_JD_UTF8_BYTES:
        raise ValueError("jdText is too large")
    return PilotAction(jd_text=jd_text, source_url=source_url)


def match_application_jd_command(message: str) -> str | None:
    if not isinstance(message, str):
        return None
    matched = _JD_COMMAND_WITH_BODY.fullmatch(message)
    if matched is None:
        return None
    body = matched.group(1)
    return body if body.strip() else None


def is_pilot_cancel_message(message: str) -> bool:
    return isinstance(message, str) and message.strip() in _CANCEL_MESSAGES


def decide_pilot_action(
    message: str,
    *,
    has_current_jd: bool,
    collecting_jd: bool = False,
) -> PilotActionDecision:
    if collecting_jd:
        if is_pilot_cancel_message(message):
            return PilotActionDecision(kind="cancelled")
        if isinstance(message, str) and message.strip():
            return PilotActionDecision(kind="pending_confirmation", jd_text=message)
        return PilotActionDecision(kind="collecting_jd", question="请粘贴完整岗位描述")

    body = match_application_jd_command(message)
    if body is not None:
        return PilotActionDecision(kind="pending_confirmation", jd_text=body)
    if isinstance(message, str) and _JD_COMMAND_HEAD.fullmatch(message):
        return PilotActionDecision(kind="collecting_jd", question="请粘贴完整岗位描述")
    return PilotActionDecision(kind="normal_agent")


def build_pilot_pending_action(
    *,
    application_id: int,
    current_version_id: int | None,
    jd_text: str,
    source_url: str | None,
    id_factory: Callable[[], str],
    key_factory: Callable[[], str],
) -> PendingAction:
    if type(application_id) is not int or application_id <= 0:
        raise ValueError("application_id must be a positive integer")
    if not isinstance(jd_text, str):
        raise ValueError("jd_text is required")
    if len(jd_text.encode("utf-8")) > MAX_JD_UTF8_BYTES:
        raise ValueError("jd_text is too large")
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("source_url must be a string or null")
    tool_call_id = id_factory()
    idempotency_key = key_factory()
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("tool_call_id is invalid")
    if not isinstance(idempotency_key, str) or _ASCII_KEY.fullmatch(idempotency_key) is None:
        raise ValueError("idempotency_key is invalid")
    args = json.dumps(
        {
            "application_id": application_id,
            "jd_text": jd_text,
            "source_url": source_url,
            "expected_current_version_id": current_version_id,
            "idempotency_key": idempotency_key,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return PendingAction(
        tool_call_id=tool_call_id,
        tool_name="save_application_jd_version",
        args=args,
        human="请确认将这份岗位资料保存到当前投递。",
    )
