from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from offerpilot.ai.interview_preparation_proposals import safe_empty_interview_preparation_proposal
from offerpilot.ai.types import Assistant
from offerpilot.db import init_database
from offerpilot.models import (
    Application,
    ApplicationEvent,
    InterviewNote,
    InterviewPreparationProposal,
    KnowledgeEvidence,
    KnowledgeNoteEvidence,
    KnowledgeNoteVersion,
    Resume,
)
from offerpilot.repositories.interview_knowledge_capture import InterviewKnowledgeCaptureRepository
from offerpilot.repositories.json_contract import canonical_json
from offerpilot.repositories.interview_preparation_proposals import (
    InterviewPreparationConflictError,
    InterviewPreparationNotFound,
    InterviewPreparationProviderError,
    InterviewPreparationProposalsRepository,
    _InterviewPreparationLeaseHeartbeat,
)


JD_TEXT = "Build reliable APIs with Python."


class ManualClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class ControlledWaiter:
    def __init__(self) -> None:
        self.entered = Event()
        self._wake = Event()

    def __call__(self, timeout: float) -> bool:
        self.entered.set()
        released = self._wake.wait(timeout)
        self._wake.clear()
        return released

    def release_tick(self) -> None:
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()


class CountingWaiter(ControlledWaiter):
    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0
        self.second_call = Event()

    def __call__(self, timeout: float) -> bool:
        self.call_count += 1
        if self.call_count == 2:
            self.second_call.set()
        return super().__call__(timeout)


