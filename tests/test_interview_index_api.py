from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import InterviewReviewProposal, KnowledgeCapturedSourceMetadata, KnowledgeSource
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
        "has_review_proposal": False,
        "review_summary": None,
        "has_confirmed_knowledge": False,
        "preparation_available": True,
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


def test_interview_index_puts_unscheduled_events_last_and_uses_recent_tie_breakers(tmp_path) -> None:
    client, _applications, application, scheduled, _note = _ready(tmp_path)
    events = ApplicationEventsRepository(session_factory_for_data_dir(tmp_path))
    unscheduled = events.create(
        ApplicationEventCreate(
            application_id=application.id,
            event_type="interview",
            scheduled_at=None,
            duration_minutes=None,
        )
    )
    later = events.create(
        ApplicationEventCreate(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 29, 9, tzinfo=timezone.utc),
            duration_minutes=60,
        )
    )

    items = client.get("/api/interviews").json()["items"]
    assert [item["event_id"] for item in items] == [scheduled.id, later.id, unscheduled.id]


def test_interview_index_exposes_preparation_entry(tmp_path) -> None:
    client, *_ = _ready(tmp_path)

    item = client.get("/api/interviews").json()["items"][0]

    assert item["preparation_available"] is True


def test_interview_index_marks_changed_review_source(tmp_path) -> None:
    client, _applications, _application, event, note = _ready(tmp_path)
    with session_factory_for_data_dir(tmp_path)() as session:
        session.add(
            InterviewReviewProposal(
                note_id=note.id,
                application_event_id=event.id,
                idempotency_key="review-index-source-change",
                input_snapshot_json="{}",
                source_fingerprint="old-fingerprint",
                proposal_json="{}",
                proposal_hash="proposal-hash",
            )
        )
        session.commit()

    item = client.get("/api/interviews").json()["items"][0]
    assert item["note_source_status"] == "source_changed"


def test_interview_index_keeps_review_history_after_note_unbind(tmp_path) -> None:
    client, _applications, _application, event, note = _ready(tmp_path)
    with session_factory_for_data_dir(tmp_path)() as session:
        session.add(
            InterviewReviewProposal(
                note_id=note.id,
                application_event_id=event.id,
                idempotency_key="review-index-unbound",
                input_snapshot_json=json.dumps({"event": {"id": event.id}}),
                source_fingerprint="old-fingerprint",
                proposal_json=json.dumps({"summary": {"text": "历史复盘摘要"}}),
                proposal_hash="proposal-hash",
            )
        )
        session.commit()

    assert client.put(f"/api/notes/{note.id}", json={"application_event_id": None}).status_code == 200

    item = client.get("/api/interviews").json()["items"][0]
    assert item["note_id"] is None
    assert item["has_review_proposal"] is True
    assert item["review_summary"] == "历史复盘摘要"
    assert item["note_source_status"] == "source_changed"


def test_interview_index_keeps_review_and_knowledge_history_after_note_delete(tmp_path) -> None:
    client, _applications, _application, event, note = _ready(tmp_path)
    with session_factory_for_data_dir(tmp_path)() as session:
        session.add(
            InterviewReviewProposal(
                note_id=note.id,
                application_event_id=event.id,
                idempotency_key="review-index-deleted",
                input_snapshot_json=json.dumps({"event": {"id": event.id}}),
                source_fingerprint="old-fingerprint",
                proposal_json=json.dumps({"summary": {"text": "删除后的复盘摘要"}}),
                proposal_hash="proposal-hash",
            )
        )
        source = KnowledgeSource(
            source_hash="captured-source-index",
            source_kind="captured_interview_note",
            title_hint="Captured interview",
            main_filename="interview-note.txt",
            main_media_type="text/plain",
            main_relative_path="captured://interview-note/1",
            total_bytes=10,
        )
        session.add(source)
        session.flush()
        session.add(
            KnowledgeCapturedSourceMetadata(
                source_id=source.id,
                origin_note_id=note.id,
                application_event_id=event.id,
                note_fingerprint="note-fingerprint",
                selected_fragments_json="[]",
                capture_schema_version="interview-note-capture-v1",
            )
        )
        session.commit()

    assert client.delete(f"/api/notes/{note.id}").status_code == 200

    item = client.get("/api/interviews").json()["items"][0]
    assert item["note_id"] is None
    assert item["has_review_proposal"] is True
    assert item["has_confirmed_knowledge"] is True
    assert item["review_summary"] == "删除后的复盘摘要"
    assert item["note_source_status"] == "source_changed"
