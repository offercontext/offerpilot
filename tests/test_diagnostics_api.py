from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.diagnostics import append_log_entry


def test_get_logs_returns_recent_entries(tmp_path):
    append_log_entry(tmp_path, "INFO", "server started")
    append_log_entry(tmp_path, "WARNING", "provider retry")
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/logs?limit=1")

    assert response.status_code == 200
    assert response.json() == {
        "entries": [
            {
                "level": "WARNING",
                "message": "provider retry",
            }
        ]
    }


def test_get_logs_filters_by_level_before_limit(tmp_path):
    append_log_entry(tmp_path, "INFO", "server started")
    append_log_entry(tmp_path, "ERROR", "provider failed")
    append_log_entry(tmp_path, "ERROR", "second failure")
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/logs?level=ERROR&limit=1")

    assert response.status_code == 200
    assert response.json() == {"entries": [{"level": "ERROR", "message": "second failure"}]}


def test_get_logs_rejects_unknown_level(tmp_path):
    response = TestClient(create_app(data_dir=tmp_path)).get("/api/logs?level=TRACE")

    assert response.status_code == 422
    assert response.json() == {"error": "invalid log level"}