class FailingHeartbeatSessionFactory:
    def __init__(self, factory, *, fail_calls: int = 1) -> None:  # type: ignore[no-untyped-def]
        self.factory = factory
        self.fail_calls = fail_calls
        self.calls = 0
        self.failed = Event()

    def __call__(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls <= self.fail_calls:
            self.failed.set()
            raise SQLAlchemyError("injected heartbeat lock failure")
        return self.factory()


class DeferredFailingHeartbeatSessionFactory:
    def __init__(self, factory, *, fail_calls: int) -> None:  # type: ignore[no-untyped-def]
        self._factory = factory
        self._failing = FailingHeartbeatSessionFactory(factory, fail_calls=fail_calls)
        self.enabled = False

    @property
    def calls(self) -> int:
        return self._failing.calls

    @property
    def failed(self) -> Event:
        return self._failing.failed

    def __call__(self):  # type: ignore[no-untyped-def]
        if not self.enabled:
            return self._factory()
        return self._failing()


class CommitObservingSessionFactory:
    def __init__(self, factory) -> None:  # type: ignore[no-untyped-def]
        self.factory = factory
        self.enabled = False
        self.committed = Event()

    def __call__(self):  # type: ignore[no-untyped-def]
        session = self.factory()
        original_commit = session.commit

        def commit(*args, **kwargs):  # type: ignore[no-untyped-def]
            result = original_commit(*args, **kwargs)
            if self.enabled:
                self.committed.set()
            return result

        session.commit = commit  # type: ignore[method-assign]
        return session


class TrackingSession:
    def __init__(self, session, factory) -> None:  # type: ignore[no-untyped-def]
        self._session = session
        self._factory = factory

    def __enter__(self):  # type: ignore[no-untyped-def]
        self._session.__enter__()
        self._factory.active += 1
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        try:
            return self._session.__exit__(*args)
        finally:
            self._factory.active -= 1

    def __getattr__(self, name):  # type: ignore[no-untyped-def]
        return getattr(self._session, name)


class TrackingSessionFactory:
    def __init__(self, factory) -> None:  # type: ignore[no-untyped-def]
        self.factory = factory
        self.active = 0

    def __call__(self):  # type: ignore[no-untyped-def]
        return TrackingSession(self.factory(), self)


def _as_aware_for_test(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _setup(tmp_path):
    factory = init_database(tmp_path / "data.db")
    with factory() as session:
        application = Application(company_name="Acme", position_name="Backend", source="test")
        session.add(application)
        session.flush()
        event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            subtype="technical",
            round=2,
            scheduled_at=datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
            duration_minutes=45,
            status="todo",
        )
        resume = Resume(
            title="Backend Resume",
            name="Backend Resume",
            parse_status="text-ready",
            content_json=json.dumps(
                {"experience": [{"highlights": ["Built reliable API services"]}]},
                ensure_ascii=False,
            ),
        )
        session.add_all([event, resume])
        session.commit()
        ids = (application.id, event.id, resume.id)
    return factory, ids


class SafeEmptyModel:
    supports_json_schema = False

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return Assistant(
            content=json.dumps(safe_empty_interview_preparation_proposal(), ensure_ascii=False)
        )


class DistinctPreparationModel(SafeEmptyModel):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        payload = {
            "preparation_directions": [
                {
                    "id": f"direction-{self.label}",
                    "text": f"Prepare the {self.label} direction.",
                    "evidence_refs": [
                        {
                            "source": "jd",
                            "path": "/jd/text",
                            "excerpt": "Build reliable APIs with Python.",
                        }
                    ],
                }
            ],
            "story_prompts": [],
            "review_points": [],
            "interviewer_questions": [],
            "items_to_clarify": [],
        }
        return Assistant(content=json.dumps(payload, ensure_ascii=False))


class SessionClosedModel(SafeEmptyModel):
    def __init__(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.session_factory = session_factory

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        assert self.session_factory.active == 0
        return super().complete(messages, tools)


class FailingModel:
    supports_json_schema = False

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise TimeoutError("provider is unavailable")


class BlockingSafeEmptyModel(SafeEmptyModel):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self._lock = Lock()

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        with self._lock:
            self.calls += 1
        self.entered.set()
        assert self.release.wait(5)
        return Assistant(
            content=json.dumps(safe_empty_interview_preparation_proposal(), ensure_ascii=False)
        )


class BlockingDistinctPreparationModel(DistinctPreparationModel):
    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.entered = Event()
        self.release = Event()

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.entered.set()
        assert self.release.wait(5)
        return super().complete(messages, tools)


class EventDeletingModel(SafeEmptyModel):
    def __init__(self, factory, event_id: int) -> None:
        super().__init__()
        self.factory = factory
        self.event_id = event_id

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        with self.factory() as session:
            session.execute(text("DELETE FROM application_events WHERE id=:id"), {"id": self.event_id})
            session.commit()
        return Assistant(
            content=json.dumps(safe_empty_interview_preparation_proposal(), ensure_ascii=False)
        )


def _generate(repository, ids, key, model, *, jd_text=JD_TEXT):
    application_id, event_id, resume_id = ids
    return repository.create_generated(
        application_id=application_id,
        event_id=event_id,
        resume_id=resume_id,
        jd_text=jd_text,
        knowledge_selections=[],
        user_assertions=["I led the migration."],
        idempotency_key=key,
        model=model,
    )


def test_repository_uses_injected_utc_clock_and_production_lease_defaults(tmp_path) -> None:
    factory, _ = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))

    production_repository = InterviewPreparationProposalsRepository(factory)
    repository = InterviewPreparationProposalsRepository(
        factory,
        now_factory=clock.now,
    )

    assert production_repository._lease_seconds == 30
    assert production_repository._heartbeat_interval_seconds == 10
    assert repository._lease_seconds == 30
    assert repository._heartbeat_interval_seconds == 10
    assert repository._now_factory() == clock.current


