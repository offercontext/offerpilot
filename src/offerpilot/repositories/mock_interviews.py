from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import (
    Application,
    ApplicationEvent,
    MockInterviewFeedbackProposal,
    MockInterviewAttempt,
    MockInterviewTurn,
    Resume,
)
from offerpilot.repositories.json_contract import canonical_json, sha256_text


class MockInterviewIdempotencyConflict(ValueError):
    pass


class MockInterviewTurnIdempotencyConflict(ValueError):
    pass


class MockInterviewSourceChanged(ValueError):
    pass


@dataclass(frozen=True)
class MockInterviewStartResult:
    attempt: MockInterviewAttempt
    turn: MockInterviewTurn
    created: bool = False


class MockInterviewRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_or_replay_start(
        self,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        preparation_proposal_id: int | None,
        attempt_idempotency_key: str,
        initial_question_idempotency_key: str,
    ) -> MockInterviewStartResult:
        if not jd_text.strip():
            raise ValueError("jd_text must not be blank")
        if not attempt_idempotency_key or not initial_question_idempotency_key:
            raise ValueError("idempotency keys are required")

        with self._session_factory() as session:
            self._begin_immediate(session)
            snapshot = self._build_input_snapshot(
                session,
                application_id,
                event_id,
                resume_id,
                jd_text,
                preparation_proposal_id,
            )
            fingerprint = sha256_text(canonical_json(snapshot))
            existing = session.scalar(
                select(MockInterviewAttempt).where(
                    MockInterviewAttempt.application_id == application_id,
                    MockInterviewAttempt.event_id == event_id,
                    MockInterviewAttempt.idempotency_key == attempt_idempotency_key,
                )
            )
            if existing is not None:
                turn = session.scalar(
                    select(MockInterviewTurn).where(
                        MockInterviewTurn.attempt_id == existing.id,
                        MockInterviewTurn.turn_no == 1,
                    )
                )
                if existing.source_fingerprint != fingerprint:
                    raise MockInterviewIdempotencyConflict("mock interview input changed")
                if turn is None or turn.question_idempotency_key != initial_question_idempotency_key:
                    raise MockInterviewTurnIdempotencyConflict("initial question key changed")
                return MockInterviewStartResult(existing, turn, False)

            attempt = MockInterviewAttempt(
                application_id=application_id,
                event_id=event_id,
                resume_id=resume_id,
                idempotency_key=attempt_idempotency_key,
                input_snapshot_json=canonical_json(snapshot),
                source_fingerprint=fingerprint,
                attempt_status="awaiting_answer",
                generation_revision=1,
                provider_call_token=_token(),
                provider_lease_until=_lease_until(),
                transcript_fingerprint=_transcript_fingerprint([]),
            )
            session.add(attempt)
            session.flush()
            turn = MockInterviewTurn(
                attempt_id=attempt.id,
                turn_no=1,
                question_idempotency_key=initial_question_idempotency_key,
                question_text="请介绍一次与本次岗位相关的经历。",
                turn_status="awaiting_answer",
            )
            session.add(turn)
            session.commit()
            session.refresh(attempt)
            session.refresh(turn)
            return MockInterviewStartResult(attempt, turn, True)

    def submit_answer(
        self,
        attempt_id: int,
        turn_no: int,
        answer_text: str,
        turn_idempotency_key: str,
    ) -> MockInterviewAttempt:
        if not turn_idempotency_key:
            raise ValueError("turn_idempotency_key is required")
        with self._session_factory() as session:
            self._begin_immediate(session)
            attempt = session.get(MockInterviewAttempt, attempt_id)
            turn = session.scalar(
                select(MockInterviewTurn).where(
                    MockInterviewTurn.attempt_id == attempt_id,
                    MockInterviewTurn.turn_no == turn_no,
                )
            )
            if attempt is None or turn is None:
                raise LookupError("mock interview turn not found")
            self._assert_attempt_sources(session, attempt)
            if turn.answer_text:
                if turn.turn_idempotency_key != turn_idempotency_key or turn.answer_text != answer_text:
                    raise MockInterviewTurnIdempotencyConflict("submitted answer changed")
                return attempt
            if turn.turn_idempotency_key and turn.turn_idempotency_key != turn_idempotency_key:
                raise MockInterviewTurnIdempotencyConflict("submitted answer key changed")
            turn.turn_idempotency_key = turn_idempotency_key
            turn.answer_text = answer_text
            turn.answer_sha256 = sha256_text(answer_text)
            turn.turn_status = "answered"
            attempt.current_turn_no = max(attempt.current_turn_no, turn_no)
            turns = session.scalars(
                select(MockInterviewTurn)
                .where(MockInterviewTurn.attempt_id == attempt_id)
                .order_by(MockInterviewTurn.turn_no.asc())
            ).all()
            attempt.transcript_fingerprint = _transcript_fingerprint(turns)
            attempt.attempt_status = "awaiting_answer"
            session.commit()
            session.refresh(attempt)
            return attempt

    def claim_question(
        self, attempt_id: int, turn_no: int, question_idempotency_key: str
    ) -> tuple[int, str] | None:
        with self._session_factory() as session:
            self._begin_immediate(session)
            attempt = session.get(MockInterviewAttempt, attempt_id)
            if attempt is None:
                raise LookupError("mock interview attempt not found")
            now = datetime.now(timezone.utc)
            lease_until = _as_utc(attempt.provider_lease_until)
            if lease_until is not None and lease_until > now:
                return None
            attempt.generation_revision += 1
            attempt.provider_call_token = _token()
            attempt.provider_lease_until = _lease_until()
            attempt.attempt_status = "generating_question"
            session.commit()
            return attempt.generation_revision, attempt.provider_call_token

    def complete_question(
        self,
        attempt_id: int,
        turn_no: int,
        revision: int,
        provider_call_token: str,
        transcript_fingerprint: str,
        question_text: str,
    ) -> MockInterviewAttempt | None:
        with self._session_factory() as session:
            self._begin_immediate(session)
            attempt = session.get(MockInterviewAttempt, attempt_id)
            turn = session.scalar(
                select(MockInterviewTurn).where(
                    MockInterviewTurn.attempt_id == attempt_id,
                    MockInterviewTurn.turn_no == turn_no,
                )
            )
            if attempt is None or turn is None:
                return None
            if (
                attempt.generation_revision != revision
                or attempt.provider_call_token != provider_call_token
                or attempt.transcript_fingerprint != transcript_fingerprint
            ):
                return attempt
            turn.question_text = question_text
            turn.turn_status = "awaiting_answer"
            attempt.attempt_status = "awaiting_answer"
            attempt.provider_lease_until = None
            session.commit()
            session.refresh(attempt)
            return attempt

    def mark_provider_unknown(
        self, attempt_id: int, revision: int, provider_call_token: str, operation: str
    ) -> MockInterviewAttempt | None:
        with self._session_factory() as session:
            self._begin_immediate(session)
            attempt = session.get(MockInterviewAttempt, attempt_id)
            if attempt is None:
                return None
            if attempt.generation_revision != revision or attempt.provider_call_token != provider_call_token:
                return attempt
            attempt.attempt_status = "provider_unknown"
            attempt.failure_category = "provider_error"
            session.commit()
            session.refresh(attempt)
            return attempt

    def feedback_context(
        self, attempt_id: int, application_id: int, event_id: int
    ) -> tuple[MockInterviewAttempt, list[MockInterviewTurn]]:
        with self._session_factory() as session:
            attempt = session.get(MockInterviewAttempt, attempt_id)
            if (
                attempt is None
                or attempt.application_id != application_id
                or attempt.event_id != event_id
            ):
                raise LookupError("mock interview attempt not found")
            application = session.get(Application, application_id)
            event = session.get(ApplicationEvent, event_id)
            if application is None or application.deleted_at is not None:
                raise LookupError("application not found")
            if (
                event is None
                or event.application_id != application_id
                or event.event_type != "interview"
                or event.scheduled_at is None
            ):
                raise LookupError("event not found")
            self._assert_attempt_sources(session, attempt)
            turns = session.scalars(
                select(MockInterviewTurn)
                .where(MockInterviewTurn.attempt_id == attempt_id)
                .order_by(MockInterviewTurn.turn_no.asc())
            ).all()
            session.expunge(attempt)
            for turn in turns:
                session.expunge(turn)
            return attempt, turns

    def validate_event_context(self, application_id: int, event_id: int) -> None:
        with self._session_factory() as session:
            application = session.get(Application, application_id)
            event = session.get(ApplicationEvent, event_id)
            if application is None or application.deleted_at is not None:
                raise LookupError("application not found")
            if (
                event is None
                or event.application_id != application_id
                or event.event_type != "interview"
                or event.scheduled_at is None
            ):
                raise LookupError("event not found")

    @staticmethod
    def _assert_attempt_sources(session: Session, attempt: MockInterviewAttempt) -> None:
        snapshot = json.loads(attempt.input_snapshot_json)
        jd_text = str(snapshot.get("jd", {}).get("text", ""))
        try:
            current = MockInterviewRepository._build_input_snapshot(
                session,
                attempt.application_id,
                attempt.event_id,
                attempt.resume_id,
                jd_text,
                None,
            )
        except (LookupError, ValueError) as exc:
            raise MockInterviewSourceChanged("mock_interview_source_conflict") from exc
        if (
            current.get("application") != snapshot.get("application")
            or current.get("event") != snapshot.get("event")
            or current.get("resume") != snapshot.get("resume")
        ):
            raise MockInterviewSourceChanged("mock_interview_source_conflict")

    def create_or_replay_feedback(
        self,
        attempt_id: int,
        feedback_idempotency_key: str,
        proposal: dict[str, Any],
        proposal_status: str,
        failure_category: str = "",
    ) -> tuple[MockInterviewFeedbackProposal, bool]:
        if not feedback_idempotency_key:
            raise ValueError("feedback_idempotency_key is required")
        with self._session_factory() as session:
            self._begin_immediate(session)
            attempt = session.get(MockInterviewAttempt, attempt_id)
            if attempt is None:
                raise LookupError("mock interview attempt not found")
            existing = session.scalar(
                select(MockInterviewFeedbackProposal).where(
                    MockInterviewFeedbackProposal.attempt_id == attempt_id,
                    MockInterviewFeedbackProposal.idempotency_key == feedback_idempotency_key,
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing, False
            proposal_json = canonical_json(proposal)
            record = MockInterviewFeedbackProposal(
                attempt_id=attempt_id,
                idempotency_key=feedback_idempotency_key,
                input_snapshot_json=attempt.input_snapshot_json,
                source_fingerprint=attempt.source_fingerprint,
                transcript_fingerprint=attempt.transcript_fingerprint,
                proposal_json=proposal_json,
                proposal_hash=sha256_text(proposal_json),
                proposal_status=proposal_status,
                failure_category=failure_category,
            )
            session.add(record)
            attempt.attempt_status = "feedback_ready"
            attempt.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(record)
            session.expunge(record)
            return record, True

    def list_feedback_history(
        self, application_id: int, event_id: int
    ) -> list[MockInterviewFeedbackProposal]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(MockInterviewFeedbackProposal)
                .join(
                    MockInterviewAttempt,
                    MockInterviewAttempt.id == MockInterviewFeedbackProposal.attempt_id,
                )
                .where(
                    MockInterviewAttempt.application_id == application_id,
                    MockInterviewAttempt.event_id == event_id,
                )
                .order_by(MockInterviewFeedbackProposal.created_at.desc())
            ).all()
            for row in rows:
                session.expunge(row)
            return rows

    @staticmethod
    def _begin_immediate(session: Session) -> None:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    @staticmethod
    def _build_input_snapshot(
        session: Session,
        application_id: int,
        event_id: int,
        resume_id: int,
        jd_text: str,
        preparation_proposal_id: int | None,
    ) -> dict[str, Any]:
        application = session.get(Application, application_id)
        event = session.get(ApplicationEvent, event_id)
        resume = session.get(Resume, resume_id)
        if application is None or application.deleted_at is not None:
            raise LookupError("application not found")
        if (
            event is None
            or event.application_id != application_id
            or event.event_type != "interview"
            or event.scheduled_at is None
        ):
            raise ValueError("event is not a scheduled interview")
        if resume is None or resume.deleted_at is not None:
            raise LookupError("resume not found")
        return {
            "schema_version": "mock-interview-input-v1",
            "application": {
                "company_name": application.company_name,
                "position_name": application.position_name,
            },
            "event": {
                "event_type": event.event_type,
                "subtype": event.subtype,
                "round": event.round,
                "scheduled_at": event.scheduled_at.isoformat(),
                "duration_minutes": event.duration_minutes,
                "status": event.status,
            },
            "resume": {
                "title": resume.title,
                "content_json": _json_object(resume.content_json),
            },
            "jd": {"text": jd_text},
            "selected_preparation": [] if preparation_proposal_id is None else [preparation_proposal_id],
            "turns": [],
        }


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("resume content_json is invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("resume content_json must be an object")
    return parsed


def _transcript_fingerprint(turns: list[MockInterviewTurn]) -> str:
    payload = [
        {"turn_no": turn.turn_no, "question": turn.question_text, "answer": turn.answer_text}
        for turn in turns
    ]
    return sha256_text(canonical_json(payload))


def _token() -> str:
    return hashlib.sha256(f"{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()


def _lease_until() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=30)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
