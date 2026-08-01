from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.offer_negotiation import build_offer_negotiation_snapshot
from offerpilot.models import Offer, OfferComparisonDimension, OfferComparisonValue, OfferNegotiationProposal
from offerpilot.repositories.json_contract import canonical_json, sha256_text


LEASE_SECONDS = 30
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class OfferNegotiationError(ValueError):
    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OfferNegotiationValidationError(OfferNegotiationError):
    def __init__(self, message: str, code: str = "offer_negotiation_invalid_request") -> None:
        super().__init__(message, code, 422)


class OfferNegotiationNotFoundError(OfferNegotiationError):
    def __init__(self, message: str, code: str = "offer_negotiation_offer_not_found") -> None:
        super().__init__(message, code, 404)


class OfferNegotiationConflictError(OfferNegotiationError):
    def __init__(self, message: str, code: str = "offer_negotiation_idempotency_conflict") -> None:
        super().__init__(message, code, 409)


class OfferNegotiationUnverifiableError(OfferNegotiationError):
    def __init__(self, message: str = "offer negotiation output was not verifiable") -> None:
        super().__init__(message, "offer_negotiation_unverifiable", 502)


@dataclass
class OfferNegotiationGenerationResult:
    proposal: OfferNegotiationProposal
    snapshot: dict[str, Any]
    source_fingerprint: str
    should_call: bool
    pending: bool
    created: bool
    revision: int
    owner_token: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lease_until() -> datetime:
    return _utcnow() + timedelta(seconds=LEASE_SECONDS)


def _is_live(lease_expires_at: datetime | None) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    return lease_expires_at > _utcnow()


class OfferNegotiationRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def prepare_or_replay(
        self,
        *,
        offer_id: int,
        dimension_ids: list[int],
        user_brief: dict[str, str],
        idempotency_key: str,
    ) -> OfferNegotiationGenerationResult:
        self._validate_key(idempotency_key)
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            offer = session.get(Offer, offer_id)
            if offer is None:
                raise OfferNegotiationNotFoundError("offer is not visible")
            snapshot = self._build_snapshot(session, offer, dimension_ids, user_brief)
            fingerprint = sha256_text(canonical_json(snapshot))
            existing = session.scalar(
                select(OfferNegotiationProposal).where(
                    OfferNegotiationProposal.offer_id == offer_id,
                    OfferNegotiationProposal.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                token = uuid4().hex
                row = OfferNegotiationProposal(
                    offer_id=offer_id,
                    application_id=offer.application_id,
                    idempotency_key=idempotency_key,
                    attempt_status="generating",
                    source_fingerprint=fingerprint,
                    input_snapshot_json=canonical_json(snapshot),
                    source_states_json=canonical_json({"offer": "current"}),
                    provider_call_token=token,
                    lease_expires_at=_lease_until(),
                    revision=1,
                )
                session.add(row)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.scalar(
                        select(OfferNegotiationProposal).where(
                            OfferNegotiationProposal.offer_id == offer_id,
                            OfferNegotiationProposal.idempotency_key == idempotency_key,
                        )
                    )
                    if existing is None:
                        raise
                    return self._existing_result(existing, snapshot, fingerprint, session)
                session.refresh(row)
                return OfferNegotiationGenerationResult(
                    row, snapshot, fingerprint, True, False, True, row.revision, token
                )

            result = self._existing_result(existing, snapshot, fingerprint, session)
            session.commit()
            return result

    def complete_ready(
        self,
        *,
        proposal_id: int,
        revision: int,
        provider_call_token: str,
        proposal: dict[str, Any],
        proposal_hash: str,
    ) -> OfferNegotiationProposal:
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(OfferNegotiationProposal, proposal_id)
            if row is None:
                raise OfferNegotiationNotFoundError("proposal is not visible", "offer_negotiation_proposal_not_found")
            if row.attempt_status == "ready":
                session.commit()
                return row
            if not self._owns(row, revision, provider_call_token) or row.attempt_status != "generating":
                session.commit()
                raise OfferNegotiationConflictError("proposal generation ownership was lost")
            row.proposal_json = canonical_json(proposal)
            row.proposal_hash = proposal_hash
            row.attempt_status = "ready"
            row.provider_call_token = ""
            row.lease_expires_at = None
            row.ready_at = _utcnow()
            session.commit()
            session.refresh(row)
            return row

    def mark_provider_unknown(
        self, *, proposal_id: int, revision: int, provider_call_token: str
    ) -> OfferNegotiationProposal:
        return self._mark_status(
            proposal_id=proposal_id,
            revision=revision,
            provider_call_token=provider_call_token,
            status="provider_unknown",
            reason="",
        )

    def invalidate(
        self,
        *,
        proposal_id: int,
        revision: int,
        provider_call_token: str,
        reason: str,
    ) -> OfferNegotiationProposal:
        return self._mark_status(
            proposal_id=proposal_id,
            revision=revision,
            provider_call_token=provider_call_token,
            status="invalidated",
            reason=reason,
        )

    def get(self, proposal_id: int) -> OfferNegotiationProposal | None:
        with self._session_factory() as session:
            return session.get(OfferNegotiationProposal, proposal_id)

    def list_for_offer(self, offer_id: int) -> list[OfferNegotiationProposal]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(OfferNegotiationProposal)
                    .where(OfferNegotiationProposal.offer_id == offer_id)
                    .order_by(OfferNegotiationProposal.created_at.desc(), OfferNegotiationProposal.id.desc())
                )
            )

    def expire_for_test(self, proposal_id: int) -> None:
        with self._session_factory() as session:
            row = session.get(OfferNegotiationProposal, proposal_id)
            assert row is not None
            row.lease_expires_at = _utcnow() - timedelta(seconds=1)
            session.commit()

    @staticmethod
    def _validate_key(idempotency_key: str) -> None:
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise OfferNegotiationValidationError("idempotency_key must be ASCII")

    @staticmethod
    def _build_snapshot(
        session: Session,
        offer: Offer,
        dimension_ids: list[int],
        user_brief: dict[str, str],
    ) -> dict[str, Any]:
        if not isinstance(dimension_ids, list) or len(dimension_ids) > 8:
            raise OfferNegotiationValidationError("at most eight dimensions are allowed", "offer_negotiation_too_many_dimensions")
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in dimension_ids):
            raise OfferNegotiationValidationError("dimension ids are invalid")
        if len(set(dimension_ids)) != len(dimension_ids):
            raise OfferNegotiationValidationError("dimension ids must be unique")
        for field in ("goal", "concerns", "scenario"):
            if not isinstance(user_brief.get(field, ""), str):
                raise OfferNegotiationValidationError("user brief is invalid")
        dimensions: list[dict[str, Any]] = []
        for dimension_id in sorted(dimension_ids):
            dimension = session.get(OfferComparisonDimension, dimension_id)
            if dimension is None or dimension.archived_at is not None:
                raise OfferNegotiationValidationError(
                    "only active dimensions may be selected", "offer_negotiation_dimension_not_available"
                )
            value = session.scalar(
                select(OfferComparisonValue).where(
                    OfferComparisonValue.offer_id == offer.id,
                    OfferComparisonValue.dimension_id == dimension_id,
                )
            )
            dimensions.append(
                {"id": dimension.id, "label": dimension.label, "value_text": value.value_text if value else None}
            )
        return build_offer_negotiation_snapshot(
            offer={
                "company_name": offer.company_name,
                "position_name": offer.position_name,
                "base_monthly": offer.base_monthly,
                "months_per_year": offer.months_per_year,
                "signing_bonus": offer.signing_bonus,
                "equity": offer.equity,
                "perks": offer.perks,
                "deadline": offer.deadline,
                "notes": offer.notes,
                "assessment": offer.assessment,
            },
            dimensions=dimensions,
            user_brief=user_brief,
            idempotency_key="",
        )

    def _existing_result(
        self,
        row: OfferNegotiationProposal,
        snapshot: dict[str, Any],
        fingerprint: str,
        session: Session,
    ) -> OfferNegotiationGenerationResult:
        if row.source_fingerprint != fingerprint:
            if row.attempt_status in {"generating", "provider_unknown"}:
                row.attempt_status = "invalidated"
                row.invalidation_reason = "source_changed"
                row.provider_call_token = ""
                row.lease_expires_at = None
                session.commit()
            raise OfferNegotiationConflictError("source snapshot changed")
        if row.attempt_status == "ready":
            return OfferNegotiationGenerationResult(row, snapshot, fingerprint, False, False, False, row.revision, "")
        if row.attempt_status == "invalidated":
            if row.invalidation_reason == "contract_failed":
                raise OfferNegotiationUnverifiableError()
            raise OfferNegotiationConflictError(
                "offer negotiation attempt was invalidated", "offer_negotiation_attempt_invalidated"
            )
        if row.attempt_status in {"generating", "provider_unknown"} and _is_live(row.lease_expires_at):
            return OfferNegotiationGenerationResult(row, snapshot, fingerprint, False, True, False, row.revision, "")
        token = uuid4().hex
        row.attempt_status = "generating"
        row.revision += 1
        row.provider_call_token = token
        row.lease_expires_at = _lease_until()
        session.flush()
        return OfferNegotiationGenerationResult(row, snapshot, fingerprint, True, False, False, row.revision, token)

    @staticmethod
    def _owns(row: OfferNegotiationProposal, revision: int, token: str) -> bool:
        return row.revision == revision and row.provider_call_token == token

    def _mark_status(
        self,
        *,
        proposal_id: int,
        revision: int,
        provider_call_token: str,
        status: str,
        reason: str,
    ) -> OfferNegotiationProposal:
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(OfferNegotiationProposal, proposal_id)
            if row is None:
                raise OfferNegotiationNotFoundError("proposal is not visible", "offer_negotiation_proposal_not_found")
            if row.attempt_status == "ready":
                session.commit()
                return row
            if not self._owns(row, revision, provider_call_token) or row.attempt_status != "generating":
                session.commit()
                raise OfferNegotiationConflictError("proposal generation ownership was lost")
            row.attempt_status = status
            row.invalidation_reason = reason
            if status == "invalidated":
                row.provider_call_token = ""
                row.lease_expires_at = None
            session.commit()
            session.refresh(row)
            return row
