from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from offerpilot.ai.types import Assistant
from offerpilot.db import init_database
from offerpilot.models import Application, ApplicationEvent, InterviewNote, InterviewReviewProposal
from offerpilot.repositories.interview_review_proposals import (
    InterviewReviewConflictError,
    InterviewReviewEventRequired,
    InterviewReviewNotFound,
    InterviewReviewProposalsRepository,
)


def _payload() -> dict[str, object]:
    return {
        "summary": {
            "text": "The reflection highlights a tradeoff to revisit.",
            "evidence_refs": [
                {
                    "source": "interview_note",
                    "path": "/self_reflection",
                    "excerpt": "I struggled to explain the tradeoff.",
                }
            ],
        },
        "observations": [
            {
                "id": "observation-1",
                "text": "The tradeoff was difficult to explain.",
                "evidence_refs": [
                    {
                        "source": "interview_note",
                        "path": "/difficulty_points",
                        "excerpt": "Explaining tradeoffs",
                    }
                ],
            }
        ],
        "clarifications": [],
        "practice_focuses": [],
        "next_questions": [],
    }


class FakeModel:
    def __init__(self, session_factory=None, note_id: int | None = None) -> None:
        self.calls = 0
        self.session_factory = session_factory
        self.note_id = note_id

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.session_factory is not None and self.note_id is not None:
            with self.session_factory() as session:
                note = session.get(InterviewNote, self.note_id)
                assert note is not None
                note.self_reflection = "Changed during generation"
                session.commit()
        return Assistant(content=json.dumps(_payload(), ensure_ascii=False))


def _setup(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    with session_factory() as session:
        application = Application(company_name="Acme", position_name="Backend", source="web")
        session.add(application)
        session.flush()
        event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            subtype="technical",
            round=2,
            scheduled_at=datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
            duration_minutes=45,
            status="done",
        )
        note = InterviewNote(
            application_id=application.id,
            company="Acme",
            position="Backend",
            round="technical",
            date="2026-07-20",
            questions="How would you design a cache?",
            self_reflection="I struggled to explain the tradeoff.",
            difficulty_points="Explaining tradeoffs",
            mood="nervous",
        )
        session.add_all([event, note])
        session.flush()
        note.application_event_id = event.id
        session.commit()
        return session_factory, application.id, event.id, note.id


def test_create_generated_freezes_snapshot_and_reuses_same_key(tmp_path) -> None:
    session_factory, _, _, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    model = FakeModel()

    first, created = repository.create_generated(note_id, "attempt-1", model)
    second, reused = repository.create_generated(note_id, "attempt-1", model)

    assert created is True
    assert reused is False
    assert first.id == second.id
    assert model.calls == 1
    assert first.source_fingerprint
    assert json.loads(first.input_snapshot_json)["event"]["event_type"] == "interview"
    assert "location" not in json.loads(first.input_snapshot_json)["event"]


def test_create_generated_rechecks_fingerprint_before_insert(tmp_path) -> None:
    session_factory, _, _, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    model = FakeModel(session_factory, note_id)

    with pytest.raises(InterviewReviewConflictError):
        repository.create_generated(note_id, "attempt-drift", model)

    with session_factory() as session:
        assert session.query(InterviewReviewProposal).count() == 0


def test_deleted_event_history_is_source_changed_but_generation_is_event_required(tmp_path) -> None:
    session_factory, _, event_id, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    repository.create_generated(note_id, "attempt-1", FakeModel())
    with session_factory() as session:
        event = session.get(ApplicationEvent, event_id)
        assert event is not None
        session.delete(event)
        session.commit()

    history = repository.list(note_id)
    assert history[0].source_status == "source_changed"
    with pytest.raises(InterviewReviewEventRequired):
        repository.create_generated(note_id, "attempt-2", FakeModel())


def test_non_null_missing_event_id_is_not_found(tmp_path) -> None:
    session_factory, _, _, note_id = _setup(tmp_path)
    with session_factory() as session:
        session.commit()
        session.execute(text("PRAGMA foreign_keys=OFF"))
        session.execute(
            text("UPDATE interview_notes SET application_event_id = 9999 WHERE id = :id"),
            {"id": note_id},
        )
        session.commit()
        session.execute(text("PRAGMA foreign_keys=ON"))

    with pytest.raises(InterviewReviewNotFound):
        InterviewReviewProposalsRepository(session_factory).create_generated(
            note_id, "attempt-1", FakeModel()
        )


def test_history_source_algorithm_does_not_require_current_event_when_id_changed(tmp_path) -> None:
    session_factory, _, event_id, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    repository.create_generated(note_id, "attempt-1", FakeModel())
    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.application_event_id = None
        session.commit()

    history = repository.list(note_id)
    assert history[0].source_status == "source_changed"
    assert event_id


def test_soft_deleted_application_hides_notes_and_proposals(tmp_path) -> None:
    session_factory, application_id, _, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    repository.create_generated(note_id, "attempt-1", FakeModel())
    with session_factory() as session:
        application = session.get(Application, application_id)
        assert application is not None
        application.deleted_at = datetime.now(timezone.utc)
        session.commit()

    with pytest.raises(InterviewReviewNotFound):
        repository.list(note_id)
    with pytest.raises(InterviewReviewNotFound):
        repository.create_generated(note_id, "attempt-2", FakeModel())


def test_edit_unbind_and_rebind_do_not_overwrite_old_proposals(tmp_path) -> None:
    session_factory, application_id, _, note_id = _setup(tmp_path)
    repository = InterviewReviewProposalsRepository(session_factory)
    first, _ = repository.create_generated(note_id, "attempt-1", FakeModel())
    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.application_event_id = None
        session.commit()
        event = ApplicationEvent(
            application_id=application_id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 21, 10, tzinfo=timezone.utc),
            duration_minutes=30,
        )
        session.add(event)
        session.flush()
        note.application_event_id = event.id
        session.commit()

    second, _ = repository.create_generated(note_id, "attempt-2", FakeModel())
    assert first.id != second.id
    assert len(repository.list(note_id)) == 2
    assert {item.source_status for item in repository.list(note_id)} == {"source_changed", "current"}
