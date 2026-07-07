from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def test_create_application_defaults_and_list(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    )
    listed_response = client.get("/api/applications")

    assert response.status_code == 201
    created = response.json()
    listed = listed_response.json()
    assert created["status"] == "applied"
    assert created["source"] == "web"
    assert listed[0]["company_name"] == "ByteDance"


def test_application_status_options_are_exposed_from_backend(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/application-statuses")

    assert response.status_code == 200
    assert [item["value"] for item in response.json()] == [
        "pending",
        "applied",
        "written_test",
        "interview",
        "offer",
        "closed",
    ]
    assert response.json()[0]["label"] == "待投递"


def test_create_application_requires_company_and_position(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/applications", json={"company_name": "ByteDance"})

    assert response.status_code == 400
    assert response.json() == {"error": "company_name and position_name are required"}


def test_create_application_normalizes_legacy_status(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "assessment"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "written_test"


def test_create_application_rejects_invalid_status(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "onsite"},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "invalid application status: onsite"}


def test_list_applications_rejects_invalid_status_filter(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/applications", params={"status": "onsite"})

    assert response.status_code == 422
    assert response.json() == {"error": "invalid application status: onsite"}


def test_get_application_not_found(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/applications/404")

    assert response.status_code == 404
    assert response.json() == {"error": "Application not found"}


def test_update_application_full_object(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    created = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "notes": "first"},
    ).json()

    response = client.put(
        f"/api/applications/{created['id']}",
        json={
            "company_name": "Tencent",
            "position_name": "Frontend",
            "job_url": "https://example.test",
            "status": "offer",
            "notes": "second",
        },
    )

    assert response.status_code == 200
    assert response.json()["company_name"] == "Tencent"
    assert response.json()["notes"] == "second"


def test_update_application_preserves_existing_source(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(
        ApplicationCreate(company_name="ByteDance", position_name="Backend", source="cli")
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        f"/api/applications/{created.id}",
        json={
            "company_name": "ByteDance",
            "position_name": "Backend",
            "status": "offer",
        },
    )

    assert response.status_code == 200
    assert response.json()["source"] == "cli"


def test_dashboard_groups_by_status(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    client.post(
        "/api/applications",
        json={"company_name": "A", "position_name": "Backend", "status": "interview"},
    )
    client.post(
        "/api/applications",
        json={"company_name": "B", "position_name": "Frontend", "status": "offer"},
    )

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert len(response.json()["board"]["interview"]) == 1
    assert len(response.json()["board"]["offer"]) == 1
