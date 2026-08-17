from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from offerpilot.agent_runtime.keyring import JournalKeyDomain

_CONTEXT_TYPES = {"workspace", "global", "application", "mode"}
_INTEGER_REFERENCE_TYPES = {
    "application",
    "application_event",
    "attachment",
    "conversation",
    "message",
    "snapshot",
}
_UUID_REFERENCE_TYPES = {
    "agent_run",
    "context_snapshot",
    "execution_segment",
    "model_call",
    "transport_run",
}
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_OPERATION_ID = re.compile(r"[0-9a-f]{32}")
_FORBIDDEN_KEYS = {
    "answer",
    "api_key",
    "args",
    "attachment_name",
    "confirmation_token",
    "content",
    "context_ref",
    "exception",
    "idempotency_key",
    "jd_text",
    "message",
    "model_id",
    "output",
    "prompt",
    "provider_url",
    "resume_text",
    "secret",
    "text",
    "token",
    "tool_result",
    "url",
}
_FACT_KEYS: dict[str, set[str]] = {
    "run.started": {"agent_run_id", "origin_kind", "conversation_id", "context_type", "transport_mode"},
    "segment.started": {"request_kind", "transport_mode", "execution_path", "transport_run_id"},
    "segment.finished": {"outcome", "terminal_run_status"},
    "route.selected": {"route_kind", "route_reason_code"},
    "context.captured": {"snapshot_id", "snapshot_key", "manifest_digest", "logical_input_fingerprint"},
    "model.requested": {
        "snapshot_id",
        "provider_kind",
        "model_id_fingerprint",
        "supports_tools",
        "supports_json_schema",
        "stream",
        "tools_count",
        "response_format_kind",
    },
    "model.completed": {"assistant_kind", "tool_call_count", "finish_category"},
    "model.failed": {"failure_category", "provider_outcome"},
    "tool.proposed": {"tool_call_id", "tool_name", "tool_kind", "args_shape_digest", "proposal_outcome"},
    "tool.started": {"tool_call_id", "tool_name", "result_contract"},
    "tool.completed": {"tool_call_id", "tool_name", "outcome", "result_shape_digest"},
    "tool.failed": {"tool_call_id", "tool_name", "failure_category"},
    "approval.requested": {"tool_call_id", "confirmation_mode", "pending_identity_fingerprint"},
    "approval.decided": {
        "confirmation_attempt_id",
        "decision",
        "tool_call_id",
        "original_input_fingerprint",
        "decided_input_fingerprint",
    },
    "run.waiting_confirmation": {"tool_call_id"},
    "run.resumed": {"confirmation_attempt_id", "tool_call_id"},
    "assistant.persisted": {"message_id", "message_kind"},
    "run.completed": {"agent_run_id", "status", "failure_code"},
    "run.failed": {"agent_run_id", "status", "failure_code"},
    "run.cancelled": {"agent_run_id", "status", "failure_code"},
    "run.timed_out": {"agent_run_id", "status", "failure_code"},
}
_TELEMETRY_KEYS = {"duration_ms", "retry_count", "item_count", "byte_count"}
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_CANONICAL_STRING_BYTES = 1_048_576


class JournalEventValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedContextIdentity:
    context_type: Literal["workspace", "global", "application", "mode", "unknown"]
    entity_id: int | str | None
    ref_fingerprint: str | None


@dataclass(frozen=True)
class ContextManifestInput:
    conversation_message_ids: tuple[int, ...]
    tool_names: tuple[str, ...]
    attachment_refs: tuple[Mapping[str, object], ...]
    domain_source_refs: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class PreparedSnapshot:
    manifest_schema_version: int
    manifest_json: str
    manifest_digest: str
    logical_input_fingerprint: str
    fingerprint_key_id: str


@dataclass(frozen=True)
class EventDraft:
    event_type: str
    schema_version: int
    execution_segment_id: str
    model_step: int | None
    model_call_id: str | None
    source_ref_type: str | None
    source_ref_id: str | None
    fingerprint_key_id: str | None
    payload_json: str
    payload_digest: str
    fact_digest: str
    dedupe_key: str


