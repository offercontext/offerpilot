from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.opportunity_fit_reviews import (
    build_source_snapshot,
    generate_deep_review,
    generate_triage,
)
from offerpilot.models import Application, OpportunityFitReview, Resume
from offerpilot.repositories.json_contract import (
    JsonContractError,
    canonical_json,
    parse_json_object,
    sha256_text,
)


class OpportunityFitReviewNotFound(Exception):
    pass


class OpportunityFitReviewValidationError(ValueError):
    pass


class OpportunityFitReviewConflictError(ValueError):
    pass


HUMAN_APPLICATION_SOURCES = frozenset({"cli", "manual", "web"})


class OpportunityFitReviewsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_triage(
        self,
        application_id: int,
        resume_id: int,
        jd_text: str,
        jd_source_label: str,
        candidate_assertions: list[str],
        idempotency_key: str,
        model: ChatModel,
    ) -> tuple[OpportunityFitReview, bool]:
        with self._session_factory() as session:
            application = _visible_application(session, application_id)
            if application is None:
                raise OpportunityFitReviewNotFound()
            existing = _find_by_idempotency(session, application_id, idempotency_key)
            if existing is not None:
                return _normalize_review_timestamps(existing), False
            snapshot = _build_snapshot(
                session,
                application,
                resume_id,
                jd_text,
                jd_source_label,
                candidate_assertions,
            )

        triage = generate_triage(model, snapshot)
        snapshot_json = canonical_json(snapshot)
        triage_json = canonical_json(triage.payload)
        fingerprint = sha256_text(snapshot_json)

        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if _visible_application(session, application_id) is None:
                raise OpportunityFitReviewNotFound()
            existing = _find_by_idempotency(session, application_id, idempotency_key)
            if existing is not None:
                return _normalize_review_timestamps(existing), False
            review = OpportunityFitReview(
                application_id=application_id,
                resume_id=resume_id,
                idempotency_key=idempotency_key,
                source_fingerprint_sha256=fingerprint,
                source_snapshot_json=snapshot_json,
                triage_json=triage_json,
                triage_sha256=sha256_text(triage_json),
            )
            session.add(review)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = _find_by_idempotency(session, application_id, idempotency_key)
                if existing is None:
                    raise
                return _normalize_review_timestamps(existing), False
            session.refresh(review)
            return _normalize_review_timestamps(review), True

    def list(self, application_id: int) -> list[OpportunityFitReview]:
        statement = (
            select(OpportunityFitReview)
            .join(Application, Application.id == OpportunityFitReview.application_id)
            .where(OpportunityFitReview.application_id == application_id)
            .where(Application.deleted_at.is_(None))
            .where(Application.source.in_(HUMAN_APPLICATION_SOURCES))
            .order_by(OpportunityFitReview.created_at.desc(), OpportunityFitReview.id.desc())
        )
        with self._session_factory() as session:
            return [_normalize_review_timestamps(item) for item in session.scalars(statement)]

    def get(self, application_id: int, review_id: int) -> OpportunityFitReview | None:
        with self._session_factory() as session:
            review = _visible_review(session, application_id, review_id)
            return _normalize_review_timestamps(review) if review is not None else None

    def create_deep_review(
        self,
        application_id: int,
        review_id: int,
        model: ChatModel,
    ) -> tuple[OpportunityFitReview, bool]:
        with self._session_factory() as session:
            review = _visible_review(session, application_id, review_id)
            if review is None:
                raise OpportunityFitReviewNotFound()
            if review.deep_review_json is not None:
                return _normalize_review_timestamps(review), False
            snapshot = _parse_stored_object(review.source_snapshot_json, "source snapshot")
            triage = _parse_stored_object(review.triage_json, "triage")

        deep_review = generate_deep_review(model, snapshot, triage)
        deep_review_json = canonical_json(deep_review.payload)

        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            review = _visible_review(session, application_id, review_id)
            if review is None:
                raise OpportunityFitReviewNotFound()
            if review.deep_review_json is not None:
                return _normalize_review_timestamps(review), False
            review.deep_review_json = deep_review_json
            review.deep_review_sha256 = sha256_text(deep_review_json)
            review.deep_reviewed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(review)
            return _normalize_review_timestamps(review), True


def _build_snapshot(
    session: Session,
    application: Application,
    resume_id: int,
    jd_text: str,
    jd_source_label: str,
    candidate_assertions: list[str],
) -> dict[str, Any]:
    if not jd_text.strip():
        raise OpportunityFitReviewValidationError("jd_text is required")
    resume = session.scalar(
        select(Resume)
        .where(Resume.id == resume_id)
        .where(Resume.deleted_at.is_(None))
    )
    if resume is None:
        raise OpportunityFitReviewNotFound()
    try:
        content = parse_json_object("resume", resume.content_json)
    except JsonContractError as exc:
        raise OpportunityFitReviewValidationError(str(exc)) from exc
    return build_source_snapshot(
        application_id=application.id,
        company_name=application.company_name,
        position_name=application.position_name,
        resume_id=resume.id,
        resume_title=resume.title or resume.name,
        resume_content=content,
        jd_text=jd_text,
        jd_source_label=jd_source_label.strip(),
        candidate_assertions=candidate_assertions,
    )


def _visible_application(session: Session, application_id: int) -> Application | None:
    return session.scalar(
        select(Application)
        .where(Application.id == application_id)
        .where(Application.deleted_at.is_(None))
        .where(Application.source.in_(HUMAN_APPLICATION_SOURCES))
    )


def _visible_review(
    session: Session,
    application_id: int,
    review_id: int,
) -> OpportunityFitReview | None:
    return session.scalar(
        select(OpportunityFitReview)
        .join(Application, Application.id == OpportunityFitReview.application_id)
        .where(OpportunityFitReview.application_id == application_id)
        .where(OpportunityFitReview.id == review_id)
        .where(Application.deleted_at.is_(None))
        .where(Application.source.in_(HUMAN_APPLICATION_SOURCES))
    )


def _find_by_idempotency(
    session: Session,
    application_id: int,
    idempotency_key: str,
) -> OpportunityFitReview | None:
    return session.scalar(
        select(OpportunityFitReview)
        .where(OpportunityFitReview.application_id == application_id)
        .where(OpportunityFitReview.idempotency_key == idempotency_key)
    )


def _parse_stored_object(value: str, name: str) -> dict[str, Any]:
    try:
        return parse_json_object(name, value)
    except JsonContractError as exc:
        raise OpportunityFitReviewConflictError(str(exc)) from exc


def _normalize_review_timestamps(review: OpportunityFitReview) -> OpportunityFitReview:
    for attr in ("created_at", "deep_reviewed_at"):
        value = getattr(review, attr)
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            setattr(review, attr, value.replace(tzinfo=timezone.utc))
        elif value is not None:
            setattr(review, attr, value.astimezone(timezone.utc))
    return review
