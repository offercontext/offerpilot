import json
import re
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from secrets import compare_digest
from typing import Any, Optional

import httpx
from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pypdf import PdfReader

from offerpilot.ai.agent import DEFAULT_MAX_ITERATIONS, ChatModel, PendingAction, resume_after_confirm, run_turn
from offerpilot.ai.client import ConfiguredAIClient
from offerpilot.ai.tools import offerpilot_tool_registry
from offerpilot.ai.types import Message, ToolCall
from offerpilot.application_status import application_status_options, normalize_application_status
from offerpilot.config import (
    AIProviderProfile,
    Config,
    load_config,
    normalize_runtime_mode,
    resolve_data_dir,
    save_config,
)
from offerpilot.db import session_factory_for_data_dir
from offerpilot.diagnostics import read_recent_log_entries
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.chat import ChatRepository
from offerpilot.repositories.application_events import (
    ApplicationEventCreate,
    ApplicationEventsRepository,
    duration_minutes,
)
from offerpilot.repositories.jd import JDAnalysesRepository, JDAnalysisCreate
from offerpilot.repositories.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeRepository,
)
from offerpilot.repositories.material_kits import MaterialKitCreate, MaterialKitsRepository
from offerpilot.repositories.mock import MockSessionCreate, MockSessionsRepository
from offerpilot.repositories.notes import NoteCreate, NotesRepository
from offerpilot.repositories.offers import OfferCreate, OffersRepository
from offerpilot.repositories.questions import QuestionCreate, QuestionsRepository, question_hash
from offerpilot.repositories.resumes import ResumeCreate, ResumeMatchCreate, ResumesRepository
from offerpilot.repositories.wakeups import WakeupCreate, WakeupsRepository, wakeup_payload
from offerpilot.schemas import (
    ApplicationOut,
    ChatMessageOut,
    ConversationOut,
    ApplicationEventOut,
    InterviewNoteOut,
    JDAnalysisOut,
    KnowledgeDocumentOut,
    MaterialKitOut,
    MockSessionOut,
    OfferOut,
    QuestionOut,
    QuestionReviewOut,
    ResumeMatchOut,
    normalize_resume_content,
    resume_payload,
)
from offerpilot.skills import SkillRegistryError, register_skill, skills_payload, update_skill


