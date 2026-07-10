from fastapi.testclient import TestClient

from offerpilot.ai import client as ai_client
from offerpilot.api import create_app
from offerpilot.config import AIProviderProfile, Config, load_config, save_config
from offerpilot.diagnostics import read_recent_log_entries


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
            "runtime_mode": "server",
            "auth_enabled": True,
            "log_level": "DEBUG",
        },
    )

    assert response.status_code == 200
    assert response.json()["chat_auto_approve_writes"] is True
    assert response.json()["runtime_mode"] == "server"
    assert response.json()["auth_enabled"] is True
    assert response.json()["log_level"] == "DEBUG"
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


def test_put_settings_without_providers_preserves_existing_provider_profiles(tmp_path):
    save_config(
        tmp_path,
        Config(
            chat_auto_approve_writes=False,
            active_provider_id="deepseek",
            providers=[
                AIProviderProfile(
                    id="openai",
                    label="OpenAI",
                    provider="openai",
                    api_key="sk-openai",
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o",
                ),
                AIProviderProfile(
                    id="deepseek",
                    label="DeepSeek",
                    provider="openai_compatible",
                    api_key="sk-deepseek",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                ),
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": True,
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )

    assert response.status_code == 200
    cfg = load_config(tmp_path)
    assert cfg.chat_auto_approve_writes is True
    assert cfg.active_provider_id == "deepseek"
    assert [(profile.id, profile.api_key) for profile in cfg.providers] == [
        ("openai", "sk-openai"),
        ("deepseek", "sk-deepseek"),
    ]


def test_put_settings_persists_fallback_provider_id(tmp_path):
    save_config(
        tmp_path,
        Config(
            active_provider_id="openai",
            providers=[
                AIProviderProfile(id="openai", label="OpenAI", api_key="sk-openai"),
                AIProviderProfile(id="openrouter", label="OpenRouter", api_key="sk-openrouter"),
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": False,
            "active_provider_id": "openai",
            "fallback_provider_id": "openrouter",
            "providers": [
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o",
                    "api_key": "",
                    "enabled": True,
                },
                {
                    "id": "openrouter",
                    "label": "OpenRouter",
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "openai/gpt-4o",
                    "api_key": "",
                    "enabled": True,
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["fallback_provider_id"] == "openrouter"
    assert load_config(tmp_path).fallback_provider_id == "openrouter"


def test_provider_connection_test_uses_saved_profile(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    save_config(
        tmp_path,
        Config(
            active_provider_id="openai",
            providers=[
                AIProviderProfile(
                    id="openai",
                    label="OpenAI",
                    provider="openai",
                    api_key="sk-openai",
                    model="gpt-4o-mini",
                )
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/settings/providers/test", json={"provider_id": "openai"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider_id"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert body["latency_ms"] >= 0
    assert body["message"] == "连接成功"
    assert captured["api_key"] == "sk-openai"


def test_provider_connection_test_masks_secret_and_logs_failure(monkeypatch, tmp_path):
    def fake_completion(**_kwargs):
        raise RuntimeError("invalid key sk-secret-value")

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/settings/providers/test",
        json={
            "provider": {
                "id": "draft",
                "label": "Draft",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
                "api_key": "sk-secret-value",
                "enabled": True,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "sk-secret-value" not in body["error"]
    assert read_recent_log_entries(tmp_path, limit=1)[0]["level"] == "ERROR"


def test_provider_connection_test_reuses_saved_key_for_draft_profile(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(ai_client, "completion", fake_completion)
    save_config(
        tmp_path,
        Config(
            active_provider_id="openai",
            providers=[
                AIProviderProfile(
                    id="openai",
                    label="OpenAI",
                    provider="openai",
                    api_key="sk-openai",
                    model="gpt-4o",
                )
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/settings/providers/test",
        json={
            "provider": {
                "id": "openai",
                "label": "OpenAI",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "",
                "enabled": True,
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["model"] == "gpt-4o-mini"
    assert captured["api_key"] == "sk-openai"


def test_settings_backup_omits_plaintext_api_keys(tmp_path):
    save_config(
        tmp_path,
        Config(
            active_provider_id="openai",
            fallback_provider_id="openrouter",
            providers=[
                AIProviderProfile(id="openai", label="OpenAI", api_key="sk-openai"),
                AIProviderProfile(id="openrouter", label="OpenRouter", api_key="sk-openrouter"),
            ],
            auth_enabled=True,
            auth_token="local-secret",
            log_level="DEBUG",
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/settings/backup", headers={"X-OfferPilot-Token": "local-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["active_provider_id"] == "openai"
    assert body["fallback_provider_id"] == "openrouter"
    assert body["providers"][0]["has_api_key"] is True
    assert "api_key" not in body["providers"][0]
    assert "sk-openai" not in response.text
    assert "sk-openrouter" not in response.text
