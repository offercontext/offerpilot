from datetime import datetime, timezone

import pytest

from offerpilot.db import init_database
from offerpilot.models import (
    APPLICATION_FOREIGN_KEY_MODELS,
    ApplicationEvent,
    ApplicationEvidenceBundle,
    ApplicationMaterialKit,
    Base,
    Conversation,
    InterviewNote,
    JDAnalysis,
    MockSession,
    Offer,
    Question,
    Resume,
    ResumeMatch,
)
from offerpilot.repositories.application_events import (
    ApplicationEventCreate,
    ApplicationEventsRepository,
)
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository


def _application_dependency(model, application_id):
    if model is ApplicationEvent:
        return model(application_id=application_id, event_type="interview")
    if model is InterviewNote:
        return model(application_id=application_id, company="A", position="Engineer")
    if model is Offer:
        return model(application_id=application_id, company_name="A", position_name="Engineer")
    if model is JDAnalysis:
        return model(application_id=application_id, jd_text="JD", result="{}")
    if model is ApplicationMaterialKit:
        return model(application_id=application_id)
    if model is ApplicationEvidenceBundle:
        return model(
            application_id=application_id,
            sequence=1,
            submitted_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            confirmed_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            confirmation_kind="user_asserted",
            idempotency_key="8f4a6b48-b554-49a0-bccf-b1bf211ef824",
            snapshot_json="{}",
            bundle_sha256="0" * 64,
        )
    if model is Question:
        return model(application_id=application_id, question="Why?")
    raise AssertionError(f"dependency {model.__name__} needs related rows")


def test_application_dependency_test_matrix_covers_every_model_fk():
    actual = {
        mapper.class_
        for mapper in Base.registry.mappers
        if any(
            foreign_key.target_fullname == "applications.id"
            for column in mapper.local_table.columns
            for foreign_key in column.foreign_keys
        )
    }

    assert set(APPLICATION_FOREIGN_KEY_MODELS) == actual


@pytest.mark.parametrize("dependency_model", APPLICATION_FOREIGN_KEY_MODELS)
def test_application_delete_if_matches_rejects_every_fk_dependency(tmp_path, dependency_model):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)
    app = repo.create(ApplicationCreate(company_name="A", position_name="Engineer"))
    expected = {
        "company_name": app.company_name,
        "position_name": app.position_name,
        "job_url": app.job_url,
        "status": app.status,
        "source": app.source,
        "notes": app.notes,
        "applied_at": app.applied_at.isoformat(),
        "closed_reason": app.closed_reason,
        "updated_at": app.updated_at.isoformat(),
    }
    with session_factory() as session:
        if dependency_model is ResumeMatch:
            resume = Resume(name="Main")
            session.add(resume)
            session.flush()
            dependency = ResumeMatch(
                resume_id=resume.id,
                application_id=app.id,
                jd_text="JD",
                result="{}",
            )
        elif dependency_model is MockSession:
            conversation = Conversation(title="Mock")
            session.add(conversation)
            session.flush()
            dependency = MockSession(
                conversation_id=conversation.id,
                application_id=app.id,
                title="Mock",
                role="Engineer",
            )
        else:
            dependency = _application_dependency(dependency_model, app.id)
        session.add(dependency)
        session.commit()
        dependency_id = dependency.id

    assert repo.delete_if_matches(app.id, expected) is False
    assert repo.get(app.id) is not None
    with session_factory() as session:
        preserved = session.get(dependency_model, dependency_id)
        assert preserved is not None
        assert preserved.application_id == app.id


def test_application_delete_if_matches_is_conditional(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    app = repo.create(ApplicationCreate(company_name="A", position_name="Engineer"))
    expected = {
        "company_name": app.company_name,
        "position_name": app.position_name,
        "job_url": app.job_url,
        "status": app.status,
        "source": app.source,
        "notes": app.notes,
        "applied_at": app.applied_at.isoformat(),
        "closed_reason": app.closed_reason,
        "updated_at": app.updated_at.isoformat(),
    }

    assert repo.delete_if_matches(app.id, {**expected, "notes": "changed"}) is False
    assert repo.get(app.id) is not None
    assert repo.delete_if_matches(app.id, expected) is True
    assert repo.get(app.id) is None


def test_event_delete_if_matches_is_conditional(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="A", position_name="Engineer"))
    event = events.create(
        ApplicationEventCreate(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            duration_minutes=60,
            location="Room A",
        )
    )
    expected = {
        "application_id": app.id,
        "event_type": "interview",
        "subtype": "",
        "tags": [],
        "round": 0,
        "scheduled_at": "2026-08-01T10:00:00Z",
        "duration_minutes": 60,
        "location": "Room A",
        "notes": "",
        "remind_at": None,
        "status": "todo",
    }

    assert events.delete_if_matches(event.id, {**expected, "location": "changed"}) is False
    assert events.get(event.id) is not None
    assert events.delete_if_matches(event.id, expected) is True
    assert events.get(event.id) is None


def test_note_delete_if_matches_is_conditional(tmp_path):
    repo = NotesRepository(init_database(tmp_path / "data.db"))
    note = repo.create(
        NoteCreate(
            company="A",
            position="Engineer",
            date="2026-08-01",
            questions="Original",
        )
    )
    expected = {
        "application_id": None,
        "company": "A",
        "position": "Engineer",
        "round": "",
        "date": "2026-08-01",
        "questions": "Original",
        "self_reflection": "",
        "difficulty_points": "",
        "mood": "",
    }

    assert repo.delete_if_matches(note.id, {**expected, "questions": "changed"}) is False
    assert repo.get(note.id) is not None
    assert repo.delete_if_matches(note.id, expected) is True
    assert repo.get(note.id) is None
