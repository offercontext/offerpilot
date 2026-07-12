from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_bad_path_id_returns_go_style_error(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/applications/not-a-number")

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid ID"}


def test_body_schema_violation_returns_422_with_detail(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/applications", json=[])

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_failed"
    assert isinstance(body["detail"], list)
    assert body["detail"]


def test_options_returns_ok_with_cors_headers(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.options("/api/applications")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"

