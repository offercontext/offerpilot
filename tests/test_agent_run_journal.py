from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from offerpilot.agent_runtime.events import (
    ContextManifestInput,
    JournalEventValidationError,
    canonical_json,
    normalize_context_identity,
    normalize_source_reference,
    prepare_context_snapshot,
    prepare_event,
)
from offerpilot.agent_runtime.keyring import JournalKeyDomain

KEY = JournalKeyDomain(
    key_id="11111111-1111-4111-8111-111111111111",
    secret=b"k" * 32,
)
SEGMENT_A = "22222222-2222-4222-8222-222222222222"
SEGMENT_B = "33333333-3333-4333-8333-333333333333"
CALL_A = "44444444-4444-4444-8444-444444444444"
CALL_B = "55555555-5555-4555-8555-555555555555"


@pytest.mark.parametrize(
    ("context_type", "context_ref", "expected_type", "expected_entity"),
    [
        ("workspace", "private free text", "workspace", None),
        ("global", "https://private.example/path", "global", None),
        ("application", "37", "application", 37),
        ("application", "../../etc/passwd", "application", None),
        ("custom-private-type", "candidate secret", "unknown", None),
    ],
)
def test_context_identity_never_persists_arbitrary_strings(
    context_type: str,
    context_ref: str,
    expected_type: str,
    expected_entity: int | None,
) -> None:
    normalized = normalize_context_identity(
        context_type,
        context_ref,
        application_visible=lambda value: value == 37,
        key=KEY,
    )

    assert normalized.context_type == expected_type
    assert normalized.entity_id == expected_entity
    serialized = json.dumps(asdict(normalized), ensure_ascii=False)
    assert "private" not in serialized
    assert "candidate secret" not in serialized
    assert "../../" not in serialized


def test_mode_and_unknown_context_use_hmac_not_plain_reference() -> None:
    normalized = normalize_context_identity(
        "mode",
        "private-mode-instance",
        application_visible=lambda _value: False,
        key=KEY,
    )

    assert normalized.entity_id is None
    assert normalized.ref_fingerprint is not None
    assert len(normalized.ref_fingerprint) == 64
    assert normalized.ref_fingerprint != hashlib.sha256(b"private-mode-instance").hexdigest()


@pytest.mark.parametrize(
    ("source_type", "source_id", "expected"),
    [
        ("message", 42, "42"),
        ("transport_run", SEGMENT_A, SEGMENT_A),
        ("model_call", CALL_A, CALL_A),
        ("tool_call", "call_safe-01", "call_safe-01"),
        ("operation", "a" * 32, "a" * 32),
    ],
)
def test_source_reference_accepts_only_type_specific_stable_ids(
    source_type: str,
    source_id: object,
    expected: str,
) -> None:
    assert normalize_source_reference(source_type, source_id) == (source_type, expected)


@pytest.mark.parametrize(
    ("source_type", "source_id"),
    [
        ("message", "01"),
        ("transport_run", "NOT-A-UUID"),
        ("tool_call", "contains private spaces"),
        ("operation", "../private"),
        ("unknown", "private"),
    ],
)
def test_source_reference_rejects_invalid_or_free_strings(
    source_type: str,
    source_id: object,
) -> None:
    assert normalize_source_reference(source_type, source_id) == (None, None)


def _model_completed(**overrides: object):
    values = {
        "event_type": "model.completed",
        "execution_segment_id": SEGMENT_A,
        "model_step": 1,
        "model_call_id": CALL_A,
        "facts": {
            "assistant_kind": "text",
            "tool_call_count": 0,
            "finish_category": "stop",
        },
        "telemetry": {"duration_ms": 10},
    }
    values.update(overrides)
    return prepare_event(**values)  # type: ignore[arg-type]


def test_fact_digest_ignores_telemetry_but_not_stable_envelope() -> None:
    base = _model_completed()

    assert _model_completed(telemetry={"duration_ms": 90}).fact_digest == base.fact_digest
    assert _model_completed(execution_segment_id=SEGMENT_B).fact_digest != base.fact_digest
    assert _model_completed(model_step=2).fact_digest != base.fact_digest
    assert _model_completed(model_call_id=CALL_B).fact_digest != base.fact_digest
    assert _model_completed(telemetry={"duration_ms": 90}).payload_digest != base.payload_digest


def test_event_payload_is_canonical_bounded_and_rejects_unknown_or_sensitive_keys() -> None:
    prepared = _model_completed()
    assert prepared.payload_json == canonical_json(
        {
            "facts": {
                "assistant_kind": "text",
                "finish_category": "stop",
                "tool_call_count": 0,
            },
            "telemetry": {"duration_ms": 10},
        }
    )
    assert len(prepared.payload_json.encode("utf-8")) <= 4096

    with pytest.raises(JournalEventValidationError):
        _model_completed(facts={"assistant_kind": "text", "prompt": "private"})
    with pytest.raises(JournalEventValidationError):
        _model_completed(telemetry={"duration_ms": float("nan")})
    with pytest.raises(JournalEventValidationError):
        _model_completed(telemetry={"duration_ms": lambda: None})
    with pytest.raises(JournalEventValidationError):
        _model_completed(
            facts={
                "assistant_kind": "private answer copied into a legal field",
                "tool_call_count": 0,
                "finish_category": "stop",
            }
        )
    with pytest.raises(JournalEventValidationError):
        _model_completed(
            facts={
                "assistant_kind": {"nested": "private"},
                "tool_call_count": 0,
                "finish_category": "stop",
            }
        )
    with pytest.raises(JournalEventValidationError):
        _model_completed(facts={"assistant_kind": "text", "tool_call_count": 0})


