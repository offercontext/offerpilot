from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from offerpilot.agent_runtime.journal import RunRecorder
from offerpilot.ai.tool_runtime.contracts import (
    BindingAudit,
    BindingStatus,
    BindingTarget,
    ToolFailure,
    ToolSpec,
    TransientToolRuntimeValue,
)
from offerpilot.repositories.application_events import ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationsRepository
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.notes import NotesRepository
from offerpilot.repositories.offers import OffersRepository
from offerpilot.repositories.resumes import ResumesRepository


class ToolCapability(str, Enum):
    APPLICATIONS_READ = "applications.read"
    APPLICATIONS_WRITE = "applications.write"
    APPLICATION_EVENTS_READ = "application_events.read"
    APPLICATION_EVENTS_WRITE = "application_events.write"
    NOTES_READ = "notes.read"
    NOTES_WRITE = "notes.write"
    OFFERS_READ = "offers.read"
    OFFERS_WRITE = "offers.write"
    RESUMES_READ = "resumes.read"
    RESUMES_WRITE = "resumes.write"
    JD_ANALYSES_READ = "jd_analyses.read"

    def __str__(self) -> str:
        return self.value


class _UnavailableBindingTarget:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNAVAILABLE"


UNAVAILABLE = _UnavailableBindingTarget()
BindingIdentity = int | str | _UnavailableBindingTarget


@dataclass(frozen=True)
class ToolExecutionContext(TransientToolRuntimeValue):
    capabilities: frozenset[ToolCapability]
    current_bindings: Mapping[str, int | str] = field(repr=False)
    applications: ApplicationsRepository = field(repr=False)
    events: ApplicationEventsRepository = field(repr=False)
    notes: NotesRepository = field(repr=False)
    offers: OffersRepository = field(repr=False)
    resumes: ResumesRepository = field(repr=False)
    jd_analyses: JDAnalysesRepository = field(repr=False)
    run_recorder: RunRecorder = field(repr=False, compare=False)


def aggregate_binding(
    current: int | str | None,
    targets: Sequence[BindingIdentity | object],
) -> BindingStatus:
    if current is None:
        return "unbound"
    if not targets:
        return "unavailable"
    if any(target is not UNAVAILABLE and target != current for target in targets):
        return "mismatched"
    if any(target is UNAVAILABLE for target in targets):
        return "unavailable"
    return "matched"


ArgsT = TypeVar("ArgsT")


def evaluate_context(
    spec: ToolSpec[ArgsT, Any],
    typed_args: ArgsT,
    context: ToolExecutionContext,
) -> BindingAudit | ToolFailure:
    permission = require_capabilities(spec, context)
    if permission is not None:
        return permission
    return audit_bindings(spec, typed_args, context)


def require_capabilities(
    spec: ToolSpec[Any, Any],
    context: ToolExecutionContext,
) -> ToolFailure | None:
    if spec.required_capabilities.issubset(context.capabilities):
        return None
    return ToolFailure(
        category="permission_denied",
        code="missing_capability",
        compatibility_detail="permission denied",
    )


def audit_bindings(
    spec: ToolSpec[ArgsT, Any],
    typed_args: ArgsT,
    context: ToolExecutionContext,
) -> BindingAudit:
    targets = tuple(resolver(typed_args, context) for resolver in spec.binding_resolvers)
    if not targets:
        status: BindingStatus = "unbound" if not context.current_bindings else "unavailable"
        return BindingAudit(status=status, target_count=0)

    statuses = _binding_statuses(targets, context.current_bindings)
    status = _aggregate_statuses(statuses)
    return BindingAudit(
        status=status,
        target_count=len(targets),
        entity_kinds=tuple(sorted({target.entity_kind for target in targets})),
    )


def _binding_statuses(
    targets: tuple[BindingTarget, ...],
    current_bindings: Mapping[str, int | str],
) -> tuple[BindingStatus, ...]:
    grouped: dict[str, list[BindingIdentity]] = {}
    for target in targets:
        if target.available:
            if target.identity is None:
                raise ValueError("available binding target is missing identity")
            identity: BindingIdentity = target.identity
        else:
            identity = UNAVAILABLE
        grouped.setdefault(target.entity_kind, []).append(identity)
    return tuple(
        aggregate_binding(current_bindings.get(entity_kind), identities)
        for entity_kind, identities in grouped.items()
    )


def _aggregate_statuses(statuses: Sequence[BindingStatus]) -> BindingStatus:
    for status in ("mismatched", "unavailable", "unbound", "matched"):
        if status in statuses:
            return status
    return "unavailable"
