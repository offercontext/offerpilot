from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any, Callable

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.types import Message
from offerpilot.ai.workflows import parse_json_reply


PREPARATION_FIELDS = (
    "preparation_directions",
    "story_prompts",
    "review_points",
    "interviewer_questions",
    "items_to_clarify",
)
MAX_ITEMS = 8
MAX_EVIDENCE_REFS = 5
MAX_ITEM_TEXT_CHARS = 1000
_ID_PATTERN = re.compile(r"^[\x21-\x7e]{1,64}$")
_ALLOWED_SOURCES = {"jd", "resume", "knowledge_evidence"}
_TOP_LEVEL_FIELDS = set(PREPARATION_FIELDS)
_ITEM_FIELDS = {"id", "text", "evidence_refs"}
_REPAIR_CATEGORIES = {
    "invalid_json",
    "duplicate_json_key",
    "unexpected_field",
    "invalid_item_shape",
    "limit_exceeded",
    "missing_evidence_ref",
    "unknown_evidence_ref",
    "excerpt_mismatch",
}

INTERVIEW_PREPARATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(PREPARATION_FIELDS),
    "properties": {
        field: {
            "type": "array",
            "maxItems": MAX_ITEMS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "text", "evidence_refs"],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "text": {"type": "string", "minLength": 1, "maxLength": MAX_ITEM_TEXT_CHARS},
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_EVIDENCE_REFS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["source", "path", "excerpt"],
                            "properties": {
                                "source": {"enum": sorted(_ALLOWED_SOURCES)},
                                "path": {"type": "string", "minLength": 1},
                                "excerpt": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
        }
        for field in PREPARATION_FIELDS
    },
}

INTERVIEW_PREPARATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "interview_preparation_proposal",
        "strict": True,
        "schema": INTERVIEW_PREPARATION_JSON_SCHEMA,
    },
}


class InterviewPreparationModelError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_category: str = "unverifiable",
        validation_category: str | None = None,
        retry_count: int = 0,
        duration_ms: int = 0,
        provider_request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.failure_category = failure_category
        self.validation_category = validation_category or failure_category
        self.retry_count = retry_count
        self.duration_ms = duration_ms
        self.provider_request_id = provider_request_id


InterviewPreparationDiagnosticSink = Callable[[dict[str, Any]], None]


def safe_empty_interview_preparation_proposal() -> dict[str, list[Any]]:
    return {field: [] for field in PREPARATION_FIELDS}