def _canonical_value(
    value: object,
    *,
    active: set[int],
    depth: int,
    nodes: list[int],
) -> object:
    nodes[0] += 1
    if nodes[0] > 100_000 or depth > 128:
        raise JournalEventValidationError("journal value exceeds canonicalization budget")
    if type(value) is str:
        if len(value.encode("utf-8")) > _MAX_CANONICAL_STRING_BYTES:
            raise JournalEventValidationError("journal string exceeds canonicalization budget")
        return value
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise JournalEventValidationError("non-finite number is not valid journal JSON")
        return value
    if type(value) not in {dict, list, tuple}:
        raise JournalEventValidationError("unsupported journal JSON value")
    identity = id(value)
    if identity in active:
        raise JournalEventValidationError("cyclic journal JSON value")
    active.add(identity)
    try:
        if type(value) is dict:
            object_value = cast(dict[object, object], value)
            result: dict[str, object] = {}
            for key in sorted(object_value, key=lambda item: item if isinstance(item, str) else ""):
                if type(key) is not str:
                    raise JournalEventValidationError("journal JSON object keys must be strings")
                result[key] = _canonical_value(
                    object_value[key], active=active, depth=depth + 1, nodes=nodes
                )
            return result
        sequence_value = cast(list[object] | tuple[object, ...], value)
        return [
            _canonical_value(item, active=active, depth=depth + 1, nodes=nodes)
            for item in sequence_value
        ]
    finally:
        active.remove(identity)


