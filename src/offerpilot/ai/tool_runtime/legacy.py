from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
