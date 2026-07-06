from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_create_note_for_application_backfills_company_and_position(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    response = client.post(
        f"/api/applications/{app['id']}/notes",
        json={"round": "一面", "date": "2026-07-11", "questions": "Go?"},
    )

    assert response.status_code == 201
    assert response.json()["application_id"] == app["id"]
    assert response.json()["company"] == "ByteDance"
    assert response.json()["position"] == "Backend"


def test_create_standalone_note_requires_company(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/notes", json={"position": "Backend"})

    assert response.status_code == 400
    assert response.json() == {"error": "company is required"}


def test_list_update_delete_notes(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    note = client.post(
        "/api/notes",
        json={"company": "ByteDance", "position": "Backend", "round": "一面"},
    ).json()

    listed = client.get("/api/notes")
    updated = client.put(
        f"/api/notes/{note['id']}",
        json={"company": "Tencent", "position": "Frontend", "round": "二面"},
    )
    deleted = client.delete(f"/api/notes/{note['id']}")

    assert listed.status_code == 200
    assert listed.json()[0]["company"] == "ByteDance"
    assert updated.status_code == 200
    assert updated.json()["company"] == "Tencent"
    assert "application_id" not in updated.json()
    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Deleted"}

