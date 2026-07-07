from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from offerpilot.application_status import APPLICATION_STATUS_IDS, normalize_application_status
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.events import EventCreate, EventsRepository, duration_minutes
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.schemas import ApplicationOut, EventOut, InterviewNoteOut, OfferOut


EVENT_TYPES = ("written_test", "interview", "assessment")
OFFER_STATUSES = ("pending", "negotiating", "accepted", "declined", "expired")


def offerpilot_tool_registry(
    applications: ApplicationsRepository,
    events: EventsRepository,
    notes: NotesRepository,
    offers: OffersRepository,
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    registry.update(application_tool_registry(applications))
    registry.update(event_tool_registry(applications, events))
    registry.update(note_tool_registry(applications, notes))
    registry.update(offer_tool_registry(offers))
    return registry


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


def event_tool_registry(
    applications: ApplicationsRepository,
    repo: EventsRepository,
) -> dict[str, dict[str, Any]]:
    return {
        "list_events": {
            "write": False,
            "description": "List interview, written test, or assessment events.",
            "schema": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Optional YYYY-MM month filter."},
                    "application_id": {"type": "integer"},
                    "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
                },
            },
            "handler": lambda args: _list_events(repo, args),
        },
        "get_event": {
            "write": False,
            "description": "Get one event by id.",
            "schema": _id_schema("Event id."),
            "handler": lambda args: _get_event(repo, args),
        },
        "create_event": {
            "write": True,
            "description": "Create an interview, written test, or assessment event.",
            "schema": _event_schema(["application_id", "event_type", "scheduled_at", "duration_minutes"]),
            "describe": lambda args: _describe_id_action(args, "新建日程"),
            "handler": lambda args: _create_event(applications, repo, args),
        },
        "update_event": {
            "write": True,
            "description": "Update an existing event.",
            "schema": _event_schema(["id", "application_id", "event_type", "scheduled_at", "duration_minutes"]),
            "describe": lambda args: _describe_id_action(args, "更新日程"),
            "handler": lambda args: _update_event(applications, repo, args),
        },
        "delete_event": {
            "write": True,
            "description": "Delete an event by id.",
            "schema": _id_schema("Event id."),
            "describe": lambda args: _describe_id_action(args, "删除日程"),
            "handler": lambda args: _delete_event(repo, args),
        },
    }


def note_tool_registry(
    applications: ApplicationsRepository,
    repo: NotesRepository,
) -> dict[str, dict[str, Any]]:
    return {
        "list_notes": {
            "write": False,
            "description": "List interview review notes. Optionally filter by application id.",
            "schema": {
                "type": "object",
                "properties": {"application_id": {"type": "integer"}},
            },
            "handler": lambda args: _list_notes(repo, args),
        },
        "add_note": {
            "write": True,
            "description": "Add an interview review note. If application_id is present, company and position can be omitted.",
            "schema": _note_schema([]),
            "describe": lambda args: _describe_note_action(args, "新增复盘"),
            "handler": lambda args: _add_note(applications, repo, args),
        },
        "update_note": {
            "write": True,
            "description": "Update an existing interview review note. Missing fields keep existing values.",
            "schema": _note_schema(["id"]),
            "describe": lambda args: _describe_id_action(args, "更新复盘"),
            "handler": lambda args: _update_note(repo, args),
        },
        "delete_note": {
            "write": True,
            "description": "Delete an interview review note by id.",
            "schema": _id_schema("Note id."),
            "describe": lambda args: _describe_id_action(args, "删除复盘"),
            "handler": lambda args: _delete_note(repo, args),
        },
    }


