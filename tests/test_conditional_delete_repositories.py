from datetime import datetime, timezone

from offerpilot.db import init_database
from offerpilot.repositories.application_events import (
    ApplicationEventCreate,
    ApplicationEventsRepository,
)
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository


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
