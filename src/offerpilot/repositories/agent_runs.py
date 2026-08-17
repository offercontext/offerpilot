from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypeVar, cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.agent_runtime.events import EventDraft, PreparedSnapshot, prepare_event
from offerpilot.models import AgentContextSnapshot, AgentEvent, AgentRun, ChatMessage

RunStatus = Literal[
    "running",
    "waiting_confirmation",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
]
TerminalRunStatus = Literal["completed", "failed", "cancelled", "timed_out"]

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
_ModelT = TypeVar("_ModelT")


@dataclass(frozen=True)
class StartRunCommand:
    run_id: str
    conversation_id: int
    input_message_id: int | None
    origin_kind: str
    initial_context_type: str
    initial_context_entity_id: str | None
    initial_context_ref_fingerprint: str | None
    fingerprint_key_id: str
    initial_transport_mode: str
    initial_route_kind: str
    run_started: EventDraft
    segment_started: EventDraft


@dataclass(frozen=True)
class StartSegmentCommand:
    run_id: str
    segment_started: EventDraft


@dataclass(frozen=True)
class CaptureContextCommand:
    snapshot_id: str
    execution_segment_id: str
    snapshot_key: str
    snapshot_kind: str
    model_step: int | None
    model_call_id: str | None
    prepared: PreparedSnapshot
    estimated_token_count: int | None = None
    token_estimator_name: str | None = None
    token_estimator_version: str | None = None


@dataclass(frozen=True)
class DispositionCommand:
    target_status: RunStatus
    events: tuple[EventDraft, ...]
    waiting_tool_call_id: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class StartedRun:
    run: AgentRun
    events: tuple[AgentEvent, AgentEvent]


@dataclass(frozen=True)
class CapturedContext:
    snapshot: AgentContextSnapshot
    event: AgentEvent


class JournalConflictError(RuntimeError):
    pass


