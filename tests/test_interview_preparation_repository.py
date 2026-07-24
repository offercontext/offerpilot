from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock

import pytest
from sqlalchemy import select, text

from offerpilot.ai.interview_preparation_proposals import safe_empty_interview_preparation_proposal
from offerpilot.ai.types import Assistant
from offerpilot.db import init_database
from offerpilot.models import (
    Application,
    ApplicationEvent,
    InterviewPreparationProposal,
    Resume,
)
from offerpilot.repositories.interview_preparation_proposals import (
    InterviewPreparationConflictError,
    InterviewPreparationNotFound,
    InterviewPreparationProviderError,
    InterviewPreparationProposalsRepository,
)


JD_TEXT = "Build reliable APIs with Python."


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


def test_first_request_without_old_row_creates_lease_before_provider_and_calls_once(tmp_path) -> None:
    factory_a, ids = _setup(tmp_path)
    factory_b = init_database(tmp_path / "data.db")
    repository_a = InterviewPreparationProposalsRepository(factory_a)
    repository_b = InterviewPreparationProposalsRepository(factory_b)
    model = BlockingSafeEmptyModel()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_generate, repository_a, ids, "first-key", model)
        assert model.entered.wait(5)
        second_future = pool.submit(_generate, repository_b, ids, "first-key", model)
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
    repository = InterviewPreparationProposalsRepository(factory)
    model = FailingModel()

    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "unknown-key", model)

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "provider_unknown"
        assert row.provider_call_token
        assert row.provider_lease_until is not None
        assert row.provider_lease_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        original_token = row.provider_call_token

    retry = _generate(repository, ids, "unknown-key", SafeEmptyModel())
    assert retry.pending is True
    assert retry.attempt_status == "provider_unknown"
    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.provider_call_token == original_token
    factory.kw["bind"].dispose()


def test_expired_lease_takeover_atomically_bumps_revision_and_only_one_wins(tmp_path) -> None:
    factory_a, ids = _setup(tmp_path)
    factory_b = init_database(tmp_path / "data.db")
    repository_a = InterviewPreparationProposalsRepository(factory_a)
    repository_b = InterviewPreparationProposalsRepository(factory_b)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository_a, ids, "expired-key", FailingModel())
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        old_token = row.provider_call_token
        row.provider_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    model = BlockingSafeEmptyModel()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_generate, repository_a, ids, "expired-key", model)
        assert model.entered.wait(5)
        second_future = pool.submit(_generate, repository_b, ids, "expired-key", model)
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


def test_ready_different_snapshot_returns_409_and_original_ready_remains_stable(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    first = _generate(repository, ids, "stable-key", SafeEmptyModel())

    with pytest.raises(InterviewPreparationConflictError) as exc_info:
        _generate(repository, ids, "stable-key", SafeEmptyModel(), jd_text="Different JD")

    assert exc_info.value.code == "interview_preparation_idempotency_conflict"
    replay = _generate(repository, ids, "stable-key", SafeEmptyModel())
    assert replay.pending is False
    assert replay.proposal is not None
    assert replay.proposal.id == first.proposal.id  # type: ignore[union-attr]
    factory.kw["bind"].dispose()


def test_event_delete_keeps_history_readable_and_source_changed(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "event-history-key", SafeEmptyModel())
    with factory() as session:
        session.execute(text("DELETE FROM application_events WHERE id=:id"), {"id": ids[1]})
        session.commit()

    history = repository.list(ids[0])
    assert history[0].source_status == "source_changed"
    factory.kw["bind"].dispose()


def test_resume_delete_keeps_history_readable_and_source_changed(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "resume-history-key", SafeEmptyModel())
    with factory() as session:
        session.execute(text("DELETE FROM resumes WHERE id=:id"), {"id": ids[2]})
        session.commit()

    history = repository.list(ids[0])
    assert history[0].source_status == "source_changed"
    factory.kw["bind"].dispose()


def test_soft_deleted_application_returns_not_found_for_history(tmp_path) -> None:
    factory, ids = _setup(tmp_path)
    repository = InterviewPreparationProposalsRepository(factory)
    _generate(repository, ids, "application-history-key", SafeEmptyModel())
    with factory() as session:
        session.execute(
            text("UPDATE applications SET deleted_at=CURRENT_TIMESTAMP WHERE id=:id"),
            {"id": ids[0]},
        )
        session.commit()

    with pytest.raises(InterviewPreparationNotFound):
        repository.list(ids[0])
    factory.kw["bind"].dispose()
