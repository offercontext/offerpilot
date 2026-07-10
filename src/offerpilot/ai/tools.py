from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from offerpilot.application_status import APPLICATION_STATUS_IDS, normalize_application_status
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.application_events import (
    ApplicationEventCreate,
    ApplicationEventsRepository,
    duration_minutes,
)
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.knowledge import KnowledgeRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.repositories.resumes import ResumesRepository
from offerpilot.schemas import (
    ApplicationOut,
    ApplicationEventOut,
    InterviewNoteOut,
    JDAnalysisOut,
    KnowledgeDocumentOut,
    OfferOut,
    ResumeMatchOut,
    normalize_resume_content,
    resume_payload,
)


EVENT_TYPES = ("written_test", "interview", "offer_step", "deadline", "custom")
OFFER_STATUSES = ("pending", "negotiating", "accepted", "declined", "expired")


def offerpilot_tool_registry(
    applications: ApplicationsRepository,
    events: ApplicationEventsRepository,
    notes: NotesRepository,
    offers: OffersRepository,
    *,
    resumes: ResumesRepository | None = None,
    jd_analyses: JDAnalysesRepository | None = None,
    knowledge: KnowledgeRepository | None = None,
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    registry.update(application_tool_registry(applications))
    registry.update(event_tool_registry(applications, events))
    registry.update(note_tool_registry(applications, notes))
    registry.update(offer_tool_registry(offers))
    if resumes is not None:
        registry.update(resume_tool_registry(resumes))
    if jd_analyses is not None:
        registry.update(jd_tool_registry(jd_analyses))
    if knowledge is not None:
        registry.update(knowledge_tool_registry(knowledge))
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
            "description": (
                "Create a job application record. If the same company already has records but this is a new "
                "position, ask the user before creating it; set confirmed_new_position=true only after the user "
                "explicitly confirms the new position should be added."
            ),
            "schema": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "position_name": {"type": "string"},
                    "job_url": {"type": "string"},
                    "status": {"type": "string", "enum": list(APPLICATION_STATUS_IDS)},
                    "confirmed_new_position": {
                        "type": "boolean",
                        "description": (
                            "Set true only when the user explicitly confirmed creating a new position for "
                            "an existing company."
                        ),
                    },
                    "closed_reason": {
                        "type": "string",
                        "description": "Required when status is closed.",
                    },
                },
                "required": ["company_name", "position_name"],
            },
            "describe": _describe_create_application,
            "validate": lambda args: _validate_create_application(repo, args),
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
                    "closed_reason": {
                        "type": "string",
                        "description": "Required when status is closed.",
                    },
                },
                "required": ["id", "status"],
            },
            "describe": _describe_update_application_status,
            "handler": lambda args: _update_application_status(repo, args),
        },
    }


