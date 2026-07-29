from __future__ import annotations

import json
import hashlib
from time import perf_counter
from typing import Any, cast

from offerpilot.ai.types import Assistant, Message


class MockInterviewContractError(ValueError):
    def __init__(self, category: str, message: str | None = None):
        self.category = category
        super().__init__(f"{category}: {message or category}")


SAFE_EMPTY_FEEDBACK = {
    "schema_version": "mock-interview-feedback-v1",
    "proposal_status": "safe_empty",
    "strengths": [],
    "practice_points": [],
    "follow_up_questions": [],
    "next_practice_steps": [],
}

_FIELDS = set(SAFE_EMPTY_FEEDBACK)
_ITEM_FIELDS = {"id", "text", "evidence_refs"}
_FEEDBACK_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "text", "evidence_refs"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "text": {"type": "string", "minLength": 1, "maxLength": 1000},
        "evidence_refs": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "path", "excerpt"],
                "properties": {
                    "source": {"type": "string", "minLength": 1},
                    "path": {"type": "string", "minLength": 1},
                    "excerpt": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}
MOCK_INTERVIEW_FEEDBACK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "proposal_status",
        "strengths",
        "practice_points",
        "follow_up_questions",
        "next_practice_steps",
    ],
    "properties": {
        "schema_version": {"const": "mock-interview-feedback-v1"},
        "proposal_status": {"enum": ["normal", "safe_empty"]},
        "strengths": {"type": "array", "maxItems": 8, "items": _FEEDBACK_ITEM_SCHEMA},
        "practice_points": {"type": "array", "maxItems": 8, "items": _FEEDBACK_ITEM_SCHEMA},
        "follow_up_questions": {"type": "array", "maxItems": 8, "items": _FEEDBACK_ITEM_SCHEMA},
        "next_practice_steps": {"type": "array", "maxItems": 8, "items": _FEEDBACK_ITEM_SCHEMA},
    },
    "oneOf": [
        {
            "properties": {
                "proposal_status": {"const": "safe_empty"},
                "strengths": {"maxItems": 0},
                "practice_points": {"maxItems": 0},
                "follow_up_questions": {"maxItems": 0},
                "next_practice_steps": {"maxItems": 0},
            },
        },
        {"properties": {"proposal_status": {"const": "normal"}}},
    ],
}
_FIXED_QUESTIONS = {
    "clarify_answer": "您希望进一步澄清哪一部分？",
    "add_example": "您希望补充一个具体例子吗？",
    "choose_next_focus": "下一次练习时，您想先补充哪一步？",
}
_FORMAT_REPAIR_CATEGORIES = {
    "invalid_json",
    "duplicate_key",
    "root_not_object",
    "unexpected_field",
    "field_type",
    "item_shape",
    "evidence_refs_not_array",
    "evidence_ref_not_object",
    "evidence_ref_missing_field",
    "evidence_ref_unexpected_field",
    "evidence_ref_field_type",
}


def parse_mock_interview_json(raw: str) -> dict[str, Any]:
    if "```" in raw:
        raise MockInterviewContractError("invalid_json", "fenced JSON is not allowed")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except MockInterviewContractError:
        raise
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise MockInterviewContractError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise MockInterviewContractError("root_not_object")
    return parsed


def validate_feedback(
    proposal: dict[str, Any], snapshot: dict[str, Any], turns: list[dict[str, Any]]
) -> dict[str, Any]:
    if set(proposal) != _FIELDS:
        raise MockInterviewContractError("unexpected_field")
    if proposal["schema_version"] != "mock-interview-feedback-v1":
        raise MockInterviewContractError("wrong_schema_version")
    status = proposal["proposal_status"]
    if status == "safe_empty":
        if proposal != SAFE_EMPTY_FEEDBACK:
            raise MockInterviewContractError("safe_empty_shape")
        return proposal
    if status != "normal":
        raise MockInterviewContractError("invalid_status")

    seen_ids: set[str] = set()
    for field in ("strengths", "practice_points", "follow_up_questions", "next_practice_steps"):
        items = proposal[field]
        if not isinstance(items, list):
            raise MockInterviewContractError("field_type")
        if len(items) > 8:
            raise MockInterviewContractError("limit_exceeded")
        for item in items:
            _validate_item(item, seen_ids, snapshot, turns, field)
    return proposal


