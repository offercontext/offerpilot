from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (Index("idx_applications_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    position_name: Mapped[str] = mapped_column(String, nullable=False)
    job_url: Mapped[str] = mapped_column(String, default="", server_default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="applied", server_default="applied")
    source: Mapped[str] = mapped_column(String, nullable=False, default="cli", server_default="cli")
    notes: Mapped[str] = mapped_column(String, default="", server_default="")
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    first_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_written_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_offer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_reason: Mapped[str] = mapped_column(String, default="", server_default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        Index("idx_application_events_app", "application_id"),
        Index("idx_application_events_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    subtype: Mapped[str] = mapped_column(String, default="", server_default="")
    _tags: Mapped[str] = mapped_column("tags", String, default="[]", server_default="[]")
    round: Mapped[int] = mapped_column(default=0, server_default="0")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(default=0, server_default="0")
    location: Mapped[str] = mapped_column(String, default="", server_default="")
    notes: Mapped[str] = mapped_column(String, default="", server_default="")
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="todo", server_default="todo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    @property
    def tags(self) -> list[str]:
        if not self._tags:
            return []
        value = json.loads(self._tags)
        return value if isinstance(value, list) else []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self._tags = json.dumps(value or [], ensure_ascii=False)


class InterviewNote(Base):
    __tablename__ = "interview_notes"
    __table_args__ = (Index("idx_notes_app", "application_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    company: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)
    round: Mapped[str] = mapped_column(String, default="", server_default="")
    date: Mapped[str] = mapped_column(String, default="", server_default="")
    questions: Mapped[str] = mapped_column(String, default="", server_default="")
    self_reflection: Mapped[str] = mapped_column(String, default="", server_default="")
    difficulty_points: Mapped[str] = mapped_column(String, default="", server_default="")
    mood: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        Index("idx_offers_app", "application_id"),
        Index("idx_offers_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    position_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", server_default="pending")
    base_monthly: Mapped[int] = mapped_column(default=0, server_default="0")
    months_per_year: Mapped[int] = mapped_column(default=12, server_default="12")
    signing_bonus: Mapped[int] = mapped_column(default=0, server_default="0")
    equity: Mapped[str] = mapped_column(String, default="", server_default="")
    perks: Mapped[str] = mapped_column(String, default="", server_default="")
    deadline: Mapped[str] = mapped_column(String, default="", server_default="")
    notes: Mapped[str] = mapped_column(String, default="", server_default="")
    assessment: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    @property
    def total_cash(self) -> int:
        return self.base_monthly * self.months_per_year + self.signing_bonus


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, default="", server_default="")
    file_path: Mapped[str] = mapped_column(String, default="", server_default="")
    parsed_data: Mapped[str] = mapped_column(String, default="", server_default="")
    parse_status: Mapped[str] = mapped_column(String, default="pending", server_default="pending")
    title: Mapped[str] = mapped_column(String, default="", server_default="")
    is_master: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    parent_resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String, default="manual", server_default="manual")
    source_file_path: Mapped[str] = mapped_column(String, default="", server_default="")
    content_json: Mapped[str] = mapped_column(String, default="{}", server_default="{}")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class ResumeMatch(Base):
    __tablename__ = "resume_matches"
    __table_args__ = (Index("idx_matches_resume", "resume_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_text: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class JDAnalysis(Base):
    __tablename__ = "jd_analyses"
    __table_args__ = (Index("idx_jd_app", "application_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_source: Mapped[str] = mapped_column(String, default="text", server_default="text")
    jd_text: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class ApplicationMaterialKit(Base):
    __tablename__ = "application_material_kits"
    __table_args__ = (
        Index("idx_material_kits_app", "application_id"),
        Index("idx_material_kits_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("jd_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_snapshot: Mapped[str] = mapped_column(String, default="", server_default="")
    status: Mapped[str] = mapped_column(String, default="draft", server_default="draft")
    content_json: Mapped[str] = mapped_column(String, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("idx_knowledge_documents_kind", "doc_kind"),
        Index("idx_knowledge_documents_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, default="", server_default="")
    _tags: Mapped[str] = mapped_column("tags", String, default="[]", server_default="[]")
    doc_kind: Mapped[str] = mapped_column(String, default="wiki", server_default="wiki")
    status: Mapped[str] = mapped_column(String, default="confirmed", server_default="confirmed")
    source_type: Mapped[str] = mapped_column(String, default="manual", server_default="manual")
    source_name: Mapped[str] = mapped_column(String, default="", server_default="")
    source_refs: Mapped[str] = mapped_column(String, default="[]", server_default="[]")
    summary_type: Mapped[str] = mapped_column(String, default="", server_default="")
    generation_meta: Mapped[str] = mapped_column(String, default="{}", server_default="{}")
    superseded_by: Mapped[int | None] = mapped_column(nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    @property
    def tags(self) -> list[str]:
        if not self._tags:
            return []
        value = json.loads(self._tags)
        return value if isinstance(value, list) else []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self._tags = json.dumps(value or [], ensure_ascii=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("idx_knowledge_chunks_document", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(default=0, server_default="0")
    content: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[str] = mapped_column(String, default="", server_default="")
    embedding_model: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index("idx_questions_topic", "topic"),
        Index("idx_questions_status", "status"),
        Index("idx_questions_next_review", "next_review_at"),
        Index("idx_questions_hash", "question_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    topic: Mapped[str] = mapped_column(String, default="", server_default="")
    category: Mapped[str] = mapped_column(String, default="", server_default="")
    difficulty: Mapped[str] = mapped_column(String, default="medium", server_default="medium")
    question: Mapped[str] = mapped_column(String, nullable=False)
    reference_answer: Mapped[str] = mapped_column(String, default="", server_default="")
    _tags: Mapped[str] = mapped_column("tags", String, default="[]", server_default="[]")
    source_type: Mapped[str] = mapped_column(String, default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String, default="new", server_default="new")
    practice_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    question_hash: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    @property
    def tags(self) -> list[str]:
        if not self._tags:
            return []
        value = json.loads(self._tags)
        return value if isinstance(value, list) else []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self._tags = json.dumps(value or [], ensure_ascii=False)


class QuestionReview(Base):
    __tablename__ = "question_reviews"
    __table_args__ = (Index("idx_question_reviews_question", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(nullable=False)
    note: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class MockSession(Base):
    __tablename__ = "mock_sessions"
    __table_args__ = (
        Index("idx_mock_sessions_conv", "conversation_id"),
        Index("idx_mock_sessions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, default="", server_default="")
    round_type: Mapped[str] = mapped_column(String, default="technical", server_default="technical")
    difficulty: Mapped[str] = mapped_column(String, default="medium", server_default="medium")
    question_count: Mapped[int] = mapped_column(default=5, server_default="5")
    duration_min: Mapped[int] = mapped_column(default=0, server_default="0")
    question_source: Mapped[str] = mapped_column(String, default="mixed", server_default="mixed")
    status: Mapped[str] = mapped_column(String, default="in_progress", server_default="in_progress")
    question_index: Mapped[int] = mapped_column(default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_overall: Mapped[int | None] = mapped_column(nullable=True)
    score_communication: Mapped[int | None] = mapped_column(nullable=True)
    score_depth: Mapped[int | None] = mapped_column(nullable=True)
    score_structure: Mapped[int | None] = mapped_column(nullable=True)
    score_confidence: Mapped[int | None] = mapped_column(nullable=True)
    feedback: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


# Every model with a direct foreign key to applications.id. Conditional application
# deletion iterates this explicit inventory; a metadata-backed test keeps it exhaustive.
APPLICATION_FOREIGN_KEY_MODELS = (
    ApplicationEvent,
    InterviewNote,
    Offer,
    ResumeMatch,
    JDAnalysis,
    ApplicationMaterialKit,
    Question,
    MockSession,
)


class Wakeup(Base):
    __tablename__ = "wakeups"
    __table_args__ = (
        Index("idx_wakeups_status_due", "status", "due_at"),
        Index("idx_wakeups_kind", "kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(String, default="{}", server_default="{}")
    status: Mapped[str] = mapped_column(String, default="pending", server_default="pending")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="新对话", server_default="新对话")
    title_source: Mapped[str] = mapped_column(String, nullable=False, default="fallback", server_default="fallback")
    mode: Mapped[str] = mapped_column(String, default="general", server_default="general")
    context_type: Mapped[str] = mapped_column(String, default="workspace", server_default="workspace")
    context_ref: Mapped[str] = mapped_column(String, default="", server_default="")
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_tool_call_id: Mapped[str] = mapped_column(String, default="", server_default="")
    pending_tool_name: Mapped[str] = mapped_column(String, default="", server_default="")
    pending_args: Mapped[str] = mapped_column(String, default="", server_default="")
    pending_human: Mapped[str] = mapped_column(String, default="", server_default="")
    clarification_tool_call_id: Mapped[str] = mapped_column(String, default="", server_default="")
    clarification_tool_name: Mapped[str] = mapped_column(String, default="", server_default="")
    clarification_args: Mapped[str] = mapped_column(String, default="", server_default="")
    clarification_human: Mapped[str] = mapped_column(String, default="", server_default="")
    clarification_question: Mapped[str] = mapped_column(String, default="", server_default="")
    last_write_undo_json: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    @property
    def pending_action(self) -> dict[str, object] | None:
        if not self.pending_tool_name:
            return None
        try:
            args = json.loads(self.pending_args) if self.pending_args else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return {
            "tool_name": self.pending_tool_name,
            "human": self.pending_human or self.pending_tool_name,
            "args": args,
        }

    @property
    def pending_clarification(self) -> dict[str, object] | None:
        if not self.clarification_tool_name:
            return None
        try:
            args = json.loads(self.clarification_args) if self.clarification_args else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return {
            "tool_name": self.clarification_tool_name,
            "human": self.clarification_human or self.clarification_tool_name,
            "args": args,
            "question": self.clarification_question,
        }

    @property
    def last_write_undo(self) -> dict[str, object] | None:
        if not self.last_write_undo_json:
            return None
        try:
            payload = json.loads(self.last_write_undo_json)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("idx_chat_messages_conv", "conversation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, default="", server_default="")
    tool_calls: Mapped[str] = mapped_column(String, default="", server_default="")
    tool_call_id: Mapped[str] = mapped_column(String, default="", server_default="")
    provider_blocks: Mapped[str] = mapped_column(String, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