def event_tool_registry(
    applications: ApplicationsRepository,
    repo: ApplicationEventsRepository,
) -> dict[str, dict[str, Any]]:
    return {
        "list_application_events": {
            "write": False,
            "description": "List application events such as written tests, interviews, offer steps, deadlines, or custom events.",
            "schema": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Optional YYYY-MM month filter."},
                    "application_id": {"type": "integer"},
                    "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
                },
            },
            "handler": lambda args: _list_application_events(repo, args),
        },
        "get_application_event": {
            "write": False,
            "description": "Get one application event by id.",
            "schema": _id_schema("Application event id."),
            "handler": lambda args: _get_application_event(repo, args),
        },
        "create_application_event": {
            "write": True,
            "description": "Create an application event. Use written_test.subtype=assessment for assessments.",
            "schema": _event_schema(["application_id", "event_type", "scheduled_at", "duration_minutes"]),
            "describe": _describe_create_application_event,
            "handler": lambda args: _create_application_event(applications, repo, args),
        },
        "update_application_event": {
            "write": True,
            "description": "Update an existing application event.",
            "schema": _event_schema(["id", "application_id", "event_type", "scheduled_at", "duration_minutes"]),
            "describe": lambda args: _describe_id_action(args, "更新日程"),
            "handler": lambda args: _update_application_event(applications, repo, args),
        },
        "delete_application_event": {
            "write": True,
            "always_confirm": True,
            "description": "Delete an application event by id.",
            "schema": _id_schema("Application event id."),
            "describe": lambda args: _describe_id_action(args, "删除日程"),
            "handler": lambda args: _delete_application_event(repo, args),
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
            "always_confirm": True,
            "description": "Add an interview review note. If application_id is present, company and position can be omitted.",
            "schema": _note_schema([]),
            "describe": lambda args: _describe_note_action(args, "新增复盘"),
            "validate": _validate_note_action,
            "handler": lambda args: _add_note(applications, repo, args),
        },
        "update_note": {
            "write": True,
            "always_confirm": True,
            "description": "Update an existing interview review note. Missing fields keep existing values.",
            "schema": _note_schema(["id"]),
            "describe": lambda args: _describe_id_action(args, "更新复盘"),
            "handler": lambda args: _update_note(repo, args),
        },
        "delete_note": {
            "write": True,
            "always_confirm": True,
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
            "description": (
                "List offers. The returned id is an offer id, not an application id; "
                "use application_id only when it is present."
            ),
            "schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": list(OFFER_STATUSES)}},
            },
            "handler": lambda args: _list_offers(repo, args),
        },
        "get_offer": {
            "write": False,
            "description": "Get one offer by offer id. Offer id is not an application id.",
            "schema": _id_schema("Offer id."),
            "handler": lambda args: _get_offer(repo, args),
        },
        "compare_offers": {
            "write": False,
            "description": "Compare offers by offer ids. Missing ids are skipped.",
            "schema": {
                "type": "object",
                "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
                "required": ["ids"],
            },
            "handler": lambda args: _compare_offers(repo, args),
        },
        "update_offer": {
            "write": True,
            "always_confirm": True,
            "description": "Update an offer. Missing fields keep existing values.",
            "schema": _offer_schema(["id"]),
            "describe": lambda args: _describe_id_action(args, "更新 Offer"),
            "handler": lambda args: _update_offer(repo, args),
        },
        "save_offer_assessment": {
            "write": True,
            "always_confirm": True,
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


def resume_tool_registry(repo: ResumesRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_resumes": {
            "write": False,
            "description": "List resumes and their parse status.",
            "schema": {"type": "object", "properties": {}},
            "handler": lambda args: _list_resumes(repo, args),
        },
        "get_resume": {
            "write": False,
            "description": "Get one resume including parsed text by id.",
            "schema": _id_schema("Resume id."),
            "handler": lambda args: _get_resume(repo, args),
        },
        "resume_update_career_intent": {
            "write": True,
            "always_confirm": True,
            "description": "Update a resume's career_intent block. Requires user confirmation.",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "career_intent": {"type": "object"},
                },
                "required": ["id", "career_intent"],
            },
            "describe": lambda args: _describe_id_action(args, "更新简历求职意向"),
            "handler": lambda args: _resume_update_career_intent(repo, args),
        },
        "resume_rewrite_highlight": {
            "write": True,
            "always_confirm": True,
            "description": "Rewrite one highlight in a structured resume section. Requires user confirmation.",
            "schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "section": {"type": "string"},
                    "item_index": {"type": "integer"},
                    "highlight_index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "section", "item_index", "highlight_index", "text"],
            },
            "describe": lambda args: _describe_id_action(args, "改写简历亮点"),
            "handler": lambda args: _resume_rewrite_highlight(repo, args),
        },
        "list_resume_matches": {
            "write": False,
            "description": "List saved JD match results for a resume.",
            "schema": {
                "type": "object",
                "properties": {"resume_id": {"type": "integer"}},
                "required": ["resume_id"],
            },
            "handler": lambda args: _list_resume_matches(repo, args),
        },
    }


