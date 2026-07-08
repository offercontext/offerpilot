from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_create_and_list_application_events_with_application_fields(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    created = client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "written_test",
            "subtype": "assessment",
            "tags": ["campus", "online"],
            "round": 2,
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
            "location": "Zoom",
            "notes": "tech",
            "remind_at": "2026-07-10T09:30:00Z",
        },
    )
    listed = client.get("/api/application-events", params={"event_type": "written_test"})

    assert created.status_code == 201
    body = created.json()
    assert body["event_type"] == "written_test"
    assert body["subtype"] == "assessment"
    assert body["tags"] == ["campus", "online"]
    assert created.json()["duration_minutes"] == 45
    assert body["remind_at"] == "2026-07-10T09:30:00Z"
    assert listed.status_code == 200
    assert listed.json()[0]["company_name"] == "ByteDance"
    assert listed.json()[0]["position_name"] == "Backend"


def test_list_application_events_month_stays_within_requested_month(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()
    for scheduled_at in ["2026-07-10T10:00:00Z", "2026-08-01T10:00:00Z"]:
        client.post(
            "/api/application-events",
            json={
                "application_id": app["id"],
                "event_type": "interview",
                "scheduled_at": scheduled_at,
                "duration_minutes": 45,
            },
        )

    response = client.get("/api/application-events", params={"month": "2026-07"})

    assert response.status_code == 200
    assert [item["scheduled_at"] for item in response.json()] == [
        "2026-07-10T10:00:00Z"
    ]


def test_create_event_rejects_missing_application(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/application-events",
        json={
            "application_id": 404,
            "event_type": "interview",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"error": "Application not found"}


def test_application_event_validation_and_delete(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    invalid = client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "coffee",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 45,
        },
    )
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "Invalid event type"}

    legacy_assessment = client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "assessment",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 30,
        },
    )
    assert legacy_assessment.status_code == 400
    assert legacy_assessment.json() == {"error": "Invalid event type"}

    event = client.post(
        "/api/application-events",
        json={
            "application_id": app["id"],
            "event_type": "written_test",
            "subtype": "assessment",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 30,
        },
    ).json()
    deleted = client.delete(f"/api/application-events/{event['id']}")

    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Deleted"}
    assert client.get(f"/api/application-events/{event['id']}").status_code == 404


def test_legacy_events_api_is_not_exposed(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/events")

    assert response.status_code == 404
