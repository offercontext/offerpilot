from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    position_name: str
    job_url: str
    status: str
    source: str
    notes: str
    applied_at: datetime
    first_pending_at: datetime | None = None
    first_applied_at: datetime | None = None
    first_written_test_at: datetime | None = None
    first_interview_at: datetime | None = None
    first_offer_at: datetime | None = None
    closed_reason: str = ""
    closed_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    mode: str = "general"
    context_type: str = "workspace"
    context_ref: str = ""
    pinned_at: datetime | None = None
    archived_at: datetime | None = None
    pending_action: dict[str, object] | None = None
    pending_clarification: dict[str, object] | None = None
    last_write_undo: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    tool_calls: str = ""
    tool_call_id: str = ""
    created_at: datetime


class ApplicationEventOut(BaseModel):
    id: int
    application_id: int
    event_type: str
    subtype: str = ""
    tags: list[str] = []
    round: int
    scheduled_at: str
    duration_minutes: int
    location: str
    notes: str
    remind_at: str | None = None
    status: str = "todo"
    created_at: datetime
    company_name: str | None = None
    position_name: str | None = None


class InterviewNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None = None
    company: str
    position: str
    round: str
    date: str
    questions: str
    self_reflection: str
    difficulty_points: str
    mood: str
    created_at: datetime


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None = None
    company_name: str
    position_name: str
    status: str
    base_monthly: int
    months_per_year: int
    signing_bonus: int
    equity: str
    perks: str
    deadline: str
    notes: str
    assessment: str
    total_cash: int
    created_at: datetime
    updated_at: datetime


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str = ""
    file_path: str = ""
    parsed_data: str = ""
    parse_status: str = "pending"
    title: str = ""
    is_master: bool = False
    parent_resume_id: int | None = None
    source: str = "manual"
    source_file_path: str = ""
    content_json: dict[str, Any] = Field(default_factory=dict)
    deleted_at: datetime | None = None
    created_at: datetime

    @field_validator("content_json", mode="before")
    @classmethod
    def _parse_content_json(cls, value: Any) -> dict[str, Any]:
        return normalize_resume_content(value)


class ResumeMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resume_id: int
    application_id: int | None = None
    jd_text: str
    result: str
    created_at: datetime


class JDAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None = None
    jd_source: str
    jd_text: str
    result: str
    created_at: datetime


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    tags: list[str]
    doc_kind: str = "wiki"
    status: str = "confirmed"
    source_type: str
    source_name: str
    source_refs: str = "[]"
    summary_type: str = ""
    generation_meta: str = "{}"
    superseded_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None = None
    topic: str = ""
    category: str
    difficulty: str
    question: str
    reference_answer: str
    tags: list[str]
    source_type: str
    status: str
    practice_count: int
    last_practiced_at: datetime | None = None
    next_review_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QuestionReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_id: int
    rating: int
    note: str
    created_at: datetime


class MaterialKitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    resume_id: int | None = None
    jd_analysis_id: int | None = None
    jd_snapshot: str
    status: str
    content_json: str
    created_at: datetime
    updated_at: datetime


class MockSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    application_id: int | None = None
    title: str
    role: str
    company: str
    round_type: str
    difficulty: str
    question_count: int
    duration_min: int
    question_source: str
    status: str
    question_index: int
    started_at: datetime
    ended_at: datetime | None = None
    score_overall: int | None = None
    score_communication: int | None = None
    score_depth: int | None = None
    score_structure: int | None = None
    score_confidence: int | None = None
    feedback: str
    created_at: datetime


RESUME_COMPLETION_SECTIONS = (
    "career_intent",
    "contact",
    "education",
    "experience",
    "projects",
    "skills",
)


def normalize_resume_content(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resume_completion(content: dict[str, Any]) -> tuple[int, list[str], bool]:
    missing = [
        section
        for section in RESUME_COMPLETION_SECTIONS
        if not _resume_section_present(section, content.get(section))
    ]
    present_count = len(RESUME_COMPLETION_SECTIONS) - len(missing)
    completion_percent = round(present_count / len(RESUME_COMPLETION_SECTIONS) * 100)
    return completion_percent, missing, not missing


def resume_payload(resume: Any) -> dict[str, Any]:
    payload = ResumeOut.model_validate(resume).model_dump(mode="json")
    title = payload.get("title") or payload.get("name") or ""
    source_file_path = payload.get("source_file_path") or payload.get("file_path") or ""
    payload["title"] = title
    payload["name"] = payload.get("name") or title
    payload["source_file_path"] = source_file_path
    payload["file_path"] = payload.get("file_path") or source_file_path
    content = normalize_resume_content(payload.get("content_json"))
    if not content and payload.get("parsed_data"):
        content = {"raw_text": payload["parsed_data"]}
    payload["content_json"] = content
    completion_percent, missing_sections, is_complete = resume_completion(content)
    payload["completion_percent"] = completion_percent
    payload["missing_sections"] = missing_sections
    payload["is_complete"] = is_complete
    return payload


def _resume_section_present(section: str, value: Any) -> bool:
    if section == "career_intent":
        if not isinstance(value, dict):
            return False
        roles = value.get("target_roles")
        return isinstance(roles, list) and any(str(role).strip() for role in roles)
    if isinstance(value, list):
        return any(_non_empty(item) for item in value)
    return _non_empty(value)


def _non_empty(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_non_empty(item) for item in value.values())
    if isinstance(value, list):
        return any(_non_empty(item) for item in value)
    return bool(str(value or "").strip())
