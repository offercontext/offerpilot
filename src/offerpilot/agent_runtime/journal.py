from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from offerpilot.agent_runtime.events import (
    ContextManifestInput,
    EventDraft,
    JournalEventValidationError,
    PreparedSnapshot,
    model_id_fingerprint,
    pending_identity_fingerprint,
    prepare_context_snapshot,
    prepare_event,
)
from offerpilot.agent_runtime.keyring import JournalKeyDomain
from offerpilot.repositories.agent_runs import (
    AgentRunRepository,
    CaptureContextCommand,
    DispositionCommand,
    JournalDeadlineExceeded,
    RunStatus,
    StartRunCommand,
    StartSegmentCommand,
)

RecordingStatus = Literal["healthy", "degraded"]
TerminalStatus = Literal["completed", "failed", "cancelled", "timed_out"]
EventPreparer = Callable[["EventInput", float], EventDraft]
ContextPreparer = Callable[[object, ContextManifestInput, float], PreparedSnapshot]
StartRunBuilder = Callable[
    [JournalKeyDomain, Callable[[], None]],
    StartRunCommand,
]
StartSegmentBuilder = Callable[
    [str, JournalKeyDomain, Callable[[], None]],
    StartSegmentCommand,
]
_PENDING_IDENTITY_UNSET = object()


class JournalBudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class EventInput:
    event_type: str
    facts: Mapping[str, object]
    telemetry: Mapping[str, object] = field(default_factory=dict)
    model_step: int | None = None
    model_call_id: str | None = None
    source_ref_type: str | None = None
    source_ref_id: object = None


@dataclass(frozen=True)
class SuspendedDisposition:
    tool_call_id: str
    tool_name: str
    tool_kind: Literal["read", "write"]
    args_shape_digest: str
    pending_identity_fingerprint: str | None = None
    pending_identity: object = field(default=_PENDING_IDENTITY_UNSET, repr=False)


@dataclass(frozen=True)
class TerminalDisposition:
    status: TerminalStatus
    failure_code: str | None = None


class RunRecorder(Protocol):
    @property
    def run_id(self) -> str | None: ...

    @property
    def segment_id(self) -> str | None: ...

    @property
    def diagnostics(self) -> list[str]: ...

    def start_segment(self, command: StartSegmentCommand) -> None: ...

    def attach_input_message(self, message_id: int) -> None: ...

    def capture_context(
        self,
        logical_input: object,
        manifest: ContextManifestInput,
        *,
        snapshot_kind: str,
        model_step: int | None = None,
        model_call_id: str | None = None,
        estimated_token_count: int | None = None,
        token_estimator_name: str | None = None,
        token_estimator_version: str | None = None,
    ) -> str | None: ...

    def append_event(self, event: EventInput) -> None: ...

    def suspend(self, command: SuspendedDisposition) -> None: ...

    def finish(self, command: TerminalDisposition) -> None: ...

    def fingerprint_model_id(self, value: str) -> str | None: ...

    def fingerprint_pending_identity(self, value: object) -> str | None: ...


class NullRunRecorder:
    run_id = None
    segment_id = None
    recording_status: RecordingStatus = "healthy"

    def __init__(self, diagnostics: list[str] | None = None) -> None:
        self.diagnostics = list(diagnostics or ())

    def start_segment(self, _command: StartSegmentCommand) -> None:
        return None

    def attach_input_message(self, _message_id: int) -> None:
        return None

    def capture_context(
        self,
        _logical_input: object,
        _manifest: ContextManifestInput,
        *,
        snapshot_kind: str,
        model_step: int | None = None,
        model_call_id: str | None = None,
        estimated_token_count: int | None = None,
        token_estimator_name: str | None = None,
        token_estimator_version: str | None = None,
    ) -> None:
        del (
            snapshot_kind,
            model_step,
            model_call_id,
            estimated_token_count,
            token_estimator_name,
            token_estimator_version,
        )
        return None

    def append_event(self, _event: EventInput) -> None:
        return None

    def suspend(self, _command: SuspendedDisposition) -> None:
        return None

    def finish(self, _command: TerminalDisposition) -> None:
        return None

    def fingerprint_model_id(self, _value: str) -> None:
        return None

    def fingerprint_pending_identity(self, _value: object) -> None:
        return None


