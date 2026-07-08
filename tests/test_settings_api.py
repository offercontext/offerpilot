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


def test_put_settings_persists_fallback_provider_order(tmp_path):
    save_config(
        tmp_path,
        Config(
            active_provider_id="openai",
            providers=[
                AIProviderProfile(id="openai", label="OpenAI", provider="openai", api_key="sk-openai"),
                AIProviderProfile(id="deepseek", label="DeepSeek", provider="openai_compatible", api_key="sk-deepseek"),
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put(
        "/api/settings",
        json={
            "chat_auto_approve_writes": False,
            "active_provider_id": "openai",
            "fallback_provider_ids": ["deepseek", "missing", "openai"],
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
                    "id": "deepseek",
                    "label": "DeepSeek",
                    "provider": "openai_compatible",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "api_key": "",
                    "enabled": True,
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["fallback_provider_ids"] == ["deepseek"]
    assert load_config(tmp_path).fallback_provider_ids == ["deepseek"]


def test_provider_test_endpoint_calls_litellm_without_exposing_key(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_completion(**payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("offerpilot.ai.client.completion", fake_completion)
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
                    base_url="https://api.openai.com/v1",
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
    assert body["latency_ms"] >= 0
    assert "api_key" not in body
    assert calls[0]["api_key"] == "sk-openai"
    assert calls[0]["messages"][-1]["content"]


def test_provider_test_endpoint_reports_provider_failure(tmp_path, monkeypatch):
    def fake_completion(**_payload):
        raise RuntimeError("provider down")

    monkeypatch.setattr("offerpilot.ai.client.completion", fake_completion)
    save_config(
        tmp_path,
        Config(
            providers=[
                AIProviderProfile(id="openai", provider="openai", api_key="sk-openai"),
            ],
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/settings/providers/test", json={"provider_id": "openai"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "provider down"


def test_backup_export_returns_zip_with_local_data_files(tmp_path):
    save_config(tmp_path, Config(api_key="sk-secret"))
    (tmp_path / "offerpilot.log").write_text("log line\n", encoding="utf-8")
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.get("/api/backups/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "offerpilot-backup-" in response.headers["content-disposition"]
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "config.json" in names
        assert "data.db" in names
        assert "offerpilot.log" in names