def jd_tool_registry(repo: JDAnalysesRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_jd_analyses": {
            "write": False,
            "description": "List saved JD analyses. Optionally filter by application id.",
            "schema": {
                "type": "object",
                "properties": {"application_id": {"type": "integer"}},
            },
            "handler": lambda args: _list_jd_analyses(repo, args),
        },
        "get_jd_analysis": {
            "write": False,
            "description": "Get one saved JD analysis by id.",
            "schema": _id_schema("JD analysis id."),
            "handler": lambda args: _get_jd_analysis(repo, args),
        },
    }


def knowledge_tool_registry(repo: KnowledgeRepository) -> dict[str, dict[str, Any]]:
    return {
        "list_knowledge_documents": {
            "write": False,
            "description": "List documents in the single v0.1 knowledge library, optionally filtered by query.",
            "schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
            "handler": lambda args: _list_knowledge_documents(repo, args),
        },
        "get_knowledge_document": {
            "write": False,
            "description": "Get one knowledge document by id.",
            "schema": _id_schema("Knowledge document id."),
            "handler": lambda args: _get_knowledge_document(repo, args),
        },
        "search_knowledge": {
            "write": False,
            "description": "Search knowledge content and return matching snippets.",
            "schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            "handler": lambda args: _search_knowledge(repo, args),
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
            closed_reason=str(payload.get("closed_reason") or ""),
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
            closed_reason=str(payload.get("closed_reason") or ""),
        ),
    )
    if updated is None:
        raise ValueError("application not found")
    return json.dumps(_application_json(updated), ensure_ascii=False)


