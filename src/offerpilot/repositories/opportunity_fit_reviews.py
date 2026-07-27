from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.opportunity_fit_reviews import (
    build_source_snapshot,
    generate_deep_review,
    generate_deep_review_v2,
    generate_triage,
    generate_triage_v2,
)
from offerpilot.models import (
    Application,
    OpportunityFitReview,
    OpportunityFitReviewSession,
    OpportunityFitReviewStage,
    Resume,
)
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


class OpportunityFitReviewConfirmationExpired(ValueError):
    pass


class OpportunityFitReviewConfirmationConsumed(OpportunityFitReviewConflictError):
    pass


HUMAN_APPLICATION_SOURCES = frozenset({"cli", "manual", "web"})


class OpportunityFitReviewsRepository:
    def __init__(self, session_factory: sessionmaker[Session], confirmation_secret: str = ""):
        self._session_factory = session_factory
        self._confirmation_secret = confirmation_secret or "development-only-confirmation-secret"

    def create_triage_v2(
        self,
        application_id: int,
        resume_id: int,
        jd_text: str,
        jd_source_label: str,
        candidate_assertions: list[str],
        idempotency_key: str,
        model: ChatModel,
    ) -> tuple[OpportunityFitReviewSession, OpportunityFitReviewStage, bool, str]:
        with self._session_factory() as session:
            application = _visible_application(session, application_id)
            if application is None:
                raise OpportunityFitReviewNotFound()
            snapshot = _build_snapshot(
                session, application, resume_id, jd_text, jd_source_label, candidate_assertions
            )
            fingerprint = sha256_text(canonical_json(snapshot))
            existing = _find_v2_session(session, application_id, idempotency_key)
            if existing is not None:
                stage = _find_v2_stage(session, existing.id, "triage", idempotency_key)
                if stage is None:
                    raise OpportunityFitReviewConflictError("v2 triage stage is missing")
                if stage.source_fingerprint_sha256 != fingerprint:
                    raise OpportunityFitReviewConflictError("opportunity fit idempotency conflict")
                return existing, stage, False, _confirmation_token_for_stage(
                    stage, self._confirmation_secret
                )

        # The first write claims the root and stage before calling the provider.  A
        # unique application/key constraint makes concurrent first requests converge.
        provider_token = secrets.token_urlsafe(24)
        lease = datetime.now(timezone.utc) + timedelta(minutes=2)
        snapshot_json = canonical_json(snapshot)
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if _visible_application(session, application_id) is None:
                raise OpportunityFitReviewNotFound()
            existing = _find_v2_session(session, application_id, idempotency_key)
            if existing is not None:
                stage = _find_v2_stage(session, existing.id, "triage", idempotency_key)
                if stage is None:
                    raise OpportunityFitReviewConflictError("v2 triage stage is missing")
                if stage.source_fingerprint_sha256 != fingerprint:
                    raise OpportunityFitReviewConflictError("opportunity fit idempotency conflict")
                return existing, stage, False, _confirmation_token_for_stage(
                    stage, self._confirmation_secret
                )
            root = OpportunityFitReviewSession(
                application_id=application_id,
                triage_idempotency_key=idempotency_key,
                proposal_schema_version=2,
            )
            session.add(root)
            session.flush()
            stage = OpportunityFitReviewStage(
                review_id=root.id,
                application_id=application_id,
                resume_id=resume_id,
                stage="triage",
                proposal_schema_version=2,
                idempotency_key=idempotency_key,
                source_snapshot_json=snapshot_json,
                source_fingerprint_sha256=fingerprint,
                proposal_json="{}",
                proposal_sha256="",
                status="generating",
                provider_call_token=provider_token,
                lease_expires_at=lease,
            )
            session.add(stage)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                winner = _find_v2_session(session, application_id, idempotency_key)
                if winner is None:
                    raise
                stage = _find_v2_stage(session, winner.id, "triage", idempotency_key)
                if stage is None:
                    raise OpportunityFitReviewConflictError("v2 triage stage is missing")
                if stage.source_fingerprint_sha256 != fingerprint:
                    raise OpportunityFitReviewConflictError("opportunity fit idempotency conflict")
                return winner, stage, False, _confirmation_token_for_stage(
                    stage, self._confirmation_secret
                )
            session.refresh(root)
            session.refresh(stage)

        try:
            triage = generate_triage_v2(model, snapshot)
        except Exception:
            _mark_v2_provider_unknown(self._session_factory, stage.id, provider_token)
            raise
        proposal_json = canonical_json(triage.payload)
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            stage = session.get(OpportunityFitReviewStage, stage.id)
            if stage is None:
                raise OpportunityFitReviewNotFound()
            if stage.status != "generating" or stage.provider_call_token != provider_token:
                winner = session.get(OpportunityFitReviewSession, stage.review_id)
                if winner is None:
                    raise OpportunityFitReviewNotFound()
                return winner, stage, False, _confirmation_token_for_stage(
                    stage, self._confirmation_secret
                )
            stage.status = "ready"
            stage.proposal_json = proposal_json
            stage.proposal_sha256 = sha256_text(proposal_json)
            stage.provider_call_token = ""
            stage.lease_expires_at = None
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            stage.confirmation_expires_at = expires_at
            token = _confirmation_token(stage, self._confirmation_secret, expires_at=expires_at)
            stage.confirmation_token_hash = _hash_token(token)
            session.commit()
            root_after = session.get(OpportunityFitReviewSession, stage.review_id)
            if root_after is None:
                raise OpportunityFitReviewNotFound()
            session.refresh(stage)
            return root_after, stage, True, token

    def confirm_triage_v2(
        self, review_id: int, stage_id: int, confirmation_token: str
    ) -> OpportunityFitReviewStage:
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            stage = session.get(OpportunityFitReviewStage, stage_id)
            if stage is None or stage.review_id != review_id or stage.stage != "triage":
                raise OpportunityFitReviewNotFound()
            if stage.status == "confirmed":
                raise OpportunityFitReviewConfirmationConsumed()
            expires_at = _as_utc(stage.confirmation_expires_at)
            if expires_at is None or expires_at <= datetime.now(timezone.utc):
                raise OpportunityFitReviewConfirmationExpired()
            if not _verify_confirmation_token(stage, confirmation_token, self._confirmation_secret):
                raise OpportunityFitReviewConflictError("confirmation token is invalid")
            result = session.execute(
                text(
                    "UPDATE opportunity_fit_review_stages SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP "
                    "WHERE id=:id AND review_id=:review_id AND stage='triage' AND status='ready' "
                    "AND stage_generation=:generation AND confirmation_token_hash=:token_hash "
                    "AND confirmed_at IS NULL"
                ),
                {
                    "id": stage_id,
                    "review_id": review_id,
                    "generation": stage.stage_generation,
                    "token_hash": stage.confirmation_token_hash,
                },
            )
            if getattr(result, "rowcount", 0) != 1:
                raise OpportunityFitReviewConfirmationConsumed()
            session.commit()
            session.refresh(stage)
            return stage

    def list_v2(self, application_id: int) -> list[tuple[OpportunityFitReviewSession, list[OpportunityFitReviewStage]]]:
        with self._session_factory() as session:
            if _visible_application(session, application_id) is None:
                raise OpportunityFitReviewNotFound()
            roots = list(
                session.scalars(
                    select(OpportunityFitReviewSession)
                    .where(OpportunityFitReviewSession.application_id == application_id)
                    .order_by(OpportunityFitReviewSession.created_at.desc(), OpportunityFitReviewSession.id.desc())
                )
            )
            return [
                (
                    root,
                    list(
                        session.scalars(
                            select(OpportunityFitReviewStage)
                            .where(OpportunityFitReviewStage.review_id == root.id)
                            .order_by(OpportunityFitReviewStage.created_at.asc(), OpportunityFitReviewStage.id.asc())
                        )
                    ),
                )
                for root in roots
            ]

    def get_v2(
        self, application_id: int, review_id: int
    ) -> tuple[OpportunityFitReviewSession, list[OpportunityFitReviewStage]] | None:
        with self._session_factory() as session:
            if _visible_application(session, application_id) is None:
                return None
            root = session.scalar(
                select(OpportunityFitReviewSession)
                .where(OpportunityFitReviewSession.id == review_id)
                .where(OpportunityFitReviewSession.application_id == application_id)
            )
            if root is None:
                return None
            stages = list(
                session.scalars(
                    select(OpportunityFitReviewStage)
                    .where(OpportunityFitReviewStage.review_id == root.id)
                    .order_by(OpportunityFitReviewStage.created_at.asc(), OpportunityFitReviewStage.id.asc())
                )
            )
            return root, stages

    def create_deep_review_v2(
        self,
        application_id: int,
        review_id: int,
        parent_triage_stage_id: int,
        resume_id: int,
        jd_text: str,
        jd_source_label: str,
        candidate_assertions: list[str],
        idempotency_key: str,
        model: ChatModel,
    ) -> tuple[OpportunityFitReviewStage, bool]:
        with self._session_factory() as session:
            application = _visible_application(session, application_id)
            root = session.get(OpportunityFitReviewSession, review_id)
            parent = session.get(OpportunityFitReviewStage, parent_triage_stage_id)
            if application is None or root is None or root.application_id != application_id:
                raise OpportunityFitReviewNotFound()
            if parent is None or parent.review_id != review_id or parent.application_id != application_id:
                raise OpportunityFitReviewConflictError("opportunity fit parent stage is invalid")
            if parent.stage != "triage" or parent.status != "confirmed":
                raise OpportunityFitReviewConflictError("triage must be confirmed before deep review")
            snapshot = _build_snapshot(
                session, application, resume_id, jd_text, jd_source_label, candidate_assertions
            )
            snapshot_json = canonical_json(snapshot)
            fingerprint = sha256_text(snapshot_json)
            if fingerprint != parent.source_fingerprint_sha256:
                raise OpportunityFitReviewConflictError("opportunity fit source changed")
            existing = _find_v2_stage(session, review_id, "deep_review", idempotency_key)
            if existing is not None:
                if existing.source_fingerprint_sha256 != fingerprint:
                    raise OpportunityFitReviewConflictError("opportunity fit idempotency conflict")
                return existing, False
            provider_token = secrets.token_urlsafe(24)
            lease = datetime.now(timezone.utc) + timedelta(minutes=2)
            stage = OpportunityFitReviewStage(
                review_id=review_id,
                application_id=application_id,
                resume_id=resume_id,
                parent_triage_stage_id=parent_triage_stage_id,
                stage="deep_review",
                proposal_schema_version=2,
                idempotency_key=idempotency_key,
                source_snapshot_json=snapshot_json,
                source_fingerprint_sha256=fingerprint,
                proposal_json="{}",
                proposal_sha256="",
                status="generating",
                provider_call_token=provider_token,
                lease_expires_at=lease,
            )
            session.add(stage)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = _find_v2_stage(session, review_id, "deep_review", idempotency_key)
                if existing is None:
                    raise
                return existing, False
            session.refresh(stage)

        try:
            deep = generate_deep_review_v2(model, snapshot, json.loads(parent.proposal_json))
        except Exception:
            _mark_v2_provider_unknown(self._session_factory, stage.id, provider_token)
            raise
        proposal_json = canonical_json(deep.payload)
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            current_stage = session.get(OpportunityFitReviewStage, stage.id)
            if current_stage is None:
                raise OpportunityFitReviewNotFound()
            if current_stage.status != "generating" or current_stage.provider_call_token != provider_token:
                return current_stage, False
            current_stage.status = "ready"
            current_stage.proposal_json = proposal_json
            current_stage.proposal_sha256 = sha256_text(proposal_json)
            current_stage.provider_call_token = ""
            current_stage.lease_expires_at = None
            session.commit()
            session.refresh(current_stage)
            return current_stage, True

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


