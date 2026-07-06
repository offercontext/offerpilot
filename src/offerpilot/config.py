import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_PORT = 8080


class Config(BaseModel):
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    local_port: int = DEFAULT_PORT
    chat_auto_approve_writes: bool = False


def resolve_data_dir() -> Path:
    configured = os.environ.get("OFFERPILOT_DATA")
    if configured:
        return Path(configured)
    return Path.home() / ".offerpilot"


def load_config(data_dir: Path) -> Config:
    path = data_dir / "config.json"
    if not path.exists():
        return Config()

    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    cfg = Config.model_validate(raw)
    if not cfg.base_url:
        cfg.base_url = DEFAULT_BASE_URL
    if not cfg.model:
        cfg.model = DEFAULT_MODEL
    if cfg.local_port == 0:
        cfg.local_port = DEFAULT_PORT
    return cfg


def save_config(data_dir: Path, config: Config) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "config.json"
    path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)