def validate_interview_preparation(
    payload: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    _assert_finite_json(payload)
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise _model_error("invalid top-level fields", "unexpected_field")
    _validate_snapshot(snapshot)
    normalized: dict[str, Any] = {}
    for field in PREPARATION_FIELDS:
        items = payload[field]
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise _model_error(f"{field} exceeds the item limit", "limit_exceeded")
        normalized[field] = []
        for item in items:
            normalized[field].append(_validate_item(item, snapshot))
    return normalized


def generate_interview_preparation_proposal(
    model: ChatModel,
    snapshot: dict[str, Any],
    *,
    on_diagnostic: InterviewPreparationDiagnosticSink | None = None,
) -> dict[str, Any]:
    system = _system_prompt()
    initial_prompt = _initial_prompt(snapshot)
    response_format = (
        INTERVIEW_PREPARATION_RESPONSE_FORMAT
        if getattr(model, "supports_json_schema", False) is True
        else None
    )
    started_at = perf_counter()
    last_category = "invalid_json"
    provider_request_id = ""
    for attempt in range(2):
        user_prompt = (
            initial_prompt
            if attempt == 0
            else _repair_prompt(last_category)
        )
        try:
            if response_format is None:
                assistant = model.complete(
                    [Message(role="system", content=system), Message(role="user", content=user_prompt)],
                    [],
                )
            else:
                assistant = model.complete(
                    [Message(role="system", content=system), Message(role="user", content=user_prompt)],
                    [],
                    response_format=response_format,
                )
            provider_request_id = str(assistant.provider_blocks.get("request_id") or "")
        except Exception as exc:
            duration_ms = _elapsed_ms(started_at)
            _emit_diagnostic(
                on_diagnostic,
                failure_category="provider_error",
                repair_attempted=attempt > 0,
                retry_count=attempt,
                duration_ms=duration_ms,
                provider_request_id=provider_request_id,
            )
            raise InterviewPreparationModelError(
                "model provider request failed",
                failure_category="provider_error",
                validation_category="provider_error",
                retry_count=attempt,
                duration_ms=duration_ms,
                provider_request_id=provider_request_id,
            ) from exc
        try:
            payload = parse_json_reply(
                assistant.content,
                allow_fenced=False,
                reject_non_finite=True,
                reject_duplicate_keys=True,
            )
            return validate_interview_preparation(payload, snapshot)
        except InterviewPreparationModelError as exc:
            last_category = exc.validation_category
        except (TypeError, ValueError, RuntimeError) as exc:
            last_category = _parse_failure_category(exc)
        if last_category not in _REPAIR_CATEGORIES:
            last_category = "invalid_json"

    safe_empty = safe_empty_interview_preparation_proposal()
    validated_empty = validate_interview_preparation(safe_empty, snapshot)
    _emit_diagnostic(
        on_diagnostic,
        failure_category=last_category,
        repair_attempted=True,
        retry_count=1,
        duration_ms=_elapsed_ms(started_at),
        provider_request_id=provider_request_id,
    )
    return validated_empty


def _validate_snapshot(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        raise _model_error("snapshot must be an object", "invalid_item_shape")
    jd = snapshot.get("jd")
    resume = snapshot.get("resume")
    evidence = snapshot.get("knowledge_evidence")
    if not isinstance(jd, dict) or not isinstance(jd.get("text"), str):
        raise _model_error("snapshot JD is invalid", "invalid_item_shape")
    if not isinstance(resume, dict) or not isinstance(resume.get("content_json"), dict):
        raise _model_error("snapshot Resume is invalid", "invalid_item_shape")
    if not isinstance(evidence, list):
        raise _model_error("snapshot Evidence is invalid", "invalid_item_shape")


def _validate_item(item: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
        raise _model_error("invalid item shape", "invalid_item_shape")
    item_id = item.get("id")
    text = item.get("text")
    refs = item.get("evidence_refs")
    if not isinstance(item_id, str) or not _ID_PATTERN.fullmatch(item_id):
        raise _model_error("invalid item id", "invalid_item_shape")
    if not isinstance(text, str) or not text or len(text) > MAX_ITEM_TEXT_CHARS:
        raise _model_error("invalid item text", "limit_exceeded" if isinstance(text, str) else "invalid_item_shape")
    if not isinstance(refs, list) or not refs or len(refs) > MAX_EVIDENCE_REFS:
        raise _model_error("invalid evidence refs", "missing_evidence_ref" if not refs else "limit_exceeded")
    return {
        "id": item_id,
        "text": text,
        "evidence_refs": [_validate_ref(ref, snapshot) for ref in refs],
    }


def _validate_ref(ref: Any, snapshot: dict[str, Any]) -> dict[str, str]:
    if not isinstance(ref, dict) or set(ref) != {"source", "path", "excerpt"}:
        raise _model_error("invalid evidence ref", "invalid_item_shape")
    source = ref.get("source")
    path = ref.get("path")
    excerpt = ref.get("excerpt")
    if source not in _ALLOWED_SOURCES or not isinstance(path, str) or not isinstance(excerpt, str):
        raise _model_error("unknown evidence ref", "unknown_evidence_ref")
    if not excerpt:
        raise _model_error("evidence excerpt is empty", "excerpt_mismatch")
    if source == "jd":
        if path != "/jd/text" or excerpt not in snapshot["jd"]["text"]:
            raise _model_error("JD evidence excerpt does not match", "excerpt_mismatch")
    elif source == "resume":
        value = _resolve_resume_pointer(snapshot["resume"]["content_json"], path)
        if not isinstance(value, str):
            raise _model_error("Resume path must resolve to a string leaf", "unknown_evidence_ref")
        if excerpt not in value:
            raise _model_error("Resume evidence excerpt does not match", "excerpt_mismatch")
    else:
        evidence = next(
            (item for item in snapshot["knowledge_evidence"] if item.get("id") == path),
            None,
        )
        if evidence is None:
            raise _model_error("Knowledge Evidence is not selected", "unknown_evidence_ref")
        if excerpt != evidence.get("excerpt"):
            raise _model_error("Knowledge Evidence excerpt does not match", "excerpt_mismatch")
    return {"source": source, "path": path, "excerpt": excerpt}


def _resolve_resume_pointer(content: dict[str, Any], path: str) -> Any:
    if not path.startswith("/"):
        raise _model_error("Resume path is not a JSON Pointer", "unknown_evidence_ref")
    parts = path[1:].split("/")
    current: Any = content
    normalized_parts: list[str] = []
    for part in parts:
        if "~" in part and "~0" not in part and "~1" not in part:
            raise _model_error("Resume path has invalid escape", "unknown_evidence_ref")
        try:
            token = part.replace("~1", "/").replace("~0", "~")
        except Exception as exc:
            raise _model_error("Resume path has invalid escape", "unknown_evidence_ref") from exc
        if token.replace("/", "~1").replace("~", "~0") != part:
            raise _model_error("Resume path is not canonical", "unknown_evidence_ref")
        normalized_parts.append(token)
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise _model_error("Resume path does not exist", "unknown_evidence_ref")
    return current


def _system_prompt() -> str:
    return (
        "只根据用户确认的 JD、所选 Resume 和已确认 Knowledge Evidence 生成面试准备建议。"
        "只输出原始 JSON；顶层只能有 preparation_directions、story_prompts、review_points、"
        "interviewer_questions、items_to_clarify 五个数组。每个条目只能有 id、text、evidence_refs，"
        "每个条目必须至少引用一条证据；无法可靠建议时返回五个空数组。不要输出分数、预测、决定、"
        "能力判断、旧建议、复盘、Memory、用户断言或额外字段。"
    )


def _initial_prompt(snapshot: dict[str, Any]) -> str:
    event = dict(snapshot.get("event", {}))
    event.pop("id", None)
    event.pop("application_id", None)
    resume = dict(snapshot.get("resume", {}))
    resume.pop("id", None)
    knowledge_evidence = [
        {
            "id": item.get("id"),
            "path": item.get("path"),
            "excerpt": item.get("excerpt"),
        }
        for item in snapshot.get("knowledge_evidence", [])
        if isinstance(item, dict)
    ]
    provider_input = {
        "event": event,
        "jd": snapshot.get("jd", {}),
        "resume": resume,
        "knowledge_evidence": knowledge_evidence,
    }
    return (
        "请基于以下冻结输入生成严格 JSON。所有具体文本必须逐项引用冻结输入中的 JD、Resume 或已确认 "
        "Knowledge Evidence；不要使用用户断言作为事实或证据。冻结输入："
        + json.dumps(provider_input, ensure_ascii=False, separators=(",", ":"))
    )


def _repair_prompt(category: str) -> str:
    return (
        "上一次输出未通过严格验证。失败类别为 "
        + category
        + "。只返回符合既定契约的 raw JSON；不要解释、不要返回 Markdown、不要加入额外字段，"
        "没有可验证建议时返回五个空数组。"
    )


def _parse_failure_category(exc: Exception) -> str:
    message = str(exc).lower()
    if "duplicate" in message:
        return "duplicate_json_key"
    if "non-finite" in message or "nan" in message or "infinity" in message:
        return "invalid_json"
    return "invalid_json"


def _model_error(message: str, category: str) -> InterviewPreparationModelError:
    return InterviewPreparationModelError(
        message,
        failure_category="unverifiable",
        validation_category=category,
    )


def _assert_finite_json(value: Any) -> None:
    if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
        raise _model_error("non-finite JSON value", "invalid_json")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite_json(item)


def _emit_diagnostic(
    sink: InterviewPreparationDiagnosticSink | None,
    *,
    failure_category: str,
    repair_attempted: bool,
    retry_count: int,
    duration_ms: int,
    provider_request_id: str,
) -> None:
    if sink is None:
        return
    sink(
        {
            "failure_category": failure_category,
            "repair_attempted": repair_attempted,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
            "provider_request_id": provider_request_id,
        }
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))
