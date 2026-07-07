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
