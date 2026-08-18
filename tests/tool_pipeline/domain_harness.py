from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.agent_runtime.journal import NullRunRecorder
from offerpilot.ai.tool_runtime.catalog import ToolCatalog
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    ConfirmationRequired,
    ExecutionAuthorization,
    ReadyToExecute,
    ToolSpec,
)
from offerpilot.ai.tool_runtime.pipeline import Rejected, execute_prepared, prepare_call
from offerpilot.ai.tool_runtime.rendering import render_compatibility
from offerpilot.ai.types import ToolCall
from offerpilot.db import init_database
from offerpilot.models import Application, ApplicationEvent, InterviewNote, JDAnalysis, Offer, Resume
from offerpilot.repositories.application_events import ApplicationEventCreate, ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.jd import JDAnalysesRepository, JDAnalysisCreate
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.repositories.resumes import ResumeCreate, ResumeMatchCreate, ResumesRepository


DYNAMIC_TIME_FIELD = re.compile(
    r'("(?:created_at|updated_at|applied_at|closed_at|deleted_at|first_pending_at|'
    r'first_applied_at|first_written_test_at|first_interview_at|first_offer_at)":\s*)"[^"]*"'
)
MODEL_BY_TABLE = {
    "applications": Application,
    "application_events": ApplicationEvent,
    "interview_notes": InterviewNote,
    "offers": Offer,
    "resumes": Resume,
    "jd_analyses": JDAnalysis,
}


@dataclass
class Harness:
    context: ToolExecutionContext
    session_factory: sessionmaker[Session]

    def close(self) -> None:
        self.session_factory.kw["bind"].dispose()


def normalize_visible(value: str) -> str:
    return DYNAMIC_TIME_FIELD.sub(r'\1"<timestamp>"', value)


def build_harness(path: Path, tool_name: str, case: str) -> Harness:
    mode = "full"
    closed = False
    deleted_resume = False
    if tool_name == "create_application" and case in {
        "success",
        "invalid_application_status",
        "closed_application_without_reason",
    }:
        mode = "empty"
    elif tool_name == "create_application_event" and case == "success":
        mode = "without_event"
    elif tool_name == "add_note" and case == "success":
        mode = "without_note"
    if case == "closed_application_cannot_reopen":
        closed = True
    if case == "deleted_resume":
        deleted_resume = True

    session_factory = init_database(path)
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    jd_analyses = JDAnalysesRepository(session_factory)
    if mode != "empty":
        app = applications.create(
            ApplicationCreate(
                company_name="Alpha",
                position_name="Platform Engineer",
                status="closed" if closed else "applied",
                closed_reason="position filled" if closed else "",
            )
        )
        if mode != "without_event":
            events.create(
                ApplicationEventCreate(
                    application_id=app.id,
                    event_type="interview",
                    scheduled_at=datetime(2026, 8, 19, 9, tzinfo=timezone.utc),
                    duration_minutes=30,
                )
            )
        if mode != "without_note":
            notes.create(
                NoteCreate(
                    application_id=app.id,
                    company=app.company_name,
                    position=app.position_name,
                    date="2026-08-18",
                    questions="Q0",
                )
            )
        offers.create(
            OfferCreate(
                application_id=app.id,
                company_name=app.company_name,
                position_name=app.position_name,
                base_monthly=25000,
                months_per_year=14,
            )
        )
        resume = resumes.create(
            ResumeCreate(
                title="Synthetic Resume",
                source="manual",
                content_json={
                    "career_intent": {"target_roles": []},
                    "experience": [
                        {"company": "Synthetic Co", "highlights": ["Built APIs"]}
                    ],
                },
            )
        )
        resumes.create_match(
            ResumeMatchCreate(
                resume_id=resume.id,
                application_id=app.id,
                jd_text="Synthetic backend role",
                result='{"match_score":88}',
            )
        )
        jd_analyses.create(
            JDAnalysisCreate(
                application_id=app.id,
                jd_source="manual",
                jd_text="Synthetic backend engineer",
                result='{"summary":"Synthetic role"}',
            )
        )
        if deleted_resume:
            resumes.delete(resume.id)

    capabilities = frozenset(ToolCapability)
    context = ToolExecutionContext(
        applications=applications,
        capabilities=capabilities,
        current_bindings={},
        events=events,
        jd_analyses=jd_analyses,
        notes=notes,
        offers=offers,
        resumes=resumes,
        run_recorder=cast(Any, NullRunRecorder()),
    )
    return Harness(context=context, session_factory=session_factory)


def execute_case(
    specs: tuple[ToolSpec[Any, Any], ...],
    case: dict[str, Any],
    path: Path,
) -> tuple[str, dict[str, Any]]:
    harness = build_harness(path, case["tool_name"], case["case"])
    try:
        catalog = ToolCatalog(specs, expected_names=tuple(spec.name for spec in specs))
        spec = cast(ToolSpec[Any, Any], catalog.resolve(case["tool_name"]))
        prepared = prepare_call(
            catalog,
            harness.context,
            ToolCall(
                id="golden-call",
                name=case["tool_name"],
                args=_canonical_arguments(case["arguments"]),
            ),
            pending_action_revision=1,
            pending_identity="golden-pending",
        )
        if isinstance(prepared, Rejected):
            visible = render_compatibility(spec, prepared.failure)
        else:
            assert isinstance(prepared, (ReadyToExecute, ConfirmationRequired))

            def claim(call: Any) -> ExecutionAuthorization:
                return ExecutionAuthorization(
                    arguments_digest=call.arguments_digest,
                    pending_action_revision=1,
                    pending_identity="golden-pending",
                    tool_call_id="golden-call",
                    tool_name=spec.name,
                )

            record = execute_prepared(
                prepared.prepared,
                harness.context,
                confirmation_claimer=claim if isinstance(prepared, ConfirmationRequired) else None,
            )
            visible = render_compatibility(spec, record.outcome)
        projection: dict[str, Any] = {}
        expected_projection = case["business_projection"]
        if expected_projection:
            table = expected_projection["table"]
            model = MODEL_BY_TABLE[table]
            with harness.session_factory() as session:
                projection = {
                    "table": table,
                    "row_count": int(
                        session.scalar(select(func.count()).select_from(model)) or 0
                    ),
                }
        return normalize_visible(visible), projection
    finally:
        harness.close()


def _canonical_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