def test_heartbeat_renew_once_extends_lease_with_fenced_owner(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    token = "heartbeat-owner-token"
    with factory() as session:
        row = InterviewPreparationProposal(
            application_id=ids[0],
            application_event_id=ids[1],
            resume_id=ids[2],
            idempotency_key="heartbeat-key-0001",
            attempt_status="generating",
            generation_revision=1,
            provider_call_token=token,
            provider_lease_until=(clock.now() + timedelta(seconds=30)).replace(tzinfo=None),
            input_snapshot_json="{}",
            source_fingerprint="source-fingerprint",
        )
        session.add(row)
        session.commit()
        attempt_id = row.id

    heartbeat = _InterviewPreparationLeaseHeartbeat(
        session_factory=factory,
        attempt_id=attempt_id,
        owner_revision=1,
        owner_token=token,
        lease_seconds=30,
        now_factory=clock.now,
    )
    clock.advance(seconds=31)

    assert heartbeat.renew_once() is True
    assert heartbeat.heartbeat_count == 1
    assert heartbeat.confirmed_ownership_lost is False
    assert heartbeat.heartbeat_uncertain is False
    with factory() as session:
        row = session.get(InterviewPreparationProposal, attempt_id)
        assert row is not None
        assert row.provider_lease_until == (clock.now() + timedelta(seconds=30)).replace(
            tzinfo=None
            )


def test_heartbeat_retries_one_transient_lock_and_renews_once(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    failing_factory = FailingHeartbeatSessionFactory(factory, fail_calls=1)
    token = "heartbeat-retry-token"
    with factory() as session:
        row = InterviewPreparationProposal(
            application_id=ids[0],
            application_event_id=ids[1],
            resume_id=ids[2],
            idempotency_key="heartbeat-retry-key",
            attempt_status="generating",
            generation_revision=1,
            provider_call_token=token,
            provider_lease_until=(clock.now() + timedelta(seconds=30)).replace(
                tzinfo=None
            ),
            input_snapshot_json="{}",
            source_fingerprint="source-fingerprint",
        )
        session.add(row)
        session.commit()

    heartbeat = _InterviewPreparationLeaseHeartbeat(
        session_factory=failing_factory,
        attempt_id=row.id,
        owner_revision=1,
        owner_token=token,
        lease_seconds=30,
        now_factory=clock.now,
    )

    assert heartbeat.renew_once() is True
    assert failing_factory.calls == 2
    assert heartbeat.heartbeat_count == 1
    assert heartbeat.heartbeat_uncertain is False
    assert heartbeat.confirmed_ownership_lost is False


def test_heartbeat_uncertain_stops_future_renewals(
    tmp_path,
) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    failing_factory = FailingHeartbeatSessionFactory(factory, fail_calls=2)
    waiter = CountingWaiter()
    with factory() as session:
        row = InterviewPreparationProposal(
            application_id=ids[0],
            application_event_id=ids[1],
            resume_id=ids[2],
            idempotency_key="heartbeat-uncertain-key",
            attempt_status="generating",
            generation_revision=1,
            provider_call_token="heartbeat-uncertain-token",
            provider_lease_until=(clock.now() + timedelta(seconds=30)).replace(
                tzinfo=None
            ),
            input_snapshot_json="{}",
            source_fingerprint="source-fingerprint",
        )
        session.add(row)
        session.commit()

    heartbeat = _InterviewPreparationLeaseHeartbeat(
        session_factory=failing_factory,
        attempt_id=row.id,
        owner_revision=1,
        owner_token="heartbeat-uncertain-token",
        lease_seconds=30,
        now_factory=clock.now,
        waiter=waiter,
    )
    heartbeat.start()
    assert waiter.entered.wait(1)
    waiter.release_tick()
    assert failing_factory.failed.wait(1)
    assert heartbeat.heartbeat_uncertain is True

    waiter.release_tick()
    assert waiter.second_call.wait(0.1) is False
    heartbeat.stop_and_join()
    assert failing_factory.calls == 2


def test_heartbeat_uncertain_still_completes_final_fencing_cas(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    heartbeat_factory = DeferredFailingHeartbeatSessionFactory(factory, fail_calls=2)
    waiter = ControlledWaiter()
    repository = InterviewPreparationProposalsRepository(
        heartbeat_factory,
        lease_seconds=1,
        heartbeat_interval_seconds=10,
        now_factory=clock.now,
        waiter=waiter,
    )
    model = BlockingSafeEmptyModel()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_generate, repository, ids, "uncertain-final-cas-key", model)
        assert model.entered.wait(5)
        assert waiter.entered.wait(5)
        heartbeat_factory.enabled = True
        waiter.release_tick()
        assert heartbeat_factory.failed.wait(1)
        model.release.set()
        result = future.result(timeout=5)

    assert result.created is True
    assert result.pending is False
    assert result.attempt_status == "ready"
    assert model.calls == 1
    assert heartbeat_factory.calls == 3
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "ready"
        assert row.proposal_status == "safe_empty"
        assert row.proposal_json == canonical_json(safe_empty_interview_preparation_proposal())


def test_slow_provider_renews_expired_lease_and_calls_provider_once(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    waiter = ControlledWaiter()
    observed_factory = CommitObservingSessionFactory(factory)
    repository = InterviewPreparationProposalsRepository(
        observed_factory,
        lease_seconds=1,
        heartbeat_interval_seconds=10,
        now_factory=clock.now,
        waiter=waiter,
    )
    model = BlockingSafeEmptyModel()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_generate, repository, ids, "slow-heartbeat-key", model)
        assert model.entered.wait(5)
        assert waiter.entered.wait(5)
        observed_factory.enabled = True
        observed_factory.committed.clear()
        clock.advance(seconds=30)
        waiter.release_tick()
        assert observed_factory.committed.wait(1)

        with factory() as session:
            row = session.scalar(select(InterviewPreparationProposal))
            lease_until = _as_aware_for_test(row.provider_lease_until) if row else None
        assert lease_until is not None and lease_until > clock.now()

        model.release.set()
        result = future.result(timeout=5)

    assert result.created is True
    assert result.pending is False
    assert result.attempt_status == "ready"
    assert model.calls == 1


def test_expired_lease_without_takeover_can_persist_valid_provider_result(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    repository = InterviewPreparationProposalsRepository(factory, now_factory=clock.now)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "expired-final-key-01", FailingModel())

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        snapshot = json.loads(row.input_snapshot_json)
        source_fingerprint = row.source_fingerprint
        row.attempt_status = "generating"
        row.generation_revision = 2
        row.provider_call_token = "expired-final-owner"
        row.provider_lease_until = (clock.now() - timedelta(seconds=1)).replace(tzinfo=None)
        session.commit()

    result = repository._call_and_store(
        model=SafeEmptyModel(),
        owner_revision=2,
        owner_token="expired-final-owner",
        application_id=ids[0],
        event_id=ids[1],
        resume_id=ids[2],
        jd_text=JD_TEXT,
        knowledge_selections=[],
        user_assertions=["I led the migration."],
        idempotency_key="expired-final-key-01",
        source_fingerprint=source_fingerprint,
        snapshot=snapshot,
        on_diagnostic=None,
    )

    assert result.pending is False
    assert result.attempt_status == "ready"


def test_heartbeat_confirms_ownership_loss_after_token_changes(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    token = "old-heartbeat-token"
    with factory() as session:
        row = InterviewPreparationProposal(
            application_id=ids[0],
            application_event_id=ids[1],
            resume_id=ids[2],
            idempotency_key="heartbeat-loss-key",
            attempt_status="generating",
            generation_revision=1,
            provider_call_token=token,
            provider_lease_until=(clock.now() + timedelta(seconds=30)).replace(tzinfo=None),
            input_snapshot_json="{}",
            source_fingerprint="source-fingerprint",
        )
        session.add(row)
        session.commit()
        attempt_id = row.id
        row.provider_call_token = "new-owner-token"
        session.commit()

    heartbeat = _InterviewPreparationLeaseHeartbeat(
        session_factory=factory,
        attempt_id=attempt_id,
        owner_revision=1,
        owner_token=token,
        lease_seconds=30,
        now_factory=clock.now,
    )

    assert heartbeat.renew_once() is False
    assert heartbeat.confirmed_ownership_lost is True
    assert heartbeat.heartbeat_uncertain is False


class _FailingHeartbeatSession:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *_args):  # type: ignore[no-untyped-def]
        return False

    def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        from sqlalchemy.exc import OperationalError

        raise OperationalError("locked", {}, RuntimeError("locked"))


class _FailingHeartbeatFactory:
    def __call__(self):  # type: ignore[no-untyped-def]
        return _FailingHeartbeatSession()


def test_heartbeat_lock_failure_is_uncertain_not_confirmed_loss(tmp_path) -> None:
    _setup(tmp_path)
    heartbeat = _InterviewPreparationLeaseHeartbeat(
        session_factory=_FailingHeartbeatFactory(),
        attempt_id=1,
        owner_revision=1,
        owner_token="heartbeat-token",
        lease_seconds=30,
        now_factory=lambda: datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc),
    )

    assert heartbeat.renew_once() is False
    assert heartbeat.confirmed_ownership_lost is False
    assert heartbeat.heartbeat_uncertain is True


def test_provider_error_stops_heartbeat_worker_in_cleanup(monkeypatch, tmp_path) -> None:
    instances = []

    class TrackingHeartbeat:
        confirmed_ownership_lost = False
        heartbeat_uncertain = False

        def __init__(self, **_kwargs):
            self.started = False
            self.stopped = False
            instances.append(self)

        def start(self) -> None:
            self.started = True

        def stop_and_join(self) -> None:
            self.stopped = True

    monkeypatch.setattr(
        "offerpilot.repositories.interview_preparation_proposals._InterviewPreparationLeaseHeartbeat",
        TrackingHeartbeat,
    )
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)

    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "heartbeat-cleanup-key", FailingModel())

    assert len(instances) == 1
    assert instances[0].started is True
    assert instances[0].stopped is True