def canonical_json(value: object) -> str:
    normalized = _canonical_value(value, active=set(), depth=0, nodes=[0])
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_uuid(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        parsed = str(UUID(value))
    except ValueError:
        return None
    return parsed if parsed == value else None


def _hmac_fingerprint(key: JournalKeyDomain, domain: bytes, value: object) -> str:
    payload = canonical_json(value).encode("utf-8")
    return hmac.new(key.secret, domain + payload, hashlib.sha256).hexdigest()


def pending_identity_fingerprint(key: JournalKeyDomain, value: object) -> str:
    return _hmac_fingerprint(key, b"offerpilot-agent-pending-v1\0", value)


def model_id_fingerprint(key: JournalKeyDomain, value: str) -> str:
    return _hmac_fingerprint(key, b"offerpilot-agent-model-v1\0", value)


def normalize_context_identity(
    context_type: object,
    context_ref: object,
    *,
    application_visible: Callable[[int], bool],
    key: JournalKeyDomain,
) -> NormalizedContextIdentity:
    normalized_type = context_type.strip().lower() if type(context_type) is str else "unknown"
    if normalized_type not in _CONTEXT_TYPES:
        return NormalizedContextIdentity(
            context_type="unknown",
            entity_id=None,
            ref_fingerprint=_hmac_fingerprint(
                key,
                b"offerpilot-agent-context-v1\0",
                [normalized_type, context_ref if type(context_ref) is str else None],
            ),
        )
    if normalized_type in {"workspace", "global"}:
        return NormalizedContextIdentity(normalized_type, None, None)  # type: ignore[arg-type]
    if normalized_type == "application":
        parsed: int | None = None
        if type(context_ref) is str and re.fullmatch(r"[1-9][0-9]{0,17}", context_ref):
            parsed = int(context_ref)
        if parsed is not None and application_visible(parsed):
            return NormalizedContextIdentity("application", parsed, None)
        return NormalizedContextIdentity("application", None, None)
    return NormalizedContextIdentity(
        "mode",
        None,
        _hmac_fingerprint(
            key,
            b"offerpilot-agent-context-v1\0",
            ["mode", context_ref if type(context_ref) is str else None],
        ),
    )


def normalize_source_reference(source_type: object, source_id: object) -> tuple[str | None, str | None]:
    if type(source_type) is not str:
        return None, None
    if source_type in _INTEGER_REFERENCE_TYPES:
        if type(source_id) is int and source_id > 0:
            return source_type, str(source_id)
        return None, None
    if source_type in _UUID_REFERENCE_TYPES:
        normalized = _canonical_uuid(source_id)
        return (source_type, normalized) if normalized is not None else (None, None)
    if source_type == "tool_call":
        if type(source_id) is str and _SAFE_NAME.fullmatch(source_id):
            return source_type, source_id
        return None, None
    if source_type == "operation":
        if type(source_id) is str and _OPERATION_ID.fullmatch(source_id):
            return source_type, source_id
        return None, None
    return None, None


def _ordered_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_manifest_ref(value: Mapping[str, object]) -> dict[str, object]:
    if type(value) is not dict or not set(value).issubset({"id", "revision", "kind", "path_category"}):
        raise JournalEventValidationError("invalid manifest reference shape")
    result: dict[str, object] = {}
    identifier = value.get("id")
    if type(identifier) is int and identifier > 0:
        result["id"] = identifier
    elif (normalized := _canonical_uuid(identifier)) is not None:
        result["id"] = normalized
    else:
        raise JournalEventValidationError("invalid manifest reference id")
    revision = value.get("revision")
    if revision is not None:
        if type(revision) is not int or revision < 0:
            raise JournalEventValidationError("invalid manifest revision")
        result["revision"] = revision
    for field in ("kind", "path_category"):
        item = value.get(field)
        if item is not None:
            if type(item) is not str or _SAFE_NAME.fullmatch(item) is None:
                raise JournalEventValidationError("invalid manifest label")
            result[field] = item
    return result


def prepare_context_snapshot(
    logical_input: object,
    manifest: ContextManifestInput,
    *,
    key: JournalKeyDomain,
) -> PreparedSnapshot:
    messages = manifest.conversation_message_ids
    if any(type(item) is not int or item <= 0 for item in messages):
        raise JournalEventValidationError("invalid conversation message id")
    tools = manifest.tool_names
    if any(type(item) is not str or _SAFE_NAME.fullmatch(item) is None for item in tools):
        raise JournalEventValidationError("invalid tool name")
    attachments = [_normalize_manifest_ref(item) for item in manifest.attachment_refs]
    sources = [_normalize_manifest_ref(item) for item in manifest.domain_source_refs]
    manifest_payload = {
        "manifest_schema_version": 1,
        "conversation": {
            "message_count": len(messages),
            "first_message_id": messages[0] if messages else None,
            "last_message_id": messages[-1] if messages else None,
            "ordered_ids_digest": _ordered_digest(messages),
            "included_recent_message_ids": list(messages[-16:]),
        },
        "tools": {
            "count": len(tools),
            "ordered_names_digest": _ordered_digest(tools),
            "included_names": list(tools[:32]),
        },
        "attachments": {
            "count": len(attachments),
            "ordered_refs_digest": _ordered_digest(attachments),
            "included_refs": attachments[:16],
        },
        "domain_sources": {
            "count": len(sources),
            "ordered_refs_digest": _ordered_digest(sources),
            "included_refs": sources[:32],
        },
    }
    manifest_json = canonical_json(manifest_payload)
    if len(manifest_json.encode("utf-8")) > 16_384:
        raise JournalEventValidationError("manifest exceeds 16 KiB")
    logical_json = canonical_json(logical_input).encode("utf-8")
    return PreparedSnapshot(
        manifest_schema_version=1,
        manifest_json=manifest_json,
        manifest_digest=hashlib.sha256(manifest_json.encode("utf-8")).hexdigest(),
        logical_input_fingerprint=hmac.new(
            key.secret,
            b"offerpilot-agent-input-v1\0" + logical_json,
            hashlib.sha256,
        ).hexdigest(),
        fingerprint_key_id=key.key_id,
    )


def _dedupe_key(
    event_type: str,
    segment_id: str,
    model_call_id: str | None,
    facts: dict[str, object],
) -> str:
    if event_type == "run.started" or event_type.startswith("run.") and event_type in {
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.timed_out",
    }:
        identity = facts.get("agent_run_id")
    elif event_type in {"segment.started", "segment.finished", "route.selected"}:
        identity = segment_id
    elif event_type == "context.captured":
        identity = facts.get("snapshot_id")
    elif event_type.startswith("model."):
        identity = model_call_id
    elif event_type == "tool.proposed" or event_type == "run.waiting_confirmation":
        identity = facts.get("tool_call_id")
    elif event_type in {"tool.started", "tool.completed", "tool.failed"}:
        identity = f"{segment_id}:{facts.get('tool_call_id')}"
    elif event_type == "approval.requested":
        identity = facts.get("tool_call_id")
    elif event_type in {"approval.decided", "run.resumed"}:
        identity = facts.get("confirmation_attempt_id")
    elif event_type == "assistant.persisted":
        identity = facts.get("message_id")
    else:
        identity = None
    if identity is None or type(identity) not in {str, int}:
        raise JournalEventValidationError("event is missing its stable dedupe identity")
    return f"{event_type}:{identity}"


def prepare_event(
    *,
    event_type: str,
    execution_segment_id: str,
    facts: dict[str, object],
    telemetry: dict[str, object] | None = None,
    model_step: int | None = None,
    model_call_id: str | None = None,
    source_ref_type: str | None = None,
    source_ref_id: object = None,
    fingerprint_key_id: str | None = None,
) -> EventDraft:
    if event_type not in _FACT_KEYS or type(facts) is not dict:
        raise JournalEventValidationError("unsupported journal event type")
    if set(facts) != _FACT_KEYS[event_type] or set(facts) & _FORBIDDEN_KEYS:
        raise JournalEventValidationError("journal event contains unknown or sensitive facts")
    telemetry = {} if telemetry is None else telemetry
    if type(telemetry) is not dict or not set(telemetry).issubset(_TELEMETRY_KEYS):
        raise JournalEventValidationError("journal event contains unknown telemetry")
    for field, value in facts.items():
        _validate_fact_value(field, value)
    for value in telemetry.values():
        if type(value) not in {int, float}:
            raise JournalEventValidationError("invalid journal telemetry value")
        numeric_value = cast(int | float, value)
        if not math.isfinite(numeric_value) or numeric_value < 0:
            raise JournalEventValidationError("invalid journal telemetry value")
    segment = _canonical_uuid(execution_segment_id)
    if segment is None:
        raise JournalEventValidationError("invalid execution segment id")
    if model_step is not None and (type(model_step) is not int or model_step <= 0):
        raise JournalEventValidationError("invalid model step")
    call = _canonical_uuid(model_call_id) if model_call_id is not None else None
    if model_call_id is not None and call is None:
        raise JournalEventValidationError("invalid model call id")
    if fingerprint_key_id is not None and _canonical_uuid(fingerprint_key_id) is None:
        raise JournalEventValidationError("invalid fingerprint key id")
    normalized_type: str | None = None
    normalized_id: str | None = None
    if source_ref_type is not None or source_ref_id is not None:
        normalized_type, normalized_id = normalize_source_reference(source_ref_type, source_ref_id)
        if normalized_type is None:
            raise JournalEventValidationError("invalid source reference")
    payload = {"facts": facts, "telemetry": telemetry}
    payload_json = canonical_json(payload)
    if len(payload_json.encode("utf-8")) > 4096:
        raise JournalEventValidationError("event payload exceeds 4 KiB")
    fact_envelope = {
        "event_type": event_type,
        "schema_version": 1,
        "execution_segment_id": segment,
        "model_step": model_step,
        "model_call_id": call,
        "source_ref_type": normalized_type,
        "source_ref_id": normalized_id,
        "facts": facts,
    }
    return EventDraft(
        event_type=event_type,
        schema_version=1,
        execution_segment_id=segment,
        model_step=model_step,
        model_call_id=call,
        source_ref_type=normalized_type,
        source_ref_id=normalized_id,
        fingerprint_key_id=fingerprint_key_id,
        payload_json=payload_json,
        payload_digest=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        fact_digest=hashlib.sha256(canonical_json(fact_envelope).encode("utf-8")).hexdigest(),
        dedupe_key=_dedupe_key(event_type, segment, call, facts),
    )


def _validate_fact_value(field: str, value: object) -> None:
    if field in {"agent_run_id", "snapshot_id", "transport_run_id"}:
        if _canonical_uuid(value) is None:
            raise JournalEventValidationError("invalid journal UUID fact")
        return
    if field in {"conversation_id", "message_id"}:
        if type(value) is not int or value <= 0:
            raise JournalEventValidationError("invalid journal database id fact")
        return
    if field in {"tool_call_count", "tools_count"}:
        if type(value) is not int or value < 0:
            raise JournalEventValidationError("invalid journal count fact")
        return
    if field in {"supports_tools", "supports_json_schema", "stream"}:
        if type(value) is not bool:
            raise JournalEventValidationError("invalid journal boolean fact")
        return
    if field.endswith("_digest") or field.endswith("_fingerprint"):
        if type(value) is not str or _HEX_DIGEST.fullmatch(value) is None:
            raise JournalEventValidationError("invalid journal digest fact")
        return
    if field in {"failure_code", "terminal_run_status"} and value is None:
        return
    if type(value) is not str or _SAFE_NAME.fullmatch(value) is None:
        raise JournalEventValidationError("invalid journal token fact")
