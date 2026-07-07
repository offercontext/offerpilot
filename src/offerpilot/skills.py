from __future__ import annotations

from typing import Any

from offerpilot.config import Config, SkillPackage


class SkillRegistryError(ValueError):
    pass


def skills_payload(cfg: Config) -> dict[str, Any]:
    loaded = loaded_skill_ids(cfg)
    return {
        "packages": [_skill_payload(skill, loaded) for skill in cfg.skills],
        "loaded": loaded,
    }


def loaded_skill_ids(cfg: Config) -> list[str]:
    return [skill.id for skill in cfg.skills if skill.trusted and skill.enabled]


def register_skill(cfg: Config, payload: dict[str, Any]) -> Config:
    skill_id = _required_text(payload, "id")
    current = _skill_by_id(cfg, skill_id)
    trusted = bool(payload.get("trusted", current.trusted if current is not None else False))
    enabled = bool(payload.get("enabled", current.enabled if current is not None else False))
    if enabled and not trusted:
        raise SkillRegistryError("skill must be trusted before enabling")
    next_skill = SkillPackage(
        id=skill_id,
        label=str(payload.get("label") or (current.label if current is not None else skill_id)),
        version=str(payload.get("version") or (current.version if current is not None else "")),
        source=str(payload.get("source") or (current.source if current is not None else "")),
        trusted=trusted,
        enabled=enabled,
    )
    skills = [next_skill if skill.id == skill_id else skill for skill in cfg.skills]
    if current is None:
        skills.append(next_skill)
    return cfg.model_copy(update={"skills": skills})


def update_skill(cfg: Config, skill_id: str, payload: dict[str, Any]) -> Config:
    current = _skill_by_id(cfg, skill_id)
    if current is None:
        raise KeyError(skill_id)
    trusted = bool(payload.get("trusted", current.trusted))
    enabled = bool(payload.get("enabled", current.enabled))
    if enabled and not trusted:
        raise SkillRegistryError("skill must be trusted before enabling")
    next_skill = current.model_copy(update={"trusted": trusted, "enabled": enabled})
    return cfg.model_copy(
        update={"skills": [next_skill if skill.id == skill_id else skill for skill in cfg.skills]}
    )


def _skill_payload(skill: SkillPackage, loaded: list[str]) -> dict[str, Any]:
    return {
        "id": skill.id,
        "label": skill.label,
        "version": skill.version,
        "source": skill.source,
        "trusted": skill.trusted,
        "enabled": skill.enabled,
        "loaded": skill.id in loaded,
    }


def _skill_by_id(cfg: Config, skill_id: str) -> SkillPackage | None:
    for skill in cfg.skills:
        if skill.id == skill_id:
            return skill
    return None


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise SkillRegistryError(f"{key} is required")
    return value
