from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    created_at: datetime
    updated_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    offer_id: int | None = None
    mode: str = "general"
    pending_action: dict[str, object] | None = None
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


class EventOut(BaseModel):
    id: int
    application_id: int
    event_type: str
    round: int
    scheduled_at: str
    duration_minutes: int
    location: str
    notes: str
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
    name: str
    file_path: str
    parsed_data: str
    parse_status: str
    created_at: datetime


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


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    title: str
    content: str
    tags: list[str]
    source_type: str
    source_name: str
    created_at: datetime
    updated_at: datetime


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int | None = None
    application_id: int | None = None
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
    knowledge_base_id: int | None = None
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