def _list_application_events(repo: ApplicationEventsRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list(
        month=str(payload.get("month") or ""),
        application_id=_optional_int(payload, "application_id"),
        event_type=str(payload.get("event_type") or ""),
    )
    return _json([_event_with_application_json(item) for item in rows])


def _get_application_event(repo: ApplicationEventsRepository, args: str) -> str:
    payload = _payload(args)
    event = repo.get(_required_int(payload, "id", "get_application_event"))
    if event is None:
        raise ValueError("application event not found")
    return _json(_event_json(event))


def _create_application_event(
    applications: ApplicationsRepository,
    repo: ApplicationEventsRepository,
    args: str,
) -> str:
    payload = _payload(args)
    event = repo.create(_event_create_from_payload(applications, payload, "create_application_event"))
    return _json(_event_json(event))


def _update_application_event(
    applications: ApplicationsRepository,
    repo: ApplicationEventsRepository,
    args: str,
) -> str:
    payload = _payload(args)
    event_id = _required_int(payload, "id", "update_application_event")
    if repo.get(event_id) is None:
        raise ValueError("application event not found")
    event = repo.update(event_id, _event_create_from_payload(applications, payload, "update_application_event"))
    if event is None:
        raise ValueError("application event not found")
    return _json(_event_json(event))


def _delete_application_event(repo: ApplicationEventsRepository, args: str) -> str:
    payload = _payload(args)
    event_id = _required_int(payload, "id", "delete_application_event")
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


def _list_resumes(repo: ResumesRepository, args: str) -> str:
    _payload(args)
    return _json([_resume_json(resume) for resume in repo.list()])


def _get_resume(repo: ResumesRepository, args: str) -> str:
    payload = _payload(args)
    resume = repo.get(_required_int(payload, "id", "get_resume"))
    if resume is None:
        raise ValueError("resume not found")
    return _json(_resume_json(resume))


def _resume_update_career_intent(repo: ResumesRepository, args: str) -> str:
    payload = _payload(args)
    resume_id = _required_int(payload, "id", "resume_update_career_intent")
    career_intent = payload.get("career_intent")
    if not isinstance(career_intent, dict):
        raise ValueError("resume_update_career_intent requires career_intent object")
    resume = repo.get(resume_id)
    if resume is None or resume.deleted_at is not None:
        raise ValueError("resume not found")
    content = normalize_resume_content(resume.content_json)
    content["career_intent"] = career_intent
    updated = repo.update(resume_id, {"content_json": content})
    if updated is None:
        raise ValueError("resume not found")
    return _json(_resume_json(updated))


def _resume_rewrite_highlight(repo: ResumesRepository, args: str) -> str:
    payload = _payload(args)
    resume_id = _required_int(payload, "id", "resume_rewrite_highlight")
    section = str(payload.get("section") or "").strip()
    item_index = _required_int(payload, "item_index", "resume_rewrite_highlight")
    highlight_index = _required_int(payload, "highlight_index", "resume_rewrite_highlight")
    text = str(payload.get("text") or "").strip()
    if not section:
        raise ValueError("resume_rewrite_highlight requires section")
    if item_index < 0:
        raise ValueError("item_index must be non-negative")
    if highlight_index < 0:
        raise ValueError("highlight_index must be non-negative")
    if not text:
        raise ValueError("resume_rewrite_highlight requires text")
    resume = repo.get(resume_id)
    if resume is None or resume.deleted_at is not None:
        raise ValueError("resume not found")
    content = normalize_resume_content(resume.content_json)
    section_items = content.get(section)
    if not isinstance(section_items, list):
        raise ValueError(f"resume section not found: {section}")
    try:
        item = section_items[item_index]
    except IndexError as exc:
        raise ValueError("resume_rewrite_highlight item_index out of range") from exc
    if not isinstance(item, dict):
        raise ValueError("resume_rewrite_highlight item must be an object")
    highlights = item.get("highlights")
    if not isinstance(highlights, list):
        raise ValueError("resume_rewrite_highlight requires highlights list")
    try:
        highlights[highlight_index] = text
    except IndexError as exc:
        raise ValueError("resume_rewrite_highlight highlight_index out of range") from exc
    updated = repo.update(resume_id, {"content_json": content})
    if updated is None:
        raise ValueError("resume not found")
    return _json(_resume_json(updated))


def _list_resume_matches(repo: ResumesRepository, args: str) -> str:
    payload = _payload(args)
    resume_id = _required_int(payload, "resume_id", "list_resume_matches")
    if repo.get(resume_id) is None:
        raise ValueError("resume not found")
    return _json([_resume_match_json(match) for match in repo.list_matches(resume_id)])


def _list_jd_analyses(repo: JDAnalysesRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list(application_id=_optional_int(payload, "application_id"))
    return _json([_jd_analysis_json(row) for row in rows])


def _get_jd_analysis(repo: JDAnalysesRepository, args: str) -> str:
    payload = _payload(args)
    analysis = repo.get(_required_int(payload, "id", "get_jd_analysis"))
    if analysis is None:
        raise ValueError("jd analysis not found")
    return _json(_jd_analysis_json(analysis))


def _list_knowledge_documents(repo: KnowledgeRepository, args: str) -> str:
    payload = _payload(args)
    rows = repo.list_documents(
        query=str(payload.get("query") or ""),
    )
    return _json([_knowledge_document_json(row) for row in rows])


def _get_knowledge_document(repo: KnowledgeRepository, args: str) -> str:
    payload = _payload(args)
    document = repo.get_document(_required_int(payload, "id", "get_knowledge_document"))
    if document is None:
        raise ValueError("knowledge document not found")
    return _json(_knowledge_document_json(document))


def _search_knowledge(repo: KnowledgeRepository, args: str) -> str:
    payload = _payload(args)
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("search_knowledge requires query")
    rows = repo.search(
        query,
        limit=_optional_int(payload, "limit") or 5,
    )
    return _json([_knowledge_search_result_json(row) for row in rows])


def _describe_create_application(args: str) -> str:
    payload = _payload(args)
    return f"新建投递：{payload.get('company_name', '')} - {payload.get('position_name', '')}"


def _validate_create_application(repo: ApplicationsRepository, args: str) -> str:
    payload = _payload(args)
    company = str(payload.get("company_name") or "").strip()
    position = str(payload.get("position_name") or "").strip()
    if not company or not position or bool(payload.get("confirmed_new_position")):
        return ""

    company_key = company.casefold()
    position_key = position.casefold()
    same_company = [item for item in repo.list() if item.company_name.strip().casefold() == company_key]
    if not same_company:
        return ""
    if any(item.position_name.strip().casefold() == position_key for item in same_company):
        return ""
    existing_positions = "、".join(sorted({item.position_name for item in same_company if item.position_name}))
    return (
        "create_application requires explicit user confirmation before adding a new position "
        f"for existing company {company}. Existing positions: {existing_positions or 'unknown'}."
    )


def _describe_update_application_status(args: str) -> str:
    payload = _payload(args)
    return f"将投递 #{payload.get('id', '')} 的状态改为 {payload.get('status', '')}"


_EVENT_TYPE_LABELS = {
    "written_test": "笔试",
    "interview": "面试",
    "offer_step": "Offer 进展",
    "deadline": "截止",
    "custom": "自定义",
}


def _describe_create_application_event(args: str) -> str:
    payload = _payload(args)
    event_type = str(payload.get("event_type") or "")
    title = _EVENT_TYPE_LABELS.get(event_type, "日程")
    scheduled_at = _format_pending_datetime(str(payload.get("scheduled_at") or ""))
    duration = _format_pending_duration(payload.get("duration_minutes"))
    details = " · ".join(value for value in [title, scheduled_at, duration] if value)
    return f"新建日程：{details}" if details else "新建日程"


def _describe_id_action(args: str, action: str) -> str:
    payload = _payload(args)
    return f"{action} #{payload.get('id', '')}"


def _format_pending_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=8)))
    return parsed.strftime("%Y-%m-%d %H:%M")


