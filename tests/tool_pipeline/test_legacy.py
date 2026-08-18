from __future__ import annotations

from dataclasses import dataclass

import pytest

from offerpilot.ai.tool_runtime.legacy import (
    LEGACY_DETERMINISTIC_NAMES,
    LegacyDeterministicAdapter,
    LegacyDeterministicCatalog,
)
from offerpilot.ai.tool_specs.catalog import MODEL_TOOL_CATALOG


@dataclass(frozen=True)
class ServerPending:
    tool_name: str


def _adapter(name: str) -> LegacyDeterministicAdapter:
    return LegacyDeterministicAdapter(
        name=name,
        editable_fields=(),
        describe=lambda args: args,
        validate=lambda args: "",
        execute=lambda args: args,
    )


def test_legacy_catalog_is_exact_and_never_model_visible() -> None:
    catalog = LegacyDeterministicCatalog(tuple(_adapter(name) for name in sorted(LEGACY_DETERMINISTIC_NAMES)))

    assert LEGACY_DETERMINISTIC_NAMES == frozenset(
        {
            "save_application_jd_version",
            "create_application_submission_snapshot",
            "record_application_outcome",
        }
    )
    assert all(MODEL_TOOL_CATALOG.resolve(name) is None for name in LEGACY_DETERMINISTIC_NAMES)
    assert all(name not in {contract.name for contract in MODEL_TOOL_CATALOG.provider_contracts()} for name in LEGACY_DETERMINISTIC_NAMES)
    assert catalog.resolve_server_loaded(ServerPending("save_application_jd_version")) is not None
    assert catalog.resolve_server_loaded(ServerPending("create_application")) is None


def test_legacy_catalog_rejects_missing_or_extra_names() -> None:
    with pytest.raises(ValueError, match="legacy deterministic catalog mismatch"):
        LegacyDeterministicCatalog((_adapter("save_application_jd_version"),))


def test_client_tool_name_alone_has_no_legacy_lookup_api() -> None:
    assert not hasattr(LegacyDeterministicCatalog, "resolve")