def _find_v2_session(
    session: Session, application_id: int, idempotency_key: str
) -> OpportunityFitReviewSession | None:
    return session.scalar(
        select(OpportunityFitReviewSession)
        .where(OpportunityFitReviewSession.application_id == application_id)
        .where(OpportunityFitReviewSession.triage_idempotency_key == idempotency_key)
    )


def _find_v2_stage(
    session: Session, review_id: int, stage: str, idempotency_key: str
) -> OpportunityFitReviewStage | None:
    return session.scalar(
        select(OpportunityFitReviewStage)
        .where(OpportunityFitReviewStage.review_id == review_id)
        .where(OpportunityFitReviewStage.stage == stage)
        .where(OpportunityFitReviewStage.idempotency_key == idempotency_key)
    )


def _mark_v2_provider_unknown(
    session_factory: sessionmaker[Session], stage_id: int, provider_token: str
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        stage = session.get(OpportunityFitReviewStage, stage_id)
        if stage is not None and stage.status == "generating" and stage.provider_call_token == provider_token:
            stage.status = "provider_unknown"
            session.commit()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _confirmation_payload(
    stage: OpportunityFitReviewStage, expires_at: datetime
) -> str:
    return canonical_json(
        {
            "review_id": stage.review_id,
            "stage_id": stage.id,
            "stage_generation": stage.stage_generation,
            "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
        }
    )


def _confirmation_token(
    stage: OpportunityFitReviewStage,
    secret: str,
    *,
    expires_at: datetime,
) -> str:
    payload = _confirmation_payload(stage, expires_at)
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _confirmation_token_for_stage(stage: OpportunityFitReviewStage, secret: str) -> str:
    expires_at = _as_utc(stage.confirmation_expires_at)
    if stage.status != "ready" or expires_at is None or expires_at <= datetime.now(timezone.utc):
        return ""
    return _confirmation_token(stage, secret, expires_at=expires_at)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _verify_confirmation_token(
    stage: OpportunityFitReviewStage, token: str, secret: str
) -> bool:
    try:
        payload, signature = token.rsplit(".", 1)
        data = json.loads(payload)
        expires_at = datetime.fromisoformat(str(data["expires_at"])).astimezone(timezone.utc)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    if data != {
        "review_id": stage.review_id,
        "stage_id": stage.id,
        "stage_generation": stage.stage_generation,
        "expires_at": expires_at.isoformat(),
    }:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected) and hmac.compare_digest(
        _hash_token(token), stage.confirmation_token_hash
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
