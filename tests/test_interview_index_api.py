from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.repositories.application_events import ApplicationEventCreate, ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository


def _ready(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    applications = ApplicationsRepository(session_factory_for_data_dir(tmp_path))
    application = applications.create(ApplicationCreate(company_name="Acme", position_name="Backend"))
    event = ApplicationEventsRepository(session_factory_for_data_dir(tmp_path)).create(
        ApplicationEventCreate(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 28, 9, tzinfo=timezone.utc),
            duration_minutes=60,
        )
    )
    note = NotesRepository(session_factory_for_data_dir(tmp_path)).create(
        NoteCreate(
            application_id=application.id,
            application_event_id=event.id,
            company="Acme",
            position="Backend",
            questions="Tell me about APIs",
        )
    )
    return client, applications, application, event, note


def test_interview_index_lists_visible_events_and_bound_notes(tmp_path) -> None:
    client, _applications, application, event, note = _ready(tmp_path)

    response = client.get("/api/interviews")

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert body["items"] == [
        {
            "application_id": application.id,
            "event_id": event.id,
            "company_name": "Acme",
            "position_name": "Backend",
            "scheduled_at": "2026-07-28T09:00:00+00:00",
            "note_id": note.id,
            "note_source_status": "current",
        }
    ]


def test_interview_index_excludes_soft_deleted_application_but_deep_link_is_404(tmp_path) -> None:
    client, applications, application, event, _note = _ready(tmp_path)
    applications.delete(application.id)

    assert client.get("/api/interviews").status_code == 200
    assert client.get("/api/interviews").json()["items"] == []
    detail = client.get(f"/api/interviews/{event.id}")
    assert detail.status_code == 404
    assert detail.json()["error_code"] == "interview_not_found"


def test_interview_index_rejects_invalid_pagination(tmp_path) -> None:
    client, *_ = _ready(tmp_path)
    assert client.get("/api/interviews?limit=0").status_code == 422
    assert client.get("/api/interviews?limit=201").status_code == 422