def create_app(
    data_dir: Optional[Path] = None,
    chat_model: Optional[ChatModel] = None,
    static_dir: Optional[Path] = None,
) -> FastAPI:
    resolved_data_dir = data_dir or resolve_data_dir()
    resolved_static_dir = static_dir or _find_static_dir()
    session_factory = session_factory_for_data_dir(resolved_data_dir)
    applications = ApplicationsRepository(session_factory)
    chat = ChatRepository(session_factory)
    events = ApplicationEventsRepository(session_factory)
    notes = NotesRepository(session_factory)
    offers = OffersRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    jd_analyses = JDAnalysesRepository(session_factory)
    knowledge = KnowledgeRepository(session_factory)
    questions = QuestionsRepository(session_factory)
    material_kits = MaterialKitsRepository(session_factory)
    mock_sessions = MockSessionsRepository(session_factory)
    wakeups = WakeupsRepository(session_factory)
    app = FastAPI(title="OfferPilot")

    @app.middleware("http")
    async def cors_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "OPTIONS":
            response = Response(status_code=200)
        else:
            auth_response = _auth_guard_response(request, resolved_data_dir)
            response = auth_response if auth_response is not None else await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-OfferPilot-Token"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(400, "Invalid ID")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/auth/status")
    def auth_status(request: Request) -> dict[str, bool]:
        cfg = load_config(resolved_data_dir)
        return {
            "auth_enabled": cfg.auth_enabled,
            "authenticated": (not cfg.auth_enabled) or _request_has_valid_auth_token(request, cfg.auth_token),
        }

    @app.get("/api/application-statuses")
    def list_application_statuses() -> list[dict[str, str]]:
        return application_status_options()

    @app.get("/api/applications")
    def list_applications(status: str = "") -> Any:
        parsed_status = _parse_application_status(status)
        if isinstance(parsed_status, JSONResponse):
            return parsed_status
        apps = applications.list(status=parsed_status)
        return [ApplicationOut.model_validate(item).model_dump(mode="json") for item in apps]

    @app.post("/api/applications", status_code=201)
    def create_application(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        company_name = str(payload.get("company_name") or "")
        position_name = str(payload.get("position_name") or "")
        if not company_name or not position_name:
            return error_response(400, "company_name and position_name are required")

        parsed_status = _parse_application_status(str(payload.get("status") or "applied"))
        if isinstance(parsed_status, JSONResponse):
            return parsed_status

        try:
            app_model = applications.create(
                ApplicationCreate(
                    company_name=company_name,
                    position_name=position_name,
                    job_url=str(payload.get("job_url") or ""),
                    status=parsed_status,
                    source="web",
                    notes=str(payload.get("notes") or ""),
                    closed_reason=str(payload.get("closed_reason") or ""),
                )
            )
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(ApplicationOut.model_validate(app_model).model_dump(mode="json"), status_code=201)

    @app.get("/api/applications/{app_id}")
    def get_application(app_id: int) -> JSONResponse:
        app_model = applications.get(app_id)
        if app_model is None:
            return error_response(404, "Application not found")
        return JSONResponse(ApplicationOut.model_validate(app_model).model_dump(mode="json"))

    @app.put("/api/applications/{app_id}")
    def update_application(app_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        existing = applications.get(app_id)
        if existing is None:
            return error_response(404, "Application not found")
        parsed_status = _parse_application_status(str(payload.get("status") or existing.status))
        if isinstance(parsed_status, JSONResponse):
            return parsed_status

        try:
            app_model = applications.update_full(
                app_id,
                ApplicationCreate(
                    company_name=_payload_text(payload, "company_name", existing.company_name),
                    position_name=_payload_text(payload, "position_name", existing.position_name),
                    job_url=_payload_text(payload, "job_url", existing.job_url),
                    status=parsed_status,
                    source=existing.source,
                    notes=_payload_text(payload, "notes", existing.notes),
                    applied_at=existing.applied_at,
                    closed_reason=str(payload.get("closed_reason") or ""),
                ),
            )
        except ValueError as exc:
            return error_response(400, str(exc))
        if app_model is None:
            return error_response(404, "Application not found")
        return JSONResponse(ApplicationOut.model_validate(app_model).model_dump(mode="json"))

    @app.delete("/api/applications/{app_id}")
    def delete_application(app_id: int) -> dict[str, str]:
        applications.delete(app_id)
        return {"message": "Deleted"}

    @app.get("/api/dashboard")
    def get_dashboard() -> dict[str, Any]:
        dashboard = applications.dashboard()
        return {
            "total": dashboard["total"],
            "board": {
                status: [ApplicationOut.model_validate(item).model_dump(mode="json") for item in items]
                for status, items in dashboard["board"].items()
            },
        }

    @app.get("/api/applications/{app_id}/material-kit")
    def get_application_material_kit(app_id: int) -> JSONResponse:
        kit = material_kits.get_by_application(app_id)
        if kit is None:
            return error_response(404, "Material kit not found")
        return JSONResponse(_material_kit_json(kit))

    @app.post("/api/applications/{app_id}/material-kit/generate", status_code=201)
    def generate_application_material_kit(app_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        resume_id = int(payload.get("resume_id") or 0)
        if resume_id <= 0:
            return error_response(400, "resume_id is required")
        jd_text = str(payload.get("jd_text") or "")
        if not jd_text.strip():
            return error_response(400, "jd_text is required")

        existing = material_kits.get_by_application(app_id)
        if existing is not None and not bool(payload.get("overwrite")):
            return error_response(409, "Material kit already exists")
        app_model = applications.get(app_id)
        if app_model is None:
            return error_response(404, "Application not found")
        resume = resumes.get(resume_id)
        if resume is None:
            return error_response(404, "Resume not found")
        if not resume.parsed_data.strip():
            return error_response(400, "Resume has no text content")
        jd_analysis_id = int(payload["jd_analysis_id"]) if payload.get("jd_analysis_id") is not None else None
        if jd_analysis_id is not None and jd_analyses.get(jd_analysis_id) is None:
            return error_response(404, "JD analysis not found")

        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        try:
            result = _complete_json(
                model,
                system=_structured_ai_system(),
                user=_material_kit_prompt(
                    app_model.company_name,
                    app_model.position_name,
                    resume.parsed_data,
                    jd_text,
                ),
            )
        except RuntimeError as exc:
            return error_response(502, str(exc))
        data = MaterialKitCreate(
            application_id=app_id,
            resume_id=resume_id,
            jd_analysis_id=jd_analysis_id,
            jd_snapshot=jd_text,
            status="draft",
            content_json=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        )
        if existing is None:
            kit = material_kits.create(data)
            return JSONResponse(_material_kit_json(kit), status_code=201)
        updated_kit = material_kits.update(existing.id, data)
        if updated_kit is None:
            return error_response(404, "Material kit not found")
        return JSONResponse(_material_kit_json(updated_kit), status_code=200)

    @app.put("/api/material-kits/{kit_id}")
    def update_material_kit(kit_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        existing = material_kits.get(kit_id)
        if existing is None:
            return error_response(404, "Material kit not found")
        try:
            content_json = (
                _compact_json_value(payload["content_json"])
                if "content_json" in payload
                else existing.content_json
            )
        except ValueError:
            return error_response(400, "content_json must be valid JSON")
        data = MaterialKitCreate(
            application_id=existing.application_id,
            resume_id=int(payload["resume_id"]) if payload.get("resume_id") is not None else existing.resume_id,
            jd_analysis_id=int(payload["jd_analysis_id"])
            if payload.get("jd_analysis_id") is not None
            else existing.jd_analysis_id,
            jd_snapshot=str(payload["jd_snapshot"]) if payload.get("jd_snapshot") is not None else existing.jd_snapshot,
            status=str(payload.get("status") or existing.status),
            content_json=content_json,
        )
        kit = material_kits.update(kit_id, data)
        if kit is None:
            return error_response(404, "Material kit not found")
        return JSONResponse(_material_kit_json(kit))

    @app.get("/api/application-events")
    def list_application_events(
        month: str = "",
        application_id: int = 0,
        event_type: str = "",
    ) -> JSONResponse:
        if month and not _valid_month(month):
            return error_response(400, "Invalid month")
        if event_type and not _valid_event_type(event_type):
            return error_response(400, "Invalid event type")
        if application_id < 0:
            return error_response(400, "Invalid application_id")
        if application_id > 0 and applications.get(application_id) is None:
            return error_response(404, "Application not found")
        rows = events.list(month=month, application_id=application_id, event_type=event_type)
        return JSONResponse([_event_with_application_json(item) for item in rows])

    @app.post("/api/application-events", status_code=201)
    def create_application_event(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _event_create_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        if applications.get(parsed.application_id) is None:
            return error_response(404, "Application not found")
        event = events.create(parsed)
        return JSONResponse(_event_json(event), status_code=201)

    @app.get("/api/application-events/{event_id}")
    def get_application_event(event_id: int) -> JSONResponse:
        event = events.get(event_id)
        if event is None:
            return error_response(404, "Application event not found")
        return JSONResponse(_event_json(event))

    @app.put("/api/application-events/{event_id}")
    def update_application_event(event_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        if events.get(event_id) is None:
            return error_response(404, "Application event not found")
        parsed = _event_create_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        if applications.get(parsed.application_id) is None:
            return error_response(404, "Application not found")
        event = events.update(event_id, parsed)
        if event is None:
            return error_response(404, "Application event not found")
        return JSONResponse(_event_json(event))

    @app.delete("/api/application-events/{event_id}")
    def delete_application_event(event_id: int) -> JSONResponse:
        if not events.delete(event_id):
            return error_response(404, "Application event not found")
        return JSONResponse({"message": "Deleted"})

    @app.get("/api/wakeups")
    def list_wakeups(status: str = "") -> list[dict[str, Any]]:
        return [wakeup_payload(wakeup) for wakeup in wakeups.list_wakeups(status=status)]

    @app.post("/api/wakeups", status_code=201)
    def create_wakeup(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _wakeup_create_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        wakeup = wakeups.create(parsed)
        return JSONResponse(wakeup_payload(wakeup), status_code=201)

    @app.post("/api/wakeups/dispatch-due")
    def dispatch_due_wakeups(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        now = _parse_rfc3339(str(payload.get("now") or datetime.now(timezone.utc).isoformat()))
        if isinstance(now, JSONResponse):
            return now
        limit = int(payload.get("limit") or 25)
        dispatched = wakeups.dispatch_due(now, limit=limit)
        return JSONResponse({"dispatched": [wakeup_payload(wakeup) for wakeup in dispatched]})

    @app.get("/api/applications/{app_id}/notes")
    def list_notes_by_app(app_id: int) -> list[dict[str, Any]]:
        return [_note_json(note) for note in notes.list(application_id=app_id)]

    @app.post("/api/applications/{app_id}/notes", status_code=201)
    def create_note_for_app(app_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _note_create_from_payload(payload, fallback_app_id=app_id, applications=applications)
        if isinstance(parsed, JSONResponse):
            return parsed
        note = notes.create(parsed)
        return JSONResponse(_note_json(note), status_code=201)

    @app.get("/api/notes")
    def list_notes() -> list[dict[str, Any]]:
        return [_note_json(note) for note in notes.list()]

    @app.post("/api/notes", status_code=201)
    def create_standalone_note(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _note_create_from_payload(payload, fallback_app_id=None, applications=applications)
        if isinstance(parsed, JSONResponse):
            return parsed
        note = notes.create(parsed)
        return JSONResponse(_note_json(note), status_code=201)

    @app.put("/api/notes/{note_id}")
    def update_note(note_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        note = notes.update(
            note_id,
            NoteCreate(
                company=str(payload.get("company") or ""),
                position=str(payload.get("position") or ""),
                round=str(payload.get("round") or ""),
                date=str(payload.get("date") or ""),
                questions=str(payload.get("questions") or ""),
                self_reflection=str(payload.get("self_reflection") or ""),
                difficulty_points=str(payload.get("difficulty_points") or ""),
                mood=str(payload.get("mood") or ""),
            ),
        )
        if note is None:
            return error_response(500, "Failed to update note")
        payload = _note_json(note)
        payload.pop("application_id", None)
        return JSONResponse(payload)

    @app.delete("/api/notes/{note_id}")
    def delete_note(note_id: int) -> dict[str, str]:
        notes.delete(note_id)
        return {"message": "Deleted"}

    @app.get("/api/offers")
    def list_offers(status: str = "") -> list[dict[str, Any]]:
        return [_offer_json(offer) for offer in offers.list(status=status)]

    @app.post("/api/offers", status_code=201)
    def create_offer(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _offer_create_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        application_id = parsed.application_id
        if application_id is not None:
            if application_id <= 0:
                return error_response(422, "invalid application_id")
            if applications.get(application_id) is None:
                return error_response(422, "application not found")
        offer = offers.create(parsed)
        return JSONResponse(_offer_json(offer), status_code=201)

    @app.get("/api/offers/compare")
    def compare_offers(ids: str = "") -> JSONResponse:
        if not ids:
            return error_response(400, "ids query param is required")
        compared: list[dict[str, Any]] = []
        for part in ids.split(","):
            raw_id = part.strip()
            if not raw_id:
                continue
            try:
                offer_id = int(raw_id)
            except ValueError:
                return error_response(400, f"invalid id in ids: {raw_id}")
            offer = offers.get(offer_id)
            if offer is not None:
                compared.append(_offer_json(offer))
        return JSONResponse(compared)

    @app.get("/api/offers/{offer_id}")
    def get_offer(offer_id: int) -> JSONResponse:
        offer = offers.get(offer_id)
        if offer is None:
            return error_response(404, "offer not found")
        return JSONResponse(_offer_json(offer))

    @app.put("/api/offers/{offer_id}")
    def update_offer(offer_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        existing = offers.get(offer_id)
        if existing is None:
            return error_response(404, "offer not found")
        parsed = _offer_create_from_payload(payload, fallback_months=existing.months_per_year)
        if isinstance(parsed, JSONResponse):
            return parsed
        parsed.application_id = existing.application_id
        offer = offers.update(offer_id, parsed)
        if offer is None:
            return error_response(404, "offer not found")
        return JSONResponse(_offer_json(offer))

    @app.delete("/api/offers/{offer_id}")
    def delete_offer(offer_id: int) -> dict[str, str]:
        offers.delete(offer_id)
        return {"status": "deleted"}

    @app.post("/api/jd/analyze", status_code=201)
    def analyze_jd(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        jd_text = str(payload.get("jd_text") or "")
        jd_source = "text"
        if not jd_text and payload.get("jd_url"):
            try:
                jd_text = _fetch_text_from_url(str(payload["jd_url"]))
            except RuntimeError as exc:
                return error_response(400, str(exc))
            jd_source = "url"
        if not jd_text:
            return error_response(400, "jd_text or jd_url is required")
        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        try:
            result = _complete_json(
                model,
                system=_structured_ai_system(),
                user=_jd_analysis_prompt(jd_text),
            )
        except RuntimeError as exc:
            return error_response(502, str(exc))
        result_json = json.dumps(result, ensure_ascii=False)
        application_id = (
            int(payload["application_id"]) if payload.get("application_id") is not None else None
        )
        analysis = jd_analyses.create(
            JDAnalysisCreate(
                application_id=application_id,
                jd_source=jd_source,
                jd_text=jd_text,
                result=result_json,
            )
        )
        return JSONResponse(
            {
                "id": analysis.id,
                "application_id": application_id,
                "jd_source": jd_source,
                "result": result,
            },
            status_code=201,
        )

    @app.get("/api/jd/analyses")
    def list_jd_analyses(application_id: int = 0) -> list[dict[str, Any]]:
        return [_jd_analysis_json(analysis) for analysis in jd_analyses.list(application_id)]

    @app.get("/api/jd/analyses/{analysis_id}")
    def get_jd_analysis(analysis_id: int) -> JSONResponse:
        analysis = jd_analyses.get(analysis_id)
        if analysis is None:
            return error_response(404, "JD analysis not found")
        return JSONResponse(_jd_analysis_json(analysis))

    @app.get("/api/knowledge-documents")
    def list_knowledge_documents(
        q: str = "",
    ) -> list[dict[str, Any]]:
        return [
            _knowledge_document_json(doc)
            for doc in knowledge.list_documents(query=q)
        ]

    @app.post("/api/knowledge-documents", status_code=201)
    def create_knowledge_document(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _knowledge_document_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        doc = knowledge.create_document(parsed)
        return JSONResponse(_knowledge_document_json(doc), status_code=201)

    @app.post("/api/knowledge-documents/import", status_code=201)
    async def import_knowledge_document(
        file: UploadFile | None = File(default=None),
    ) -> JSONResponse:
        if file is None or not file.filename:
            return error_response(400, "file is required")
        filename = Path(file.filename).name
        if Path(filename).suffix.lower() not in {".md", ".txt"}:
            return error_response(400, "only .md and .txt files are supported")
        data = await file.read()
        if len(data) > 1024 * 1024:
            return error_response(400, "file is too large")
        doc = knowledge.create_document(
            KnowledgeDocumentCreate(
                title=Path(filename).stem,
                content=data.decode("utf-8", errors="replace"),
                tags=[],
                source_type="markdown" if Path(filename).suffix.lower() == ".md" else "paste",
                source_name=filename,
            )
        )
        return JSONResponse(_knowledge_document_json(doc), status_code=201)

    @app.get("/api/knowledge-documents/{document_id}")
    def get_knowledge_document(document_id: int) -> JSONResponse:
        doc = knowledge.get_document(document_id)
        if doc is None:
            return error_response(404, "Knowledge document not found")
        return JSONResponse(_knowledge_document_json(doc))

    @app.put("/api/knowledge-documents/{document_id}")
    def update_knowledge_document(document_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        existing = knowledge.get_document(document_id)
        if existing is None:
            return error_response(404, "Knowledge document not found")
        parsed = _knowledge_document_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        parsed.source_type = existing.source_type
        parsed.source_name = existing.source_name
        doc = knowledge.update_document(document_id, parsed)
        if doc is None:
            return error_response(404, "Knowledge document not found")
        return JSONResponse(_knowledge_document_json(doc))

    @app.delete("/api/knowledge-documents/{document_id}")
    def delete_knowledge_document(document_id: int) -> JSONResponse:
        if not knowledge.delete_document(document_id):
            return error_response(404, "Knowledge document not found")
        return JSONResponse({"message": "Deleted"})

    @app.get("/api/knowledge/search")
    def search_knowledge(q: str = "", limit: int = 5) -> JSONResponse:
        query = q.strip()
        if not query:
            return error_response(400, "query is required")
        if limit <= 0:
            return error_response(400, "Invalid limit")
        return JSONResponse(knowledge.search(query, limit=limit))

    @app.get("/api/questions")
    def list_questions(
        topic: str = "",
        category: str = "",
        difficulty: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]:
        return [
            _question_json(question)
            for question in questions.list(
                topic=topic,
                category=category,
                difficulty=difficulty,
                status=status,
            )
        ]

    @app.post("/api/questions", status_code=201)
    def create_question(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _question_from_payload(payload, source_type="manual")
        if isinstance(parsed, JSONResponse):
            return parsed
        question = questions.create(parsed)
        return JSONResponse(_question_json(question), status_code=201)

    @app.post("/api/questions/generate", status_code=201)
    def generate_questions(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        source = str(payload.get("source") or "knowledge").strip() or "knowledge"
        application_id: int | None = None
        if source == "knowledge":
            documents = knowledge.list_documents()
            label = "知识库资料"
            context_text = "\n\n".join(
                f"## {doc.title}\n{doc.content.strip()}"
                for doc in documents
                if doc.content.strip()
            )
            source_type = "ai_knowledge"
        elif source == "notes":
            raw_app = int(payload.get("application_id") or 0)
            note_rows = notes.list(application_id=raw_app) if raw_app > 0 else notes.list()
            label = "面试复盘真题"
            context_text = "\n\n".join(note.questions.strip() for note in note_rows if note.questions.strip())
            source_type = "ai_notes"
            application_id = raw_app if raw_app > 0 else None
        else:
            return error_response(400, "不支持的来源类型")
        if not context_text.strip():
            return error_response(400, "所选来源没有可用于生成题目的内容")
        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        count = _clamp_question_count(int(payload.get("count") or 8))
        try:
            result = _complete_json(
                model,
                system=_structured_ai_system(),
                user=_questions_prompt(label, context_text, count),
            )
        except RuntimeError as exc:
            return error_response(502, str(exc))
        saved, skipped = _persist_generated_questions(
            questions,
            result.get("questions", []),
            source_type=source_type,
            application_id=application_id,
            topic=str(payload.get("topic") or ""),
        )
        return JSONResponse(
            {"count": len(saved), "skipped": skipped, "questions": [_question_json(q) for q in saved]},
            status_code=201,
        )

    @app.get("/api/questions/due")
    def list_due_questions(limit: int = 0) -> list[dict[str, Any]]:
        return [_question_json(question) for question in questions.list_due(limit=limit)]

    @app.get("/api/questions/stats")
    def question_stats() -> dict[str, Any]:
        return questions.stats()

    @app.get("/api/questions/{question_id}")
    def get_question(question_id: int) -> JSONResponse:
        question = questions.get(question_id)
        if question is None:
            return error_response(404, "题目不存在")
        return JSONResponse(_question_json(question))

    @app.put("/api/questions/{question_id}")
    def update_question(question_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _question_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        question = questions.update(question_id, parsed)
        if question is None:
            return error_response(404, "题目不存在")
        return JSONResponse(_question_json(question))

    @app.delete("/api/questions/{question_id}", status_code=204)
    def delete_question(question_id: int) -> Response:
        if not questions.delete(question_id):
            return error_response(404, "题目不存在")
        return Response(status_code=204)

    @app.post("/api/questions/{question_id}/reviews", status_code=201)
    def create_question_review(question_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        rating = int(payload.get("rating") or 0)
        if rating < 1 or rating > 3:
            return error_response(400, "rating 需为 1(不会)、2(模糊) 或 3(掌握)")
        result = questions.add_review(question_id, rating, note=str(payload.get("note") or ""))
        if result is None:
            return error_response(404, "题目不存在")
        review, question = result
        return JSONResponse(
            {
                "review": QuestionReviewOut.model_validate(review).model_dump(mode="json"),
                "question": _question_json(question),
            },
            status_code=201,
        )

    @app.post("/api/resumes", status_code=201)
    def create_resume(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        parsed = _resume_create_from_payload(payload)
        if isinstance(parsed, JSONResponse):
            return parsed
        resume = resumes.create(
            ResumeCreate(
                title=parsed["title"],
                name=parsed["title"],
                parsed_data=parsed["parsed_data"],
                parse_status=parsed["parse_status"],
                source=parsed["source"],
                content_json=parsed["content_json"],
            )
        )
        return JSONResponse(_resume_json(resume), status_code=201)

    @app.get("/api/resumes")
    def list_resumes() -> list[dict[str, Any]]:
        return [_resume_json(resume) for resume in resumes.list()]

    @app.post("/api/resumes/upload", status_code=201)
    async def upload_resume(file: UploadFile | None = File(default=None)) -> JSONResponse:
        if file is None or not file.filename:
            return error_response(400, "file is required")
        filename = Path(file.filename).name
        if Path(filename).suffix.lower() != ".pdf":
            return error_response(400, "only .pdf files are supported")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            return error_response(400, "file is too large")

        try:
            parsed = _extract_pdf_text(data)
        except ValueError:
            return error_response(400, "invalid PDF file")
        parse_status = "text-ready" if parsed.strip() else "parse-failed"
        resume = resumes.create(
            ResumeCreate(
                title=Path(filename).stem,
                name=Path(filename).stem,
                parsed_data=parsed,
                parse_status=parse_status,
                source="upload",
                content_json={"raw_text": parsed},
            )
        )
        relative_path = f"resumes/{resume.id}_{filename}"
        absolute_path = resolved_data_dir / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(data)
        updated = resumes.update_file(resume.id, relative_path) or resume
        return JSONResponse(_resume_json(updated), status_code=201)

    @app.post("/api/resumes/from-sample", status_code=201)
    def create_resume_from_sample(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        sample_id = str(payload.get("sample_id") or "backend")
        sample = _resume_sample(sample_id)
        if sample is None:
            return error_response(404, "sample resume not found")
        title = str(payload.get("title") or sample["title"])
        resume = resumes.create(
            ResumeCreate(
                title=title,
                name=title,
                source="sample",
                parse_status="text-ready",
                parsed_data=str(sample.get("raw_text") or ""),
                content_json=sample["content_json"],
            )
        )
        return JSONResponse(_resume_json(resume), status_code=201)

    @app.get("/api/resumes/{resume_id}")
    def get_resume(resume_id: int) -> JSONResponse:
        resume = resumes.get(resume_id)
        if resume is None:
            return error_response(404, "Resume not found")
        return JSONResponse(_resume_json(resume))

    @app.patch("/api/resumes/{resume_id}")
    def patch_resume(resume_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        resume = resumes.get(resume_id)
        if resume is None or resume.deleted_at is not None:
            return error_response(404, "Resume not found")
        changes: dict[str, Any] = {}
        if "title" in payload:
            changes["title"] = str(payload.get("title") or "")
        if "content_json" in payload:
            content = _content_json_from_payload(payload["content_json"])
            if isinstance(content, JSONResponse):
                return content
            changes["content_json"] = content
            if isinstance(content.get("raw_text"), str):
                raw_text = str(content["raw_text"])
                changes["parsed_data"] = raw_text
                changes["parse_status"] = "text-ready" if raw_text.strip() else "structured-ready"
        else:
            content = normalize_resume_content(resume.content_json)
        if "career_intent" in payload:
            career_intent = payload["career_intent"]
            if not isinstance(career_intent, dict):
                return error_response(400, "career_intent must be an object")
            content = {**content, "career_intent": career_intent}
            changes["content_json"] = content
        if "is_master" in payload:
            is_master = bool(payload["is_master"])
            if not is_master and resume.is_master and resumes.count_active_masters() <= 1:
                return error_response(400, "at least one master resume is required")
            changes["is_master"] = is_master
        if "source" in payload:
            changes["source"] = str(payload.get("source") or "manual")
        updated = resumes.update(resume_id, changes)
        if updated is None:
            return error_response(404, "Resume not found")
        return JSONResponse(_resume_json(updated))

    @app.post("/api/resumes/{resume_id}/copy", status_code=201)
    def copy_resume(resume_id: int, payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        copied = resumes.copy(resume_id, title=str(payload.get("title") or ""))
        if copied is None:
            return error_response(404, "Resume not found")
        return JSONResponse(_resume_json(copied), status_code=201)

    @app.delete("/api/resumes/{resume_id}")
    def delete_resume(resume_id: int) -> JSONResponse:
        resume = resumes.get(resume_id)
        if resume is None or resume.deleted_at is not None:
            return error_response(404, "Resume not found")
        if resume.is_master and not _resume_is_empty_draft(resume):
            return error_response(400, "master resume cannot be deleted")
        resumes.delete(resume_id)
        return JSONResponse({"message": "Deleted"})

    @app.post("/api/resumes/{resume_id}/match", status_code=201)
    def match_resume(resume_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        resume = resumes.get(resume_id)
        if resume is None:
            return error_response(404, "Resume not found")
        if not resume.parsed_data:
            return error_response(400, "Resume has no text content")

        jd_text = str(payload.get("jd_text") or "")
        if not jd_text and payload.get("jd_url"):
            try:
                jd_text = _fetch_text_from_url(str(payload["jd_url"]))
            except RuntimeError as exc:
                return error_response(400, str(exc))
        if not jd_text:
            return error_response(400, "jd_text or jd_url is required")

        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        try:
            result = _complete_json(
                model,
                system=_structured_ai_system(),
                user=_resume_match_prompt(resume.parsed_data, jd_text),
            )
        except RuntimeError as exc:
            return error_response(502, str(exc))
        application_id = (
            int(payload["application_id"]) if payload.get("application_id") is not None else None
        )
        result_json = json.dumps(result, ensure_ascii=False)
        match = resumes.create_match(
            ResumeMatchCreate(
                resume_id=resume_id,
                application_id=application_id,
                jd_text=jd_text,
                result=result_json,
            )
        )
        return JSONResponse(
            {
                "id": match.id,
                "resume_id": resume_id,
                "application_id": application_id,
                "result": result,
            },
            status_code=201,
        )

    @app.get("/api/resumes/{resume_id}/matches")
    def list_resume_matches(resume_id: int) -> JSONResponse:
        if resumes.get(resume_id) is None:
            return error_response(404, "Resume not found")
        return JSONResponse(
            [
                ResumeMatchOut.model_validate(match).model_dump(mode="json", exclude_none=True)
                for match in resumes.list_matches(resume_id)
            ]
        )

    @app.put("/api/resumes/{resume_id}/text")
    def update_resume_text(resume_id: int, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        text = str(payload.get("text") or "")
        status = "text-ready" if text.strip() else "parse-failed"
        if not resumes.update_text(resume_id, text, status):
            return error_response(404, "Resume not found")
        return JSONResponse({"message": "Updated"})

    @app.get("/api/resumes/{resume_id}/file")
    def download_resume_file(resume_id: int) -> Response:
        resume = resumes.get(resume_id)
        if resume is None:
            return error_response(404, "Resume not found")
        if not resume.file_path:
            return error_response(404, "resume has no original file")
        absolute_path = resolved_data_dir / resume.file_path
        if not absolute_path.exists():
            return error_response(404, "file not found on disk")
        return FileResponse(
            absolute_path,
            media_type="application/pdf",
            filename=Path(resume.file_path).name,
        )

    @app.get("/api/calendar")
    def get_calendar(month: str = "") -> list[dict[str, Any]]:
        start = _month_start_or_current(month)
        end = _add_month(start)
        entries: list[dict[str, Any]] = []

        for note in notes.list():
            try:
                note_date = datetime.strptime(note.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if start <= note_date < end:
                entries.append(
                    {
                        "date": note_date.date().isoformat(),
                        "type": "interview",
                        "title": f"{note.company} · {note.round}" if note.round else note.company,
                        "subtitle": note.position,
                        "app_id": note.application_id or 0,
                        "note_id": note.id,
                    }
                )

        for item in events.list(month=start.strftime("%Y-%m")):
            scheduled_at = item.event.scheduled_at
            if scheduled_at is None:
                continue
            event_id = item.event.id
            entries.append(
                {
                    "date": scheduled_at.date().isoformat(),
                    "type": item.event.event_type,
                    "title": f"{item.company_name} · {_event_type_label(item.event.event_type)}",
                    "subtitle": item.position_name,
                    "app_id": item.event.application_id,
                    "event_id": event_id,
                    "event_type": item.event.event_type,
                    "scheduled_at": scheduled_at.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "duration_minutes": duration_minutes(item.event.duration_minutes),
                    "location": item.event.location,
                    "editable": True,
                }
            )

        for app_model in applications.list():
            applied_at = app_model.applied_at
            if applied_at.tzinfo is None:
                applied_at = applied_at.replace(tzinfo=timezone.utc)
            applied_at = applied_at.astimezone(timezone.utc)
            if start <= applied_at < end:
                entries.append(
                    {
                        "date": applied_at.date().isoformat(),
                        "type": "applied",
                        "title": f"{app_model.company_name} · {app_model.position_name}",
                        "app_id": app_model.id,
                    }
                )
        return entries

    @app.post("/api/chat")
    def send_chat(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        message = str(payload.get("message") or "")
        if not message:
            return error_response(400, "message is required")

        conversation_id = int(payload.get("conversation_id") or 0)
        if conversation_id == 0:
            context_type = str(payload.get("context_type") or "workspace").strip() or "workspace"
            context_ref = str(payload.get("context_ref") or "").strip()
            mode = str(payload.get("mode") or "general").strip() or "general"
            title = _title_from_message(message)
            conversation = chat.create_conversation(
                title,
                mode=mode,
                context_type=context_type,
                context_ref=context_ref,
            )
            conversation_id = conversation.id
        elif chat.get_conversation(conversation_id) is None:
            return error_response(404, "conversation not found")

        chat.append_message(conversation_id, "user", content=message)
        history = [_chat_response_system_message(), *_stored_messages_to_ai(chat.list_messages(conversation_id))]
        try:
            added, reply, pending = run_turn(
                model,
                offerpilot_tool_registry(
                    applications,
                    events,
                    notes,
                    offers,
                    resumes=resumes,
                    jd_analyses=jd_analyses,
                    knowledge=knowledge,
                ),
                history,
                auto_approve=load_config(resolved_data_dir).chat_auto_approve_writes,
                max_iter=DEFAULT_MAX_ITERATIONS,
                checkpoint_path=_agent_checkpoint_path(resolved_data_dir),
                thread_id=_agent_thread_id(conversation_id),
            )
        except Exception as exc:
            return _ai_provider_error(exc)
        _persist_ai_messages(chat, conversation_id, added)
        if pending is not None:
            chat.set_pending_action(conversation_id, pending)
            return JSONResponse(
                {
                    "type": "confirmation_required",
                    "conversation_id": conversation_id,
                    "pending_action": _pending_action_json(pending),
                }
            )
        chat.clear_pending_action(conversation_id)
        return JSONResponse({"type": "message", "conversation_id": conversation_id, "message": reply})

    @app.post("/api/chat/confirm")
    def confirm_chat(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        conversation_id = int(payload.get("conversation_id") or 0)
        if conversation_id == 0:
            return error_response(400, "conversation_id is required")
        stored = chat.list_messages(conversation_id)
        if not stored:
            return error_response(404, "conversation not found")
        pending = chat.get_pending_action(conversation_id) or _pending_action_from_stored_messages(stored)
        if pending is None:
            return error_response(400, "no pending action to confirm")
        try:
            added, reply, new_pending = resume_after_confirm(
                model,
                offerpilot_tool_registry(
                    applications,
                    events,
                    notes,
                    offers,
                    resumes=resumes,
                    jd_analyses=jd_analyses,
                    knowledge=knowledge,
                ),
                [_chat_response_system_message(), *_stored_messages_to_ai(stored)],
                pending,
                approved=bool(payload.get("approved")),
                auto_approve=load_config(resolved_data_dir).chat_auto_approve_writes,
                max_iter=DEFAULT_MAX_ITERATIONS,
                checkpoint_path=_agent_checkpoint_path(resolved_data_dir),
                thread_id=_agent_thread_id(conversation_id),
            )
        except Exception as exc:
            return _ai_provider_error(exc)
        _persist_ai_messages(chat, conversation_id, added)
        if new_pending is not None:
            chat.set_pending_action(conversation_id, new_pending)
            return JSONResponse(
                {
                    "type": "confirmation_required",
                    "conversation_id": conversation_id,
                    "pending_action": _pending_action_json(new_pending),
                }
            )
        chat.clear_pending_action(conversation_id)
        return JSONResponse({"type": "message", "conversation_id": conversation_id, "message": reply})

    @app.get("/api/chat/conversations")
    def list_conversations() -> list[dict[str, Any]]:
        return [
            ConversationOut.model_validate(item).model_dump(mode="json")
            for item in chat.list_conversations()
        ]

    @app.get("/api/chat/conversations/{conversation_id}")
    def get_conversation(conversation_id: int) -> list[dict[str, Any]]:
        return [
            ChatMessageOut.model_validate(item).model_dump(mode="json")
            for item in chat.list_messages(conversation_id)
        ]

    @app.delete("/api/chat/conversations/{conversation_id}")
    def delete_conversation(conversation_id: int) -> dict[str, str]:
        chat.delete_conversation(conversation_id)
        return {"status": "deleted"}

    @app.get("/api/mock/sessions")
    def list_mock_sessions(status: str = "") -> list[dict[str, Any]]:
        return [_mock_session_json(session) for session in mock_sessions.list(status=status)]

    @app.post("/api/mock/sessions", status_code=201)
    def create_mock_session(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        role = str(payload.get("role") or "").strip()
        if not role:
            return error_response(400, "role is required")
        company = str(payload.get("company") or "")
        title = str(payload.get("title") or "").strip() or (
            f"{company} · {role}" if company else role or "模拟面试"
        )
        conversation = chat.create_conversation(title, mode="mock_interview")
        session_model = mock_sessions.create(
            MockSessionCreate(
                conversation_id=conversation.id,
                application_id=int(payload["application_id"]) if payload.get("application_id") is not None else None,
                title=conversation.title,
                role=role,
                company=company,
                round_type=str(payload.get("round_type") or "technical"),
                difficulty=str(payload.get("difficulty") or "medium"),
                question_count=int(payload.get("question_count") or 5),
                duration_min=int(payload.get("duration_min") or 0),
                question_source=str(payload.get("question_source") or "mixed"),
            )
        )
        return JSONResponse(
            {
                "session": _mock_session_json(session_model),
                "conversation_id": conversation.id,
                "conversation": ConversationOut.model_validate(conversation).model_dump(mode="json"),
            },
            status_code=201,
        )

    @app.get("/api/mock/sessions/{session_id}")
    def get_mock_session(session_id: int) -> JSONResponse:
        session_model = mock_sessions.get(session_id)
        if session_model is None:
            return error_response(404, "session not found")
        return JSONResponse(
            {
                "session": _mock_session_json(session_model),
                "messages": [
                    ChatMessageOut.model_validate(item).model_dump(mode="json")
                    for item in chat.list_messages(session_model.conversation_id)
                ],
            }
        )

    @app.post("/api/mock/sessions/{session_id}/end")
    def end_mock_session(session_id: int, payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        session_model = mock_sessions.get(session_id)
        if session_model is None:
            return error_response(404, "session not found")
        auto_save_note = bool(payload.get("auto_save_note"))
        if session_model.status == "completed" and auto_save_note:
            feedback = _stored_feedback(session_model.feedback)
            note_id = _save_mock_feedback_note(applications, notes, session_model, feedback)
            return JSONResponse(
                {
                    "session": _mock_session_json(session_model),
                    "feedback": feedback,
                    "saved_note_id": note_id,
                }
            )
        if session_model.status != "in_progress":
            return error_response(409, "session already ended")

        model = _chat_model(chat_model, resolved_data_dir)
        if isinstance(model, JSONResponse):
            return model
        transcript = _mock_transcript(chat.list_messages(session_model.conversation_id))
        try:
            feedback = _complete_json(
                model,
                system="你是一位面试评估专家，严格按JSON输出。",
                user=_mock_scoring_prompt(session_model, transcript),
            )
        except RuntimeError as exc:
            mock_sessions.abort(session_id)
            return error_response(502, "评分失败：" + str(exc))
        feedback_json = json.dumps(feedback, ensure_ascii=False)
        done = mock_sessions.finish(session_id, feedback, feedback_json)
        if done is None:
            return error_response(404, "session not found")
        response_payload: dict[str, Any] = {
            "session": _mock_session_json(done),
            "feedback": feedback,
            "parse_error": False,
        }
        if auto_save_note:
            response_payload["saved_note_id"] = _save_mock_feedback_note(
                applications,
                notes,
                done,
                feedback,
            )
        return JSONResponse(response_payload)

    @app.delete("/api/mock/sessions/{session_id}")
    def delete_mock_session(session_id: int) -> JSONResponse:
        session_model = mock_sessions.get(session_id)
        if session_model is None:
            return error_response(404, "session not found")
        chat.delete_conversation(session_model.conversation_id)
        return JSONResponse({"status": "deleted"})

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        cfg = load_config(resolved_data_dir)
        return _settings_payload(cfg)

    @app.get("/api/logs")
    def get_logs(limit: int = 100) -> dict[str, Any]:
        return {"entries": read_recent_log_entries(resolved_data_dir, limit=limit)}

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        return skills_payload(load_config(resolved_data_dir))

    @app.post("/api/skills", status_code=201)
    def register_skill_package(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        current = load_config(resolved_data_dir)
        try:
            next_config = register_skill(current, payload)
        except SkillRegistryError as exc:
            return error_response(400, str(exc))
        save_config(resolved_data_dir, next_config)
        return JSONResponse(skills_payload(next_config), status_code=201)

    @app.put("/api/skills/{skill_id}")
    def update_skill_package(skill_id: str, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        current = load_config(resolved_data_dir)
        try:
            next_config = update_skill(current, skill_id, payload)
        except KeyError:
            return error_response(404, "skill not found")
        except SkillRegistryError as exc:
            return error_response(400, str(exc))
        save_config(resolved_data_dir, next_config)
        return JSONResponse(skills_payload(next_config))

    @app.put("/api/settings")
    def update_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        current = load_config(resolved_data_dir)
        providers = _settings_providers_from_payload(payload, current)
        active_provider_id = str(payload.get("active_provider_id") or current.active_provider_id)
        active = _active_provider_from(providers, active_provider_id)
        next_config = Config(
            api_key=active.api_key,
            base_url=active.base_url,
            model=active.model,
            local_port=current.local_port,
            chat_auto_approve_writes=bool(payload.get("chat_auto_approve_writes")),
            active_provider_id=active.id,
            providers=providers,
            runtime_mode=normalize_runtime_mode(
                str(payload.get("runtime_mode") or current.runtime_mode),
                current.runtime_mode,
            ),
            auth_enabled=bool(payload.get("auth_enabled", current.auth_enabled)),
            auth_token=current.auth_token,
            log_level=str(payload.get("log_level") or current.log_level).upper(),
        )
        api_key = payload.get("api_key")
        if api_key:
            next_config.api_key = str(api_key)
            next_config.providers = [
                profile.model_copy(update={"api_key": str(api_key)})
                if profile.id == next_config.active_provider_id
                else profile
                for profile in next_config.providers
            ]
        auth_token = payload.get("auth_token")
        if auth_token:
            next_config.auth_token = str(auth_token)
        save_config(resolved_data_dir, next_config)
        return _settings_payload(next_config)

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> Response:
        if full_path == "favicon.ico":
            return Response(status_code=204)
        if full_path == "api" or full_path.startswith("api/"):
            return error_response(404, "not found")
        if resolved_static_dir is not None:
            root = resolved_static_dir.resolve()
            requested = (root / full_path).resolve()
            if _is_relative_to(requested, root) and requested.is_file():
                return FileResponse(requested)
            index = root / "index.html"
            if index.is_file():
                return FileResponse(index)
        return HTMLResponse(_dev_placeholder_html(), status_code=200)

    return app


def error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _ai_provider_error(exc: Exception) -> JSONResponse:
    detail = str(exc).strip()
    message = "AI provider request failed"
    if detail:
        message = f"{message}: {detail}"
    return error_response(502, message)


def _auth_guard_response(request: Request, data_dir: Path) -> JSONResponse | None:
    path = request.url.path
    if not path.startswith("/api/") or path in {"/api/health", "/api/auth/status"}:
        return None
    cfg = load_config(data_dir)
    if not cfg.auth_enabled:
        return None
    if not cfg.auth_token:
        return error_response(503, "auth token is not configured")
    if _request_has_valid_auth_token(request, cfg.auth_token):
        return None
    return error_response(401, "unauthorized")


def _request_has_valid_auth_token(request: Request, expected_token: str) -> bool:
    authorization = request.headers.get("authorization", "")
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or request.headers.get("x-offerpilot-token", "")
    return bool(token) and compare_digest(token, expected_token)


def _parse_application_status(raw: str) -> str | JSONResponse:
    if not raw:
        return ""
    try:
        return normalize_application_status(raw)
    except ValueError as exc:
        return error_response(422, str(exc))


def _payload_text(payload: dict[str, Any], key: str, fallback: str) -> str:
    if key not in payload:
        return fallback
    return str(payload.get(key) or "")


def _title_from_message(message: str) -> str:
    trimmed = message.strip()
    return trimmed[:30] or "新对话"


def _agent_checkpoint_path(data_dir: Path) -> Path:
    return data_dir / "agent_checkpoints.sqlite"


def _agent_thread_id(conversation_id: int) -> str:
    return f"conversation:{conversation_id}"


def _persist_ai_messages(repo: ChatRepository, conversation_id: int, messages: list[Message]) -> None:
    for message in messages:
        repo.append_message(
            conversation_id,
            message.role,
            content=message.content,
            tool_calls=_dump_tool_calls(message.tool_calls),
            tool_call_id=message.tool_call_id,
            provider_blocks=_dump_provider_blocks(message.provider_blocks),
        )


def _chat_response_system_message() -> Message:
    return Message(
        role="system",
        content=(
            "You are OfferPilot, a job-search copilot. Use the user's language. "
            "For substantive answers, keep the reply concise and structure it as: "
            "Conclusion, Evidence, Next steps. When local tool evidence is thin, say so clearly. "
            "Do not expose hidden reasoning."
        ),
    )


def _stored_messages_to_ai(messages: list[Any]) -> list[Message]:
    return [
        Message(
            role=message.role,
            content=message.content,
            tool_calls=_load_tool_calls(message.tool_calls),
            tool_call_id=message.tool_call_id,
            provider_blocks=_load_provider_blocks(message.provider_blocks),
        )
        for message in messages
    ]


def _dump_tool_calls(tool_calls: list[ToolCall]) -> str:
    if not tool_calls:
        return ""
    return json.dumps(
        [
            {
                "id": tool_call.id,
                "name": tool_call.name,
                "args": _safe_tool_args(tool_call.args),
            }
            for tool_call in tool_calls
        ],
        ensure_ascii=False,
    )


def _dump_provider_blocks(provider_blocks: dict[str, Any]) -> str:
    if not provider_blocks:
        return ""
    allowed = {
        key: value
        for key, value in provider_blocks.items()
        if key == "reasoning_content" and value is not None
    }
    if not allowed:
        return ""
    return json.dumps(allowed, ensure_ascii=False)


def _pending_action_json(pending: PendingAction) -> dict[str, Any]:
    return {
        "tool_name": pending.tool_name,
        "human": pending.human,
        "args": _safe_tool_args(pending.args),
    }


def _pending_action_from_stored_messages(messages: list[Any]) -> PendingAction | None:
    if not messages:
        return None
    last = messages[-1]
    if last.role != "assistant" or not last.tool_calls:
        return None
    tool_calls = _load_tool_calls(last.tool_calls)
    if not tool_calls:
        return None
    tool_call = tool_calls[0]
    return PendingAction(
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        args=tool_call.args,
        human=tool_call.name,
    )


def _safe_tool_args(raw: str) -> dict[str, Any]:
    try:
        args = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(args, dict):
        return {}
    return args


def _load_tool_calls(raw: str) -> list[ToolCall]:
    if not raw:
        return []
    values = json.loads(raw)
    calls: list[ToolCall] = []
    for value in values:
        args = value.get("args", {})
        calls.append(
            ToolCall(
                id=str(value.get("id", "")),
                name=str(value.get("name", "")),
                args=args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
            )
        )
    return calls


def _load_provider_blocks(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    reasoning_content = value.get("reasoning_content")
    if reasoning_content is None:
        return {}
    return {"reasoning_content": reasoning_content}


def _chat_model(injected: Optional[ChatModel], data_dir: Path) -> ChatModel | JSONResponse:
    if injected is not None:
        return injected
    try:
        return ConfiguredAIClient(load_config(data_dir))
    except ValueError as exc:
        return error_response(503, str(exc))


def _find_static_dir() -> Path | None:
    candidates = [
        Path.cwd() / "web" / "dist",
        Path(__file__).resolve().parents[2] / "web" / "dist",
        Path(__file__).resolve().parents[3] / "web" / "dist",
        Path("/app/web/dist"),
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _dev_placeholder_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
  <head><meta charset="utf-8"><title>OfferPilot</title></head>
  <body>
    <h1>OfferPilot API is running</h1>
    <p>Build the frontend with <code>cd web && npm run build</code>, or run Vite dev server with API proxy.</p>
  </body>
</html>"""


def _settings_payload(cfg: Config) -> dict[str, Any]:
    active = cfg.active_provider()
    return {
        "chat_auto_approve_writes": cfg.chat_auto_approve_writes,
        "active_provider_id": active.id,
        "providers": [_provider_payload(profile) for profile in cfg.provider_profiles()],
        "base_url": active.base_url,
        "model": active.model,
        "has_api_key": bool(active.api_key),
        "runtime_mode": cfg.runtime_mode,
        "auth_enabled": cfg.auth_enabled,
        "has_auth_token": bool(cfg.auth_token),
        "log_level": cfg.log_level,
    }


def _settings_providers_from_payload(payload: dict[str, Any], current: Config) -> list[AIProviderProfile]:
    raw_providers = payload.get("providers")
    if isinstance(raw_providers, list) and raw_providers:
        current_by_id = {profile.id: profile for profile in current.provider_profiles()}
        providers = [
            _provider_from_payload(item, current_by_id.get(str(item.get("id", ""))))
            for item in raw_providers
            if isinstance(item, dict)
        ]
        if providers:
            return providers

    active = current.active_provider()
    api_key = str(payload.get("api_key") or active.api_key)
    return [
        AIProviderProfile(
            id=active.id,
            label=active.label,
            provider=active.provider,
            api_key=api_key,
            base_url=str(payload.get("base_url") or active.base_url),
            model=str(payload.get("model") or active.model),
            enabled=active.enabled,
        )
    ]


def _provider_from_payload(
    payload: dict[str, Any], current: AIProviderProfile | None
) -> AIProviderProfile:
    api_key = payload.get("api_key")
    preserved_key = current.api_key if current is not None else ""
    return AIProviderProfile(
        id=str(payload.get("id") or (current.id if current is not None else "default")),
        label=str(payload.get("label") or (current.label if current is not None else "Default")),
        provider=str(payload.get("provider") or (current.provider if current is not None else "openai")),
        api_key=str(api_key or preserved_key),
        base_url=str(payload.get("base_url") or (current.base_url if current is not None else "")),
        model=str(payload.get("model") or (current.model if current is not None else "")),
        enabled=bool(payload.get("enabled", current.enabled if current is not None else True)),
    )


def _active_provider_from(
    providers: list[AIProviderProfile], active_provider_id: str
) -> AIProviderProfile:
    for profile in providers:
        if profile.id == active_provider_id:
            return profile
    return providers[0]


def _provider_payload(profile: AIProviderProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "label": profile.label,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "model": profile.model,
        "enabled": profile.enabled,
        "has_api_key": bool(profile.api_key),
    }


def _valid_event_type(event_type: str) -> bool:
    return event_type in {"written_test", "interview", "offer_step", "deadline", "custom"}


def _valid_month(month: str) -> bool:
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return False
    return True


def _month_start_or_current(month: str) -> datetime:
    try:
        parsed = datetime.strptime(month, "%Y-%m")
        return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _add_month(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=value.tzinfo)
    return datetime(value.year, value.month + 1, 1, tzinfo=value.tzinfo)


def _event_type_label(event_type: str) -> str:
    return {
        "written_test": "笔试",
        "interview": "面试",
        "offer_step": "Offer",
        "deadline": "截止",
        "custom": "自定义",
    }.get(event_type, event_type)


def _event_create_from_payload(payload: dict[str, Any]) -> ApplicationEventCreate | JSONResponse:
    event_type = str(payload.get("event_type") or "")
    if not _valid_event_type(event_type):
        return error_response(400, "Invalid event type")
    duration = int(payload.get("duration_minutes") or 0)
    if duration <= 0:
        return error_response(400, "duration_minutes must be greater than 0")
    scheduled_at_raw = str(payload.get("scheduled_at") or "")
    if not scheduled_at_raw:
        return error_response(400, "scheduled_at is required")
    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_raw.replace("Z", "+00:00"))
    except ValueError:
        return error_response(400, "scheduled_at must be RFC3339")
    remind_at_raw = str(payload.get("remind_at") or "")
    remind_at: datetime | None = None
    if remind_at_raw:
        try:
            remind_at = datetime.fromisoformat(remind_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return error_response(400, "remind_at must be RFC3339")
    tags_value = payload.get("tags") or []
    if not isinstance(tags_value, list):
        return error_response(400, "tags must be an array")
    return ApplicationEventCreate(
        application_id=int(payload.get("application_id") or 0),
        event_type=event_type,
        subtype=str(payload.get("subtype") or ""),
        tags=[str(item) for item in tags_value],
        round=int(payload.get("round") or 0),
        scheduled_at=scheduled_at,
        duration_minutes=duration,
        location=str(payload.get("location") or ""),
        notes=str(payload.get("notes") or ""),
        remind_at=remind_at,
        status=str(payload.get("status") or "todo"),
    )


def _wakeup_create_from_payload(payload: dict[str, Any]) -> WakeupCreate | JSONResponse:
    kind = str(payload.get("kind") or "").strip()
    if not kind:
        return error_response(400, "kind is required")
    due_at = _parse_rfc3339(str(payload.get("due_at") or ""))
    if isinstance(due_at, JSONResponse):
        return due_at
    payload_value = payload.get("payload") or {}
    if not isinstance(payload_value, dict):
        return error_response(400, "payload must be an object")
    return WakeupCreate(kind=kind, due_at=due_at, payload=payload_value)


def _parse_rfc3339(value: str) -> datetime | JSONResponse:
    if not value:
        return error_response(400, "due_at must be RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return error_response(400, "due_at must be RFC3339")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_json(event: Any) -> dict[str, Any]:
    return ApplicationEventOut(
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


def _note_create_from_payload(
    payload: dict[str, Any],
    fallback_app_id: int | None,
    applications: ApplicationsRepository,
) -> NoteCreate | JSONResponse:
    app_id = fallback_app_id
    if app_id is None and payload.get("application_id") is not None:
        app_id = int(payload["application_id"])
    company = str(payload.get("company") or "")
    position = str(payload.get("position") or "")
    if app_id is not None:
        if app_id <= 0:
            return error_response(400, "Invalid application_id")
        app = applications.get(app_id)
        if app is None:
            return error_response(404, "Application not found")
        if not company:
            company = app.company_name
        if not position:
            position = app.position_name
    if not company:
        return error_response(400, "company is required")
    return NoteCreate(
        application_id=app_id,
        company=company,
        position=position,
        round=str(payload.get("round") or ""),
        date=str(payload.get("date") or ""),
        questions=str(payload.get("questions") or ""),
        self_reflection=str(payload.get("self_reflection") or ""),
        difficulty_points=str(payload.get("difficulty_points") or ""),
        mood=str(payload.get("mood") or ""),
    )


def _note_json(note: Any) -> dict[str, Any]:
    return InterviewNoteOut.model_validate(note).model_dump(mode="json", exclude_none=True)


def _offer_create_from_payload(
    payload: dict[str, Any],
    fallback_months: int = 12,
) -> OfferCreate | JSONResponse:
    company_name = str(payload.get("company_name") or "")
    position_name = str(payload.get("position_name") or "")
    status = str(payload.get("status") or "")
    base_monthly = int(payload.get("base_monthly") or 0)
    months_per_year = int(payload.get("months_per_year") or 0)
    signing_bonus = int(payload.get("signing_bonus") or 0)

    if months_per_year == 0:
        months_per_year = fallback_months
    if not company_name.strip():
        return error_response(422, "company_name is required")
    if not position_name.strip():
        return error_response(422, "position_name is required")
    if base_monthly < 0 or signing_bonus < 0:
        return error_response(422, "base_monthly and signing_bonus must be non-negative")
    if months_per_year < 1:
        return error_response(422, "months_per_year must be at least 1")
    if status and status not in {"pending", "negotiating", "accepted", "declined", "expired"}:
        return error_response(422, "invalid status")

    raw_application_id = payload.get("application_id")
    application_id = int(raw_application_id) if raw_application_id is not None else None
    return OfferCreate(
        application_id=application_id,
        company_name=company_name,
        position_name=position_name,
        status=status or "pending",
        base_monthly=base_monthly,
        months_per_year=months_per_year,
        signing_bonus=signing_bonus,
        equity=str(payload.get("equity") or ""),
        perks=str(payload.get("perks") or ""),
        deadline=str(payload.get("deadline") or ""),
        notes=str(payload.get("notes") or ""),
        assessment=str(payload.get("assessment") or ""),
    )


def _offer_json(offer: Any) -> dict[str, Any]:
    return OfferOut.model_validate(offer).model_dump(mode="json", exclude_none=True)


def _jd_analysis_json(analysis: Any) -> dict[str, Any]:
    return JDAnalysisOut.model_validate(analysis).model_dump(mode="json", exclude_none=True)


def _knowledge_document_from_payload(
    payload: dict[str, Any],
) -> KnowledgeDocumentCreate | JSONResponse:
    title = str(payload.get("title") or "").strip()
    if not title:
        return error_response(400, "title is required")
    tags_value = payload.get("tags") or []
    tags = [str(item) for item in tags_value] if isinstance(tags_value, list) else []
    return KnowledgeDocumentCreate(
        title=title,
        content=str(payload.get("content") or ""),
        tags=tags,
        source_type=str(payload.get("source_type") or "manual"),
        source_name=str(payload.get("source_name") or ""),
    )


def _knowledge_document_json(document: Any) -> dict[str, Any]:
    return KnowledgeDocumentOut.model_validate(document).model_dump(mode="json")


def _material_kit_json(kit: Any) -> dict[str, Any]:
    return MaterialKitOut.model_validate(kit).model_dump(mode="json", exclude_none=True)


def _mock_session_json(session_model: Any) -> dict[str, Any]:
    return MockSessionOut.model_validate(session_model).model_dump(mode="json", exclude_none=True)


def _question_from_payload(
    payload: dict[str, Any],
    source_type: str | None = None,
) -> QuestionCreate | JSONResponse:
    text = str(payload.get("question") or "").strip()
    if not text:
        return error_response(400, "题目内容不能为空")
    tags_value = payload.get("tags") or []
    tags = [str(item) for item in tags_value] if isinstance(tags_value, list) else []
    return QuestionCreate(
        category=str(payload.get("category") or "").strip(),
        difficulty=_normalize_difficulty(str(payload.get("difficulty") or "medium")),
        question=text,
        reference_answer=str(payload.get("reference_answer") or "").strip(),
        tags=tags,
        source_type=source_type or str(payload.get("source_type") or "manual"),
        status=str(payload.get("status") or "new"),
    )


def _question_json(question: Any) -> dict[str, Any]:
    return QuestionOut.model_validate(question).model_dump(mode="json", exclude_none=True)


def _resume_json(resume: Any) -> dict[str, Any]:
    return resume_payload(resume)


def _resume_create_from_payload(payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    source = str(payload.get("source") or "manual").strip() or "manual"
    if source not in {"manual", "dialog"}:
        return error_response(400, "source must be manual or dialog")
    content = _content_json_from_payload(payload.get("content_json") or {})
    if isinstance(content, JSONResponse):
        return content
    if "career_intent" in payload:
        career_intent = payload["career_intent"]
        if not isinstance(career_intent, dict):
            return error_response(400, "career_intent must be an object")
        content["career_intent"] = career_intent
    text = str(payload.get("text") or payload.get("parsed_data") or "")
    if text:
        content["raw_text"] = text
    elif isinstance(content.get("raw_text"), str):
        text = str(content["raw_text"])
    title = str(payload.get("title") or payload.get("name") or "").strip()
    if not title:
        title = "未命名简历"
    parse_status = str(payload.get("parse_status") or "")
    if not parse_status:
        parse_status = "text-ready" if text.strip() else "structured-ready"
    return {
        "title": title,
        "source": source,
        "content_json": content,
        "parsed_data": text,
        "parse_status": parse_status,
    }


def _content_json_from_payload(value: Any) -> dict[str, Any] | JSONResponse:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return error_response(400, "content_json must be valid JSON")
        if isinstance(parsed, dict):
            return parsed
    return error_response(400, "content_json must be an object")


def _resume_is_empty_draft(resume: Any) -> bool:
    content = normalize_resume_content(resume.content_json)
    return not str(resume.parsed_data or "").strip() and not _resume_content_has_value(content)


def _resume_content_has_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_resume_content_has_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_resume_content_has_value(item) for item in value)
    return bool(str(value or "").strip())


def _resume_sample(sample_id: str) -> dict[str, Any] | None:
    samples: dict[str, dict[str, Any]] = {
        "backend": {
            "title": "后端工程师样例简历",
            "raw_text": "Backend Engineer sample resume with Python, FastAPI, and SQL systems.",
            "content_json": {
                "career_intent": {"target_roles": ["Backend Engineer"]},
                "contact": {"name": "OfferPilot Sample"},
                "education": [{"school": "Sample University", "degree": "B.S. Computer Science"}],
                "experience": [
                    {"company": "Sample Tech", "title": "Backend Intern", "highlights": ["Built APIs"]}
                ],
                "projects": [{"name": "Resume Builder", "highlights": ["Designed resume CRUD"]}],
                "skills": ["Python", "FastAPI", "SQLAlchemy"],
            },
        },
        "frontend": {
            "title": "前端工程师样例简历",
            "raw_text": "Frontend Engineer sample resume with React and TypeScript.",
            "content_json": {
                "career_intent": {"target_roles": ["Frontend Engineer"]},
                "contact": {"name": "OfferPilot Sample"},
                "education": [{"school": "Sample University"}],
                "experience": [{"company": "Sample Studio", "title": "Frontend Intern"}],
                "projects": [{"name": "Campus Hub"}],
                "skills": ["React", "TypeScript", "CSS"],
            },
        },
        "product": {
            "title": "产品经理样例简历",
            "raw_text": "Product Manager sample resume with user research and roadmap planning.",
            "content_json": {
                "career_intent": {"target_roles": ["Product Manager"]},
                "contact": {"name": "OfferPilot Sample"},
                "education": [{"school": "Sample University"}],
                "experience": [{"company": "Sample Lab", "title": "Product Intern"}],
                "projects": [{"name": "Job Search Workflow"}],
                "skills": ["User Research", "Roadmap", "Metrics"],
            },
        },
    }
    return samples.get(sample_id)


def _extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ValueError("invalid PDF file") from exc

    page_text: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            page_text.append(text)
    return "\n".join(page_text).strip()


def _structured_ai_system() -> str:
    return (
        "你是一名专业的招聘求职分析师。只输出 JSON，不要使用 markdown 代码块。"
        "所有文字使用简体中文，数组字段为空时返回 []。"
    )


def _jd_analysis_prompt(jd_text: str) -> str:
    return f"""请分析以下岗位描述（JD），输出如下 JSON：
{{
  "summary": "一句话总结这个岗位",
  "requirements": ["关键要求点，每条一句话"],
  "tech_stack": ["涉及的技术栈/工具"],
  "experience_years": "要求的年限，如 3-5 年，无要求填 不限",
  "education": "学历要求，如 本科及以上，无要求填 不限",
  "highlights": ["这个岗位吸引人的亮点"],
  "suggestions": ["针对求职者的准备建议，每条一句话"]
}}

JD 内容：
{_truncate_for_prompt(jd_text)}"""


def _resume_match_prompt(resume_text: str, jd_text: str) -> str:
    return f"""请对比以下简历和岗位 JD，评估匹配度，输出如下 JSON：
{{
  "match_score": 0到100的整数匹配度,
  "matched": ["简历中与 JD 匹配的点"],
  "gaps": ["简历中相对 JD 缺失或薄弱的点"],
  "suggestions": ["针对这份 JD 该如何优化简历/补足能力的建议"],
  "summary": "一句话总评"
}}

简历内容：
{_truncate_for_prompt(resume_text)}

JD 内容：
{_truncate_for_prompt(jd_text)}"""


def _material_kit_prompt(company: str, position: str, resume_text: str, jd_text: str) -> str:
    return f"""Create an application material kit for this role. Return only JSON with:
{{
  "resume_advice": {{
    "summary": "one sentence fit summary",
    "highlights": ["resume strengths to emphasize"],
    "rewrite_bullets": ["tailored resume bullets"],
    "gaps": ["missing or weak areas"],
    "notes": "optional notes"
  }},
  "messages": [
    {{"type": "recruiter_email", "title": "Intro", "body": "message body", "notes": "optional notes"}}
  ],
  "checklist": [
    {{"id": "select_resume", "label": "Select resume", "done": false}}
  ]
}}

Company: {company}
Position: {position}

Resume:
{_truncate_for_prompt(resume_text)}

JD:
{_truncate_for_prompt(jd_text)}"""


def _mock_scoring_prompt(session_model: Any, transcript: str) -> str:
    return f"""请根据以下模拟面试转写进行评分，只返回 JSON：
{{
  "score_overall": 0,
  "score_communication": 0,
  "score_depth": 0,
  "score_structure": 0,
  "score_confidence": 0,
  "summary": "总结",
  "strengths": [],
  "weaknesses": [],
  "drills": []
}}

目标岗位：{session_model.role}
面试轮次：{session_model.round_type}
难度：{session_model.difficulty}

转写：
{transcript}"""


def _mock_transcript(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        if not message.content or message.role == "tool":
            continue
        who = "面试官" if message.role == "assistant" else "候选人"
        lines.append(f"{who}：{message.content}")
    return "\n".join(lines)


def _stored_feedback(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"raw": value}


def _save_mock_feedback_note(
    applications: ApplicationsRepository,
    notes: NotesRepository,
    session_model: Any,
    feedback: dict[str, Any],
) -> int:
    company = session_model.company
    position = session_model.role or "模拟面试"
    application_id = session_model.application_id
    if application_id is not None:
        app_model = applications.get(application_id)
        if app_model is not None:
            company = company or app_model.company_name
            position = position or app_model.position_name
    weaknesses = feedback.get("weaknesses") or []
    if not isinstance(weaknesses, list):
        weaknesses = []
    note = notes.create(
        NoteCreate(
            application_id=application_id,
            company=str(company or ""),
            position=str(position or "模拟面试"),
            round=f"模拟面试·{session_model.round_type}",
            date=datetime.now(timezone.utc).date().isoformat(),
            self_reflection=str(feedback.get("summary") or ""),
            difficulty_points="待加强：" + "；".join(str(item) for item in weaknesses)
            if weaknesses
            else "",
        )
    )
    return note.id


def _questions_prompt(source_label: str, context_text: str, count: int) -> str:
    return f"""你是一名资深技术面试官。请基于以下【{source_label}】设计 {count} 道面试题。
严格输出如下 JSON，不要输出多余文字：
{{
  "questions": [
    {{
      "category": "分类",
      "difficulty": "easy|medium|hard",
      "question": "题目",
      "reference_answer": "参考答案要点",
      "tags": ["关键词"]
    }}
  ]
}}

材料内容：
{_truncate_for_prompt(context_text)}"""


def _persist_generated_questions(
    repo: QuestionsRepository,
    generated: Any,
    source_type: str,
    application_id: int | None,
    topic: str = "",
) -> tuple[list[Any], int]:
    if not isinstance(generated, list):
        return [], 0
    existing = repo.hashes()
    seen = set(existing)
    to_create: list[QuestionCreate] = []
    skipped = 0
    for item in generated:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        digest = question_hash(text)
        if digest in seen:
            skipped += 1
            continue
        seen.add(digest)
        tags_value = item.get("tags") or []
        tags = [str(tag) for tag in tags_value] if isinstance(tags_value, list) else []
        to_create.append(
            QuestionCreate(
                application_id=application_id,
                topic=topic,
                category=str(item.get("category") or "").strip(),
                difficulty=_normalize_difficulty(str(item.get("difficulty") or "medium")),
                question=text,
                reference_answer=str(item.get("reference_answer") or "").strip(),
                tags=tags,
                source_type=source_type,
                status="new",
            )
        )
    return repo.bulk_create(to_create), skipped


def _normalize_difficulty(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"easy", "简单"}:
        return "easy"
    if normalized in {"hard", "困难", "难"}:
        return "hard"
    return "medium"


def _clamp_question_count(count: int) -> int:
    if count <= 0:
        return 8
    return min(count, 20)


def _complete_json(model: ChatModel, system: str, user: str) -> dict[str, Any]:
    try:
        assistant = model.complete(
            [Message(role="system", content=system), Message(role="user", content=user)],
            [],
        )
        return _parse_json_reply(assistant.content)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _parse_json_reply(reply: str) -> dict[str, Any]:
    text = reply.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :].strip()
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise RuntimeError("AI response must be a JSON object")
    return value


def _compact_json_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError("invalid json") from exc


def _fetch_text_from_url(url: str) -> str:
    if not url:
        raise RuntimeError("empty JD URL")
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "OfferPilot/0.1 (local job-search workbench)"},
            timeout=20,
        )
    except Exception as exc:
        raise RuntimeError(f"fetch JD URL failed (you can paste the JD text instead): {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(
            f"JD URL returned HTTP {response.status_code} - please paste the JD text instead"
        )
    return _clean_html_to_text(response.text)


def _clean_html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text.replace("&nbsp;", " "))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _truncate_for_prompt(text.strip())


def _truncate_for_prompt(value: str, max_chars: int = 12000) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n...(已截断)"