def test_first_request_without_old_row_creates_lease_before_provider_and_calls_once(tmp_path) -> None:
    factory_a, ids = _setup(tmp_path)
    factory_b = init_database(tmp_path / "data.db")
    repository_a = InterviewPreparationProposalsRepository(factory_a)
    repository_b = InterviewPreparationProposalsRepository(factory_b)
    model = BlockingSafeEmptyModel()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_generate, repository_a, ids, "first-key-00000001", model)
        assert model.entered.wait(5)
        second_future = pool.submit(_generate, repository_b, ids, "first-key-00000001", model)
        second = second_future.result(timeout=5)
        assert second.pending is True
        assert second.attempt_status == "generating"
        model.release.set()
        first = first_future.result(timeout=5)

    assert first.created is True
    assert first.proposal is not None
    assert model.calls == 1
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "ready"
        assert row.generation_revision == 1
        assert row.provider_call_token == ""
    factory_a.kw["bind"].dispose()
    factory_b.kw["bind"].dispose()


def test_provider_unknown_cas_preserves_token_and_unexpired_lease(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    repository = InterviewPreparationProposalsRepository(factory, now_factory=clock.now)
    model = FailingModel()

    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "unknown-key-0000001", model)

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "provider_unknown"
        assert row.provider_call_token
        assert row.provider_lease_until is not None
        assert row.provider_lease_until.replace(tzinfo=timezone.utc) > clock.now()
        original_token = row.provider_call_token

    retry = _generate(repository, ids, "unknown-key-0000001", SafeEmptyModel())
    assert retry.pending is True
    assert retry.attempt_status == "provider_unknown"
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.provider_call_token == original_token
    factory.kw["bind"].dispose()