def offer_tool_registry(repo: OffersRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_offers": {
            "write": False,
            "description": "List offers. Optionally filter by offer status.",
            "schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": list(OFFER_STATUSES)}},
            },
            "handler": lambda args: _list_offers(repo, args),
        },
        "get_offer": {
            "write": False,
            "description": "Get one offer by id.",
            "schema": _id_schema("Offer id."),
            "handler": lambda args: _get_offer(repo, args),
        },
        "compare_offers": {
            "write": False,
            "description": "Compare offers by ids. Missing ids are skipped.",
            "schema": {
                "type": "object",
                "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
                "required": ["ids"],
            },
            "handler": lambda args: _compare_offers(repo, args),
        },
        "update_offer": {
            "write": True,
            "description": "Update an offer. Missing fields keep existing values.",
            "schema": _offer_schema(["id"]),
            "describe": lambda args: _describe_id_action(args, "更新 Offer"),
            "handler": lambda args: _update_offer(repo, args),
        },
        "save_offer_assessment": {
            "write": True,
            "description": "Save or replace the assessment text for an offer.",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "assessment": {"type": "string"},
                },
                "required": ["id", "assessment"],
            },
            "describe": lambda args: _describe_id_action(args, "保存 Offer 评估"),
            "handler": lambda args: _save_offer_assessment(repo, args),
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


