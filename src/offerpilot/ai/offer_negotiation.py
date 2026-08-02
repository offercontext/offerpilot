from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Callable
from time import perf_counter
from typing import Any

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.types import Message
from offerpilot.ai.workflows import parse_json_reply
from offerpilot.repositories.json_contract import canonical_json

OFFER_NEGOTIATION_FIELDS = (
    "proposal_status",
    "communication_goals",
    "clarification_questions",
    "talking_points",
    "preparation_checks",
)
_ARRAY_FIELDS = OFFER_NEGOTIATION_FIELDS[1:]
_ITEM_FIELDS = {"id", "text", "rationale", "evidence_refs"}
_REF_FIELDS = {"source", "path", "excerpt"}
_ALLOWED_SOURCES = {"offer_snapshot", "user_brief"}
_SHAPE_CATEGORIES = {
    "invalid_json",
    "duplicate_json_key",
    "unexpected_field",
    "invalid_item_shape",
    "missing_field",
    "invalid_field_type",
}
OfferNegotiationDiagnosticSink = Callable[[dict[str, Any]], None]
_ID_RE = re.compile(r"^[\x21-\x7e]{1,64}$")
_FORBIDDEN = re.compile(r"接受|拒绝|放弃|最优|最佳|应该选|通过率|录用|市场薪酬|法律结论|公司政策|tax|salary market", re.I)

OFFER_NEGOTIATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(OFFER_NEGOTIATION_FIELDS),
    "properties": {
        "proposal_status": {"enum": ["normal", "safe_empty"]},
        **{
            field: {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "text", "rationale", "evidence_refs"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "text": {"type": "string", "minLength": 1, "maxLength": 600},
                        "rationale": {"type": "string", "minLength": 1, "maxLength": 600},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["source", "path", "excerpt"],
                                "properties": {
                                    "source": {"enum": sorted(_ALLOWED_SOURCES)},
                                    "path": {"type": "string", "minLength": 1},
                                    "excerpt": {"type": "string", "minLength": 1, "maxLength": 400},
                                },
                            },
                        },
                    },
                },
            }
            for field in _ARRAY_FIELDS
        },
    },
}

OFFER_NEGOTIATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "offer_negotiation_proposal",
        "strict": True,
        "schema": OFFER_NEGOTIATION_JSON_SCHEMA,
    },
}


class OfferNegotiationModelError(ValueError):
    def __init__(self, message: str, validation_category: str = "invalid_json") -> None:
        super().__init__(message)
        self.validation_category = validation_category
        self.provider_request_id = ""
        self.repair_count = 0
        self.elapsed_ms = 0
        self.http_status: int | None = None
        self.timeout = False


def _redact_provider_request_id(value: object) -> str:
    request_id = str(value or "")
    if not request_id:
        return ""
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:12]
    return f"request-redacted-{digest}"


def safe_empty_offer_negotiation_proposal() -> dict[str, Any]:
    return {
        "proposal_status": "safe_empty",
        "communication_goals": [],
        "clarification_questions": [],
        "talking_points": [],
        "preparation_checks": [],
    }


