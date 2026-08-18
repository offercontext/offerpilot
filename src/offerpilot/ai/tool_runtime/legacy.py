from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
from typing import Protocol

from offerpilot.ai.tool_runtime.contracts import JSONValue


LEGACY_DETERMINISTIC_NAMES = frozenset(
    {
        "save_application_jd_version",
        "create_application_submission_snapshot",
        "record_application_outcome",
    }
)


class ServerLoadedPending(Protocol):
    tool_name: str


@dataclass(frozen=True)
class LegacyDeterministicAdapter:
    name: str
    editable_fields: tuple[Mapping[str, JSONValue], ...]
    describe: Callable[[str], str] = field(repr=False, compare=False)
    validate: Callable[[str], str] = field(repr=False, compare=False)
    execute: Callable[[str], str] = field(repr=False, compare=False)


class LegacyDeterministicCatalog:
    def __init__(self, adapters: Sequence[LegacyDeterministicAdapter]) -> None:
        ordered = tuple(adapters)
        names = tuple(adapter.name for adapter in ordered)
        if len(set(names)) != len(names) or frozenset(names) != LEGACY_DETERMINISTIC_NAMES:
            raise ValueError("legacy deterministic catalog mismatch")
        self._adapters = {adapter.name: adapter for adapter in ordered}

    def resolve_server_loaded(
        self,
        pending: ServerLoadedPending,
    ) -> LegacyDeterministicAdapter | None:
        return self._adapters.get(pending.tool_name)


def prepare_legacy_arguments(
    adapter: LegacyDeterministicAdapter,
    encoded_args: str,
    edited_args: Mapping[str, JSONValue] | None,
) -> tuple[str, str]:
    if edited_args is None:
        return encoded_args, adapter.describe(encoded_args)
    value = json.loads(encoded_args)
    if not isinstance(value, dict):
        raise ValueError("pending arguments must be a valid JSON object")
    editable = {
        str(field["field"]): field
        for field in adapter.editable_fields
        if isinstance(field.get("field"), str)
    }
    forbidden = sorted(str(key) for key in edited_args if key not in editable)
    if forbidden:
        raise ValueError("non-editable fields: " + ", ".join(forbidden))
    effective = {**value, **edited_args}
    encoded = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    validation_error = adapter.validate(encoded)
    if validation_error:
        raise ValueError(validation_error)
    return encoded, adapter.describe(encoded)