def test_source_deletion_during_provider_call_invalidates_attempt_without_ready_result(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)

    with pytest.raises(InterviewPreparationConflictError) as exc_info:
        _generate(repository, ids, "event-drift-key-0001", EventDeletingModel(factory, ids[1]))

    assert exc_info.value.code == "interview_preparation_source_conflict"
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "invalidated"
        assert row.proposal_json == ""
    factory.kw["bind"].dispose()

def test_expired_lease_takeover_atomically_bumps_revision_and_only_one_wins(tmp_path) -> None:
    factory_a, ids = _setup(tmp_path)
    factory_b = init_database(tmp_path / "data.db")
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    repository_a = InterviewPreparationProposalsRepository(factory_a, now_factory=clock.now)
    repository_b = InterviewPreparationProposalsRepository(factory_b, now_factory=clock.now)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository_a, ids, "expired-key-0000001", FailingModel())
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        old_token = row.provider_call_token
        row.provider_lease_until = (clock.now() - timedelta(seconds=1)).replace(tzinfo=None)
        session.commit()

    model = BlockingSafeEmptyModel()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_generate, repository_a, ids, "expired-key-0000001", model)
        assert model.entered.wait(5)
        second_future = pool.submit(_generate, repository_b, ids, "expired-key-0000001", model)
        second = second_future.result(timeout=5)
        model.release.set()
        first = first_future.result(timeout=5)

    assert sorted([first.pending, second.pending]) == [False, True]
    assert model.calls == 1
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "ready"
        assert row.generation_revision == 2
        assert row.provider_call_token == ""
        assert old_token != row.provider_call_token
    factory_a.kw["bind"].dispose()
    factory_b.kw["bind"].dispose()