def _validate_item(
    item: Any,
    seen_ids: set[str],
    snapshot: dict[str, Any],
    turns: list[dict[str, Any]],
    field: str,
) -> None:
    if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
        raise MockInterviewContractError("item_shape")
    item_id = item["id"]
    text = item["text"]
    if not isinstance(item_id, str) or not item_id.strip() or item_id in seen_ids:
        raise MockInterviewContractError("duplicate_or_blank_id")
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise MockInterviewContractError("blank_value")
    seen_ids.add(item_id)
    refs = item["evidence_refs"]
    if not isinstance(refs, list):
        raise MockInterviewContractError("evidence_refs_not_array")
    if len(refs) > 4:
        raise MockInterviewContractError("limit_exceeded")
    if field in {"strengths", "practice_points", "next_practice_steps"}:
        if not refs or not any(ref.get("source") == "turn" for ref in refs if isinstance(ref, dict)):
            raise MockInterviewContractError("missing_turn_evidence")
    if field == "follow_up_questions" and not refs:
        if _FIXED_QUESTIONS.get(item_id) == text:
            return
        if text in _FIXED_QUESTIONS.values():
            raise MockInterviewContractError("fixed_question")
        raise MockInterviewContractError("missing_evidence_ref")
    if not refs and field != "follow_up_questions":
        raise MockInterviewContractError("missing_evidence_ref")
    for ref in refs:
        _validate_reference(ref, snapshot, turns)


def _validate_reference(ref: Any, snapshot: dict[str, Any], turns: list[dict[str, Any]]) -> None:
    required_fields = {"source", "path", "excerpt"}
    if not isinstance(ref, dict):
        raise MockInterviewContractError("evidence_ref_not_object")
    ref_fields = set(ref)
    if ref_fields != required_fields:
        if required_fields - ref_fields:
            raise MockInterviewContractError("evidence_ref_missing_field")
        raise MockInterviewContractError("evidence_ref_unexpected_field")
    source, path, excerpt = ref["source"], ref["path"], ref["excerpt"]
    if not all(isinstance(value, str) for value in (source, path, excerpt)):
        raise MockInterviewContractError("evidence_ref_field_type")
    if not excerpt.strip():
        raise MockInterviewContractError("blank_value")
    if source == "jd" and path == "/jd/text":
        value = snapshot.get("jd", {}).get("text")
    elif source == "resume" and path.startswith("/resume/content_json/"):
        value = _resolve_resume_pointer(snapshot, path)
    elif source == "turn" and path.startswith("/turns/") and path.endswith("/answer"):
        try:
            turn_no = int(path.split("/")[2])
        except (IndexError, ValueError) as exc:
            raise MockInterviewContractError("unknown_evidence_ref") from exc
        value = next((turn.get("answer") for turn in turns if turn.get("turn_no") == turn_no), None)
    else:
        raise MockInterviewContractError("unknown_evidence_ref")
    if not isinstance(value, str) or excerpt not in value:
        raise MockInterviewContractError("excerpt_mismatch")


