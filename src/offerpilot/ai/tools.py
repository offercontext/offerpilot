from __future__ import annotations

import json
from typing import Any

from offerpilot.application_status import APPLICATION_STATUS_IDS, normalize_application_status
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.schemas import ApplicationOut


def application_tool_registry(repo: ApplicationsRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_applications": {
            "write": False,
            "description": "List job applications. Optionally filter by canonical application status.",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": list(APPLICATION_STATUS_IDS),
                        "description": "Optional status filter.",
                    }
                },
            },
            "handler": lambda args: _list_applications(repo, args),
        },
        "get_application": {
            "write": False,
            "description": "Get one job application by id. Use an id returned by list_applications.",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Application id returned by list_applications.",
                    }
                },
                "required": ["id"],
            },
            "handler": lambda args: _get_application(repo, args),
        },
        "create_application": {
            "write": True,
            "description": "Create a job application record.",
            "schema": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "position_name": {"type": "string"},
                    "job_url": {"type": "string"},
                    "status": {"type": "string", "enum": list(APPLICATION_STATUS_IDS)},
                },
                "required": ["company_name", "position_name"],
            },
            "describe": _describe_create_application,
            "handler": lambda args: _create_application(repo, args),
        },
        "update_application_status": {
            "write": True,
            "description": "Update one job application's status. Use an id returned by list_applications.",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Application id returned by list_applications.",
                    },
                    "status": {"type": "string", "enum": list(APPLICATION_STATUS_IDS)},
                },
                "required": ["id", "status"],
            },
            "describe": _describe_update_application_status,
            "handler": lambda args: _update_application_status(repo, args),
        },
    }


def _list_applications(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    apps = repo.list(status=str(payload.get("status") or ""))
    return json.dumps([_application_json(app) for app in apps], ensure_ascii=False)


def _get_application(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    app_id = _required_int(payload, "id", "get_application")
    app = repo.get(app_id)
    if app is None:
        raise ValueError("application not found")
    return json.dumps(_application_json(app), ensure_ascii=False)


def _create_application(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    app = repo.create(
        ApplicationCreate(
            company_name=str(payload["company_name"]),
            position_name=str(payload["position_name"]),
            job_url=str(payload.get("job_url") or ""),
            status=normalize_application_status(str(payload.get("status") or "applied")),
            source="ai",
        )
    )
    return json.dumps(_application_json(app), ensure_ascii=False)


def _update_application_status(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    app_id = _required_int(payload, "id", "update_application_status")
    app = repo.get(app_id)
    if app is None:
        raise ValueError("application not found")
    updated = repo.update_full(
        app.id,
        ApplicationCreate(
            company_name=app.company_name,
            position_name=app.position_name,
            job_url=app.job_url,
            status=normalize_application_status(str(payload["status"])),
            source=app.source,
            notes=app.notes,
            applied_at=app.applied_at,
        ),
    )
    if updated is None:
        raise ValueError("application not found")
    return json.dumps(_application_json(updated), ensure_ascii=False)


def _describe_create_application(args: str) -> str:
    payload = _payload(args)
    return f"新建投递：{payload.get('company_name', '')} - {payload.get('position_name', '')}"


def _describe_update_application_status(args: str) -> str:
    payload = _payload(args)
    return f"将投递 #{payload.get('id', '')} 的状态改为 {payload.get('status', '')}"


def _payload(args: str) -> dict[str, Any]:
    if not args:
        return {}
    value = json.loads(args)
    if not isinstance(value, dict):
        raise ValueError("tool args must be an object")
    return value


def _required_int(payload: dict[str, Any], key: str, tool_name: str) -> int:
    raw = payload.get(key)
    if raw is None or raw == "":
        raise ValueError(f"{tool_name} requires {key}")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{tool_name} requires numeric {key}") from exc


def _application_json(app: Any) -> dict[str, Any]:
    return ApplicationOut.model_validate(app).model_dump(mode="json")
