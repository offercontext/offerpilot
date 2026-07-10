import json
from datetime import datetime, timezone

import pytest

from offerpilot.ai.tools import (
    EVENT_TYPES,
    OFFER_STATUSES,
    application_tool_registry,
    editable_fields_for_tool,
    offerpilot_tool_registry,
)
from offerpilot.application_status import APPLICATION_STATUS_IDS
from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.application_events import ApplicationEventCreate, ApplicationEventsRepository
from offerpilot.repositories.jd import JDAnalysesRepository, JDAnalysisCreate
from offerpilot.repositories.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeRepository,
)
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.repositories.resumes import ResumeCreate, ResumeMatchCreate, ResumesRepository


def test_write_tools_expose_type_aware_editable_fields_defensively(tmp_path):
    event_fields = [
        {"field": "event_type", "type": "enum", "options": list(EVENT_TYPES)},
        {"field": "subtype", "type": "string"},
        {"field": "scheduled_at", "type": "datetime"},
        {
            "field": "remind_at",
            "type": "datetime",
            "clearable": True,
            "clear_value": "",
        },
        {"field": "duration_minutes", "type": "number"},
        {"field": "round", "type": "number", "clearable": True, "clear_value": 0},
        {"field": "location", "type": "string"},
        {"field": "notes", "type": "long_text"},
        {"field": "status", "type": "string"},
    ]
    note_fields = [
        {"field": "company", "type": "string"},
        {"field": "position", "type": "string"},
        {"field": "round", "type": "string"},
        {"field": "date", "type": "datetime"},
        {"field": "allow_placeholder_date", "type": "boolean"},
        {"field": "questions", "type": "long_text"},
        {"field": "self_reflection", "type": "long_text"},
        {"field": "difficulty_points", "type": "long_text"},
        {"field": "mood", "type": "long_text"},
    ]
    expected = {
        "create_application": [
            {"field": "company_name", "type": "string"},
            {"field": "position_name", "type": "string"},
            {"field": "job_url", "type": "string"},
            {"field": "status", "type": "enum", "options": list(APPLICATION_STATUS_IDS)},
            {"field": "closed_reason", "type": "long_text"},
        ],
        "update_application_status": [
            {"field": "status", "type": "enum", "options": list(APPLICATION_STATUS_IDS)},
            {"field": "closed_reason", "type": "long_text"},
        ],
        "create_application_event": event_fields,
        "update_application_event": event_fields,
        "delete_application_event": [],
        "add_note": note_fields,
        "update_note": note_fields,
        "delete_note": [],
        "update_offer": [
            {"field": "company_name", "type": "string"},
            {"field": "position_name", "type": "string"},
            {"field": "status", "type": "enum", "options": list(OFFER_STATUSES)},
            {
                "field": "base_monthly",
                "type": "number",
                "clearable": True,
                "clear_value": 0,
            },
            {"field": "months_per_year", "type": "number"},
            {
                "field": "signing_bonus",
                "type": "number",
                "clearable": True,
                "clear_value": 0,
            },
            {"field": "equity", "type": "string"},
            {"field": "perks", "type": "long_text"},
            {
                "field": "deadline",
                "type": "datetime",
                "clearable": True,
                "clear_value": "",
            },
            {"field": "notes", "type": "long_text"},
            {"field": "assessment", "type": "long_text"},
        ],
        "save_offer_assessment": [{"field": "assessment", "type": "long_text"}],
        "resume_update_career_intent": [],
        "resume_rewrite_highlight": [{"field": "text", "type": "long_text"}],
    }

    session_factory = init_database(tmp_path / "data.db")
    registry = offerpilot_tool_registry(
        ApplicationsRepository(session_factory),
        ApplicationEventsRepository(session_factory),
        NotesRepository(session_factory),
        OffersRepository(session_factory),
        resumes=ResumesRepository(session_factory),
    )
    write_names = {name for name, entry in registry.items() if entry["write"]}

    assert write_names == set(expected)
    for tool_name, descriptors in expected.items():
        assert editable_fields_for_tool(tool_name) == descriptors
        assert registry[tool_name]["editable_fields"] == descriptors

    first = editable_fields_for_tool("update_application_status")
    first[0]["field"] = "mutated"
    first[0]["options"].append("mutated")

    assert editable_fields_for_tool("update_application_status") == expected[
        "update_application_status"
    ]


