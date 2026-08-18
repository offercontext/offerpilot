from __future__ import annotations

import ast
import pickle
from pathlib import Path
from typing import Any, cast

import pytest

from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.contracts import (
    BindingAudit,
    ExecutionAuthorization,
    PreparedToolCall,
    ProviderToolContract,
    ToolExecutionRecord,
    ToolFailure,
    ToolSpec,
)
from offerpilot.ai.tool_specs.catalog import MODEL_TOOL_CATALOG, MODEL_TOOL_NAMES
from offerpilot.ai.tool_runtime.legacy import LEGACY_DETERMINISTIC_NAMES

from golden import canonical_json, load_golden


def _contract(name: str, schema: dict[str, Any] | None = None) -> ProviderToolContract:
    parameters = schema or {"properties": {}, "type": "object"}
    payload = {
        "type": "function",
        "function": {
            "description": f"{name} description",
            "name": name,
            "parameters": parameters,
            "strict": False,
        },
    }
    return ProviderToolContract(
        payload=payload,
        name=name,
        description=f"{name} description",
        parameters=parameters,
    )


def _spec(
    name: str,
    *,
    kind: str = "read",
    schema: dict[str, Any] | None = None,
) -> ToolSpec[dict[str, Any], dict[str, Any]]:
    return ToolSpec(
        contract=_contract(name, schema),
        confirmation_policy="required" if kind == "write" else "none",
        decoder=lambda values: dict(values),
        executor=lambda args, context: args,
        kind=cast(Any, kind),
    )


def test_catalog_preserves_order_full_provider_envelopes_and_write_names() -> None:
    read = _spec("read_one")
    write = _spec("write_one", kind="write")
    catalog = ToolCatalog([read, write], expected_names=("read_one", "write_one"))

    assert catalog.resolve("read_one") is read
    assert catalog.resolve("missing") is None
    assert catalog.provider_contracts() == (read.contract, write.contract)
    assert catalog.provider_contracts()[0].payload["function"]["strict"] is False
    assert catalog.write_names() == frozenset({"write_one"})
    assert catalog.validator_for("read_one").schema == read.contract.parameters


@pytest.mark.parametrize(
    ("specs", "expected_names"),
    (
        ((_spec("one"),), ("other",)),
        ((_spec("one"), _spec("one")), ("one", "one")),
        ((_spec("one"), _spec("two")), ("two", "one")),
    ),
)
def test_catalog_rejects_missing_duplicate_or_reordered_names(
    specs: tuple[ToolSpec[Any, Any], ...],
    expected_names: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="tool catalog names/order mismatch"):
        ToolCatalog(specs, expected_names=expected_names)


def test_catalog_rejects_invalid_schema_during_construction() -> None:
    spec = _spec("broken", schema={"type": "not-a-type"})

    with pytest.raises(ValueError, match="invalid_tool_schema"):
        ToolCatalog([spec], expected_names=("broken",))


def test_runtime_catalog_has_no_reverse_dependency_on_tool_specs() -> None:
    source_path = (
        Path(__file__).parents[2] / "src" / "offerpilot" / "ai" / "tool_runtime" / "catalog.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert not any("tool_specs" in module for module in imported_modules)


def test_transient_runtime_values_reject_pickle_and_hide_sensitive_fields() -> None:
    spec = _spec("read_one")
    failure = ToolFailure(
        category="internal_error",
        code="executor_exception",
        compatibility_detail="private exception text",
    )
    prepared = PreparedToolCall(
        arguments={"private": "sensitive-argument-value"},
        arguments_digest="sha256:" + "a" * 64,
        binding=BindingAudit(status="unavailable", target_count=0),
        spec=spec,
        tool_call_id="call-1",
        typed_args={"private": "sensitive-argument-value"},
    )
    authorization = ExecutionAuthorization(
        arguments_digest=prepared.arguments_digest,
        pending_action_revision=3,
        pending_identity="private pending identity",
        tool_call_id="call-1",
        tool_name="read_one",
    )
    record = ToolExecutionRecord(
        execution_started=False,
        outcome=failure,
        prepared=prepared,
    )

    for value in (failure, prepared, authorization, record):
        with pytest.raises(TypeError, match="transient tool runtime value"):
            pickle.dumps(value)
        with pytest.raises(TypeError, match="transient tool runtime value"):
            value.__getstate__()

    rendered = repr((failure, prepared, authorization, record))
    assert "private exception text" not in rendered
    assert "private pending identity" not in rendered
    assert "sensitive-argument-value" not in rendered


def test_model_catalog_is_exact_provider_golden_in_exact_order() -> None:
    manifest = load_golden("provider_manifest_30c944f.json")
    contracts = MODEL_TOOL_CATALOG.provider_contracts()

    assert len(MODEL_TOOL_NAMES) == 25
    assert len(set(MODEL_TOOL_NAMES)) == 25
    assert tuple(contract.name for contract in contracts) == MODEL_TOOL_NAMES
    assert canonical_json([contract.payload for contract in contracts]) == canonical_json(
        manifest["tools"]
    )


def test_complete_tool_classification_is_exactly_twenty_five_typed_plus_three_legacy() -> None:
    typed = frozenset(MODEL_TOOL_NAMES)

    assert len(typed) == 25
    assert len(LEGACY_DETERMINISTIC_NAMES) == 3
    assert typed.isdisjoint(LEGACY_DETERMINISTIC_NAMES)
    assert len(typed | LEGACY_DETERMINISTIC_NAMES) == 28
