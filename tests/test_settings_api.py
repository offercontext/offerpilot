from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.config import AIProviderProfile, Config, load_config, save_config


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


def test_get_settings_exposes_provider_profiles_without_keys(tmp_path):
    save_config(
        tmp_path,
        Config(
            active_provider_id="deepseek",
            providers=[
                AIProviderProfile(
                    id="deepseek",
                    label="DeepSeek",
                    provider="openai_compatible",
                    api_key="sk-deepseek",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                )
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    provider = response.json()["providers"][0]
    assert provider == {
        "id": "deepseek",
        "label": "DeepSeek",
        "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "enabled": True,
        "has_api_key": True,
    }
    assert "api_key" not in provider


def test_put_settings_preserves_blank_provider_api_key(tmp_path):
    save_config(
        tmp_path,
        Config(
            active_provider_id="default",
            providers=[
                AIProviderProfile(
                    id="default",
                    label="Default",
                    provider="openai",
                    api_key="sk-existing",
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o",
                )
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": False,
            "active_provider_id": "default",
            "providers": [
                {
                    "id": "default",
                    "label": "Default",
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                    "api_key": "",
                    "enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    cfg = load_config(tmp_path)
    assert cfg.active_provider().api_key == "sk-existing"
    assert cfg.active_provider().model == "gpt-4o-mini"


def test_put_settings_accepts_new_provider_profile(tmp_path):
    save_config(tmp_path, Config(api_key="sk-openai"))
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": False,
            "active_provider_id": "openrouter",
            "providers": [
                {
                    "id": "openrouter",
                    "label": "OpenRouter",
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "openai/gpt-4o",
                    "api_key": "sk-openrouter",
                    "enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    cfg = load_config(tmp_path)
    assert cfg.active_provider().id == "openrouter"
    assert cfg.active_provider().api_key == "sk-openrouter"

