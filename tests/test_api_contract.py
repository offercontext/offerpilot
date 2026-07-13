from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_bad_path_id_returns_go_style_error(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/applications/not-a-number")

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid ID"}


def test_options_allows_only_same_origin_cors_requests(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    same_origin = client.options(
        "/api/applications",
        headers={"Origin": "http://testserver"},
    )
    foreign_origin = client.options(
        "/api/applications",
        headers={"Origin": "https://untrusted.example"},
    )

    assert same_origin.status_code == 200
    assert same_origin.headers["access-control-allow-origin"] == "http://testserver"
    assert foreign_origin.status_code == 200
    assert "access-control-allow-origin" not in foreign_origin.headers