def _resolve_resume_pointer(snapshot: dict[str, Any], path: str) -> str:
    value: Any = snapshot.get("resume", {}).get("content_json")
    for token in path.removeprefix("/resume/content_json/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if token == "" or (len(token) > 1 and token.startswith("0")) or not token.isdigit():
                raise MockInterviewContractError("unknown_evidence_ref")
            index = int(token)
            if index >= len(value):
                raise MockInterviewContractError("unknown_evidence_ref")
            value = value[index]
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise MockInterviewContractError("unknown_evidence_ref")
    if not isinstance(value, str):
        raise MockInterviewContractError("unknown_evidence_ref")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MockInterviewContractError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MockInterviewContractError("invalid_json", value)


def should_retry_mock_interview_format(category: str) -> bool:
    return category in _FORMAT_REPAIR_CATEGORIES


def _format_repair_instruction(category: str) -> str:
    return (
        " Format repair: the previous response failed the structural check "
        f"{category!r}. Return only one raw JSON object matching the declared schema."
        " Each evidence reference must be an object with exactly these string fields: "
        "source, path, excerpt. Allowed references are exactly jd + /jd/text, "
        "resume + /resume/content_json/<string-leaf-pointer>, or turn + "
        "/turns/<turn-number>/answer. The excerpt must be a non-empty contiguous "
        "substring copied verbatim from that allowed frozen value, including its "
        "original punctuation, spacing, and Unicode. If a path or excerpt cannot "
        "be copied exactly from the supplied input, do not invent it. Do not repeat "
        "or explain the previous response."
    )


def build_mock_interview_diagnostic(
    failure_category: str,
    repair_attempted: bool,
    repair_count: int,
    elapsed_ms: int,
    provider_request_id: str,
    _sensitive_value: str = "",
) -> dict[str, Any]:
    redacted_request_id = hashlib.sha256(provider_request_id.encode("utf-8")).hexdigest()[:12] if provider_request_id else ""
    return {
        "failure_category": failure_category,
        "repair_attempted": repair_attempted,
        "repair_count": repair_count,
        "elapsed_ms": elapsed_ms,
        "provider_request_id": f"request-redacted-{redacted_request_id}" if redacted_request_id else "",
    }


class MockInterviewProviderError(RuntimeError):
    def __init__(self, category: str, diagnostic: dict[str, Any] | None = None):
        self.category = category
        self.diagnostic = diagnostic or {}
        super().__init__(category)


class MockInterviewUnverifiableError(RuntimeError):
    def __init__(self, category: str, diagnostic: dict[str, Any] | None = None):
        self.category = category
        self.diagnostic = diagnostic or {}
        super().__init__(category)


def generate_feedback(
    model: Any, snapshot: dict[str, Any], turns: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate one strictly validated feedback proposal, or a safe empty result.

    The provider sees only the frozen snapshot and transcript. Contract repair is
    deliberately bounded to one retry; provider failures remain distinguishable
    from a model response that cannot be verified.
    """
    if not any(
        isinstance(turn.get("answer"), str) and turn["answer"].strip() for turn in turns
    ):
        return dict(SAFE_EMPTY_FEEDBACK), build_mock_interview_diagnostic(
            "no_answer_evidence", False, 0, 0, ""
        )
    if model is None:
        raise MockInterviewProviderError("mock_interview_provider_error")

    started = perf_counter()
    repair_count = 0
    last_category = "invalid_json"
    failure_categories: list[str] = []
    for attempt in range(2):
        prompt = _feedback_prompt(snapshot, turns, last_category if attempt else "")
        try:
            assistant = _complete_feedback(model, prompt)
        except Exception as exc:
            diagnostic = getattr(exc, "diagnostic", None)
            safe_diagnostic = dict(diagnostic) if isinstance(diagnostic, dict) else {}
            if failure_categories:
                safe_diagnostic.setdefault("failure_categories", failure_categories)
            raise MockInterviewProviderError(
                "mock_interview_provider_error",
                safe_diagnostic or None,
            ) from exc
        try:
            parsed = parse_mock_interview_json(assistant.content)
            validated = validate_feedback(parsed, snapshot, turns)
            return validated, build_mock_interview_diagnostic(
                "", repair_count > 0, repair_count,
                int((perf_counter() - started) * 1000), ""
            )
        except MockInterviewContractError as exc:
            last_category = exc.category
            failure_categories.append(last_category)
            if attempt == 0 and should_retry_mock_interview_format(last_category):
                repair_count = 1
                continue
            break
    raise MockInterviewUnverifiableError(
        last_category,
        {
            "failure_category": last_category,
            "repair_attempted": repair_count > 0,
            "repair_count": repair_count,
            "elapsed_ms": int((perf_counter() - started) * 1000),
            "failure_categories": failure_categories,
        },
    )


def generate_question(
    model: Any, snapshot: dict[str, Any], turns: list[dict[str, Any]]
) -> str:
    if model is None:
        raise MockInterviewProviderError("mock_interview_provider_error")
    last_category = "invalid_json"
    failure_categories: list[str] = []
    for attempt in range(2):
        repair_instruction = _format_repair_instruction(last_category) if attempt else ""
        messages = [
            Message(
                role="system",
                content=(
                    "只返回原始 JSON，字段必须严格为 question 和 evidence_refs。"
                    "question 必须是非空字符串；evidence_refs 必须引用当前冻结 JD、简历或已回答轮次。"
                    "source/path/excerpt 必须使用允许的规范路径，excerpt 必须从对应输入逐字连续复制，不得改写、拼接或猜测。"
                    "不得评分、预测录用或添加额外字段。"
                    + repair_instruction
                ),
            ),
            Message(
                role="user",
                content=json.dumps(
                    {
                        "snapshot": snapshot,
                        "turns": turns,
                        "repair_failure_category": last_category if attempt else None,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        ]
        try:
            schema = {
                "type": "json_schema",
                "json_schema": {
                    "name": "mock_interview_question",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["question", "evidence_refs"],
                        "properties": {
                            "question": {"type": "string", "minLength": 1, "maxLength": 1000},
                            "evidence_refs": {
                                "type": "array",
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["source", "path", "excerpt"],
                                    "properties": {
                                        "source": {"type": "string"},
                                        "path": {"type": "string"},
                                        "excerpt": {"type": "string", "minLength": 1},
                                    },
                                },
                            },
                        },
                    },
                },
            }
            if getattr(model, "supports_json_schema", False):
                assistant = cast(Assistant, model.complete(messages, [], response_format=schema))
            else:
                assistant = cast(Assistant, model.complete(messages, []))
            parsed = parse_mock_interview_json(assistant.content)
            if set(parsed) != {"question", "evidence_refs"}:
                raise MockInterviewContractError("unexpected_field")
            question = parsed["question"]
            refs = parsed["evidence_refs"]
            if not isinstance(question, str) or not question.strip() or len(question) > 1000:
                raise MockInterviewContractError("blank_value")
            if not isinstance(refs, list):
                raise MockInterviewContractError("evidence_refs_not_array")
            if not refs:
                raise MockInterviewContractError("missing_evidence_ref")
            if len(refs) > 4:
                raise MockInterviewContractError("limit_exceeded")
            for ref in refs:
                _validate_reference(ref, snapshot, turns)
            return question
        except MockInterviewProviderError:
            raise
        except MockInterviewContractError as exc:
            last_category = exc.category
            failure_categories.append(last_category)
            if attempt == 0 and should_retry_mock_interview_format(last_category):
                continue
            raise MockInterviewUnverifiableError(
                last_category,
                {
                    "failure_category": last_category,
                    "repair_attempted": attempt > 0,
                    "repair_count": 1 if attempt > 0 else 0,
                    "elapsed_ms": 0,
                    "failure_categories": failure_categories,
                },
            ) from exc
        except Exception as exc:
            diagnostic = getattr(exc, "diagnostic", None)
            safe_diagnostic = dict(diagnostic) if isinstance(diagnostic, dict) else {}
            if failure_categories:
                safe_diagnostic.setdefault("failure_categories", failure_categories)
            raise MockInterviewProviderError(
                "mock_interview_provider_error",
                safe_diagnostic or None,
            ) from exc
    raise MockInterviewUnverifiableError(
        last_category,
        {
            "failure_category": last_category,
            "repair_attempted": True,
            "repair_count": 1,
            "elapsed_ms": 0,
            "failure_categories": failure_categories,
        },
    )


def _complete_feedback(model: Any, prompt: str) -> Assistant:
    schema_text = json.dumps(MOCK_INTERVIEW_FEEDBACK_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    messages = [
        Message(
            role="system",
            content=(
                "你是文本模拟面试练习助手。只返回符合 mock-interview-feedback-v1 的原始 JSON。"
                "顶层必须严格包含 schema_version、proposal_status、strengths、practice_points、"
                "follow_up_questions、next_practice_steps，且不得有额外字段。"
                "normal 的每项必须包含 id、text、evidence_refs；每个 evidence_refs 项必须严格包含 "
                "source、path、excerpt 三个字符串字段。safe_empty 必须是四个空数组的固定结构。"
                "不得评分、预测录用或编造证据。没有可靠建议时返回安全空结构。"
                "完整 JSON Schema 如下：" + schema_text
            ),
        ),
        Message(role="user", content=prompt),
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "mock_interview_feedback",
            "strict": True,
            "schema": MOCK_INTERVIEW_FEEDBACK_SCHEMA,
        },
    }
    if getattr(model, "supports_json_schema", False):
        return cast(Assistant, model.complete(messages, [], response_format=schema))
    return cast(Assistant, model.complete(messages, []))


def _feedback_prompt(snapshot: dict[str, Any], turns: list[dict[str, Any]], failure_category: str) -> str:
    payload = {"snapshot": snapshot, "turns": turns}
    if failure_category:
        payload["repair_failure_category"] = failure_category
        payload["repair_instruction"] = _format_repair_instruction(failure_category)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
