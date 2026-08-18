from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from offerpilot.agent_runtime.journal import EventInput, RunRecorder
from offerpilot.ai.tool_runtime.contracts import (
    PreparedToolCall,
    ToolExecutionRecord,
    ToolFailure,
    ToolSpec,
)
from offerpilot.ai.types import ToolCall


def project_tool_proposed(recorder: RunRecorder, spec: ToolSpec[Any, Any], call: ToolCall) -> bool:
    return _append(
        recorder,
        EventInput(
            event_type="tool.proposed",
            facts={
                "tool_call_id": call.id,
                "tool_name": spec.name,
                "tool_kind": spec.kind,
                "args_shape_digest": _journal_shape_digest(call.args),
                "proposal_outcome": (
                    "confirmation_required"
                    if spec.confirmation_policy == "required"
                    else "execution_allowed"
                ),
            },
            source_ref_type="tool_call",
            source_ref_id=call.id,
        ),
    )


def project_tool_started(recorder: RunRecorder, prepared: PreparedToolCall[Any, Any]) -> bool:
    return _append(
        recorder,
        EventInput(
            event_type="tool.started",
            facts={
                "tool_call_id": prepared.tool_call_id,
                "tool_name": prepared.spec.name,
                "result_contract": "legacy_string_v1",
            },
            source_ref_type="tool_call",
            source_ref_id=prepared.tool_call_id,
        ),
    )


def project_tool_terminal(
    recorder: RunRecorder,
    record: ToolExecutionRecord[Any, Any],
    *,
    started_recorded: bool,
    visible_result: str,
) -> bool:
    if not record.execution_started or not started_recorded:
        return False
    if isinstance(record.outcome, ToolFailure):
        if record.outcome.category == "confirmation_rejected":
            return False
        event = EventInput(
            event_type="tool.failed",
            facts={
                "tool_call_id": record.prepared.tool_call_id,
                "tool_name": record.prepared.spec.name,
                "failure_category": (
                    "provider_error" if record.outcome.category == "provider_error" else "tool_error"
                ),
            },
            source_ref_type="tool_call",
            source_ref_id=record.prepared.tool_call_id,
        )
    else:
        event = EventInput(
            event_type="tool.completed",
            facts={
                "tool_call_id": record.prepared.tool_call_id,
                "tool_name": record.prepared.spec.name,
                "outcome": "completed",
                "result_shape_digest": _journal_shape_digest(visible_result),
            },
            source_ref_type="tool_call",
            source_ref_id=record.prepared.tool_call_id,
        )
    return _append(recorder, event)


def _append(recorder: RunRecorder, event: EventInput) -> bool:
    if getattr(recorder, "recording_status", "healthy") == "degraded":
        return False
    try:
        recorder.append_event(event)
    except Exception:
        marker = getattr(recorder, "mark_degraded", None)
        if callable(marker):
            try:
                marker("journal_tool_projection_failed")
            except Exception:
                pass
        return False
    return getattr(recorder, "recording_status", "healthy") != "degraded"


def _journal_shape_digest(raw: str) -> str:
    if len(raw) > 65_536:
        value: object = {"type": "oversized"}
    else:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw
    shape = _journal_value_shape(value)
    encoded = json.dumps(shape, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def journal_shape_digest(raw: str) -> str:
    """Return the frozen Phase 1 shape digest without exposing payload contents."""

    return _journal_shape_digest(raw)


def _journal_value_shape(value: object, *, depth: int = 0) -> object:
    if depth >= 16:
        return {"type": "truncated"}
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if len(mapping) > 64:
            return {"type": "object", "field_count": len(mapping), "truncated": True}
        return {
            "type": "object",
            "fields": {
                str(key): _journal_value_shape(item, depth=depth + 1)
                for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0]))
            },
        }
    if type(value) is list:
        sequence = cast(list[object], value)
        return {
            "type": "array",
            "length": len(sequence),
            "items": [_journal_value_shape(item, depth=depth + 1) for item in sequence[:16]],
        }
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean"}
    if type(value) in {int, float}:
        return {"type": "number"}
    if type(value) is str:
        return {"type": "string"}
    return {"type": "unsupported"}