def test_clearable_tool_fields_use_declared_handler_sentinels(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    event = events.create(
        ApplicationEventCreate(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
            duration_minutes=45,
            round=2,
            remind_at=datetime(2026, 7, 10, 9, tzinfo=timezone.utc),
        )
    )
    offer = offers.create(
        OfferCreate(
            application_id=app.id,
            company_name=app.company_name,
            position_name=app.position_name,
            base_monthly=30000,
            months_per_year=15,
            signing_bonus=50000,
            deadline="2026-07-20T18:00:00+08:00",
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    cleared_event = json.loads(
        registry["update_application_event"]["handler"](
            json.dumps(
                {
                    "id": event.id,
                    "application_id": app.id,
                    "event_type": "interview",
                    "scheduled_at": "2026-07-10T10:00:00Z",
                    "duration_minutes": 45,
                    "remind_at": "",
                    "round": 0,
                }
            )
        )
    )
    cleared_offer = json.loads(
        registry["update_offer"]["handler"](
            json.dumps(
                {
                    "id": offer.id,
                    "base_monthly": 0,
                    "signing_bonus": 0,
                    "deadline": "",
                }
            )
        )
    )

    assert cleared_event.get("remind_at") is None
    assert cleared_event["round"] == 0
    assert cleared_offer["base_monthly"] == 0
    assert cleared_offer["signing_bonus"] == 0
    assert cleared_offer["deadline"] == ""


def test_application_read_tools_return_json(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(
        ApplicationCreate(company_name="ByteDance", position_name="Backend", status="interview")
    )
    registry = application_tool_registry(repo)

    listed = json.loads(registry["list_applications"]["handler"](json.dumps({"status": "interview"})))
    detail = json.loads(registry["get_application"]["handler"](json.dumps({"id": created.id})))

    assert listed[0]["company_name"] == "ByteDance"
    assert detail["id"] == created.id


def test_application_tool_schemas_require_detail_ids(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    registry = application_tool_registry(repo)

    get_schema = registry["get_application"]["schema"]
    update_schema = registry["update_application_status"]["schema"]

    assert get_schema["required"] == ["id"]
    assert update_schema["required"] == ["id", "status"]
    assert "id" in get_schema["properties"]
    assert "id" in update_schema["properties"]
    assert "closed_reason" in update_schema["properties"]


def test_get_application_requires_id_with_readable_error(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    registry = application_tool_registry(repo)

    try:
        registry["get_application"]["handler"](json.dumps({}))
    except ValueError as exc:
        assert str(exc) == "get_application requires id"
    else:
        raise AssertionError("missing id should raise a readable error")


def test_application_write_tools_are_marked_and_mutate_when_executed(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    assert registry["create_application"]["write"] is True
    assert registry["update_application_status"]["write"] is True

    updated = json.loads(
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "offer"})
        )
    )

    assert updated["status"] == "offer"
    assert repo.get(created.id).status == "offer"  # type: ignore[union-attr]


def test_application_status_tool_normalizes_legacy_status(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    updated = json.loads(
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "assessment"})
        )
    )

    assert updated["status"] == "written_test"
    assert repo.get(created.id).status == "written_test"  # type: ignore[union-attr]


def test_application_status_tool_rejects_invalid_status(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    try:
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "onsite"})
        )
    except ValueError as exc:
        assert str(exc) == "invalid application status: onsite"
    else:
        raise AssertionError("invalid status should raise")


def test_application_status_tool_requires_and_saves_closed_reason(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend", status="interview"))
    registry = application_tool_registry(repo)

    try:
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "closed"})
        )
    except ValueError as exc:
        assert str(exc) == "closed_reason is required when closing an application"
    else:
        raise AssertionError("closing without closed_reason should raise")

    closed = json.loads(
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "closed", "closed_reason": "已接受其他 offer"})
        )
    )

    assert closed["status"] == "closed"
    assert closed["closed_reason"] == "已接受其他 offer"
    assert closed["closed_at"] is not None