def _format_pending_duration(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{minutes} 分钟"


def _describe_note_action(args: str, action: str) -> str:
    payload = _payload(args)
    company = str(payload.get("company") or "").strip()
    position = str(payload.get("position") or "").strip()
    round_name = str(payload.get("round") or "").strip()
    details = " · ".join(value for value in [company, position, round_name] if value)
    return f"{action}：{details}" if details else action


def _validate_note_action(args: str) -> str:
    payload = _payload(args)
    date = str(payload.get("date") or "").strip()
    if date and not bool(payload.get("allow_placeholder_date")) and _looks_unclear_note_date(date):
        return (
            "add_note date is unclear; ask the user to provide a specific interview date "
            "or confirm saving it as 日期待定 before creating a pending confirmation."
        )
    if _optional_int(payload, "application_id") > 0:
        return ""
    if str(payload.get("company") or "").strip():
        return ""
    return "add_note requires company when application_id is not provided"


def _looks_unclear_note_date(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return False
    if normalized in {"日期待定", "待定", "unknown", "tbd"}:
        return True
    return bool(re.search(r"(xx|x月|x日|某|待补|待确认|不详|未知)", normalized))


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
    payload = ApplicationOut.model_validate(app).model_dump(mode="json")
    payload["record_type"] = "application"
    payload["application_id"] = app.id
    return payload


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
    payload = ApplicationEventOut(
        id=event.id,
        application_id=event.application_id,
        event_type=event.event_type,
        subtype=event.subtype,
        tags=event.tags,
        round=event.round,
        scheduled_at=_format_rfc3339(event.scheduled_at),
        duration_minutes=duration_minutes(event.duration_minutes),
        location=event.location,
        notes=event.notes,
        remind_at=_format_rfc3339(event.remind_at) if event.remind_at else None,
        status=event.status,
        created_at=event.created_at,
    ).model_dump(mode="json", exclude_none=True)
    payload["record_type"] = "application_event"
    payload["application_event_id"] = event.id
    return payload


def _format_rfc3339(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _event_with_application_json(item: Any) -> dict[str, Any]:
    payload = _event_json(item.event)
    payload["company_name"] = item.company_name
    payload["position_name"] = item.position_name
    return payload


def _note_json(note: Any) -> dict[str, Any]:
    payload = InterviewNoteOut.model_validate(note).model_dump(mode="json", exclude_none=False)
    payload["record_type"] = "note"
    payload["note_id"] = note.id
    return payload


def _offer_json(offer: Any) -> dict[str, Any]:
    payload = OfferOut.model_validate(offer).model_dump(mode="json", exclude_none=False)
    payload["record_type"] = "offer"
    payload["offer_id"] = offer.id
    return payload


def _resume_json(resume: Any) -> dict[str, Any]:
    payload = resume_payload(resume)
    payload["record_type"] = "resume"
    payload["resume_id"] = resume.id
    return payload


def _resume_match_json(match: Any) -> dict[str, Any]:
    payload = ResumeMatchOut.model_validate(match).model_dump(mode="json", exclude_none=False)
    payload["record_type"] = "resume_match"
    payload["resume_match_id"] = match.id
    return payload


def _jd_analysis_json(analysis: Any) -> dict[str, Any]:
    payload = JDAnalysisOut.model_validate(analysis).model_dump(mode="json", exclude_none=False)
    payload["record_type"] = "jd_analysis"
    payload["jd_analysis_id"] = analysis.id
    return payload


def _knowledge_document_json(document: Any) -> dict[str, Any]:
    payload = KnowledgeDocumentOut.model_validate(document).model_dump(mode="json")
    payload["record_type"] = "knowledge_document"
    payload["knowledge_document_id"] = document.id
    return payload


def _knowledge_search_result_json(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["record_type"] = "knowledge_search_result"
    payload["search_result_id"] = row["chunk_id"]
    return payload


def _event_create_from_payload(
    applications: ApplicationsRepository,
    payload: dict[str, Any],
    tool_name: str,
) -> ApplicationEventCreate:
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
    remind_at = None
    remind_at_raw = str(payload.get("remind_at") or "")
    if remind_at_raw:
        try:
            remind_at = datetime.fromisoformat(remind_at_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("remind_at must be RFC3339") from exc
    duration = _required_int(payload, "duration_minutes", tool_name)
    if duration <= 0:
        raise ValueError("duration_minutes must be greater than 0")
    return ApplicationEventCreate(
        application_id=application_id,
        event_type=event_type,
        subtype=str(payload.get("subtype") or ""),
        tags=_optional_str_list(payload, "tags"),
        scheduled_at=scheduled_at,
        duration_minutes=duration,
        round=_optional_int(payload, "round"),
        location=str(payload.get("location") or ""),
        notes=str(payload.get("notes") or ""),
        remind_at=remind_at,
        status=str(payload.get("status") or "todo"),
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


def _optional_str_list(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be an array")
    return [str(item).strip() for item in raw if str(item).strip()]


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
            "subtype": {
                "type": "string",
                "description": "Mutually exclusive detail under event_type, e.g. written_test.subtype=assessment.",
            },
            "tags": {"type": "array", "items": {"type": "string"}},
            "scheduled_at": {"type": "string", "description": "RFC3339 datetime."},
            "remind_at": {"type": "string", "description": "Optional RFC3339 reminder datetime."},
            "duration_minutes": {"type": "integer"},
            "round": {"type": "integer"},
            "location": {"type": "string"},
            "notes": {"type": "string"},
            "status": {"type": "string"},
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
            "allow_placeholder_date": {
                "type": "boolean",
                "description": "Set true only after the user confirms saving an unclear interview date as 日期待定.",
            },
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