class SafeRunRecorder:
    """Fail-open, per-segment Journal facade with an irreversible degraded latch."""

    def __init__(
        self,
        repository: AgentRunRepository,
        key: JournalKeyDomain,
        run_id: str,
        segment_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        segment_budget_seconds: float = 0.150,
        disposition_budget_seconds: float = 0.050,
        segment_started_at: float | None = None,
        event_preparer: EventPreparer | None = None,
        context_preparer: ContextPreparer | None = None,
        uuid_factory: Callable[[], str] = lambda: str(uuid4()),
        diagnostic_sink: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self.key = key
        self.run_id = run_id
        self.segment_id = segment_id
        self.clock = clock
        self.segment_budget_seconds = segment_budget_seconds
        self.disposition_budget_seconds = disposition_budget_seconds
        self._segment_started_at = (
            clock() if segment_started_at is None else segment_started_at
        )
        self._segment_deadline = self._segment_started_at + segment_budget_seconds
        self._event_preparer = event_preparer or self._prepare_event
        self._context_preparer = context_preparer or self._prepare_context
        self._uuid_factory = uuid_factory
        self._diagnostic_sink = diagnostic_sink
        self.recording_status: RecordingStatus = "healthy"
        self.diagnostics: list[str] = []
        self._degraded_persisted = False
        self._disposition_attempted = False

    def start_segment(self, command: StartSegmentCommand) -> None:
        if command.run_id != self.run_id or (
            command.segment_started.execution_segment_id != self.segment_id
        ):
            self._degrade("journal_segment_identity_changed")
            return
        self._nonterminal_write(
            lambda: self.repository.start_segment(
                command,
                deadline=self._segment_deadline,
                clock=self.clock,
            ),
            "journal_segment_write_failed",
        )

    def attach_input_message(self, message_id: int) -> None:
        self._nonterminal_write(
            lambda: self.repository.attach_input_message(
                self.run_id,
                message_id,
                deadline=self._segment_deadline,
                clock=self.clock,
            ),
            "journal_message_link_failed",
        )

    def capture_context(
        self,
        logical_input: object,
        manifest: ContextManifestInput,
        *,
        snapshot_kind: str,
        model_step: int | None = None,
        model_call_id: str | None = None,
        estimated_token_count: int | None = None,
        token_estimator_name: str | None = None,
        token_estimator_version: str | None = None,
    ) -> str | None:
        if self.recording_status == "degraded" or self._disposition_attempted:
            return None
        try:
            self._require_budget(self._segment_deadline)
            prepared = self._context_preparer(
                logical_input,
                manifest,
                self._segment_deadline,
            )
            self._require_budget(self._segment_deadline)
            snapshot_id = self._uuid_factory()
            if snapshot_kind == "model_input":
                if model_call_id is None:
                    raise JournalEventValidationError("model call identity is required")
                snapshot_key = f"model-input:{self.segment_id}:{model_call_id}"
            elif snapshot_kind == "initial":
                snapshot_key = f"initial:{self.segment_id}"
            elif snapshot_kind == "confirmation_resume":
                snapshot_key = f"confirmation-resume:{self.segment_id}"
            else:
                raise JournalEventValidationError("unsupported snapshot kind")
            command = CaptureContextCommand(
                snapshot_id=snapshot_id,
                execution_segment_id=self.segment_id,
                snapshot_key=snapshot_key,
                snapshot_kind=snapshot_kind,
                model_step=model_step,
                model_call_id=model_call_id,
                prepared=prepared,
                estimated_token_count=estimated_token_count,
                token_estimator_name=token_estimator_name,
                token_estimator_version=token_estimator_version,
            )
            self.repository.capture_context(
                self.run_id,
                command,
                deadline=self._segment_deadline,
                clock=self.clock,
            )
            self._require_budget(self._segment_deadline)
            return snapshot_id
        except JournalBudgetExhausted:
            self._degrade("journal_budget_exhausted")
        except JournalDeadlineExceeded:
            self._degrade("journal_budget_exhausted")
        except OperationalError as error:
            diagnostic = (
                "journal_budget_exhausted"
                if self._operational_error_exhausted_budget(
                    error,
                    self._segment_deadline,
                )
                else "journal_context_write_failed"
            )
            self._degrade(diagnostic)
        except JournalEventValidationError:
            self._degrade("journal_context_invalid")
        except Exception:
            self._degrade("journal_context_write_failed")
        return None

    def append_event(self, event: EventInput) -> None:
        if self.recording_status == "degraded" or self._disposition_attempted:
            return
        try:
            self._require_budget(self._segment_deadline)
            draft = self._event_preparer(event, self._segment_deadline)
            self._require_budget(self._segment_deadline)
            self.repository.append_event(
                self.run_id,
                draft,
                deadline=self._segment_deadline,
                clock=self.clock,
            )
            self._require_budget(self._segment_deadline)
        except JournalBudgetExhausted:
            self._degrade("journal_budget_exhausted")
        except JournalDeadlineExceeded:
            self._degrade("journal_budget_exhausted")
        except OperationalError as error:
            diagnostic = (
                "journal_budget_exhausted"
                if self._operational_error_exhausted_budget(
                    error,
                    self._segment_deadline,
                )
                else "journal_event_write_failed"
            )
            self._degrade(diagnostic)
        except JournalEventValidationError:
            self._degrade("journal_event_invalid")
        except Exception:
            self._degrade("journal_event_write_failed")

    def suspend(self, command: SuspendedDisposition) -> None:
        def inputs(deadline: float) -> tuple[EventDraft, ...]:
            pending_fingerprint = command.pending_identity_fingerprint
            if pending_fingerprint is None:
                if command.pending_identity is _PENDING_IDENTITY_UNSET:
                    raise JournalEventValidationError("pending identity is required")
                self._require_budget(deadline)
                pending_fingerprint = pending_identity_fingerprint(
                    self.key,
                    command.pending_identity,
                    budget_check=lambda: self._require_budget(deadline),
                )
            values = (
                EventInput(
                    event_type="tool.proposed",
                    facts={
                        "tool_call_id": command.tool_call_id,
                        "tool_name": command.tool_name,
                        "tool_kind": command.tool_kind,
                        "args_shape_digest": command.args_shape_digest,
                        "proposal_outcome": "confirmation_required",
                    },
                    source_ref_type="tool_call",
                    source_ref_id=command.tool_call_id,
                ),
                EventInput(
                    event_type="approval.requested",
                    facts={
                        "tool_call_id": command.tool_call_id,
                        "confirmation_mode": "required",
                        "pending_identity_fingerprint": pending_fingerprint,
                    },
                    source_ref_type="tool_call",
                    source_ref_id=command.tool_call_id,
                ),
                EventInput(
                    event_type="run.waiting_confirmation",
                    facts={"tool_call_id": command.tool_call_id},
                    source_ref_type="tool_call",
                    source_ref_id=command.tool_call_id,
                ),
                EventInput(
                    event_type="segment.finished",
                    facts={"outcome": "suspended", "terminal_run_status": None},
                ),
            )
            return tuple(self._event_preparer(value, deadline) for value in values)

        self._converge(
            inputs,
            target_status="waiting_confirmation",
            waiting_tool_call_id=command.tool_call_id,
            failure_code=None,
        )

    def finish(self, command: TerminalDisposition) -> None:
        def inputs(deadline: float) -> tuple[EventDraft, ...]:
            values = (
                EventInput(
                    event_type=f"run.{command.status}",
                    facts={
                        "agent_run_id": self.run_id,
                        "status": command.status,
                        "failure_code": command.failure_code,
                    },
                ),
                EventInput(
                    event_type="segment.finished",
                    facts={
                        "outcome": command.status,
                        "terminal_run_status": command.status,
                    },
                ),
            )
            return tuple(self._event_preparer(value, deadline) for value in values)

        self._converge(
            inputs,
            target_status=command.status,
            waiting_tool_call_id=None,
            failure_code=command.failure_code,
        )

    def mark_degraded(self, diagnostic: str = "journal_recording_degraded") -> None:
        self._degrade(diagnostic)

    def fingerprint_model_id(self, value: str) -> str | None:
        return self._fingerprint(
            lambda: model_id_fingerprint(
                self.key,
                value,
                budget_check=lambda: self._require_budget(self._segment_deadline),
            )
        )

    def fingerprint_pending_identity(self, value: object) -> str | None:
        return self._fingerprint(
            lambda: pending_identity_fingerprint(
                self.key,
                value,
                budget_check=lambda: self._require_budget(self._segment_deadline),
            )
        )

    def _fingerprint(self, operation: Callable[[], str]) -> str | None:
        if self.recording_status == "degraded":
            return None
        try:
            self._require_budget(self._segment_deadline)
            value = operation()
            self._require_budget(self._segment_deadline)
            return value
        except JournalBudgetExhausted:
            self._degrade("journal_budget_exhausted")
        except Exception:
            self._degrade("journal_fingerprint_failed")
        return None

    def _prepare_event(self, value: EventInput, deadline: float) -> EventDraft:
        self._require_budget(deadline)
        facts = dict(value.facts)
        contains_hmac = any(field.endswith("_fingerprint") for field in facts)
        draft = prepare_event(
            event_type=value.event_type,
            execution_segment_id=self.segment_id,
            facts=facts,
            telemetry=dict(value.telemetry),
            model_step=value.model_step,
            model_call_id=value.model_call_id,
            source_ref_type=value.source_ref_type,
            source_ref_id=value.source_ref_id,
            fingerprint_key_id=self.key.key_id if contains_hmac else None,
            budget_check=lambda: self._require_budget(deadline),
        )
        self._require_budget(deadline)
        return draft

    def _prepare_context(
        self,
        logical_input: object,
        manifest: ContextManifestInput,
        deadline: float,
    ) -> PreparedSnapshot:
        self._require_budget(deadline)
        prepared = prepare_context_snapshot(
            logical_input,
            manifest,
            key=self.key,
            budget_check=lambda: self._require_budget(deadline),
        )
        self._require_budget(deadline)
        return prepared

    def _nonterminal_write(
        self,
        operation: Callable[[], object],
        failure_diagnostic: str,
    ) -> None:
        if self.recording_status == "degraded" or self._disposition_attempted:
            return
        try:
            self._require_budget(self._segment_deadline)
            operation()
            self._require_budget(self._segment_deadline)
        except JournalBudgetExhausted:
            self._degrade("journal_budget_exhausted")
        except JournalDeadlineExceeded:
            self._degrade("journal_budget_exhausted")
        except OperationalError as error:
            diagnostic = (
                "journal_budget_exhausted"
                if self._operational_error_exhausted_budget(
                    error,
                    self._segment_deadline,
                )
                else failure_diagnostic
            )
            self._degrade(diagnostic)
        except Exception:
            self._degrade(failure_diagnostic)

    def _converge(
        self,
        prepare: Callable[[float], tuple[EventDraft, ...]],
        *,
        target_status: RunStatus,
        waiting_tool_call_id: str | None,
        failure_code: str | None,
    ) -> None:
        if self._disposition_attempted:
            return
        self._disposition_attempted = True
        deadline = self.clock() + self.disposition_budget_seconds
        try:
            events = prepare(deadline)
            self._require_budget(deadline)
            self.repository.converge_disposition(
                self.run_id,
                DispositionCommand(
                    target_status=target_status,
                    events=events,
                    waiting_tool_call_id=waiting_tool_call_id,
                    failure_code=failure_code,
                ),
                deadline=deadline,
                clock=self.clock,
            )
            self._require_budget(deadline)
            if self.recording_status == "degraded":
                self._sync_degraded(deadline)
        except JournalBudgetExhausted:
            self._degrade("journal_disposition_budget_exhausted")
        except JournalDeadlineExceeded:
            self._degrade("journal_disposition_budget_exhausted")
        except OperationalError as error:
            diagnostic = (
                "journal_disposition_budget_exhausted"
                if self._operational_error_exhausted_budget(error, deadline)
                else "journal_disposition_failed"
            )
            self._degrade(diagnostic)
        except JournalEventValidationError:
            self._degrade("journal_disposition_invalid")
        except Exception:
            self._degrade("journal_disposition_failed")

    def _degrade(self, diagnostic: str) -> None:
        first_transition = self.recording_status != "degraded"
        self.recording_status = "degraded"
        self._diagnose(diagnostic)
        if (
            first_transition
            and not diagnostic.endswith("budget_exhausted")
            and self.clock() < self._segment_deadline
        ):
            self._sync_degraded(self._segment_deadline)

    def _sync_degraded(self, deadline: float | None) -> None:
        if self._degraded_persisted:
            return
        if deadline is not None and self.clock() >= deadline:
            return
        try:
            self.repository.mark_degraded(
                self.run_id,
                deadline=deadline,
                clock=self.clock,
            )
            self._degraded_persisted = True
        except JournalDeadlineExceeded:
            return
        except OperationalError as error:
            if self._operational_error_exhausted_budget(error, deadline):
                return
            self._diagnose("journal_mark_degraded_failed")
        except Exception:
            self._diagnose("journal_mark_degraded_failed")

    def _diagnose(self, code: str) -> None:
        if code in self.diagnostics:
            return
        self.diagnostics.append(code)
        if self._diagnostic_sink is not None:
            try:
                self._diagnostic_sink(code)
            except Exception:
                pass

    def _require_budget(self, deadline: float) -> None:
        if self.clock() >= deadline:
            raise JournalBudgetExhausted

    def _operational_error_exhausted_budget(
        self,
        error: OperationalError,
        deadline: float | None,
    ) -> bool:
        if deadline is not None and self.clock() >= deadline:
            return True
        return _is_sqlite_lock_error(error)


class RunRecorderFactory:
    def __init__(
        self,
        repository: AgentRunRepository,
        *,
        key: JournalKeyDomain | None,
        enabled: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        segment_budget_seconds: float = 0.150,
        disposition_budget_seconds: float = 0.050,
        diagnostic_sink: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self.key = key
        self.enabled = _journal_enabled_from_env() if enabled is None else enabled
        self.clock = clock
        self.segment_budget_seconds = segment_budget_seconds
        self.disposition_budget_seconds = disposition_budget_seconds
        self._diagnostic_sink = diagnostic_sink
        self.diagnostics: list[str] = []

    def start_run(self, command: StartRunCommand | StartRunBuilder) -> RunRecorder:
        started_at = self.clock()
        if not self.enabled:
            return NullRunRecorder()
        if self.key is None:
            return self._null("journal_secret_unavailable")
        deadline = started_at + self.segment_budget_seconds
        if callable(command):
            try:
                command = command(
                    self.key,
                    lambda: self._require_factory_budget(deadline),
                )
                self._require_factory_budget(deadline)
            except JournalBudgetExhausted:
                return self._null("journal_budget_exhausted")
            except Exception:
                return self._null("journal_run_create_failed")
        if command.fingerprint_key_id != self.key.key_id:
            return self._null("fingerprint_key_domain_changed")
        try:
            self.repository.create_run_and_initial_segment(
                command,
                deadline=deadline,
                clock=self.clock,
            )
        except JournalDeadlineExceeded:
            return self._null("journal_budget_exhausted")
        except OperationalError as error:
            if self._operational_error_exhausted_budget(error, deadline):
                return self._null("journal_budget_exhausted")
            return self._null("journal_run_create_failed")
        except Exception:
            return self._null("journal_run_create_failed")
        recorder = self._safe(
            command.run_id,
            command.segment_started.execution_segment_id,
            started_at,
        )
        if self.clock() >= started_at + self.segment_budget_seconds:
            recorder.mark_degraded("journal_budget_exhausted")
        return recorder

    def resume_waiting_run(
        self,
        conversation_id: int,
        waiting_tool_call_id: str,
        command: StartSegmentCommand | StartSegmentBuilder,
    ) -> RunRecorder:
        started_at = self.clock()
        if not self.enabled:
            return NullRunRecorder()
        if self.key is None:
            return self._null("journal_secret_unavailable")
        deadline = started_at + self.segment_budget_seconds
        try:
            run = self.repository.find_waiting_run(
                conversation_id,
                waiting_tool_call_id,
                deadline=deadline,
                clock=self.clock,
            )
        except JournalDeadlineExceeded:
            return self._null("journal_budget_exhausted")
        except OperationalError as error:
            if self._operational_error_exhausted_budget(error, deadline):
                return self._null("journal_budget_exhausted")
            return self._null("journal_run_lookup_failed")
        except Exception:
            return self._null("journal_run_lookup_failed")
        if run is None:
            return self._null("journal_run_missing")
        if run.fingerprint_key_id != self.key.key_id:
            return self._null("fingerprint_key_domain_changed")
        if callable(command):
            try:
                command = command(
                    run.id,
                    self.key,
                    lambda: self._require_factory_budget(deadline),
                )
                self._require_factory_budget(deadline)
            except JournalBudgetExhausted:
                return self._null("journal_budget_exhausted")
            except Exception:
                return self._null("journal_segment_create_failed")
        if command.run_id != run.id:
            return self._null("journal_run_identity_changed")
        try:
            self.repository.start_segment(
                command,
                deadline=deadline,
                clock=self.clock,
            )
        except JournalDeadlineExceeded:
            return self._null("journal_budget_exhausted")
        except OperationalError as error:
            if self._operational_error_exhausted_budget(error, deadline):
                return self._null("journal_budget_exhausted")
            return self._null("journal_segment_create_failed")
        except Exception:
            return self._null("journal_segment_create_failed")
        recorder = self._safe(
            run.id,
            command.segment_started.execution_segment_id,
            started_at,
        )
        if self.clock() >= started_at + self.segment_budget_seconds:
            recorder.mark_degraded("journal_budget_exhausted")
        return recorder

    def _safe(self, run_id: str, segment_id: str, started_at: float) -> SafeRunRecorder:
        assert self.key is not None
        return SafeRunRecorder(
            self.repository,
            self.key,
            run_id,
            segment_id,
            clock=self.clock,
            segment_budget_seconds=self.segment_budget_seconds,
            disposition_budget_seconds=self.disposition_budget_seconds,
            segment_started_at=started_at,
            diagnostic_sink=self._diagnostic_sink,
        )

    def _null(self, diagnostic: str) -> NullRunRecorder:
        self._diagnose(diagnostic)
        return NullRunRecorder([diagnostic])

    def _diagnose(self, code: str) -> None:
        if code not in self.diagnostics:
            self.diagnostics.append(code)
        if self._diagnostic_sink is not None:
            try:
                self._diagnostic_sink(code)
            except Exception:
                pass

    def _require_factory_budget(self, deadline: float) -> None:
        if self.clock() >= deadline:
            raise JournalBudgetExhausted

    def _operational_error_exhausted_budget(
        self,
        error: OperationalError,
        deadline: float,
    ) -> bool:
        return self.clock() >= deadline or _is_sqlite_lock_error(error)


class NullRunRecorderFactory:
    def __init__(self, diagnostic: str | None = None) -> None:
        self.diagnostics = [] if diagnostic is None else [diagnostic]

    def start_run(self, _command: StartRunCommand | StartRunBuilder) -> RunRecorder:
        return NullRunRecorder(self.diagnostics)

    def resume_waiting_run(
        self,
        _conversation_id: int,
        _waiting_tool_call_id: str,
        _command: StartSegmentCommand | StartSegmentBuilder,
    ) -> RunRecorder:
        return NullRunRecorder(self.diagnostics)


def _is_sqlite_lock_error(error: OperationalError) -> bool:
    sqlite_error_code = getattr(error.orig, "sqlite_errorcode", None)
    return type(sqlite_error_code) is int and sqlite_error_code & 0xFF in {5, 6}


def _journal_enabled_from_env() -> bool:
    value = os.getenv("OFFERPILOT_AGENT_JOURNAL_ENABLED", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


__all__ = [
    "EventInput",
    "NullRunRecorderFactory",
    "NullRunRecorder",
    "RunRecorder",
    "RunRecorderFactory",
    "SafeRunRecorder",
    "StartRunBuilder",
    "StartSegmentBuilder",
    "SuspendedDisposition",
    "TerminalDisposition",
]
