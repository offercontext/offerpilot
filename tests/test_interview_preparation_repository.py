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
    InterviewNote,
    InterviewPreparationProposal,
    KnowledgeEvidence,
    KnowledgeNoteEvidence,
    KnowledgeNoteVersion,
    Resume,
)
from offerpilot.repositories.interview_knowledge_capture import InterviewKnowledgeCaptureRepository
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
    repository = InterviewPreparationProposalsRepository(factory)
    model = FailingModel()

    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository, ids, "unknown-key-0000001", model)

    with factory() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        assert row.attempt_status == "provider_unknown"
        assert row.provider_call_token
        assert row.provider_lease_until is not None
        assert row.provider_lease_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
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
    repository_a = InterviewPreparationProposalsRepository(factory_a)
    repository_b = InterviewPreparationProposalsRepository(factory_b)
    with pytest.raises(InterviewPreparationProviderError):
        _generate(repository_a, ids, "expired-key-0000001", FailingModel())
    with factory_a() as session:
        row = session.scalar(select(InterviewPreparationProposal))
        assert row is not None
        old_token = row.provider_call_token
        row.provider_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
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
