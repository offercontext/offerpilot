from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_create_and_list_events_with_application_fields(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    created = client.post(
        "/api/events",
        json={
            "application_id": app["id"],
            "event_type": "interview",
            "round": 2,
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
            "location": "Zoom",
            "notes": "tech",
        },
    )
    listed = client.get("/api/events", params={"type": "interview"})

    assert created.status_code == 201
    assert created.json()["duration_minutes"] == 45
    assert listed.status_code == 200
    assert listed.json()[0]["company_name"] == "ByteDance"
    assert listed.json()[0]["position_name"] == "Backend"


def test_create_event_rejects_missing_application(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/events",
        json={
            "application_id": 404,
            "event_type": "interview",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"error": "Application not found"}


def test_event_validation_and_delete(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    invalid = client.post(
        "/api/events",
        json={
            "application_id": app["id"],
            "event_type": "coffee",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
        },
    )
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "Invalid event type"}

    event = client.post(
        "/api/events",
        json={
            "application_id": app["id"],
            "event_type": "assessment",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 30,
        },
    ).json()
    deleted = client.delete(f"/api/events/{event['id']}")

    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Deleted"}
    assert client.get(f"/api/events/{event['id']}").status_code == 404

