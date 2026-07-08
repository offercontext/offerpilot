import json
from datetime import datetime, timezone

from offerpilot.ai.tools import application_tool_registry, offerpilot_tool_registry
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
    assert listed_notes[0]["id"] == note.id
    assert listed_events[0]["id"] == event.id
    assert listed_events[0]["duration_minutes"] == 45
    assert listed_offers[0]["id"] == offer.id
    assert offer_detail["total_cash"] == 30000 * 15 + 50000
    assert [item["id"] for item in compared] == [offer.id]


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
