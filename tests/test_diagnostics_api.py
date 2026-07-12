from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.diagnostics import append_log_entry


def test_get_logs_returns_newest_relative_chronological_pages(tmp_path):
    for index in range(1, 6):
        append_log_entry(tmp_path, "INFO", f"entry-{index}")
    with (tmp_path / "logs" / "offerpilot.log").open("a", encoding="utf-8") as handle:
        handle.write("not-json\n[]\n")
    client = TestClient(create_app(data_dir=tmp_path))

    first_page = client.get("/api/logs?limit=2&offset=0")
    second_page = client.get("/api/logs?limit=2&offset=2")
    final_page = client.get("/api/logs?limit=2&offset=4")
    out_of_range_page = client.get("/api/logs?limit=2&offset=20")

    assert first_page.status_code == 200
    assert first_page.json() == {
        "entries": [
            {"level": "INFO", "message": "entry-4"},
            {"level": "INFO", "message": "entry-5"},
        ],
        "total": 5,
        "limit": 2,
        "offset": 0,
        "has_more": True,
    }
    assert second_page.json()["entries"] == [
        {"level": "INFO", "message": "entry-2"},
        {"level": "INFO", "message": "entry-3"},
    ]
    assert final_page.json() == {
        "entries": [{"level": "INFO", "message": "entry-1"}],
        "total": 5,
        "limit": 2,
        "offset": 4,
        "has_more": False,
    }
    assert out_of_range_page.json() == {
        "entries": [],
        "total": 5,
        "limit": 2,
        "offset": 20,
        "has_more": False,
    }


def test_get_logs_rejects_invalid_pagination_parameters(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    for query in ("limit=0", "limit=101", "offset=-1"):
        response = client.get(f"/api/logs?{query}")

        assert response.status_code == 400
