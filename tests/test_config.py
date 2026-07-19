from pathlib import Path

from offerpilot.config import (
    AIProviderProfile,
    Config,
    load_config,
    resolve_data_dir,
    save_config,
)


def test_resolve_data_dir_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path / "custom"))

    assert resolve_data_dir() == tmp_path / "custom"


def test_resolve_data_dir_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFERPILOT_DATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_data_dir() == tmp_path / ".offerpilot"


def test_load_missing_config_returns_defaults(tmp_path):
    cfg = load_config(tmp_path)

    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.model == "gpt-4o"
    assert cfg.local_port == 8080
    assert cfg.chat_auto_approve_writes is False
    assert cfg.runtime_mode == "local"
    assert cfg.auth_enabled is False
    assert cfg.log_level == "INFO"


def test_save_and_load_config_round_trip(tmp_path):
    cfg = Config(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="model",
        local_port=9999,
        chat_auto_approve_writes=True,
        runtime_mode="server",
        auth_enabled=True,
        log_level="DEBUG",
    )

    save_config(tmp_path, cfg)
    loaded = load_config(tmp_path)

    assert loaded == cfg
    assert (tmp_path / "config.json").exists()


def test_loaded_ordered_fallback_is_available_to_knowledge_brief(tmp_path):
    providers = [
        AIProviderProfile(id="primary", label="Primary", api_key="sk-primary"),
        AIProviderProfile(id="backup", label="Backup", api_key="sk-backup"),
    ]
    save_config(
        tmp_path,
        Config(
            active_provider_id="primary",
            fallback_provider_ids=["backup"],
            providers=providers,
        ),
    )

    loaded = load_config(tmp_path)

    assert loaded.fallback_provider() == providers[1]
