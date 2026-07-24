from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.interview_preparation_proposals import (
    InterviewPreparationModelError,
    generate_interview_preparation_proposal,
)
from offerpilot.models import (
    Application,
    ApplicationEvent,
    InterviewPreparationProposal,
    KnowledgeEvidence,
    KnowledgeNote,
    KnowledgeNoteEvidence,
    KnowledgeNoteVersion,
    KnowledgeSource,
    Resume,
)
from offerpilot.repositories.json_contract import canonical_json, parse_json_object, sha256_text


LEASE_SECONDS = 30
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class InterviewPreparationNotFound(Exception):
    def __init__(self, code: str = "interview_preparation_application_not_found") -> None:
        super().__init__(code)
        self.code = code


class InterviewPreparationValidationError(ValueError):
    def __init__(self, message: str, code: str = "interview_preparation_invalid_request") -> None:
        super().__init__(message)
        self.code = code


class InterviewPreparationConflictError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class InterviewPreparationProviderError(RuntimeError):
    code = "interview_preparation_provider_error"


@dataclass
class InterviewPreparationGenerationResult:
    proposal: InterviewPreparationProposal | None
    created: bool
    pending: bool
    attempt_status: str


class InterviewPreparationProposalsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_generated(
        self,
        *,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        knowledge_selections: list[dict[str, Any]],
        user_assertions: list[str],
        idempotency_key: str,
        model: ChatModel | None,
        on_diagnostic: Any | None = None,
    ) -> InterviewPreparationGenerationResult:
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise InterviewPreparationValidationError(
                "idempotency_key must be 16-128 ASCII characters",
                "interview_preparation_invalid_request",
            )
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            snapshot = _build_snapshot(
                session,
                application_id=application_id,
                event_id=event_id,
                resume_id=resume_id,
                jd_text=jd_text,
                knowledge_selections=knowledge_selections,
                user_assertions=user_assertions,
            )
            fingerprint = sha256_text(canonical_json(snapshot))
            existing = _find_by_key(session, application_id, event_id, idempotency_key)
            if existing is not None:
                result = self._handle_existing(
                    session,
                    existing,
                    fingerprint=fingerprint,
                    snapshot=snapshot,
                    model=model,
                    application_id=application_id,
                    event_id=event_id,
                    resume_id=resume_id,
                    jd_text=jd_text,
                    knowledge_selections=knowledge_selections,
                    user_assertions=user_assertions,
                    idempotency_key=idempotency_key,
                    on_diagnostic=on_diagnostic,
                )
                if result is None:
                    raise InterviewPreparationProviderError()
                return result

            token = uuid4().hex
            row = InterviewPreparationProposal(
                application_id=application_id,
                application_event_id=event_id,
                resume_id=resume_id,
                idempotency_key=idempotency_key,
                attempt_status="generating",
                generation_revision=1,
                provider_call_token=token,
                provider_lease_until=_lease_until(),
                input_snapshot_json=canonical_json(snapshot),
                source_fingerprint=fingerprint,
            )
            session.add(row)
            session.commit()
            owner_revision = 1
            owner_token = token

        return self._call_and_store(
            model=model,
            owner_revision=owner_revision,
            owner_token=owner_token,
            application_id=application_id,
            event_id=event_id,
            resume_id=resume_id,
            jd_text=jd_text,
            knowledge_selections=knowledge_selections,
            user_assertions=user_assertions,
            idempotency_key=idempotency_key,
            source_fingerprint=fingerprint,
            snapshot=snapshot,
            on_diagnostic=on_diagnostic,
        )

    def preflight(
        self,
        *,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        knowledge_selections: List[dict[str, Any]],
        user_assertions: List[str],
        idempotency_key: str,
    ) -> InterviewPreparationGenerationResult | None:
        """Return a replayable attempt without resolving the AI provider.

        A ready result and an unexpired lease are safe to return before provider
        configuration is loaded.  ``None`` means a new row or an expired lease
        needs a provider call, so the caller must resolve the provider before
        invoking ``create_generated``.
        """
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise InterviewPreparationValidationError(
                "idempotency_key must be 16-128 ASCII characters",
                "interview_preparation_invalid_request",
            )
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            snapshot = _build_snapshot(
                session,
                application_id=application_id,
                event_id=event_id,
                resume_id=resume_id,
                jd_text=jd_text,
                knowledge_selections=knowledge_selections,
                user_assertions=user_assertions,
            )
            fingerprint = sha256_text(canonical_json(snapshot))
            existing = _find_by_key(session, application_id, event_id, idempotency_key)
            if existing is None:
                session.commit()
                return None
            result = self._handle_existing(
                session,
                existing,
                fingerprint=fingerprint,
                snapshot=snapshot,
                model=None,
                application_id=application_id,
                event_id=event_id,
                resume_id=resume_id,
                jd_text=jd_text,
                knowledge_selections=knowledge_selections,
                user_assertions=user_assertions,
                idempotency_key=idempotency_key,
                on_diagnostic=None,
            )
            return result

    def list(self, application_id: int) -> list[InterviewPreparationProposal]:
        with self._session_factory() as session:
            _require_visible_application(session, application_id)
            rows = list(
                session.scalars(
                    select(InterviewPreparationProposal)
                    .where(InterviewPreparationProposal.application_id == application_id)
                    .where(InterviewPreparationProposal.attempt_status == "ready")
                    .order_by(
                        InterviewPreparationProposal.created_at.desc(),
                        InterviewPreparationProposal.id.desc(),
                    )
                )
            )
            for row in rows:
                _set_source_status(session, row)
            return rows

    def get(self, application_id: int, proposal_id: int) -> InterviewPreparationProposal | None:
        with self._session_factory() as session:
            _require_visible_application(session, application_id)
            row = session.scalar(
                select(InterviewPreparationProposal)
                .where(InterviewPreparationProposal.application_id == application_id)
                .where(InterviewPreparationProposal.id == proposal_id)
                .where(InterviewPreparationProposal.attempt_status == "ready")
            )
            if row is not None:
                _set_source_status(session, row)
            return row

    def _handle_existing(
        self,
        session: Session,
        row: InterviewPreparationProposal,
        *,
        fingerprint: str,
        snapshot: dict[str, Any],
        model: ChatModel | None,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        knowledge_selections: List[dict[str, Any]],
        user_assertions: List[str],
        idempotency_key: str,
        on_diagnostic: Any | None,
    ) -> InterviewPreparationGenerationResult | None:
        if row.attempt_status == "invalidated":
            raise InterviewPreparationConflictError(
                "interview preparation attempt was invalidated",
                "interview_preparation_attempt_invalidated",
            )
        if row.source_fingerprint != fingerprint:
            if row.attempt_status in {"generating", "provider_unknown"}:
                row.attempt_status = "invalidated"
                row.invalidation_reason = "idempotency_conflict"
                row.provider_call_token = ""
                row.provider_lease_until = None
                session.commit()
            raise InterviewPreparationConflictError(
                "interview preparation idempotency key has a different snapshot",
                "interview_preparation_idempotency_conflict",
            )
        if row.attempt_status == "ready":
            _set_source_status(session, row)
            return InterviewPreparationGenerationResult(row, False, False, "ready")

        lease_until = _as_aware(row.provider_lease_until)
        if lease_until is not None and lease_until > datetime.now(timezone.utc):
            return InterviewPreparationGenerationResult(row, False, True, row.attempt_status)

        if model is None:
            session.commit()
            return None

        old_revision = row.generation_revision
        old_token = row.provider_call_token
        new_token = uuid4().hex
        result = session.execute(
            update(InterviewPreparationProposal)
            .where(InterviewPreparationProposal.id == row.id)
            .where(InterviewPreparationProposal.attempt_status.in_(["generating", "provider_unknown"]))
            .where(InterviewPreparationProposal.generation_revision == old_revision)
            .where(InterviewPreparationProposal.provider_call_token == old_token)
            .where(InterviewPreparationProposal.provider_lease_until <= _db_now())
            .values(
                attempt_status="generating",
                generation_revision=old_revision + 1,
                provider_call_token=new_token,
                provider_lease_until=_lease_until(),
                invalidation_reason="",
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            session.commit()
            refreshed = session.get(InterviewPreparationProposal, row.id)
            if refreshed is None:
                raise InterviewPreparationConflictError(
                    "interview preparation attempt disappeared",
                    "interview_preparation_idempotency_conflict",
                )
            return InterviewPreparationGenerationResult(
                refreshed,
                False,
                True,
                refreshed.attempt_status,
            )
        session.commit()
        return self._call_and_store(
            model=model,
            owner_revision=old_revision + 1,
            owner_token=new_token,
            application_id=application_id,
            event_id=event_id,
            resume_id=resume_id,
            jd_text=jd_text,
            knowledge_selections=knowledge_selections,
            user_assertions=user_assertions,
            idempotency_key=idempotency_key,
            source_fingerprint=fingerprint,
            snapshot=snapshot,
            on_diagnostic=on_diagnostic,
        )

    def _call_and_store(
        self,
        *,
        model: ChatModel | None,
        owner_revision: int,
        owner_token: str,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        knowledge_selections: List[dict[str, Any]],
        user_assertions: List[str],
        idempotency_key: str,
        source_fingerprint: str,
        snapshot: dict[str, Any],
        on_diagnostic: Any | None,
    ) -> InterviewPreparationGenerationResult:
        if model is None:
            raise InterviewPreparationProviderError()
        try:
            proposal = generate_interview_preparation_proposal(
                model,
                snapshot,
                on_diagnostic=on_diagnostic,
            )
        except InterviewPreparationModelError as exc:
            if exc.failure_category != "provider_error":
                raise
            self._mark_provider_unknown(
                application_id, event_id, idempotency_key, owner_revision, owner_token
            )
            raise InterviewPreparationProviderError() from exc

        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = _find_by_key(session, application_id, event_id, idempotency_key)
            if row is None:
                session.rollback()
                raise InterviewPreparationConflictError(
                    "interview preparation attempt disappeared",
                    "interview_preparation_idempotency_conflict",
                )
            current_snapshot = _build_snapshot(
                session,
                application_id=application_id,
                event_id=event_id,
                resume_id=resume_id,
                jd_text=jd_text,
                knowledge_selections=knowledge_selections,
                user_assertions=user_assertions,
            )
            current_fingerprint = sha256_text(canonical_json(current_snapshot))
            if current_fingerprint != source_fingerprint:
                row.attempt_status = "invalidated"
                row.invalidation_reason = "source_conflict"
                row.provider_call_token = ""
                row.provider_lease_until = None
                session.commit()
                raise InterviewPreparationConflictError(
                    "interview preparation source changed",
                    "interview_preparation_source_conflict",
                )
            if (
                row.attempt_status != "generating"
                or row.generation_revision != owner_revision
                or row.provider_call_token != owner_token
                or (_as_aware(row.provider_lease_until) or datetime.min.replace(tzinfo=timezone.utc))
                <= datetime.now(timezone.utc)
            ):
                session.commit()
                if row.attempt_status == "ready":
                    return InterviewPreparationGenerationResult(row, False, False, "ready")
                return InterviewPreparationGenerationResult(row, False, True, row.attempt_status)
            proposal_json = canonical_json(proposal)
            row.proposal_json = proposal_json
            row.proposal_hash = sha256_text(proposal_json)
            row.proposal_status = (
                "safe_empty"
                if all(not proposal[field] for field in ("preparation_directions", "story_prompts", "review_points", "interviewer_questions", "items_to_clarify"))
                else "normal"
            )
            row.attempt_status = "ready"
            row.provider_call_token = ""
            row.provider_lease_until = None
            session.commit()
            _set_source_status(session, row)
            return InterviewPreparationGenerationResult(row, True, False, "ready")

    def _mark_provider_unknown(
        self,
        application_id: int,
        event_id: int,
        idempotency_key: str,
        revision: int,
        token: str,
    ) -> None:
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            result = session.execute(
                update(InterviewPreparationProposal)
                .where(InterviewPreparationProposal.application_id == application_id)
                .where(InterviewPreparationProposal.application_event_id == event_id)
                .where(InterviewPreparationProposal.idempotency_key == idempotency_key)
                .where(InterviewPreparationProposal.attempt_status == "generating")
                .where(InterviewPreparationProposal.generation_revision == revision)
                .where(InterviewPreparationProposal.provider_call_token == token)
                .values(attempt_status="provider_unknown")
            )
            session.commit()
            if getattr(result, "rowcount", 0) != 1:
                return


def _build_snapshot(
    session: Session,
    *,
    application_id: int,
    event_id: int,
    resume_id: int,
    jd_text: str,
    knowledge_selections: list[dict[str, Any]],
    user_assertions: list[str],
) -> dict[str, Any]:
    _require_visible_application(session, application_id)
    event = session.scalar(
        select(ApplicationEvent)
        .where(ApplicationEvent.id == event_id)
        .where(ApplicationEvent.application_id == application_id)
    )
    if event is None or event.event_type != "interview":
        raise InterviewPreparationValidationError(
            "interview event is invalid", "interview_preparation_event_invalid"
        )
    resume = session.get(Resume, resume_id)
    if resume is None or resume.deleted_at is not None:
        raise InterviewPreparationNotFound("interview_preparation_resume_not_found")
    if not isinstance(jd_text, str) or not jd_text.strip():
        raise InterviewPreparationValidationError(
            "JD is required", "interview_preparation_jd_required"
        )
    if len(jd_text.encode("utf-8")) > 60_000:
        raise InterviewPreparationValidationError(
            "JD is too large", "interview_preparation_input_too_large"
        )
    if not isinstance(knowledge_selections, list):
        raise InterviewPreparationValidationError(
            "Knowledge selections must be an array", "interview_preparation_invalid_request"
        )
    if not isinstance(user_assertions, list) or any(not isinstance(item, str) for item in user_assertions):
        raise InterviewPreparationValidationError(
            "user_assertions must be an array of strings", "interview_preparation_invalid_request"
        )
    normalized_assertions = [item for item in user_assertions if item.strip()]
    if len(normalized_assertions) > 10 or any(len(item) > 500 for item in normalized_assertions):
        raise InterviewPreparationValidationError(
            "user_assertions is too large", "interview_preparation_input_too_large"
        )
    try:
        content_json = parse_json_object("resume", resume.content_json)
    except Exception as exc:
        raise InterviewPreparationValidationError(
            "Resume content is invalid", "interview_preparation_resume_not_found"
        ) from exc
    if len(canonical_json(content_json).encode("utf-8")) > 200_000:
        raise InterviewPreparationValidationError(
            "Resume content is too large", "interview_preparation_input_too_large"
        )
    canonical_knowledge = _validate_knowledge_selections(session, knowledge_selections)
    return {
        "event": {
            "id": event.id,
            "application_id": event.application_id,
            "event_type": event.event_type,
            "subtype": event.subtype,
            "round": event.round,
            "scheduled_at": event.scheduled_at.isoformat() if event.scheduled_at else None,
            "duration_minutes": event.duration_minutes,
            "status": event.status,
        },
        "jd": {"text": jd_text},
        "resume": {"id": resume.id, "content_json": content_json},
        "knowledge_evidence": canonical_knowledge,
        "user_assertions": normalized_assertions,
    }


def _validate_knowledge_selections(
    session: Session, selections: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(selections) > 5:
        raise InterviewPreparationValidationError(
            "Too many Knowledge Note selections", "interview_preparation_input_too_large"
        )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for selection in selections:
        if set(selection) != {"note_version_id", "evidence_ids"}:
            raise InterviewPreparationValidationError(
                "Knowledge selection shape is invalid",
                "interview_preparation_knowledge_selection_invalid",
            )
        version_id = selection.get("note_version_id")
        evidence_ids = selection.get("evidence_ids")
        if not isinstance(version_id, int) or isinstance(version_id, bool) or not isinstance(evidence_ids, list):
            raise InterviewPreparationValidationError(
                "Knowledge selection shape is invalid",
                "interview_preparation_knowledge_selection_invalid",
            )
        version = session.scalar(
            select(KnowledgeNoteVersion)
            .join(KnowledgeNote, KnowledgeNote.id == KnowledgeNoteVersion.note_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeNoteVersion.source_id)
            .where(KnowledgeNoteVersion.id == version_id)
            .where(KnowledgeNote.current_version_id == version_id)
            .where(KnowledgeNote.archived_at.is_(None))
            .where(KnowledgeSource.deleted_at.is_(None))
            .where(KnowledgeSource.lifecycle != "deleting")
        )
        if version is None:
            raise InterviewPreparationValidationError(
                "Knowledge Note Version is unavailable",
                "interview_preparation_knowledge_selection_invalid",
            )
        if len(evidence_ids) > 20 or any(
            not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen
            for evidence_id in evidence_ids
        ):
            raise InterviewPreparationValidationError(
                "Knowledge Evidence selection is invalid",
                "interview_preparation_knowledge_selection_invalid",
            )
        total += len(evidence_ids)
        if total > 20:
            raise InterviewPreparationValidationError(
                "Too many Knowledge Evidence selections",
                "interview_preparation_input_too_large",
            )
        evidence_rows = list(
            session.scalars(
                select(KnowledgeEvidence)
                .join(KnowledgeNoteEvidence, KnowledgeNoteEvidence.evidence_id == KnowledgeEvidence.id)
                .where(KnowledgeNoteEvidence.note_version_id == version_id)
                .where(KnowledgeEvidence.id.in_(evidence_ids))
            )
        )
        by_id = {row.id: row for row in evidence_rows}
        if len(by_id) != len(evidence_ids):
            raise InterviewPreparationValidationError(
                "Knowledge Evidence is not part of the selected version",
                "interview_preparation_knowledge_selection_invalid",
            )
        for evidence_id in evidence_ids:
            seen.add(evidence_id)
            row = by_id[evidence_id]
            result.append(
                {
                    "id": row.id,
                    "note_version_id": version_id,
                    "path": f"/{row.id}",
                    "excerpt": row.canonical_excerpt,
                }
            )
    return result


def _find_by_key(
    session: Session, application_id: int, event_id: int, idempotency_key: str
) -> InterviewPreparationProposal | None:
    return session.scalar(
        select(InterviewPreparationProposal)
        .where(InterviewPreparationProposal.application_id == application_id)
        .where(InterviewPreparationProposal.application_event_id == event_id)
        .where(InterviewPreparationProposal.idempotency_key == idempotency_key)
    )


def _require_visible_application(session: Session, application_id: int) -> Application:
    application = session.scalar(
        select(Application)
        .where(Application.id == application_id)
        .where(Application.deleted_at.is_(None))
    )
    if application is None:
        raise InterviewPreparationNotFound()
    return application


def _set_source_status(session: Session, row: InterviewPreparationProposal) -> None:
    states = {
        "event": "source_changed",
        "resume": "source_changed",
        "jd": "not_checked",
        "knowledge": "current",
    }
    try:
        snapshot = json.loads(row.input_snapshot_json)
        event_id = snapshot["event"]["id"]
        resume_id = snapshot["resume"]["id"]
        event = session.scalar(
            select(ApplicationEvent)
            .where(ApplicationEvent.id == event_id)
            .where(ApplicationEvent.application_id == row.application_id)
        )
        event_snapshot = snapshot["event"]
        if (
            event is not None
            and event.event_type == event_snapshot.get("event_type")
            and event.subtype == event_snapshot.get("subtype")
            and event.round == event_snapshot.get("round")
            and (event.scheduled_at.isoformat() if event.scheduled_at else None)
            == event_snapshot.get("scheduled_at")
            and event.duration_minutes == event_snapshot.get("duration_minutes")
            and event.status == event_snapshot.get("status")
        ):
            states["event"] = "current"
        resume = session.scalar(
            select(Resume)
            .where(Resume.id == resume_id)
            .where(Resume.deleted_at.is_(None))
        )
        if resume is not None:
            try:
                current_content = parse_json_object("resume", resume.content_json)
                if canonical_json(current_content) == canonical_json(snapshot["resume"]["content_json"]):
                    states["resume"] = "current"
            except Exception:
                pass
        knowledge_changed = False
        for evidence in snapshot.get("knowledge_evidence", []):
            evidence_id = evidence.get("id") if isinstance(evidence, dict) else None
            version_id = evidence.get("note_version_id") if isinstance(evidence, dict) else None
            current = session.scalar(
                select(KnowledgeEvidence)
                .join(KnowledgeNoteEvidence, KnowledgeNoteEvidence.evidence_id == KnowledgeEvidence.id)
                .join(KnowledgeNoteVersion, KnowledgeNoteVersion.id == KnowledgeNoteEvidence.note_version_id)
                .join(KnowledgeNote, KnowledgeNote.id == KnowledgeNoteVersion.note_id)
                .where(KnowledgeEvidence.id == evidence_id)
                .where(KnowledgeNoteEvidence.note_version_id == version_id)
                .where(KnowledgeNote.current_version_id == version_id)
                .where(KnowledgeNote.archived_at.is_(None))
            )
            source = session.get(KnowledgeSource, current.source_id) if current is not None else None
            if (
                current is None
                or source is None
                or source.deleted_at is not None
                or source.lifecycle == "deleting"
                or current.canonical_excerpt != evidence.get("excerpt")
            ):
                knowledge_changed = True
        if knowledge_changed:
            states["knowledge"] = "source_changed"
        source_status = "source_changed" if "source_changed" in states.values() else "not_checked"
    except (TypeError, ValueError, KeyError):
        source_status = "source_changed"
    setattr(row, "source_status", source_status)
    setattr(row, "source_states", states)


def _lease_until() -> datetime:
    return _db_now() + timedelta(seconds=LEASE_SECONDS)


def _db_now() -> datetime:
    """Return the naive UTC value SQLite returns for DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