def test_takeover_closes_database_session_before_provider_call(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    seed_repository = InterviewPreparationProposalsRepository(factory, now_factory=clock.now)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(seed_repository, ids, "session-close-key-0001", FailingModel())

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        row.provider_lease_until = (clock.now() - timedelta(seconds=1)).replace(tzinfo=None)
        session.commit()

    tracking_factory = TrackingSessionFactory(factory)
    repository = InterviewPreparationProposalsRepository(
        tracking_factory,
        now_factory=clock.now,
    )
    result = _generate(repository, ids, "session-close-key-0001", SessionClosedModel(tracking_factory))

    assert result.attempt_status == "ready"
    assert result.pending is False
    assert tracking_factory.active == 0
    factory.kw["bind"].dispose()


def test_late_old_provider_result_cannot_overwrite_new_owner_ready_result(tmp_path) -> None:
    factory_a, ids = _setup(tmp_path)
    factory_b = init_database(tmp_path / "data.db")
    clock = ManualClock(datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc))
    repository_a = InterviewPreparationProposalsRepository(factory_a, now_factory=clock.now)
    repository_b = InterviewPreparationProposalsRepository(factory_b, now_factory=clock.now)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository_a, ids, "late-takeover-key-01", FailingModel())

    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        snapshot = json.loads(row.input_snapshot_json)
        source_fingerprint = row.source_fingerprint
        row.attempt_status = "generating"
        row.generation_revision = 1
        row.provider_call_token = "old-owner-token"
        row.provider_lease_until = (clock.now() - timedelta(seconds=1)).replace(tzinfo=None)
        session.commit()

    old_model = BlockingDistinctPreparationModel("old")
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(
            repository_a._call_and_store,
            model=old_model,
            owner_revision=1,
            owner_token="old-owner-token",
            application_id=ids[0],
            event_id=ids[1],
            resume_id=ids[2],
            jd_text=JD_TEXT,
            knowledge_selections=[],
            user_assertions=["I led the migration."],
            idempotency_key="late-takeover-key-01",
            source_fingerprint=source_fingerprint,
            snapshot=snapshot,
            on_diagnostic=None,
        )
        assert old_model.entered.wait(5)
        new_result = _generate(
            repository_b,
            ids,
            "late-takeover-key-01",
            DistinctPreparationModel("new"),
        )
        old_model.release.set()
        old_result = old_future.result(timeout=5)

    assert new_result.attempt_status == "ready"
    assert old_result.attempt_status == "ready"
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "ready"
        assert row.generation_revision == 2
        assert row.proposal_hash == new_result.proposal.proposal_hash  # type: ignore[union-attr]
        assert row.proposal_json == new_result.proposal.proposal_json  # type: ignore[union-attr]
        assert '"direction-new"' in row.proposal_json
        assert '"direction-old"' not in row.proposal_json
        assert row.provider_call_token == ""
        assert row.provider_lease_until is None
    factory_a.kw["bind"].dispose()
    factory_b.kw["bind"].dispose()