class AgentRunRepository:
    """Own short, independent Journal transactions and immutable event ordering."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        supports_returning: Callable[[Session], bool] | None = None,
        before_event_insert: Callable[[AgentEvent], None] | None = None,
        now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session_factory = session_factory
        self._supports_returning = supports_returning or self._dialect_supports_returning
        self._before_event_insert = before_event_insert
        self._now_factory = now_factory

    def create_run_and_initial_segment(self, command: StartRunCommand) -> StartedRun:
        self._validate_initial_command(command)
        try:
            with self.session_factory() as session, session.begin():
                existing = session.get(AgentRun, command.run_id)
                if existing is not None:
                    self._assert_run_matches(existing, command)
                    first = self._existing_event(session, command.run_id, command.run_started)
                    second = self._existing_event(session, command.run_id, command.segment_started)
                    if first is None or second is None:
                        raise JournalConflictError("existing run is missing its initial events")
                    return StartedRun(
                        self._detach(session, existing),
                        (self._detach(session, first), self._detach(session, second)),
                    )

                now = self._utc_now()
                run = AgentRun(
                    id=command.run_id,
                    conversation_id=command.conversation_id,
                    input_message_id=command.input_message_id,
                    origin_kind=command.origin_kind,
                    initial_context_type=command.initial_context_type,
                    initial_context_entity_id=command.initial_context_entity_id,
                    initial_context_ref_fingerprint=command.initial_context_ref_fingerprint,
                    fingerprint_key_id=command.fingerprint_key_id,
                    initial_transport_mode=command.initial_transport_mode,
                    initial_route_kind=command.initial_route_kind,
                    status="running",
                    last_seq=0,
                    recording_status="healthy",
                    recording_error_count=0,
                    started_at=now,
                    updated_at=now,
                )
                session.add(run)
                session.flush()
                first = self._insert_event(session, run.id, command.run_started, now)
                second = self._insert_event(session, run.id, command.segment_started, now)
                session.refresh(run)
                return StartedRun(
                    self._detach(session, run),
                    (self._detach(session, first), self._detach(session, second)),
                )
        except IntegrityError as exc:
            raise JournalConflictError("run creation conflicts with persisted journal state") from exc

    def attach_input_message(self, run_id: str, message_id: int) -> AgentRun:
        try:
            with self.session_factory() as session, session.begin():
                run = self._required_run(session, run_id)
                if run.input_message_id == message_id:
                    return self._detach(session, run)
                if run.input_message_id is not None:
                    raise JournalConflictError("run already has a different input message")
                message = session.get(ChatMessage, message_id)
                if message is None or message.conversation_id != run.conversation_id:
                    raise JournalConflictError("input message does not belong to the run conversation")
                now = self._utc_now()
                run.input_message_id = message_id
                run.updated_at = now
                session.flush()
                return self._detach(session, run)
        except IntegrityError as exc:
            raise JournalConflictError("input message attachment conflicts") from exc

    def start_segment(self, command: StartSegmentCommand) -> AgentEvent:
        if command.segment_started.event_type != "segment.started":
            raise JournalConflictError("segment command requires segment.started")
        try:
            with self.session_factory() as session, session.begin():
                existing = self._existing_event(session, command.run_id, command.segment_started)
                if existing is not None:
                    return self._detach(session, existing)
                run = self._required_run(session, command.run_id)
                if run.status in _TERMINAL_STATUSES:
                    raise JournalConflictError("terminal run cannot start a segment")
                event = self._insert_event(
                    session, command.run_id, command.segment_started, self._utc_now()
                )
                return self._detach(session, event)
        except IntegrityError as exc:
            raise JournalConflictError("segment start conflicts with persisted journal state") from exc

    def append_event(self, run_id: str, draft: EventDraft) -> AgentEvent:
        try:
            with self.session_factory() as session, session.begin():
                existing = self._existing_event(session, run_id, draft)
                if existing is not None:
                    return self._detach(session, existing)
                run = self._required_run(session, run_id)
                if run.status in _TERMINAL_STATUSES:
                    raise JournalConflictError("terminal run cannot accept a new event")
                event = self._insert_event(session, run_id, draft, self._utc_now())
                return self._detach(session, event)
        except IntegrityError as exc:
            raise JournalConflictError("event conflicts with persisted journal state") from exc

    def capture_context(self, run_id: str, command: CaptureContextCommand) -> CapturedContext:
        event_draft = prepare_event(
            event_type="context.captured",
            execution_segment_id=command.execution_segment_id,
            model_step=command.model_step,
            model_call_id=command.model_call_id,
            facts={
                "snapshot_id": command.snapshot_id,
                "snapshot_key": command.snapshot_key,
                "manifest_digest": command.prepared.manifest_digest,
                "logical_input_fingerprint": command.prepared.logical_input_fingerprint,
            },
            fingerprint_key_id=command.prepared.fingerprint_key_id,
            source_ref_type="context_snapshot",
            source_ref_id=command.snapshot_id,
        )
        try:
            with self.session_factory() as session, session.begin():
                existing = session.scalar(
                    select(AgentContextSnapshot).where(
                        AgentContextSnapshot.run_id == run_id,
                        AgentContextSnapshot.snapshot_key == command.snapshot_key,
                    )
                )
                if existing is not None:
                    self._assert_snapshot_matches(existing, command)
                    event = self._existing_event(session, run_id, event_draft)
                    if event is None:
                        raise JournalConflictError("snapshot is missing its context event")
                    return CapturedContext(
                        self._detach(session, existing), self._detach(session, event)
                    )
                run = self._required_run(session, run_id)
                if run.status in _TERMINAL_STATUSES:
                    raise JournalConflictError("terminal run cannot capture context")
                if run.fingerprint_key_id != command.prepared.fingerprint_key_id:
                    raise JournalConflictError("snapshot key domain differs from run key domain")
                snapshot = AgentContextSnapshot(
                    id=command.snapshot_id,
                    run_id=run_id,
                    execution_segment_id=command.execution_segment_id,
                    snapshot_key=command.snapshot_key,
                    manifest_schema_version=command.prepared.manifest_schema_version,
                    snapshot_kind=command.snapshot_kind,
                    model_step=command.model_step,
                    model_call_id=command.model_call_id,
                    manifest_json=command.prepared.manifest_json,
                    manifest_digest=command.prepared.manifest_digest,
                    canonicalizer_version="1",
                    logical_input_fingerprint=command.prepared.logical_input_fingerprint,
                    fingerprint_key_id=command.prepared.fingerprint_key_id,
                    estimated_token_count=command.estimated_token_count,
                    token_estimator_name=command.token_estimator_name,
                    token_estimator_version=command.token_estimator_version,
                )
                session.add(snapshot)
                session.flush()
                event = self._insert_event(session, run_id, event_draft, self._utc_now())
                return CapturedContext(
                    self._detach(session, snapshot), self._detach(session, event)
                )
        except IntegrityError as exc:
            raise JournalConflictError("context capture conflicts with persisted journal state") from exc

    def converge_disposition(
        self, run_id: str, command: DispositionCommand
    ) -> tuple[AgentEvent, ...]:
        self._validate_disposition_shape(run_id, command)
        try:
            with self.session_factory() as session, session.begin():
                existing: list[AgentEvent | None] = [
                    self._existing_event(session, run_id, draft) for draft in command.events
                ]
                run = self._required_run(session, run_id)
                if all(item is not None for item in existing):
                    self._assert_disposition_projection(run, command)
                    return tuple(
                        self._detach(session, cast(AgentEvent, item)) for item in existing
                    )

                self._assert_status_transition(run, command.target_status)
                self._assert_disposition_matches_run(run, command)
                now = self._utc_now()
                run.status = command.target_status
                run.updated_at = now
                if command.target_status == "waiting_confirmation":
                    run.waiting_tool_call_id = command.waiting_tool_call_id
                    run.failure_code = None
                    run.finished_at = None
                elif command.target_status == "running":
                    run.waiting_tool_call_id = None
                    run.failure_code = None
                    run.finished_at = None
                else:
                    run.waiting_tool_call_id = None
                    run.failure_code = command.failure_code
                    run.finished_at = now
                created: list[AgentEvent] = []
                for item, draft in zip(existing, command.events, strict=True):
                    created.append(item or self._insert_event(session, run_id, draft, now))
                session.flush()
                return tuple(self._detach(session, event) for event in created)
        except IntegrityError as exc:
            raise JournalConflictError("disposition conflicts with persisted journal state") from exc

    def find_waiting_run(self, conversation_id: int, tool_call_id: str) -> AgentRun | None:
        with self.session_factory() as session:
            run = session.scalar(
                select(AgentRun).where(
                    AgentRun.conversation_id == conversation_id,
                    AgentRun.waiting_tool_call_id == tool_call_id,
                    AgentRun.status == "waiting_confirmation",
                )
            )
            return None if run is None else self._detach(session, run)

    def get_run(self, run_id: str) -> AgentRun | None:
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            return None if run is None else self._detach(session, run)

    def list_events(self, run_id: str) -> list[AgentEvent]:
        with self.session_factory() as session:
            events = list(
                session.scalars(
                    select(AgentEvent)
                    .where(AgentEvent.run_id == run_id)
                    .order_by(AgentEvent.seq.asc())
                )
            )
            return [self._detach(session, event) for event in events]

    def list_snapshots(self, run_id: str) -> list[AgentContextSnapshot]:
        with self.session_factory() as session:
            snapshots = list(
                session.scalars(
                    select(AgentContextSnapshot)
                    .where(AgentContextSnapshot.run_id == run_id)
                    .order_by(AgentContextSnapshot.created_at.asc())
                )
            )
            return [self._detach(session, snapshot) for snapshot in snapshots]

    def count_events(self, run_id: str, dedupe_key: str) -> int:
        with self.session_factory() as session:
            return len(
                list(
                    session.scalars(
                        select(AgentEvent.id).where(
                            AgentEvent.run_id == run_id,
                            AgentEvent.dedupe_key == dedupe_key,
                        )
                    )
                )
            )

    @staticmethod
    def _dialect_supports_returning(session: Session) -> bool:
        bind = session.get_bind()
        return bool(getattr(bind.dialect, "update_returning", False))

    def _insert_event(
        self, session: Session, run_id: str, draft: EventDraft, now: datetime
    ) -> AgentEvent:
        if draft.fingerprint_key_id is not None:
            run_key_id = session.scalar(
                select(AgentRun.fingerprint_key_id).where(AgentRun.id == run_id)
            )
            if run_key_id != draft.fingerprint_key_id:
                raise JournalConflictError("event key domain differs from run key domain")
        seq = self._allocate_seq(session, run_id, now)
        event = AgentEvent(
            id=str(uuid4()),
            run_id=run_id,
            seq=seq,
            dedupe_key=draft.dedupe_key,
            event_type=draft.event_type,
            schema_version=draft.schema_version,
            execution_segment_id=draft.execution_segment_id,
            model_step=draft.model_step,
            model_call_id=draft.model_call_id,
            source_ref_type=draft.source_ref_type,
            source_ref_id=draft.source_ref_id,
            fingerprint_key_id=draft.fingerprint_key_id,
            payload_json=draft.payload_json,
            payload_digest=draft.payload_digest,
            fact_digest=draft.fact_digest,
            created_at=now,
        )
        if self._before_event_insert is not None:
            self._before_event_insert(event)
        session.add(event)
        session.flush()
        return event

    def _allocate_seq(self, session: Session, run_id: str, now: datetime) -> int:
        if self._supports_returning(session):
            allocated = session.scalar(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(last_seq=AgentRun.last_seq + 1, updated_at=now)
                .returning(AgentRun.last_seq)
            )
            if allocated is None:
                raise JournalConflictError("agent run does not exist")
            return int(allocated)
        for attempt in range(1, 3):
            expected = session.scalar(select(AgentRun.last_seq).where(AgentRun.id == run_id))
            if expected is None:
                raise JournalConflictError("agent run does not exist")
            allocated = self._cas_increment(session, run_id, int(expected), attempt, now)
            if allocated is not None:
                return allocated
        raise JournalConflictError("sequence allocation conflict")

    def _cas_increment(
        self, session: Session, run_id: str, expected: int, _attempt: int, now: datetime
    ) -> int | None:
        result = session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.last_seq == expected)
            .values(last_seq=expected + 1, updated_at=now)
        )
        return expected + 1 if getattr(result, "rowcount", 0) == 1 else None

    def _existing_event(
        self, session: Session, run_id: str, draft: EventDraft
    ) -> AgentEvent | None:
        event = session.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run_id,
                AgentEvent.dedupe_key == draft.dedupe_key,
            )
        )
        if event is None:
            return None
        stable = (
            event.event_type,
            event.schema_version,
            event.execution_segment_id,
            event.model_step,
            event.model_call_id,
            event.source_ref_type,
            event.source_ref_id,
            event.fingerprint_key_id,
            event.fact_digest,
        )
        candidate = (
            draft.event_type,
            draft.schema_version,
            draft.execution_segment_id,
            draft.model_step,
            draft.model_call_id,
            draft.source_ref_type,
            draft.source_ref_id,
            draft.fingerprint_key_id,
            draft.fact_digest,
        )
        if stable != candidate:
            raise JournalConflictError("event dedupe identity has different stable facts")
        return event

    @staticmethod
    def _required_run(session: Session, run_id: str) -> AgentRun:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise JournalConflictError("agent run does not exist")
        return run

    @staticmethod
    def _validate_initial_command(command: StartRunCommand) -> None:
        if command.run_started.event_type != "run.started":
            raise JournalConflictError("initial command requires run.started")
        if command.segment_started.event_type != "segment.started":
            raise JournalConflictError("initial command requires segment.started")
        run_facts = json.loads(command.run_started.payload_json)["facts"]
        if run_facts["agent_run_id"] != command.run_id:
            raise JournalConflictError("run.started identity differs from command")
        if command.run_started.execution_segment_id != command.segment_started.execution_segment_id:
            raise JournalConflictError("initial events use different segments")

    @staticmethod
    def _assert_run_matches(run: AgentRun, command: StartRunCommand) -> None:
        actual = (
            run.conversation_id,
            run.input_message_id,
            run.origin_kind,
            run.initial_context_type,
            run.initial_context_entity_id,
            run.initial_context_ref_fingerprint,
            run.fingerprint_key_id,
            run.initial_transport_mode,
            run.initial_route_kind,
        )
        expected = (
            command.conversation_id,
            command.input_message_id,
            command.origin_kind,
            command.initial_context_type,
            command.initial_context_entity_id,
            command.initial_context_ref_fingerprint,
            command.fingerprint_key_id,
            command.initial_transport_mode,
            command.initial_route_kind,
        )
        if actual != expected:
            raise JournalConflictError("run identity has different stable facts")

    @staticmethod
    def _assert_snapshot_matches(
        snapshot: AgentContextSnapshot, command: CaptureContextCommand
    ) -> None:
        actual = (
            snapshot.id,
            snapshot.execution_segment_id,
            snapshot.snapshot_kind,
            snapshot.model_step,
            snapshot.model_call_id,
            snapshot.manifest_schema_version,
            snapshot.manifest_json,
            snapshot.manifest_digest,
            snapshot.logical_input_fingerprint,
            snapshot.fingerprint_key_id,
            snapshot.estimated_token_count,
            snapshot.token_estimator_name,
            snapshot.token_estimator_version,
        )
        expected = (
            command.snapshot_id,
            command.execution_segment_id,
            command.snapshot_kind,
            command.model_step,
            command.model_call_id,
            command.prepared.manifest_schema_version,
            command.prepared.manifest_json,
            command.prepared.manifest_digest,
            command.prepared.logical_input_fingerprint,
            command.prepared.fingerprint_key_id,
            command.estimated_token_count,
            command.token_estimator_name,
            command.token_estimator_version,
        )
        if actual != expected:
            raise JournalConflictError("snapshot key has different stable facts")

    @staticmethod
    def _validate_disposition_shape(run_id: str, command: DispositionCommand) -> None:
        types = [draft.event_type for draft in command.events]
        if len(types) != len(set(draft.dedupe_key for draft in command.events)):
            raise JournalConflictError("disposition contains duplicate event identities")
        if len({draft.execution_segment_id for draft in command.events}) != 1:
            raise JournalConflictError("disposition events must use one segment")
        facts_by_type = {
            draft.event_type: json.loads(draft.payload_json)["facts"] for draft in command.events
        }
        if command.target_status == "waiting_confirmation":
            if not command.waiting_tool_call_id:
                raise JournalConflictError("waiting disposition requires tool call identity")
            required = {
                "tool.proposed",
                "approval.requested",
                "run.waiting_confirmation",
                "segment.finished",
            }
            if len(types) != len(required) or set(types) != required:
                raise JournalConflictError("waiting disposition is missing required events")
            for event_type in required - {"segment.finished"}:
                if facts_by_type[event_type]["tool_call_id"] != command.waiting_tool_call_id:
                    raise JournalConflictError("waiting disposition tool identity differs")
            if facts_by_type["segment.finished"] != {
                "outcome": "suspended",
                "terminal_run_status": None,
            }:
                raise JournalConflictError("waiting disposition segment outcome differs")
        elif command.target_status == "running":
            if command.waiting_tool_call_id is not None or types != ["run.resumed"]:
                raise JournalConflictError("resume disposition is invalid")
        else:
            if command.waiting_tool_call_id is not None:
                raise JournalConflictError("terminal disposition cannot retain waiting identity")
            terminal_type = f"run.{command.target_status}"
            if len(types) != 2 or set(types) != {terminal_type, "segment.finished"}:
                raise JournalConflictError("terminal disposition is missing required events")
            if facts_by_type[terminal_type] != {
                "agent_run_id": run_id,
                "failure_code": command.failure_code,
                "status": command.target_status,
            }:
                raise JournalConflictError("terminal disposition run facts differ")
            if facts_by_type["segment.finished"] != {
                "outcome": command.target_status,
                "terminal_run_status": command.target_status,
            }:
                raise JournalConflictError("terminal disposition segment outcome differs")

    @staticmethod
    def _assert_disposition_matches_run(run: AgentRun, command: DispositionCommand) -> None:
        if command.target_status != "running":
            return
        resumed = next(draft for draft in command.events if draft.event_type == "run.resumed")
        facts = json.loads(resumed.payload_json)["facts"]
        if facts["tool_call_id"] != run.waiting_tool_call_id:
            raise JournalConflictError("resume disposition tool identity differs")

    @staticmethod
    def _assert_status_transition(run: AgentRun, target: RunStatus) -> None:
        if run.status in _TERMINAL_STATUSES:
            raise JournalConflictError("terminal run is immutable")
        allowed: dict[str, set[str]] = {
            "running": {"waiting_confirmation", *_TERMINAL_STATUSES},
            "waiting_confirmation": {"running", "failed", "cancelled", "timed_out"},
        }
        if run.recording_status == "degraded" and run.status == "waiting_confirmation":
            allowed["waiting_confirmation"].add("completed")
        if target not in allowed.get(run.status, set()):
            raise JournalConflictError("invalid run status transition")

    @staticmethod
    def _assert_disposition_projection(run: AgentRun, command: DispositionCommand) -> None:
        if run.status != command.target_status:
            raise JournalConflictError("events exist but run projection differs")
        expected_waiting = (
            command.waiting_tool_call_id
            if command.target_status == "waiting_confirmation"
            else None
        )
        if run.waiting_tool_call_id != expected_waiting:
            raise JournalConflictError("events exist but waiting projection differs")

    def _utc_now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("journal clock must return an aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _detach(session: Session, value: _ModelT) -> _ModelT:
        session.flush()
        session.expunge(value)
        return value
