from __future__ import annotations

import pickle
from typing import Any, cast

import pytest

from offerpilot.ai.tool_runtime.context import (
    UNAVAILABLE,
    ToolCapability,
    ToolExecutionContext,
    aggregate_binding,
    evaluate_context,
)
from offerpilot.ai.tool_runtime.contracts import (
    BindingAudit,
    BindingTarget,
    ProviderToolContract,
    ToolFailure,
    ToolSpec,
)


class RepositorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, record_id: int) -> object:
        self.calls += 1
        return {"id": record_id}


class BindingResolverSpy:
    def __init__(self, identity: int | str | object) -> None:
        self.calls = 0
        self.identity = identity

    def __call__(self, args: dict[str, Any], context: ToolExecutionContext) -> BindingTarget:
        self.calls += 1
        context.applications.get(int(args["application_id"]))
        if self.identity is UNAVAILABLE:
            return BindingTarget(entity_kind="application", identity=None, available=False)
        return BindingTarget(
            entity_kind="application",
            identity=cast(int | str, self.identity),
            available=True,
        )


def _spec(resolver: BindingResolverSpy) -> ToolSpec[dict[str, Any], dict[str, Any]]:
    parameters = {
        "properties": {"application_id": {"type": "integer"}},
        "required": ["application_id"],
        "type": "object",
    }
    return ToolSpec(
        binding_resolvers=(resolver,),
        contract=ProviderToolContract(
            payload={
                "type": "function",
                "function": {
                    "description": "read one application",
                    "name": "read_application",
                    "parameters": parameters,
                },
            },
            name="read_application",
            description="read one application",
            parameters=parameters,
        ),
        decoder=lambda values: dict(values),
        executor=lambda args, context: args,
        kind="read",
        required_capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
    )


def _context(
    repository: RepositorySpy,
    *,
    capabilities: frozenset[ToolCapability],
    current_bindings: dict[str, int | str] | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        applications=cast(Any, repository),
        capabilities=capabilities,
        current_bindings=current_bindings or {},
        events=cast(Any, object()),
        jd_analyses=cast(Any, object()),
        notes=cast(Any, object()),
        offers=cast(Any, object()),
        resumes=cast(Any, object()),
        run_recorder=cast(Any, object()),
    )


def test_missing_capability_short_circuits_before_binding_and_repository() -> None:
    repository = RepositorySpy()
    resolver = BindingResolverSpy(7)
    context = _context(repository, capabilities=frozenset())

    outcome = evaluate_context(_spec(resolver), {"application_id": 7}, context)

    assert outcome == ToolFailure(
        category="permission_denied",
        code="missing_capability",
        compatibility_detail="permission denied",
    )
    assert resolver.calls == 0
    assert repository.calls == 0


@pytest.mark.parametrize(
    ("current", "targets", "expected"),
    (
        (None, [], "unbound"),
        (7, [], "unavailable"),
        (7, [7, 7], "matched"),
        (7, [7, 9], "mismatched"),
        (7, [7, UNAVAILABLE], "unavailable"),
        (7, [9, UNAVAILABLE], "mismatched"),
    ),
)
def test_binding_aggregation_has_fixed_precedence(
    current: int | None,
    targets: list[int | object],
    expected: str,
) -> None:
    assert aggregate_binding(current, targets) == expected


def test_binding_is_audit_only_and_contains_no_entity_id() -> None:
    repository = RepositorySpy()
    resolver = BindingResolverSpy(9)
    context = _context(
        repository,
        capabilities=frozenset({ToolCapability.APPLICATIONS_READ}),
        current_bindings={"application": 7},
    )
    arguments = {"application_id": 9, "extra": "preserved"}

    audit = evaluate_context(_spec(resolver), arguments, context)

    assert audit == BindingAudit(
        status="mismatched",
        target_count=1,
        entity_kinds=("application",),
    )
    assert arguments == {"application_id": 9, "extra": "preserved"}
    assert "7" not in repr(audit)
    assert "9" not in repr(audit)
    assert resolver.calls == 1
    assert repository.calls == 1


def test_tool_execution_context_is_transient_and_hides_dependencies() -> None:
    repository = RepositorySpy()
    context = _context(repository, capabilities=frozenset())

    with pytest.raises(TypeError, match="transient tool runtime value"):
        pickle.dumps(context)
    assert "RepositorySpy" not in repr(context)