def test_ready_different_snapshot_returns_409_and_original_ready_remains_stable(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    first = _generate(repository, ids, "stable-key-0000001", SafeEmptyModel())

    with pytest.raises(InterviewPreparationConflictError) as exc_info:
        _generate(repository, ids, "stable-key-0000001", SafeEmptyModel(), jd_text="Different JD")

    assert exc_info.value.code == "interview_preparation_idempotency_conflict"
    replay = _generate(repository, ids, "stable-key-0000001", SafeEmptyModel())
    assert replay.pending is False
    assert replay.proposal is not None
    assert replay.proposal.id == first.proposal.id  # type: ignore[union-attr]
    factory.kw["bind"].dispose()


def test_same_knowledge_set_in_different_order_reuses_idempotent_proposal(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    with factory() as session:
        note = InterviewNote(
            application_id=ids[0],
            application_event_id=ids[1],
            company="Acme",
            position="Backend",
            questions="Describe the migration.",
            self_reflection="I explained the rollback plan.",
            difficulty_points="Clarify the signal.",
            mood="steady",
        )
        session.add(note)
        session.commit()
        note_id = note.id

    capture = InterviewKnowledgeCaptureRepository(factory)
    selected = [
        {"fragment_id": "questions", "path": "/questions", "start": 0, "end": 23, "text": "Describe the migration."},
        {"fragment_id": "reflection", "path": "/self_reflection", "start": 0, "end": 30, "text": "I explained the rollback plan."},
    ]
    attempt = capture.prepare_preview(note_id, "capture-order-key", "direct", selected)
    confirmed = capture.confirm(
        note_id,
        "capture-order-key",
        attempt.note_fingerprint,
        "Interview preparation notes",
        attempt.preview["blocks"],
    )
    with factory() as session:
        version = session.get(KnowledgeNoteVersion, confirmed.version_id)
        assert version is not None
        evidence_ids = list(
            session.scalars(
                select(KnowledgeEvidence.id)
                .join(KnowledgeNoteEvidence, KnowledgeNoteEvidence.evidence_id == KnowledgeEvidence.id)
                .where(KnowledgeNoteEvidence.note_version_id == version.id)
            )
        )
    assert len(evidence_ids) == 2

    with factory() as session:
        second_note = InterviewNote(
            application_id=ids[0],
            application_event_id=None,
            company="Acme",
            position="Backend",
            questions="Discuss observability.",
            self_reflection="I described the signal.",
            difficulty_points="Clarify the alert.",
            mood="steady",
        )
        session.add(second_note)
        session.commit()
        second_note_id = second_note.id
    second_attempt = capture.prepare_preview(
        second_note_id,
        "capture-order-key-2",
        "direct",
        [{"fragment_id": "questions", "path": "/questions", "start": 0, "end": 22, "text": "Discuss observability."}],
    )
    second_confirmed = capture.confirm(
        second_note_id,
        "capture-order-key-2",
        second_attempt.note_fingerprint,
        "Second interview notes",
        second_attempt.preview["blocks"],
    )
    with factory() as session:
        second_version = session.get(KnowledgeNoteVersion, second_confirmed.version_id)
        assert second_version is not None
        second_evidence_ids = list(
            session.scalars(
                select(KnowledgeEvidence.id)
                .join(KnowledgeNoteEvidence, KnowledgeNoteEvidence.evidence_id == KnowledgeEvidence.id)
                .where(KnowledgeNoteEvidence.note_version_id == second_version.id)
            )
        )
    assert len(second_evidence_ids) == 1

    repository = InterviewPreparationProposalsRepository(factory)
    first = repository.create_generated(
        application_id=ids[0],
        event_id=ids[1],
        resume_id=ids[2],
        jd_text=JD_TEXT,
        knowledge_selections=[
            {"note_version_id": second_version.id, "evidence_ids": second_evidence_ids},
            {"note_version_id": version.id, "evidence_ids": [evidence_ids[1]]},
            {"note_version_id": version.id, "evidence_ids": [evidence_ids[0]]},
        ],
        user_assertions=[],
        idempotency_key="knowledge-order-key-01",
        model=SafeEmptyModel(),
    )
    replay = repository.create_generated(
        application_id=ids[0],
        event_id=ids[1],
        resume_id=ids[2],
        jd_text=JD_TEXT,
        knowledge_selections=[
            {"note_version_id": version.id, "evidence_ids": [evidence_ids[0]]},
            {"note_version_id": version.id, "evidence_ids": [evidence_ids[1]]},
            {"note_version_id": second_version.id, "evidence_ids": second_evidence_ids},
        ],
        user_assertions=[],
        idempotency_key="knowledge-order-key-01",
        model=SafeEmptyModel(),
    )

    assert first.proposal is not None
    assert replay.proposal is not None
    assert replay.created is False
    assert replay.proposal.id == first.proposal.id
    with factory() as session:
        row = session.get(InterviewPreparationProposal, first.proposal.id)
        assert row is not None
        snapshot = json.loads(row.input_snapshot_json)
    ordered = snapshot["knowledge_evidence"]
    assert [(item["note_version_id"], item["id"]) for item in ordered] == sorted(
        (item["note_version_id"], item["id"]) for item in ordered
    )
    assert [item["provider_path"] for item in ordered] == [
        f"/knowledge_evidence/{index:03d}" for index in range(1, len(ordered) + 1)
    ]
    factory.kw["bind"].dispose()


def test_late_stale_owner_cannot_invalidate_ready_proposal(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    first = _generate(repository, ids, "late-owner-key-0001", SafeEmptyModel())
    assert first.proposal is not None

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        snapshot = json.loads(row.input_snapshot_json)

    result = repository._call_and_store(
        model=SafeEmptyModel(),
        owner_revision=1,
        owner_token="stale-provider-token",
        application_id=ids[0],
        event_id=ids[1],
        resume_id=ids[2],
        jd_text=JD_TEXT,
        knowledge_selections=[],
        user_assertions=["I led the migration."],
        idempotency_key="late-owner-key-0001",
        source_fingerprint="stale-fingerprint",
        snapshot=snapshot,
        on_diagnostic=None,
    )

    assert result.pending is False
    assert result.proposal is not None
    assert result.proposal.id == first.proposal.id
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "ready"
    factory.kw["bind"].dispose()


def test_invalidated_attempt_is_never_returned_as_pending(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "invalidated-key-0001", FailingModel())
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        row.attempt_status = "invalidated"
        row.invalidation_reason = "source_conflict"
        session.commit()

    with pytest.raises(InterviewPreparationConflictError) as exc_info:
        _generate(repository, ids, "invalidated-key-0001", SafeEmptyModel())
    assert exc_info.value.code == "interview_preparation_attempt_invalidated"
    factory.kw["bind"].dispose()


def test_event_delete_keeps_history_readable_and_source_changed(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "event-history-key-01", SafeEmptyModel())
    with factory() as session:
        session.execute(text("DELETE FROM application_events WHERE id=:id"), {"id": ids[1]})
        session.commit()

    history = repository.list(ids[0])
    assert history[0].source_status == "source_changed"
    factory.kw["bind"].dispose()


def test_resume_delete_keeps_history_readable_and_source_changed(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "resume-history-key-1", SafeEmptyModel())
    with factory() as session:
        session.execute(text("DELETE FROM resumes WHERE id=:id"), {"id": ids[2]})
        session.commit()

    history = repository.list(ids[0])
    assert history[0].source_status == "source_changed"
    factory.kw["bind"].dispose()


def test_soft_deleted_application_returns_not_found_for_history(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "application-history-key-1", SafeEmptyModel())
    with factory() as session:
        session.execute(
            text("UPDATE applications SET deleted_at=CURRENT_TIMESTAMP WHERE id=:id"),
            {"id": ids[0]},
        )
        session.commit()

    with pytest.raises(InterviewPreparationNotFound):
        repository.list(ids[0])
    factory.kw["bind"].dispose()
