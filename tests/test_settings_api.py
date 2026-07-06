from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.config import Config, load_config, save_config


def test_get_settings_hides_api_key(tmp_path):
    save_config(tmp_path, Config(api_key="sk-secret"))
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["has_api_key"] is True
    assert "api_key" not in response.json()


def test_put_settings_preserves_blank_api_key(tmp_path):
    save_config(tmp_path, Config(api_key="sk-secret"))
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": True,
            "base_url": "https://example.test/v1",
            "model": "model",
            "api_key": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["chat_auto_approve_writes"] is True
    assert load_config(tmp_path).api_key == "sk-secret"

