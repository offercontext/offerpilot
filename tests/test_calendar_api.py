from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_calendar_includes_applications_and_events(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()
    client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "written_test",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 60,
            "location": "online",
        },
    )
    client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "interview",
            "scheduled_at": "2026-08-01T10:00:00Z",
            "duration_minutes": 45,
            "location": "online",
        },
    )

    response = client.get("/api/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    entries = response.json()
    assert any(entry["type"] == "applied" and entry["app_id"] == app["id"] for entry in entries)
    event_entry = next(entry for entry in entries if entry["type"] == "written_test")
    assert event_entry["title"] == "ByteDance · 笔试"
    assert event_entry["event_type"] == "written_test"
    assert event_entry["duration_minutes"] == 60
    assert event_entry["editable"] is True
    assert not any(
        entry.get("event_type") == "interview"
        and entry.get("scheduled_at") == "2026-08-01T10:00:00Z"
        for entry in entries
    )


def test_calendar_bad_month_defaults_to_current_month(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/calendar", params={"month": "bad"})

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_calendar_includes_interview_notes(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    note = client.post(
        "/api/notes",
        json={
            "company": "ByteDance",
            "position": "Backend",
            "round": "一面",
            "date": "2026-07-12",
        },
    ).json()

    response = client.get("/api/calendar", params={"month": "2026-07"})

    assert response.status_code == 200
    entry = next(item for item in response.json() if item.get("note_id") == note["id"])
    assert entry["type"] == "interview"
    assert entry["title"] == "ByteDance · 一面"
    assert entry["subtitle"] == "Backend"