def build_offer_negotiation_snapshot(
    *,
    offer: dict[str, Any],
    dimensions: list[dict[str, Any]],
    user_brief: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    del idempotency_key
    for field in ("goal", "concerns", "scenario"):
        value = user_brief.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must not be blank")
    fields = (
        "company_name", "position_name", "status", "base_monthly", "months_per_year",
        "signing_bonus", "equity", "perks", "deadline", "notes",
    )
    offer_snapshot = {field: offer.get(field) for field in fields}
    sorted_dimensions = sorted(dimensions, key=lambda item: int(item["id"]))
    canonical_dimensions = [
        {
            "path_id": f"dimension_{index:03d}",
            "label": str(item["label"]),
            "value_text": item.get("value_text"),
        }
        for index, item in enumerate(sorted_dimensions, start=1)
    ]
    return {
        "snapshot_version": 1,
        "offer_snapshot": {**offer_snapshot, "dimensions": canonical_dimensions},
        "user_brief": {
            "goal": user_brief.get("goal", ""),
            "concerns": user_brief.get("concerns", ""),
            "scenario": user_brief.get("scenario", ""),
        },
    }


def validate_offer_negotiation(payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    _reject_non_finite(payload)
    if not isinstance(payload, dict):
        raise OfferNegotiationModelError("proposal must be an object", "invalid_item_shape")
    if set(payload) != set(OFFER_NEGOTIATION_FIELDS):
        raise OfferNegotiationModelError("proposal fields are invalid", "unexpected_field")
    status = payload.get("proposal_status")
    if status not in {"normal", "safe_empty"}:
        raise OfferNegotiationModelError("proposal_status is invalid", "invalid_field_type")
    if status == "safe_empty":
        if any(payload[field] != [] for field in _ARRAY_FIELDS):
            raise OfferNegotiationModelError("safe_empty must have empty arrays", "invalid_item_shape")
        return safe_empty_offer_negotiation_proposal()
    seen_ids: set[str] = set()
    normalized: dict[str, Any] = {"proposal_status": "normal"}
    for field in _ARRAY_FIELDS:
        items = payload.get(field)
        if not isinstance(items, list):
            raise OfferNegotiationModelError(f"{field} must be an array", "invalid_field_type")
        if len(items) > 8:
            raise OfferNegotiationModelError(f"{field} exceeds the limit", "limit_exceeded")
        normalized[field] = []
        for item in items:
            checked = _validate_item(item, snapshot)
            if checked["id"] in seen_ids:
                raise OfferNegotiationModelError("item ids must be unique", "duplicate_item_id")
            seen_ids.add(checked["id"])
            normalized[field].append(checked)
    if all(not normalized[field] for field in _ARRAY_FIELDS):
        return safe_empty_offer_negotiation_proposal()
    return normalized


def generate_offer_negotiation_proposal(
    model: ChatModel,
    snapshot: dict[str, Any],
    *,
    on_diagnostic: OfferNegotiationDiagnosticSink | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    last_category = "invalid_json"
    provider_request_id = ""
    for attempt in range(2):
        prompt = _generation_prompt(snapshot) if attempt == 0 else _repair_prompt(last_category)
        response_format = OFFER_NEGOTIATION_RESPONSE_FORMAT if getattr(model, "supports_json_schema", False) is True else None
        try:
            assistant = model.complete(
                [
                    Message(role="system", content=_system_prompt(snapshot)),
                    Message(role="user", content=prompt),
                ],
                [],
                response_format=response_format,
            )
        except Exception as exc:
            error = OfferNegotiationModelError("provider request failed", "provider_error")
            error.provider_request_id = _redact_provider_request_id(getattr(exc, "provider_request_id", ""))
            status = getattr(exc, "status_code", getattr(exc, "http_status", None))
            try:
                error.http_status = int(status) if status is not None else None
            except (TypeError, ValueError):
                error.http_status = None
            error.timeout = isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
            error.repair_count = attempt
            error.elapsed_ms = int((perf_counter() - started) * 1000)
            _emit_diagnostic(
                on_diagnostic,
                failure_category="provider_error",
                repair_attempted=attempt > 0,
                repair_count=attempt,
                elapsed_ms=error.elapsed_ms,
                provider_request_id=error.provider_request_id,
                http_status=error.http_status,
                timeout=error.timeout,
            )
            raise error from exc
        provider_request_id = _redact_provider_request_id(
            getattr(assistant, "provider_blocks", {}).get("request_id")
        )
        try:
            parsed = parse_json_reply(
                assistant.content,
                allow_fenced=False,
                reject_non_finite=True,
                reject_duplicate_keys=True,
            )
            return validate_offer_negotiation(parsed, snapshot)
        except OfferNegotiationModelError as exc:
            last_category = exc.validation_category
        except (TypeError, ValueError, RuntimeError) as exc:
            last_category = "duplicate_json_key" if "duplicate" in str(exc).lower() else "invalid_json"
        if last_category not in _SHAPE_CATEGORIES:
            error = OfferNegotiationModelError("proposal is not verifiable", last_category)
            error.provider_request_id = provider_request_id
            error.repair_count = attempt
            error.elapsed_ms = int((perf_counter() - started) * 1000)
            _emit_diagnostic(
                on_diagnostic,
                failure_category=last_category,
                repair_attempted=attempt > 0,
                repair_count=attempt,
                elapsed_ms=error.elapsed_ms,
                provider_request_id=provider_request_id,
            )
            raise error
    _emit_diagnostic(
        on_diagnostic,
        failure_category=last_category,
        repair_attempted=True,
        repair_count=1,
        elapsed_ms=int((perf_counter() - started) * 1000),
        provider_request_id=provider_request_id,
    )
    return safe_empty_offer_negotiation_proposal()


def _emit_diagnostic(
    sink: OfferNegotiationDiagnosticSink | None,
    *,
    failure_category: str,
    repair_attempted: bool,
    repair_count: int,
    elapsed_ms: int,
    provider_request_id: str,
    http_status: int | None = None,
    timeout: bool = False,
) -> None:
    if sink is None:
        return
    sink(
        {
            "failure_category": failure_category,
            "failure_categories": [failure_category],
            "repair_attempted": repair_attempted,
            "repair_count": repair_count,
            "elapsed_ms": max(0, elapsed_ms),
            "provider_request_id": provider_request_id,
            "http_status": http_status,
            "timeout": timeout,
        }
    )


def _validate_item(item: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
        raise OfferNegotiationModelError("item fields are invalid", "invalid_item_shape")
    item_id = item.get("id")
    text = item.get("text")
    rationale = item.get("rationale")
    refs = item.get("evidence_refs")
    if not isinstance(item_id, str) or not item_id:
        raise OfferNegotiationModelError("item id is invalid", "invalid_item_shape")
    if len(item_id) > 64:
        raise OfferNegotiationModelError("item id exceeds the limit", "limit_exceeded")
    if not _ID_RE.fullmatch(item_id):
        raise OfferNegotiationModelError("item id is invalid", "invalid_item_shape")
    if not isinstance(text, str) or not text.strip():
        raise OfferNegotiationModelError("item text is invalid", "invalid_item_shape")
    if not isinstance(rationale, str) or not rationale.strip():
        raise OfferNegotiationModelError("item rationale is invalid", "invalid_item_shape")
    if len(text) > 600 or len(rationale) > 600:
        raise OfferNegotiationModelError("item text exceeds the limit", "limit_exceeded")
    if _FORBIDDEN.search(text) or _FORBIDDEN.search(rationale):
        raise OfferNegotiationModelError("decision language is not allowed", "forbidden_decision_language")
    if not isinstance(refs, list) or not refs or len(refs) > 4:
        raise OfferNegotiationModelError("evidence_refs is invalid", "missing_evidence_ref")
    return {
        "id": item_id,
        "text": text,
        "rationale": rationale,
        "evidence_refs": [_validate_ref(ref, snapshot) for ref in refs],
    }


def _validate_ref(ref: Any, snapshot: dict[str, Any]) -> dict[str, str]:
    if not isinstance(ref, dict) or set(ref) != _REF_FIELDS:
        raise OfferNegotiationModelError("evidence reference is invalid", "unknown_evidence_ref")
    source, path, excerpt = ref.get("source"), ref.get("path"), ref.get("excerpt")
    if source not in _ALLOWED_SOURCES or not isinstance(path, str) or not isinstance(excerpt, str):
        raise OfferNegotiationModelError("evidence reference is unknown", "unknown_evidence_ref")
    if not excerpt.strip() or len(excerpt) > 400:
        raise OfferNegotiationModelError("evidence excerpt is invalid", "excerpt_mismatch")
    if source == "offer_snapshot":
        value = _resolve_snapshot_path(snapshot, source, path)
        if not isinstance(value, (str, int)) or value is None:
            raise OfferNegotiationModelError("offer evidence path is invalid", "unknown_evidence_ref")
        expected = str(value)
        if isinstance(value, int) and excerpt != expected:
            raise OfferNegotiationModelError("numeric evidence must be exact", "excerpt_mismatch")
        if isinstance(value, str) and excerpt not in value:
            raise OfferNegotiationModelError("evidence excerpt does not match", "excerpt_mismatch")
    else:
        value = _resolve_snapshot_path(snapshot, source, path)
        if not isinstance(value, str) or excerpt not in value:
            raise OfferNegotiationModelError("user brief excerpt does not match", "excerpt_mismatch")
    return {"source": source, "path": path, "excerpt": excerpt}


def _resolve_snapshot_path(snapshot: dict[str, Any], source: str, path: str) -> Any:
    if source == "offer_snapshot":
        fixed_fields = {
            "company_name", "position_name", "status", "base_monthly", "months_per_year",
            "signing_bonus", "equity", "perks", "deadline", "notes",
        }
        prefix = "/offer_snapshot/"
        if path.startswith(prefix):
            field = path[len(prefix):]
            if field in fixed_fields:
                value = snapshot.get("offer_snapshot", {}).get(field)
                if value is None or isinstance(value, (dict, list, bool)):
                    raise OfferNegotiationModelError("offer evidence path is invalid", "unknown_evidence_ref")
                return value
        dimension_match = re.fullmatch(r"/offer_snapshot/dimensions/(dimension_[0-9]{3})/value_text", path)
        if dimension_match:
            path_id = dimension_match.group(1)
            dimensions = snapshot.get("offer_snapshot", {}).get("dimensions", [])
            dimension = next((item for item in dimensions if item.get("path_id") == path_id), None)
            if dimension is None or not isinstance(dimension.get("value_text"), str) or not dimension["value_text"]:
                raise OfferNegotiationModelError("missing dimension value has no evidence", "unknown_evidence_ref")
            return dimension["value_text"]
    elif source == "user_brief":
        if path in {"/user_brief/goal", "/user_brief/concerns", "/user_brief/scenario"}:
            value = snapshot.get("user_brief", {}).get(path.rsplit("/", 1)[-1])
            if isinstance(value, str) and value:
                return value
    raise OfferNegotiationModelError("evidence path is unknown", "unknown_evidence_ref")


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise OfferNegotiationModelError("non-finite value", "invalid_field_type")
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, list):
        for item in value:
            _reject_non_finite(item)


def _evidence_catalog(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    catalog: list[dict[str, str]] = []
    offer_snapshot = snapshot.get("offer_snapshot", {})
    if isinstance(offer_snapshot, dict):
        for field, value in offer_snapshot.items():
            if isinstance(value, (str, int)) and not isinstance(value, bool) and value != "":
                catalog.append(
                    {
                        "source": "offer_snapshot",
                        "path": f"/offer_snapshot/{field}",
                        "excerpt": str(value),
                    }
                )
    dimensions = offer_snapshot.get("dimensions", [])
    if isinstance(dimensions, list):
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                continue
            value = dimension.get("value_text")
            path_id = dimension.get("path_id")
            if isinstance(path_id, str) and isinstance(value, str) and value:
                catalog.append(
                    {
                        "source": "offer_snapshot",
                        "path": f"/offer_snapshot/dimensions/{path_id}/value_text",
                        "excerpt": value,
                    }
                )
    user_brief = snapshot.get("user_brief", {})
    if isinstance(user_brief, dict):
        for field, value in user_brief.items():
            if isinstance(value, str) and value:
                catalog.append(
                    {
                        "source": "user_brief",
                        "path": f"/user_brief/{field}",
                        "excerpt": value,
                    }
                )
    return sorted(catalog, key=lambda item: (item["source"], item["path"]))


def _system_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "只输出严格 JSON，不要 Markdown。不要做接受、拒绝、放弃、排名或最优 Offer 决定。"
        "所有条目必须包含 id、text、rationale、evidence_refs；每个 evidence_refs 必须来自输入目录，"
        "excerpt 必须逐字连续匹配。没有可验证建议时输出 proposal_status=safe_empty 和四个空数组。"
        + json.dumps(OFFER_NEGOTIATION_JSON_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        + "\n只能从以下 evidence_catalog 逐条选择 source/path/excerpt；不得创造目录外引用："
        + json.dumps(_evidence_catalog(snapshot), ensure_ascii=False, separators=(",", ":"))
    )


def _generation_prompt(snapshot: dict[str, Any]) -> str:
    return "基于以下冻结输入生成 Offer 谈薪准备建议，只能引用输入中的路径和原文：" + canonical_json(snapshot)


def _repair_prompt(category: str) -> str:
    return (
        "上次输出未通过机器校验。只修复失败类别：" + category
        + "。请重新输出完整严格 JSON；不要输出解释、原始模型内容或输入快照。"
        + json.dumps(OFFER_NEGOTIATION_JSON_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    )
