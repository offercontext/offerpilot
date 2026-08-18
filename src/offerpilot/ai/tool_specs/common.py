from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

from offerpilot.ai.tool_runtime.contracts import (
    JSONValue,
    ProviderToolContract,
    ToolExceptionMapping,
)
from offerpilot.repositories.application_events import duration_minutes
from offerpilot.schemas import ApplicationEventOut, ApplicationOut


class ToolInputError(Exception):
    """A declared domain input failure whose text is part of the legacy contract."""


class ToolRecordNotFound(Exception):
    """A declared missing-record failure."""


class ToolStateConflict(Exception):
    """A declared mutable-state conflict."""


INPUT_EXCEPTION_MAP = (
    ToolExceptionMapping(ToolInputError, "validation_error", "domain_validation", str),
)
NOT_FOUND_EXCEPTION_MAP = (
    ToolExceptionMapping(ToolRecordNotFound, "not_found", "record_not_found", str),
)
CONFLICT_EXCEPTION_MAP = (
    ToolExceptionMapping(ToolStateConflict, "conflict", "state_conflict", str),
)


def provider_contract(
    name: str,
    description: str,
    parameters: Mapping[str, JSONValue],
) -> ProviderToolContract:
    function: dict[str, JSONValue] = {
        "name": name,
        "description": description,
        "parameters": dict(parameters),
    }
    payload: dict[str, JSONValue] = {"type": "function", "function": function}
    return ProviderToolContract(
        payload=payload,
        name=name,
        description=description,
        parameters=parameters,
    )


def decode_mapping(values: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    return dict(values)


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def spaced_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def application_json(app: Any) -> dict[str, Any]:
    payload = ApplicationOut.model_validate(app).model_dump(mode="json")
    payload["record_type"] = "application"
    payload["application_id"] = app.id
    return payload


def event_json(event: Any) -> dict[str, Any]:
    payload = ApplicationEventOut(
        id=event.id,
        application_id=event.application_id,
        event_type=event.event_type,
        subtype=event.subtype,
        tags=event.tags,
        round=event.round,
        scheduled_at=format_rfc3339(event.scheduled_at),
        duration_minutes=duration_minutes(event.duration_minutes),
        location=event.location,
        notes=event.notes,
        remind_at=format_rfc3339(event.remind_at) if event.remind_at else None,
        status=event.status,
        created_at=event.created_at,
    ).model_dump(mode="json", exclude_none=True)
    payload["record_type"] = "application_event"
    payload["application_event_id"] = event.id
    return payload


def event_with_application_json(item: Any) -> dict[str, Any]:
    payload = event_json(item.event)
    payload["company_name"] = item.company_name
    payload["position_name"] = item.position_name
    return payload


def format_rfc3339(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def integer(args: Mapping[str, object], key: str, tool_name: str) -> int:
    raw = args.get(key)
    if raw is None or raw == "":
        raise ToolInputError(f"{tool_name} requires {key}")
    try:
        return int(cast(Any, raw))
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"{tool_name} requires numeric {key}") from exc


def optional_integer(args: Mapping[str, object], key: str) -> int:
    raw = args.get(key)
    if raw is None or raw == "":
        return 0
    try:
        return int(cast(Any, raw))
    except (TypeError, ValueError) as exc:
        raise ToolInputError(f"{key} must be numeric") from exc