def test_manifest_is_bounded_versioned_and_preserves_ordered_summaries() -> None:
    messages = tuple(range(1, 10_001))
    tools = tuple(f"tool_{index:03d}" for index in range(100))
    attachments = tuple(
        {"id": index + 1, "revision": index, "kind": "resume"} for index in range(100)
    )
    sources = tuple(
        {"id": index + 1, "revision": index, "kind": "application"}
        for index in range(100)
    )
    prepared = prepare_context_snapshot(
        logical_input={"messages": [{"role": "user", "content": "private input"}]},
        manifest=ContextManifestInput(messages, tools, attachments, sources),
        key=KEY,
    )
    manifest = json.loads(prepared.manifest_json)

    assert prepared.manifest_schema_version == 1
    assert prepared.fingerprint_key_id == KEY.key_id
    assert len(prepared.manifest_json.encode("utf-8")) < 16_384
    assert manifest["conversation"]["message_count"] == 10_000
    assert manifest["conversation"]["first_message_id"] == 1
    assert manifest["conversation"]["last_message_id"] == 10_000
    assert manifest["conversation"]["included_recent_message_ids"] == list(range(9985, 10001))
    assert manifest["tools"]["count"] == 100
    assert manifest["tools"]["included_names"] == list(tools[:32])
    assert len(manifest["attachments"]["included_refs"]) == 16
    assert len(manifest["domain_sources"]["included_refs"]) == 32
    assert "private input" not in prepared.manifest_json


def test_input_fingerprint_uses_exact_domain_formula() -> None:
    logical_input = {"tools": [], "messages": [{"role": "user", "content": "hello"}]}
    canonical = canonical_json(logical_input).encode("utf-8")
    expected = hmac.new(
        KEY.secret,
        b"offerpilot-agent-input-v1\0" + canonical,
        hashlib.sha256,
    ).hexdigest()

    prepared = prepare_context_snapshot(
        logical_input=logical_input,
        manifest=ContextManifestInput((), (), (), ()),
        key=KEY,
    )

    assert prepared.logical_input_fingerprint == expected


@pytest.mark.parametrize(
    "value",
    [
        {"bad": {1, 2}},
        {"bad": float("inf")},
        {"bad": lambda: None},
        {"bad": Path("private")},
    ],
)
def test_canonical_json_rejects_unsupported_values_without_stringifying(value: object) -> None:
    with pytest.raises(JournalEventValidationError):
        canonical_json(value)


def test_canonical_json_rejects_cycles() -> None:
    value: dict[str, object] = {}
    value["cycle"] = value

    with pytest.raises(JournalEventValidationError):
        canonical_json(value)


def test_canonical_json_rejects_oversized_leaf_before_serialization() -> None:
    with pytest.raises(JournalEventValidationError):
        canonical_json("x" * 1_048_577)


def test_uuid_normalizer_does_not_execute_str_subclass_methods() -> None:
    called = False

    class EvilStr(str):
        def replace(self, *_args: object, **_kwargs: object) -> str:
            nonlocal called
            called = True
            raise AssertionError("untrusted str subclass executed")

    assert normalize_source_reference("transport_run", EvilStr(SEGMENT_A)) == (None, None)
    assert called is False


def test_event_draft_is_immutable() -> None:
    event = _model_completed()
    changed = replace(event, execution_segment_id=SEGMENT_B)
    assert event.execution_segment_id == SEGMENT_A
    assert changed.execution_segment_id == SEGMENT_B


def test_context_captured_accepts_versioned_snapshot_key() -> None:
    snapshot_id = "66666666-6666-4666-8666-666666666666"
    event = prepare_event(
        event_type="context.captured",
        execution_segment_id=SEGMENT_A,
        facts={
            "snapshot_id": snapshot_id,
            "snapshot_key": f"model-input:{SEGMENT_A}:{CALL_A}",
            "manifest_digest": "a" * 64,
            "logical_input_fingerprint": "b" * 64,
        },
        fingerprint_key_id=KEY.key_id,
    )

    assert event.dedupe_key == f"context.captured:{snapshot_id}"


def test_sync_segment_has_no_transport_run_id() -> None:
    event = prepare_event(
        event_type="segment.started",
        execution_segment_id=SEGMENT_A,
        facts={
            "request_kind": "initial",
            "transport_mode": "sync",
            "execution_path": "model_turn",
            "transport_run_id": None,
        },
    )

    assert json.loads(event.payload_json)["facts"]["transport_run_id"] is None


def test_event_fixed_enums_reject_safe_looking_private_canary() -> None:
    with pytest.raises(JournalEventValidationError):
        _model_completed(
            facts={
                "assistant_kind": "private-canary",
                "tool_call_count": 0,
                "finish_category": "stop",
            }
        )


def test_hmac_facts_require_key_domain_id() -> None:
    with pytest.raises(JournalEventValidationError):
        prepare_event(
            event_type="model.requested",
            execution_segment_id=SEGMENT_A,
            model_step=1,
            model_call_id=CALL_A,
            facts={
                "snapshot_id": "66666666-6666-4666-8666-666666666666",
                "provider_kind": "openai_compatible",
                "model_id_fingerprint": "a" * 64,
                "supports_tools": True,
                "supports_json_schema": False,
                "stream": False,
                "tools_count": 3,
                "response_format_kind": "text",
            },
        )


def test_canonical_json_rejects_str_subclass_keys_without_comparing_them() -> None:
    called = False

    class EvilKey(str):
        def __lt__(self, _other: object) -> bool:
            nonlocal called
            called = True
            raise AssertionError("untrusted key comparison executed")

    with pytest.raises(JournalEventValidationError):
        canonical_json({EvilKey("a"): 1, EvilKey("b"): 2})
    assert called is False