def _list_events(repo: EventsRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list(
        month=str(payload.get("month") or ""),
        application_id=_optional_int(payload, "application_id"),
        event_type=str(payload.get("event_type") or ""),
    )
    return _json([_event_with_application_json(item) for item in rows])


def _get_event(repo: EventsRepository, args: str) -> str:
    payload = _payload(args)
    event = repo.get(_required_int(payload, "id", "get_event"))
    if event is None:
        raise ValueError("event not found")
    return _json(_event_json(event))


def _create_event(applications: ApplicationsRepository, repo: EventsRepository, args: str) -> str:
    payload = _payload(args)
    event = repo.create(_event_create_from_payload(applications, payload, "create_event"))
    return _json(_event_json(event))


def _update_event(applications: ApplicationsRepository, repo: EventsRepository, args: str) -> str:
    payload = _payload(args)
    event_id = _required_int(payload, "id", "update_event")
    if repo.get(event_id) is None:
        raise ValueError("event not found")
    event = repo.update(event_id, _event_create_from_payload(applications, payload, "update_event"))
    if event is None:
        raise ValueError("event not found")
    return _json(_event_json(event))


def _delete_event(repo: EventsRepository, args: str) -> str:
    payload = _payload(args)
    event_id = _required_int(payload, "id", "delete_event")
    return _json({"deleted": repo.delete(event_id)})


def _list_notes(repo: NotesRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list(application_id=_optional_int(payload, "application_id"))
    return _json([_note_json(note) for note in rows])


def _add_note(applications: ApplicationsRepository, repo: NotesRepository, args: str) -> str:
    payload = _payload(args)
    note = repo.create(_note_create_from_payload(applications, payload, None, "add_note"))
    return _json(_note_json(note))


def _update_note(repo: NotesRepository, args: str) -> str:
    payload = _payload(args)
    note_id = _required_int(payload, "id", "update_note")
    existing = repo.get(note_id)
    if existing is None:
        raise ValueError("note not found")
    updated = repo.update(
        note_id,
        NoteCreate(
            application_id=existing.application_id,
            company=_payload_or_existing(payload, "company", existing.company),
            position=_payload_or_existing(payload, "position", existing.position),
            round=_payload_or_existing(payload, "round", existing.round),
            date=_payload_or_existing(payload, "date", existing.date),
            questions=_payload_or_existing(payload, "questions", existing.questions),
            self_reflection=_payload_or_existing(payload, "self_reflection", existing.self_reflection),
            difficulty_points=_payload_or_existing(payload, "difficulty_points", existing.difficulty_points),
            mood=_payload_or_existing(payload, "mood", existing.mood),
        ),
    )
    if updated is None:
        raise ValueError("note not found")
    return _json(_note_json(updated))


def _delete_note(repo: NotesRepository, args: str) -> str:
    payload = _payload(args)
    note_id = _required_int(payload, "id", "delete_note")
    deleted = repo.get(note_id) is not None
    repo.delete(note_id)
    return _json({"deleted": deleted})


def _list_offers(repo: OffersRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list(status=str(payload.get("status") or ""))
    return _json([_offer_json(offer) for offer in rows])


def _get_offer(repo: OffersRepository, args: str) -> str:
    payload = _payload(args)
    offer = repo.get(_required_int(payload, "id", "get_offer"))
    if offer is None:
        raise ValueError("offer not found")
    return _json(_offer_json(offer))


def _compare_offers(repo: OffersRepository, args: str) -> str:
    payload = _payload(args)
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError("compare_offers requires ids")
    compared = []
    for raw_id in ids:
        try:
            offer_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        offer = repo.get(offer_id)
        if offer is not None:
            compared.append(_offer_json(offer))
    return _json(compared)


def _update_offer(repo: OffersRepository, args: str) -> str:
    payload = _payload(args)
    offer_id = _required_int(payload, "id", "update_offer")
    existing = repo.get(offer_id)
    if existing is None:
        raise ValueError("offer not found")
    updated = repo.update(offer_id, _offer_create_from_payload(payload, existing))
    if updated is None:
        raise ValueError("offer not found")
    return _json(_offer_json(updated))


def _save_offer_assessment(repo: OffersRepository, args: str) -> str:
    payload = _payload(args)
    offer_id = _required_int(payload, "id", "save_offer_assessment")
    existing = repo.get(offer_id)
    if existing is None:
        raise ValueError("offer not found")
    payload["assessment"] = str(payload.get("assessment") or "")
    updated = repo.update(offer_id, _offer_create_from_payload(payload, existing))
    if updated is None:
        raise ValueError("offer not found")
    return _json(_offer_json(updated))


def _describe_create_application(args: str) -> str:
    payload = _payload(args)
    return f"新建投递：{payload.get('company_name', '')} - {payload.get('position_name', '')}"


def _describe_update_application_status(args: str) -> str:
    payload = _payload(args)
    return f"将投递 #{payload.get('id', '')} 的状态改为 {payload.get('status', '')}"


def _describe_id_action(args: str, action: str) -> str:
    payload = _payload(args)
    return f"{action} #{payload.get('id', '')}"


def _describe_note_action(args: str, action: str) -> str:
    payload = _payload(args)
    return f"{action}: {payload.get('company', '')} {payload.get('round', '')}"


def _payload(args: str) -> dict[str, Any]:
    if not args:
        return {}
    value = json.loads(args)
    if not isinstance(value, dict):
        raise ValueError("tool args must be an object")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def _optional_int(payload: dict[str, Any], key: str) -> int:
    raw = payload.get(key)
    if raw is None or raw == "":
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc


def _payload_or_existing(payload: dict[str, Any], key: str, existing: str) -> str:
    if payload.get(key) is None:
        return existing
    return str(payload.get(key) or "")


def _event_json(event: Any) -> dict[str, Any]:
    return EventOut(
        id=event.id,
        application_id=event.application_id,
        event_type=event.event_type,
        round=event.round,
        scheduled_at=event.scheduled_at.isoformat().replace("+00:00", "Z") if event.scheduled_at else "",
        duration_minutes=duration_minutes(event.duration),
        location=event.location,
        notes=event.notes,
        created_at=event.created_at,
    ).model_dump(mode="json", exclude_none=True)


def _event_with_application_json(item: Any) -> dict[str, Any]:
    payload = _event_json(item.event)
    payload["company_name"] = item.company_name
    payload["position_name"] = item.position_name
    return payload


def _note_json(note: Any) -> dict[str, Any]:
    return InterviewNoteOut.model_validate(note).model_dump(mode="json", exclude_none=True)


def _offer_json(offer: Any) -> dict[str, Any]:
    return OfferOut.model_validate(offer).model_dump(mode="json", exclude_none=True)


def _event_create_from_payload(
    applications: ApplicationsRepository,
    payload: dict[str, Any],
    tool_name: str,
) -> EventCreate:
    application_id = _required_int(payload, "application_id", tool_name)
    if applications.get(application_id) is None:
        raise ValueError("application not found")
    event_type = str(payload.get("event_type") or "")
    if event_type not in EVENT_TYPES:
        raise ValueError("invalid event type")
    scheduled_at_raw = str(payload.get("scheduled_at") or "")
    if not scheduled_at_raw:
        raise ValueError(f"{tool_name} requires scheduled_at")
    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("scheduled_at must be RFC3339") from exc
    duration = _required_int(payload, "duration_minutes", tool_name)
    if duration <= 0:
        raise ValueError("duration_minutes must be greater than 0")
    return EventCreate(
        application_id=application_id,
        event_type=event_type,
        scheduled_at=scheduled_at,
        duration_minutes=duration,
        round=_optional_int(payload, "round"),
        location=str(payload.get("location") or ""),
        notes=str(payload.get("notes") or ""),
    )


def _note_create_from_payload(
    applications: ApplicationsRepository,
    payload: dict[str, Any],
    fallback_app_id: int | None,
    tool_name: str,
) -> NoteCreate:
    application_id = fallback_app_id
    if application_id is None and payload.get("application_id") is not None:
        application_id = _optional_int(payload, "application_id")
    company = str(payload.get("company") or "")
    position = str(payload.get("position") or "")
    if application_id is not None and application_id > 0:
        app = applications.get(application_id)
        if app is None:
            raise ValueError("application not found")
        company = company or app.company_name
        position = position or app.position_name
    if not company:
        raise ValueError(f"{tool_name} requires company")
    return NoteCreate(
        application_id=application_id,
        company=company,
        position=position,
        round=str(payload.get("round") or ""),
        date=str(payload.get("date") or ""),
        questions=str(payload.get("questions") or ""),
        self_reflection=str(payload.get("self_reflection") or ""),
        difficulty_points=str(payload.get("difficulty_points") or ""),
        mood=str(payload.get("mood") or ""),
    )


def _offer_create_from_payload(payload: dict[str, Any], existing: Any) -> OfferCreate:
    status = str(payload.get("status") if payload.get("status") is not None else existing.status)
    if status not in OFFER_STATUSES:
        raise ValueError("invalid offer status")
    base_monthly = _int_or_existing(payload, "base_monthly", existing.base_monthly)
    months_per_year = _int_or_existing(payload, "months_per_year", existing.months_per_year)
    signing_bonus = _int_or_existing(payload, "signing_bonus", existing.signing_bonus)
    if base_monthly < 0 or signing_bonus < 0:
        raise ValueError("base_monthly and signing_bonus must be non-negative")
    if months_per_year < 1:
        raise ValueError("months_per_year must be at least 1")
    return OfferCreate(
        application_id=existing.application_id,
        company_name=str(
            payload.get("company_name") if payload.get("company_name") is not None else existing.company_name
        ),
        position_name=str(
            payload.get("position_name") if payload.get("position_name") is not None else existing.position_name
        ),
        status=status,
        base_monthly=base_monthly,
        months_per_year=months_per_year,
        signing_bonus=signing_bonus,
        equity=str(payload.get("equity") if payload.get("equity") is not None else existing.equity),
        perks=str(payload.get("perks") if payload.get("perks") is not None else existing.perks),
        deadline=str(payload.get("deadline") if payload.get("deadline") is not None else existing.deadline),
        notes=str(payload.get("notes") if payload.get("notes") is not None else existing.notes),
        assessment=str(
            payload.get("assessment") if payload.get("assessment") is not None else existing.assessment
        ),
    )


def _int_or_existing(payload: dict[str, Any], key: str, existing: int) -> int:
    raw = payload.get(key)
    if raw is None or raw == "":
        return existing
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc


def _id_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": description}},
        "required": ["id"],
    }


def _event_schema(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "application_id": {"type": "integer"},
            "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
            "scheduled_at": {"type": "string", "description": "RFC3339 datetime."},
            "duration_minutes": {"type": "integer"},
            "round": {"type": "integer"},
            "location": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": required,
    }


def _note_schema(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "application_id": {"type": "integer"},
            "company": {"type": "string"},
            "position": {"type": "string"},
            "round": {"type": "string"},
            "date": {"type": "string"},
            "questions": {"type": "string"},
            "self_reflection": {"type": "string"},
            "difficulty_points": {"type": "string"},
            "mood": {"type": "string"},
        },
        "required": required,
    }


def _offer_schema(required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "company_name": {"type": "string"},
            "position_name": {"type": "string"},
            "status": {"type": "string", "enum": list(OFFER_STATUSES)},
            "base_monthly": {"type": "integer"},
            "months_per_year": {"type": "integer"},
            "signing_bonus": {"type": "integer"},
            "equity": {"type": "string"},
            "perks": {"type": "string"},
            "deadline": {"type": "string"},
            "notes": {"type": "string"},
            "assessment": {"type": "string"},
        },
        "required": required,
    }
