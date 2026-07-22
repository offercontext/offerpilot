from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    application_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_events.id", ondelete="SET NULL"),
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


class ApplicationEvidenceBundle(Base):
    __tablename__ = "application_evidence_bundles"
    __table_args__ = (
        UniqueConstraint("application_id", "sequence", name="uq_evidence_bundle_sequence"),
        UniqueConstraint("application_id", "idempotency_key", name="uq_evidence_bundle_idempotency"),
        Index("idx_evidence_bundles_application", "application_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_kind: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="user_asserted",
        server_default="user_asserted",
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(String, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class MaterialRevisionProposal(Base):
    __tablename__ = "material_revision_proposals"
    __table_args__ = (
        Index("idx_material_revision_proposals_application_created", "application_id", "created_at"),
        UniqueConstraint("result_resume_id", name="uq_material_revision_proposals_result_resume"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    material_kit_id: Mapped[int] = mapped_column(
        ForeignKey("application_material_kits.id", ondelete="CASCADE"), nullable=False
    )
    source_resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    source_fingerprint_sha256: Mapped[str] = mapped_column(String, nullable=False)
    source_snapshot_json: Mapped[str] = mapped_column(String, nullable=False)
    proposal_json: Mapped[str] = mapped_column(String, nullable=False)
    proposal_sha256: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", server_default="draft")
    accepted_change_ids_json: Mapped[str] = mapped_column(String, nullable=False, default="[]", server_default="[]")
    result_resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class OpportunityFitReview(Base):
    __tablename__ = "opportunity_fit_reviews"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "idempotency_key",
            name="uq_opportunity_fit_reviews_application_idempotency",
        ),
        Index("idx_opportunity_fit_reviews_application_created", "application_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    source_fingerprint_sha256: Mapped[str] = mapped_column(String, nullable=False)
    source_snapshot_json: Mapped[str] = mapped_column(String, nullable=False)
    triage_json: Mapped[str] = mapped_column(String, nullable=False)
    triage_sha256: Mapped[str] = mapped_column(String, nullable=False)
    deep_review_json: Mapped[str | None] = mapped_column(String, nullable=True)
    deep_review_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    deep_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewReviewProposal(Base):
    __tablename__ = "interview_review_proposals"
    __table_args__ = (
        UniqueConstraint(
            "note_id",
            "idempotency_key",
            name="uq_interview_review_proposals_note_key",
        ),
        Index("idx_interview_review_proposals_note", "note_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("interview_notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    application_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    input_snapshot_json: Mapped[str] = mapped_column(String, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    proposal_json: Mapped[str] = mapped_column(String, nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String, nullable=False)
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
    ApplicationEvidenceBundle,
    MaterialRevisionProposal,
    OpportunityFitReview,
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


class KnowledgeSource(Base):
    """Knowledge Source 不可变原件 + lifecycle/extraction/brief 独立状态。"""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index("idx_knowledge_sources_hash", "source_hash"),
        Index("idx_knowledge_sources_lifecycle", "lifecycle"),
        Index("idx_knowledge_sources_extraction", "extraction_status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="markdown", server_default="markdown"
    )
    display_title: Mapped[str] = mapped_column(String, default="", server_default="")
    title_hint: Mapped[str] = mapped_column(String, default="", server_default="")
    # KBR-02：frontmatter 白名单 provenance 沿 Source 所有权持久化的文档来源字段。
    # display_title 承载 frontmatter title（可被用户 PATCH 覆盖）；author/published_at
    # 是从原文确定性提取的派生 provenance，非任意 metadata。
    author: Mapped[str] = mapped_column(String, default="", server_default="")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    main_filename: Mapped[str] = mapped_column(String, nullable=False)
    main_media_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="text/markdown",
        server_default="text/markdown",
    )
    main_relative_path: Mapped[str] = mapped_column(String, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lifecycle: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    extraction_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    extraction_error_code: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    extraction_error_message: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    brief_status: Mapped[str] = mapped_column(
        String, nullable=False, default="not_started", server_default="not_started"
    )
    brief_block_reason: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    brief_error_code: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    brief_error_message: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    active_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_brief_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class KnowledgeSourceOrigin(Base):
    """每次导入追加一条 file/paste/bundle 来源记录。"""

    __tablename__ = "knowledge_source_origins"
    __table_args__ = (
        Index("idx_knowledge_source_origins_source", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_method: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    origin_url: Mapped[str] = mapped_column(String, default="", server_default="")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KnowledgeExtractionSnapshot(Base):
    """确定性 Extraction Snapshot：规范化文本 + 结构清单 + digest。"""

    __tablename__ = "knowledge_extraction_snapshots"
    __table_args__ = (
        Index("idx_knowledge_snapshots_source", "source_id"),
        UniqueConstraint(
            "source_id",
            "extractor_version",
            name="uq_knowledge_snapshots_source_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    extractor_version: Mapped[str] = mapped_column(String, nullable=False)
    parser_version: Mapped[str] = mapped_column(
        String, nullable=False, default="markdown-it-py-3", server_default="markdown-it-py-3"
    )
    normalization_version: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="nl-1",
        server_default="nl-1",
    )
    tokenizer_version: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="none-1",
        server_default="none-1",
    )
    encoding: Mapped[str] = mapped_column(
        String, nullable=False, default="utf-8", server_default="utf-8"
    )
    detection_method: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    structure_manifest: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    # KBR-02：Snapshot 记录元数据提取版本，确定性重建可复现。空串表示旧 Snapshot
    # （由 _ensure_column 加列回填）。
    metadata_extraction_version: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    digest: Mapped[str] = mapped_column(String, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KnowledgeEvidence(Base):
    """引用单位，stable ID + 结构位置 + 邻接关系。"""

    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        Index("idx_knowledge_evidence_source", "source_id"),
        Index("idx_knowledge_evidence_snapshot", "snapshot_id"),
        UniqueConstraint(
            "snapshot_id",
            "ordinal",
            name="uq_knowledge_evidence_snapshot_ordinal",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_extraction_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    block_kind: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path_json: Mapped[str] = mapped_column(
        String, default="[]", server_default="[]"
    )
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_evidence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    next_evidence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    @property
    def heading_path(self) -> list[str]:
        if not self.heading_path_json:
            return []
        value = json.loads(self.heading_path_json)
        return value if isinstance(value, list) else []


class KnowledgeSourceAsset(Base):
    """Source Bundle 中的不可变图片附件。

    Spec §14.3：保存 source_id、逻辑名、媒体类型、相对路径、字节大小、sha256、宽、高。
    ``(source_id, logical_name)`` 唯一。原始字节保存于 ``knowledge/sources/<id>/assets/`` 下，
    不写入 SQLite BLOB。
    """

    __tablename__ = "knowledge_source_assets"
    __table_args__ = (
        Index("idx_knowledge_source_assets_source", "source_id"),
        UniqueConstraint(
            "source_id",
            "logical_name",
            name="uq_knowledge_source_assets_source_logical_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    logical_name: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KnowledgeJob(Base):
    """后台 Job：extract/brief/delete。KI-02 只产生 extract。"""

    __tablename__ = "knowledge_jobs"
    __table_args__ = (
        Index("idx_knowledge_jobs_source", "source_id"),
        Index("idx_knowledge_jobs_attempt", "attempt_id"),
        Index("idx_knowledge_jobs_status", "status"),
        Index("idx_knowledge_jobs_queue", "queue"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    queue: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Brief Job 与具体 Attempt 一一关联；Extraction/Delete Job 保持 NULL。
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_brief_attempts.id", ondelete="CASCADE"),
        nullable=True,
    )
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    lease_owner: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # KI-07：每次 claim 生成新 attempt_token；complete/heartbeat 必须验证 token 匹配，
    # 防止迟到 lease 结果提交。Spec §12 "迟到的旧 lease 结果因 owner/Attempt 不匹配
    # 而拒绝提交"。
    attempt_token: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    error_code: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    error_message: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
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


class KnowledgeLog(Base):
    """Knowledge 操作日志。

    Spec §5.4 / §18：删除日志只保留 Source ID、action、result 和时间,严禁保留标题、
    正文、URL、路径或 Provider 密钥。KI-06 仅使用 ``source_deleted`` action;后续 Ticket
    可在此基础上追加 Brief、Extraction 相关 action,但不得放宽数据最小化原则。
    """

    __tablename__ = "knowledge_logs"
    __table_args__ = (
        Index("idx_knowledge_logs_source", "source_id"),
        Index("idx_knowledge_logs_action", "action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(
        String, nullable=False, default="succeeded", server_default="succeeded"
    )
    error_code: Mapped[str] = mapped_column(
        String, default="", server_default=""
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KnowledgeSourceBrief(Base):
    """Spec §10 / §14.7：每个 Source 的当前 Brief（单行）。

    一个 Source 至多一条当前 Brief 行；重建流程在新 Attempt 全部门禁通过后，
    于同一 SQLite 事务中以新 Brief 替换旧行并更新 Source.active_brief_id。
    payload_json 严格遵循 Brief Schema v1（Spec §10.1）。
    """

    __tablename__ = "knowledge_source_briefs"
    __table_args__ = (
        Index("idx_knowledge_source_briefs_source", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_extraction_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    winning_attempt_id: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    language: Mapped[str] = mapped_column(
        String, nullable=False, default="zh-CN", server_default="zh-CN"
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    outdated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
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


class KnowledgeBriefAttempt(Base):
    """Spec §10 / §14.8 / §11.1：Brief Attempt 历史与诊断数据。

    Attempt 在创建时固定 Provider/Model/参数/Prompt 版本/Schema 版本/Snapshot；
    不保存 API Key、完整 Prompt 或不可解析原始响应（Spec §18 / §11.1）。
    候选 payload 与 validation 报告可持久化，便于排查与 KI-11 评估。
    """

    __tablename__ = "knowledge_brief_attempts"
    __table_args__ = (
        Index("idx_knowledge_brief_attempts_source", "source_id"),
        Index("idx_knowledge_brief_attempts_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_extraction_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    provider_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_model: Mapped[str] = mapped_column(String, nullable=False)
    provider_base_url: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    language: Mapped[str] = mapped_column(
        String, nullable=False, default="zh-CN", server_default="zh-CN"
    )
    candidate_payload_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    validation_report_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    error_code: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    error_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    repair_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # KI-10 / Spec §11.1 / §11.4：Attempt 固定 fallback 候选；actual_* 记录实际成功
    # Provider（可能为 fallback）；provider_retry_count 与 next_retry_at 持久化 Provider
    # 层重试进度，重启后保留。repair_count 仍是程序级 repair 次数，与之区分。
    fallback_provider_id: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    fallback_provider_model: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    actual_provider_id: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    actual_provider_model: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    provider_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_input_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    token_output_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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


class KnowledgeBriefAttemptStep(Base):
    """Brief Attempt 的追加式过程记录。

    只保存结构化元数据、Evidence ID 和限长的模型响应摘要；原始响应按不可信内容
    隔离，禁止把 Evidence 正文或 Prompt 全量复制进常规日志。
    """

    __tablename__ = "knowledge_brief_attempt_steps"
    __table_args__ = (
        Index("idx_knowledge_brief_attempt_steps_attempt", "attempt_id", "sequence"),
        Index("idx_knowledge_brief_attempt_steps_phase", "phase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_brief_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    phase: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="completed", server_default="completed")
    block_path: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    provider_id: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    provider_model: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    prompt_version: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    output_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    token_input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    token_output_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KnowledgeRetrievalTrace(Base):
    """Spec §14.10 Retrieval Trace：本地评估数据，不参与召回。

    KI-08 验收点：每次搜索本地记录 query、filters、命中 ID/score、耗时和可选评估标签。
    Trace 只保存稳定标识符与元数据，禁止保留 Evidence 原文、prompt 或外部 trace。
    ``hits_json`` 结构：``[{"evidence_id": "ev_...", "source_id": int, "score": float}, ...]``。
    """

    __tablename__ = "knowledge_retrieval_traces"
    __table_args__ = (
        Index("idx_knowledge_retrieval_traces_created", "created_at"),
        Index("idx_knowledge_retrieval_traces_label", "evaluation_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    filters_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    hits_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    evaluation_label: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    error_code: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
