from __future__ import annotations

import json
from typing import Any

from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.schemas import ApplicationOut


def application_tool_registry(repo: ApplicationsRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_applications": {
            "write": False,
            "handler": lambda args: _list_applications(repo, args),
        },
        "get_application": {
            "write": False,
            "handler": lambda args: _get_application(repo, args),
        },
        "create_application": {
            "write": True,
            "describe": _describe_create_application,
            "handler": lambda args: _create_application(repo, args),
        },
        "update_application_status": {
            "write": True,
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
    app = repo.get(int(payload["id"]))
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
            status=str(payload.get("status") or "applied"),
            source="ai",
        )
    )
    return json.dumps(_application_json(app), ensure_ascii=False)


def _update_application_status(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    app = repo.get(int(payload["id"]))
    if app is None:
        raise ValueError("application not found")
    updated = repo.update_full(
        app.id,
        ApplicationCreate(
            company_name=app.company_name,
            position_name=app.position_name,
            job_url=app.job_url,
            status=str(payload["status"]),
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


def _application_json(app: Any) -> dict[str, Any]:
    return ApplicationOut.model_validate(app).model_dump(mode="json")
