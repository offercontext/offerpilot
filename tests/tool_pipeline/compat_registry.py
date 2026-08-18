"""Test-only adapter for assertions that predate the typed runtime cutover."""

from __future__ import annotations

import json
from typing import Any, cast

from offerpilot.agent_runtime.journal import NullRunRecorder
from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    ConfirmationRequired,
    ExecutionAuthorization,
    ReadyToExecute,
    ToolFailure,
    ToolSpec,
)
from offerpilot.ai.tool_runtime.pipeline import Rejected, execute_prepared, prepare_call
from offerpilot.ai.tool_runtime.rendering import render_compatibility
from offerpilot.ai.tool_specs.application_events import (
    EVENT_TYPES as EVENT_TYPES,
    application_event_specs,
)
from offerpilot.ai.tool_specs.applications import application_specs
from offerpilot.ai.tool_specs.catalog import MODEL_TOOL_CATALOG, editable_fields_for_tool
from offerpilot.ai.tool_specs.jd_analyses import jd_analysis_specs
from offerpilot.ai.tool_specs.legacy import build_legacy_deterministic_catalog
from offerpilot.ai.tool_specs.notes import note_specs
from offerpilot.ai.tool_specs.offers import OFFER_STATUSES as OFFER_STATUSES, offer_specs
from offerpilot.ai.tool_specs.resumes import resume_specs
from offerpilot.ai.types import ToolCall
from offerpilot.repositories.application_events import ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationsRepository
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.notes import NotesRepository
from offerpilot.repositories.offers import OffersRepository
from offerpilot.repositories.resumes import ResumesRepository


def _context(
    applications: ApplicationsRepository,
    events: ApplicationEventsRepository | None = None,
    notes: NotesRepository | None = None,
    offers: OffersRepository | None = None,
    resumes: ResumesRepository | None = None,
    jd_analyses: JDAnalysesRepository | None = None,
) -> ToolExecutionContext:
    sessions = applications._session_factory
    return ToolExecutionContext(
        applications=applications,
        capabilities=frozenset(ToolCapability),
        current_bindings={},
        events=events or ApplicationEventsRepository(sessions),
        jd_analyses=jd_analyses or JDAnalysesRepository(sessions),
        notes=notes or NotesRepository(sessions),
        offers=offers or OffersRepository(sessions),
        resumes=resumes or ResumesRepository(sessions),
        run_recorder=NullRunRecorder(),
    )


def _entry(spec: ToolSpec[Any, Any], context: ToolExecutionContext) -> dict[str, Any]:
    spec = MODEL_TOOL_CATALOG.resolve(spec.name) or spec
    catalog = ToolCatalog((spec,), expected_names=(spec.name,))

    def validate(args: str) -> str:
        prepared = prepare_call(
            catalog,
            context,
            ToolCall("test-call", spec.name, args),
            pending_identity="test-pending",
            pending_action_revision=1,
        )
        return prepared.failure.compatibility_detail if isinstance(prepared, Rejected) else ""

    def handler(args: str) -> str:
        prepared = prepare_call(
            catalog,
            context,
            ToolCall("test-call", spec.name, args),
            pending_identity="test-pending",
            pending_action_revision=1,
        )
        if isinstance(prepared, Rejected):
            raise ValueError(prepared.failure.compatibility_detail or prepared.failure.code)

        def claim(call: Any) -> ExecutionAuthorization:
            return ExecutionAuthorization(
                pending_identity=call.pending_identity,
                pending_action_revision=cast(int, call.pending_action_revision),
                tool_call_id=call.tool_call_id,
                tool_name=call.spec.name,
                arguments_digest=call.arguments_digest,
            )

        assert isinstance(prepared, (ReadyToExecute, ConfirmationRequired))
        record = execute_prepared(
            prepared.prepared,
            context,
            confirmation_claimer=claim if isinstance(prepared, ConfirmationRequired) else None,
        )
        if isinstance(record.outcome, ToolFailure):
            failure = record.outcome
            raise ValueError(failure.compatibility_detail or failure.code)
        return render_compatibility(spec, record.outcome)

    entry: dict[str, Any] = {
        "write": spec.kind == "write",
        "description": spec.contract.description,
        "schema": dict(spec.contract.parameters),
        "editable_fields": editable_fields_for_tool(spec.name),
        "handler": handler,
    }
    if spec.preflight is not None:
        entry["validate"] = validate
    if spec.confirmation_description is not None:
        entry["describe"] = lambda args: spec.confirmation_description(spec.decoder(json.loads(args)))
    if spec.kind == "write":
        entry["always_confirm"] = True
    return entry