def test_application_status_tool_rejects_reopening_closed_application(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(
        ApplicationCreate(
            company_name="ByteDance",
            position_name="Backend",
            status="closed",
            closed_reason="岗位关闭",
        )
    )
    registry = application_tool_registry(repo)

    try:
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "interview"})
        )
    except ValueError as exc:
        assert str(exc) == "closed application cannot be reopened"
    else:
        raise AssertionError("reopening a closed application should raise")


def test_offerpilot_tool_registry_covers_notes_events_and_offers(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    note = notes.create(
        NoteCreate(
            application_id=app.id,
            company=app.company_name,
            position=app.position_name,
            round="screen",
            questions="Explain Python GIL",
            self_reflection="Concurrency basics need practice",
        )
    )
    event = events.create(
        ApplicationEventCreate(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
            duration_minutes=45,
            round=2,
        )
    )
    offer = offers.create(
        OfferCreate(
            application_id=app.id,
            company_name=app.company_name,
            position_name=app.position_name,
            status="pending",
            base_monthly=30000,
            months_per_year=15,
            signing_bonus=50000,
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    listed_notes = json.loads(registry["list_notes"]["handler"](json.dumps({"application_id": app.id})))
    listed_events = json.loads(
        registry["list_application_events"]["handler"](json.dumps({"application_id": app.id}))
    )
    listed_offers = json.loads(registry["list_offers"]["handler"](json.dumps({"status": "pending"})))
    offer_detail = json.loads(registry["get_offer"]["handler"](json.dumps({"id": offer.id})))
    compared = json.loads(registry["compare_offers"]["handler"](json.dumps({"ids": [999, offer.id]})))

    assert registry["create_application_event"]["write"] is True
    assert registry["add_note"]["schema"]["required"] == []
    assert "application_id" in registry["add_note"]["schema"]["properties"]
    assert "allow_placeholder_date" in registry["add_note"]["schema"]["properties"]
    assert listed_notes[0]["id"] == note.id
    assert listed_events[0]["id"] == event.id
    assert listed_events[0]["duration_minutes"] == 45
    assert listed_offers[0]["id"] == offer.id
    assert offer_detail["total_cash"] == 30000 * 15 + 50000
    assert [item["id"] for item in compared] == [offer.id]


def test_add_note_validation_asks_before_unclear_placeholder_date(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    validation = registry["add_note"]["validate"](
        json.dumps(
            {
                "company": "牛客网",
                "position": "软件测试工程师",
                "round": "技术一面",
                "date": "2026年XX月XX日",
            },
            ensure_ascii=False,
        )
    )
    allowed = registry["add_note"]["validate"](
        json.dumps(
            {
                "company": "牛客网",
                "position": "软件测试工程师",
                "round": "技术一面",
                "date": "日期待定",
                "allow_placeholder_date": True,
            },
            ensure_ascii=False,
        )
    )

    assert validation == (
        "add_note date is unclear; ask the user to provide a specific interview date "
        "or confirm saving it as 日期待定 before creating a pending confirmation."
    )
    assert allowed == ""


def test_offerpilot_event_tools_hide_soft_deleted_applications(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    event = events.create(
        ApplicationEventCreate(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
            duration_minutes=45,
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    applications.delete(app.id)

    assert json.loads(registry["list_application_events"]["handler"](json.dumps({}))) == []
    try:
        registry["get_application_event"]["handler"](json.dumps({"id": event.id}))
    except ValueError as exc:
        assert str(exc) == "application event not found"
    else:
        raise AssertionError("event for soft-deleted application should not be readable")

    try:
        registry["update_application_event"]["handler"](
            json.dumps(
                {
                    "id": event.id,
                    "application_id": app.id,
                    "event_type": "interview",
                    "scheduled_at": "2026-07-11T10:00:00Z",
                    "duration_minutes": 45,
                }
            )
        )
    except ValueError as exc:
        assert str(exc) == "application event not found"
    else:
        raise AssertionError("event for soft-deleted application should not be writable")

    assert registry["delete_application_event"]["handler"](json.dumps({"id": event.id})) == '{"deleted":false}'


def test_offerpilot_write_tools_mutate_notes_events_and_offers(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    offer = offers.create(
        OfferCreate(
            application_id=app.id,
            company_name=app.company_name,
            position_name=app.position_name,
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    note = json.loads(
        registry["add_note"]["handler"](
            json.dumps(
                {
                    "application_id": app.id,
                    "company": "",
                    "position": "",
                    "round": "onsite",
                    "questions": "System design",
                }
            )
        )
    )
    updated_note = json.loads(
        registry["update_note"]["handler"](
            json.dumps({"id": note["id"], "company": "Tencent", "position": "Frontend"})
        )
    )
    event_schema = registry["create_application_event"]["schema"]["properties"]
    assert registry["create_application_event"]["schema"]["properties"]["event_type"]["enum"] == [
        "written_test",
        "interview",
        "offer_step",
        "deadline",
        "custom",
    ]
    assert {"subtype", "tags", "round", "scheduled_at", "remind_at"}.issubset(event_schema)
    assert "create_event" not in registry

    event = json.loads(
        registry["create_application_event"]["handler"](
            json.dumps(
                {
                    "application_id": app.id,
                    "event_type": "interview",
                    "subtype": "technical",
                    "tags": ["backend"],
                    "scheduled_at": "2026-07-10T10:00:00Z",
                    "duration_minutes": 30,
                    "remind_at": "2026-07-10T09:30:00Z",
                }
            )
        )
    )
    updated_event = json.loads(
        registry["update_application_event"]["handler"](
            json.dumps(
                {
                    "id": event["id"],
                    "application_id": app.id,
                    "event_type": "written_test",
                    "subtype": "assessment",
                    "tags": ["campus"],
                    "scheduled_at": "2026-07-11T10:00:00Z",
                    "duration_minutes": 60,
                }
            )
        )
    )
    updated_offer = json.loads(
        registry["update_offer"]["handler"](
            json.dumps(
                {
                    "id": offer.id,
                    "company_name": app.company_name,
                    "position_name": app.position_name,
                    "status": "accepted",
                    "base_monthly": 32000,
                    "months_per_year": 16,
                }
            )
        )
    )
    assessed = json.loads(
        registry["save_offer_assessment"]["handler"](
            json.dumps({"id": offer.id, "assessment": "Strong upside"})
        )
    )

    assert note["company"] == "ByteDance"
    assert updated_note["company"] == "Tencent"
    assert updated_event["event_type"] == "written_test"
    assert updated_event["subtype"] == "assessment"
    assert updated_event["tags"] == ["campus"]
    assert updated_event["duration_minutes"] == 60
    assert updated_offer["status"] == "accepted"
    assert assessed["assessment"] == "Strong upside"
    assert registry["delete_note"]["handler"](json.dumps({"id": note["id"]})) == '{"deleted":true}'
    assert registry["delete_application_event"]["handler"](json.dumps({"id": event["id"]})) == '{"deleted":true}'


def test_offer_tools_distinguish_offer_ids_from_application_ids(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    offer = offers.create(
        OfferCreate(
            company_name="Alibaba",
            position_name="Java Backend P6",
            base_monthly=32000,
            months_per_year=16,
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    listed = json.loads(registry["list_offers"]["handler"](json.dumps({})))
    detail = json.loads(registry["get_offer"]["handler"](json.dumps({"id": offer.id})))

    assert "not an application id" in registry["list_offers"]["description"]
    assert listed[0]["record_type"] == "offer"
    assert listed[0]["offer_id"] == offer.id
    assert listed[0]["id"] == offer.id
    assert "application_id" in listed[0]
    assert listed[0]["application_id"] is None
    assert detail["offer_id"] == offer.id


def test_offerpilot_tool_registry_covers_resumes_jd_and_knowledge(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    jd_analyses = JDAnalysesRepository(session_factory)
    knowledge = KnowledgeRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    resume = resumes.create(
        ResumeCreate(name="Backend Resume", parsed_data="Python FastAPI SQLAlchemy", parse_status="text-ready")
    )
    resumes.create_match(
        ResumeMatchCreate(
            resume_id=resume.id,
            application_id=app.id,
            jd_text="Backend API",
            result='{"match_score":88}',
        )
    )
    jd = jd_analyses.create(
        JDAnalysisCreate(
            application_id=app.id,
            jd_source="manual",
            jd_text="Python backend engineer",
            result='{"summary":"Backend role"}',
        )
    )
    doc = knowledge.create_document(
        KnowledgeDocumentCreate(
            title="FastAPI Review",
            content="FastAPI dependency injection and SQLAlchemy sessions",
            tags=["python"],
        )
    )

    registry = offerpilot_tool_registry(
        applications,
        events,
        notes,
        offers,
        resumes=resumes,
        jd_analyses=jd_analyses,
        knowledge=knowledge,
    )

    listed_resumes = json.loads(registry["list_resumes"]["handler"](json.dumps({})))
    resume_detail = json.loads(registry["get_resume"]["handler"](json.dumps({"id": resume.id})))
    resume_matches = json.loads(registry["list_resume_matches"]["handler"](json.dumps({"resume_id": resume.id})))
    listed_jds = json.loads(registry["list_jd_analyses"]["handler"](json.dumps({"application_id": app.id})))
    jd_detail = json.loads(registry["get_jd_analysis"]["handler"](json.dumps({"id": jd.id})))
    documents = json.loads(registry["list_knowledge_documents"]["handler"](json.dumps({})))
    document_detail = json.loads(registry["get_knowledge_document"]["handler"](json.dumps({"id": doc.id})))
    search_results = json.loads(registry["search_knowledge"]["handler"](json.dumps({"query": "FastAPI"})))

    assert listed_resumes[0]["id"] == resume.id
    assert listed_resumes[0]["record_type"] == "resume"
    assert listed_resumes[0]["resume_id"] == resume.id
    assert resume_detail["parsed_data"] == "Python FastAPI SQLAlchemy"
    assert resume_detail["resume_id"] == resume.id
    assert resume_matches[0]["application_id"] == app.id
    assert resume_matches[0]["record_type"] == "resume_match"
    assert resume_matches[0]["resume_match_id"] == resume_matches[0]["id"]
    assert resume_matches[0]["resume_id"] == resume.id
    assert listed_jds[0]["id"] == jd.id
    assert listed_jds[0]["record_type"] == "jd_analysis"
    assert listed_jds[0]["jd_analysis_id"] == jd.id
    assert listed_jds[0]["application_id"] == app.id
    assert jd_detail["result"] == '{"summary":"Backend role"}'
    assert jd_detail["jd_analysis_id"] == jd.id
    assert documents[0]["id"] == doc.id
    assert documents[0]["record_type"] == "knowledge_document"
    assert documents[0]["knowledge_document_id"] == doc.id
    assert "knowledge_base_id" not in documents[0]
    assert document_detail["title"] == "FastAPI Review"
    assert document_detail["knowledge_document_id"] == doc.id
    assert search_results[0]["document_id"] == doc.id
    assert search_results[0]["record_type"] == "knowledge_search_result"
    assert search_results[0]["search_result_id"] == search_results[0]["chunk_id"]
    assert "knowledge_base_id" not in search_results[0]


def test_resume_write_tools_are_marked_and_update_structured_content(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    resume = resumes.create(
        ResumeCreate(
            title="Backend Resume",
            source="manual",
            content_json={
                "career_intent": {"target_roles": []},
                "experience": [{"company": "OfferPilot", "highlights": ["Built APIs"]}],
            },
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers, resumes=resumes)

    assert registry["resume_update_career_intent"]["write"] is True
    assert registry["resume_rewrite_highlight"]["write"] is True
    assert "describe" in registry["resume_update_career_intent"]
    assert "describe" in registry["resume_rewrite_highlight"]

    updated = json.loads(
        registry["resume_update_career_intent"]["handler"](
            json.dumps(
                {
                    "id": resume.id,
                    "career_intent": {
                        "target_roles": ["Backend Engineer"],
                        "target_locations": ["Shanghai"],
                    },
                }
            )
        )
    )
    rewritten = json.loads(
        registry["resume_rewrite_highlight"]["handler"](
            json.dumps(
                {
                    "id": resume.id,
                    "section": "experience",
                    "item_index": 0,
                    "highlight_index": 0,
                    "text": "Built FastAPI resume APIs with structured persistence.",
                }
            )
        )
    )

    assert updated["content_json"]["career_intent"]["target_roles"] == ["Backend Engineer"]
    assert rewritten["content_json"]["experience"][0]["highlights"] == [
        "Built FastAPI resume APIs with structured persistence."
    ]
    assert resumes.get(resume.id).content_json == json.dumps(  # type: ignore[union-attr]
        rewritten["content_json"],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_resume_tools_reject_deleted_resume_and_negative_highlight_indexes(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    active = resumes.create(
        ResumeCreate(
            title="Active Resume",
            source="manual",
            content_json={
                "career_intent": {"target_roles": ["Backend Engineer"]},
                "experience": [{"company": "OfferPilot", "highlights": ["Built APIs"]}],
            },
        )
    )
    deleted = resumes.create(
        ResumeCreate(
            title="Deleted Resume",
            source="manual",
            is_master=False,
            content_json={"experience": [{"highlights": ["Old"]}]},
        )
    )
    resumes.create_match(
        ResumeMatchCreate(
            resume_id=deleted.id,
            jd_text="Backend API engineer",
            result='{"summary":"legacy match"}',
        )
    )
    resumes.delete(deleted.id)
    registry = offerpilot_tool_registry(applications, events, notes, offers, resumes=resumes)

    with pytest.raises(ValueError, match="resume not found"):
        registry["get_resume"]["handler"](json.dumps({"id": deleted.id}))
    with pytest.raises(ValueError, match="resume not found"):
        registry["resume_update_career_intent"]["handler"](
            json.dumps({"id": deleted.id, "career_intent": {"target_roles": ["Backend"]}})
        )
    with pytest.raises(ValueError, match="resume not found"):
        registry["resume_rewrite_highlight"]["handler"](
            json.dumps(
                {
                    "id": deleted.id,
                    "section": "experience",
                    "item_index": 0,
                    "highlight_index": 0,
                    "text": "new",
                }
            )
        )
    with pytest.raises(ValueError, match="resume not found"):
        registry["list_resume_matches"]["handler"](json.dumps({"resume_id": deleted.id}))
    with pytest.raises(ValueError, match="item_index must be non-negative"):
        registry["resume_rewrite_highlight"]["handler"](
            json.dumps(
                {
                    "id": active.id,
                    "section": "experience",
                    "item_index": -1,
                    "highlight_index": 0,
                    "text": "new",
                }
            )
        )
    with pytest.raises(ValueError, match="highlight_index must be non-negative"):
        registry["resume_rewrite_highlight"]["handler"](
            json.dumps(
                {
                    "id": active.id,
                    "section": "experience",
                    "item_index": 0,
                    "highlight_index": -1,
                    "text": "new",
                }
            )
        )


def test_ai_tool_read_results_include_record_type_and_specific_ids(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    notes = NotesRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    offers = OffersRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="PDD", position_name="Agent Dev"))
    event = events.create(
        ApplicationEventCreate(
            application_id=app.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 15, 14, tzinfo=timezone.utc),
            duration_minutes=45,
        )
    )
    note = notes.create(
        NoteCreate(
            application_id=app.id,
            company=app.company_name,
            position=app.position_name,
            round="tech",
            questions="Agent memory design",
        )
    )
    offer = offers.create(
        OfferCreate(
            application_id=app.id,
            company_name=app.company_name,
            position_name=app.position_name,
        )
    )
    registry = offerpilot_tool_registry(applications, events, notes, offers)

    application_result = json.loads(registry["get_application"]["handler"](json.dumps({"id": app.id})))
    event_result = json.loads(registry["get_application_event"]["handler"](json.dumps({"id": event.id})))
    note_result = json.loads(registry["list_notes"]["handler"](json.dumps({"application_id": app.id})))[0]
    offer_result = json.loads(registry["get_offer"]["handler"](json.dumps({"id": offer.id})))

    assert application_result["record_type"] == "application"
    assert application_result["application_id"] == app.id
    assert event_result["record_type"] == "application_event"
    assert event_result["application_event_id"] == event.id
    assert event_result["application_id"] == app.id
    assert note_result["record_type"] == "note"
    assert note_result["note_id"] == note.id
    assert note_result["application_id"] == app.id
    assert offer_result["record_type"] == "offer"
    assert offer_result["offer_id"] == offer.id
    assert offer_result["application_id"] == app.id
