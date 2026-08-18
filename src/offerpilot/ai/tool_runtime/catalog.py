from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from offerpilot.ai.tool_runtime.contracts import (
    FailureCategory,
    ProviderToolContract,
    ToolSpec,
)
from offerpilot.ai.tool_runtime.validation import compile_tool_schema


_FAILURE_CATEGORIES: frozenset[str] = frozenset(
    {
        "validation_error",
        "permission_denied",
        "confirmation_rejected",
        "stale_state",
        "conflict",
        "not_found",
        "provider_error",
        "internal_error",
    }
)


class ToolCatalog:
    def __init__(
        self,
        specs: Sequence[ToolSpec[Any, Any]],
        *,
        expected_names: Sequence[str],
    ) -> None:
        ordered = tuple(specs)
        names = tuple(spec.name for spec in ordered)
        if names != tuple(expected_names) or len(set(names)) != len(names):
            raise ValueError("tool catalog names/order mismatch")
        for spec in ordered:
            self._validate_spec(spec)
        self._ordered = ordered
        self._specs = {spec.name: spec for spec in ordered}
        self._validators = {
            spec.name: compile_tool_schema(spec.contract.parameters) for spec in ordered
        }

    @staticmethod
    def _validate_spec(spec: ToolSpec[Any, Any]) -> None:
        if spec.kind == "read" and spec.confirmation_policy != "none":
            raise ValueError("read tool cannot require confirmation")
        if spec.kind == "write" and spec.confirmation_policy != "required":
            raise ValueError("write tool must require confirmation")
        if not set(spec.declared_failure_categories).issubset(_FAILURE_CATEGORIES):
            raise ValueError("tool declares unsupported failure category")
        for mapping in spec.exception_map:
            category: FailureCategory = mapping.category
            if category not in spec.declared_failure_categories:
                raise ValueError("exception mapping category is not declared")

    def resolve(self, name: str) -> ToolSpec[Any, Any] | None:
        return self._specs.get(name)

    def validator_for(self, name: str) -> Draft202012Validator:
        return self._validators[name]

    def provider_contracts(self) -> tuple[ProviderToolContract, ...]:
        return tuple(spec.contract for spec in self._ordered)

    def write_names(self) -> frozenset[str]:
        return frozenset(spec.name for spec in self._ordered if spec.kind == "write")