def application_tool_registry(repo: ApplicationsRepository) -> dict[str, dict[str, Any]]:
    context = _context(repo)
    return {spec.name: _entry(spec, context) for spec in application_specs()}


def offerpilot_tool_registry(
    applications: ApplicationsRepository,
    events: ApplicationEventsRepository,
    notes: NotesRepository,
    offers: OffersRepository,
    *,
    resumes: ResumesRepository | None = None,
    jd_analyses: JDAnalysesRepository | None = None,
    application_jd_versions: Any = None,
    application_outcomes: Any = None,
) -> dict[str, dict[str, Any]]:
    context = _context(applications, events, notes, offers, resumes, jd_analyses)
    specs = (
        *application_specs(), *application_event_specs(), *note_specs(), *offer_specs(),
        *(resume_specs() if resumes is not None else ()),
        *(jd_analysis_specs() if jd_analyses is not None else ()),
    )
    result = {spec.name: _entry(spec, context) for spec in specs}
    if application_jd_versions is not None:
        if application_outcomes is None:
            result.update(application_jd_version_tool_registry(application_jd_versions))
        else:
            legacy = build_legacy_deterministic_catalog(application_jd_versions, application_outcomes)
            for name in ("save_application_jd_version", "create_application_submission_snapshot", "record_application_outcome"):
                adapter = legacy.resolve_server_loaded(type("Pending", (), {"tool_name": name})())
                assert adapter is not None
                result[name] = _legacy_entry(adapter)
    return result


def application_jd_version_tool_registry(service: Any) -> dict[str, dict[str, Any]]:
    class UnusedOutcomes:
        pass

    catalog = build_legacy_deterministic_catalog(service, cast(Any, UnusedOutcomes()))
    pending = type("Pending", (), {"tool_name": "save_application_jd_version"})()
    adapter = catalog.resolve_server_loaded(pending)
    assert adapter is not None
    return {adapter.name: _legacy_entry(adapter)}


def _legacy_entry(adapter: Any) -> dict[str, Any]:
    entry = {
        "write": True,
        "model_visible": False,
        "always_confirm": True,
        "editable_fields": [dict(field) for field in adapter.editable_fields],
        "validate": adapter.validate,
        "describe": adapter.describe,
        "handler": adapter.execute,
    }
    if adapter.name == "save_application_jd_version":
        entry.update(
            {
                "description": (
                    "Save the user's job description to the selected application after explicit confirmation. "
                    "Never fetch the source URL and never create downstream records."
                ),
                "schema": {
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "integer"},
                        "jd_text": {"type": "string"},
                        "source_url": {"type": ["string", "null"]},
                        "expected_current_version_id": {
                            "type": ["integer", "null"],
                            "description": (
                                "The currently saved JD version id for this application, or null when none exists."
                            ),
                        },
                        "idempotency_key": {
                            "type": "string",
                            "minLength": 16,
                            "maxLength": 128,
                            "pattern": r"^[A-Za-z0-9_-]{16,128}$",
                            "description": (
                                "A new unique idempotency key, 16-128 ASCII letters, digits, underscores, or hyphens."
                            ),
                        },
                    },
                    "required": [
                        "application_id",
                        "jd_text",
                        "expected_current_version_id",
                        "idempotency_key",
                    ],
                    "additionalProperties": False,
                },
            }
        )
    return entry
