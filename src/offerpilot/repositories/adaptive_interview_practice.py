from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import (
    AdaptivePracticePlan,
    Application,
    ApplicationEvent,
    InterviewNote,
    InterviewReviewProposal,
)
from offerpilot.repositories.json_contract import canonical_json, sha256_text


class AdaptivePracticeNotFound(Exception):
    pass


class AdaptivePracticeConflict(ValueError):
    pass


class AdaptivePracticeValidationError(ValueError):
    pass


_PATH_TO_FIELD = {
    "/questions": "questions",
    "/self_reflection": "self_reflection",
    "/difficulty_points": "difficulty_points",
    "/mood": "mood",
}

_DRILLS = {
    "/difficulty_points": (
        "difficulty_breakdown",
        "拆解卡住的关键一步",
        "这个问题在复盘中被明确记录为卡点，先把关键一步拆开，比继续泛练更有效。",
        "写出当时卡住的具体节点，并用三步说明下一次如何推进。",
    ),
    "/self_reflection": (
        "answer_reframe",
        "重构一次更清晰的回答",
        "你的复盘已经指出表达结构问题，现在适合立刻重写一版可复用回答。",
        "重新组织一次回答：先结论，再给关键事实，最后说明影响。",
    ),
    "/questions": (
        "question_decode",
        "练习问题解码",
        "从真实被问问题出发，先识别考察意图，再组织回答。",
        "写出面试官可能在验证什么，再给出一版针对性的回答。",
    ),
    "/mood": (
        "pressure_rehearsal",
        "复盘压力情境",
        "情绪信号已经影响当时表达，先准备稳定节奏的过渡方式。",
        "写出压力出现的触发点，并准备一句稳定节奏的过渡表达。",
    ),
}

_ASSESSMENTS = {"needs_work", "clearer", "confident"}


class AdaptivePracticeRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def list_recommendations(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            used = {
                (row.interview_review_proposal_id, row.focus_id)
                for row in session.scalars(select(AdaptivePracticePlan))
            }
            proposals = list(
                session.scalars(
                    select(InterviewReviewProposal)
                    .order_by(
                        InterviewReviewProposal.created_at.desc(),
                        InterviewReviewProposal.id.desc(),
                    )
                )
            )
            result: list[dict[str, Any]] = []
            for proposal in proposals:
                context = _visible_context(session, proposal)
                if context is None:
                    continue
                note, event, application = context
                for item in _proposal_focuses(proposal):
                    focus_id = item.get("id")
                    if not isinstance(focus_id, str) or not focus_id or (proposal.id, focus_id) in used:
                        continue
                    recommendation = _recommendation(
                        proposal, item, note, event, application
                    )
                    if recommendation is not None:
                        result.append(recommendation)
            return result

    def list_plans(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            plans = list(
                session.scalars(
                    select(AdaptivePracticePlan)
                    .join(InterviewNote, InterviewNote.id == AdaptivePracticePlan.interview_note_id)
                    .join(ApplicationEvent, ApplicationEvent.id == AdaptivePracticePlan.application_event_id)
                    .join(Application, Application.id == AdaptivePracticePlan.application_id)
                    .where(
                        Application.deleted_at.is_(None),
                        InterviewNote.application_id == AdaptivePracticePlan.application_id,
                        InterviewNote.application_event_id == AdaptivePracticePlan.application_event_id,
                        ApplicationEvent.application_id == AdaptivePracticePlan.application_id,
                        ApplicationEvent.event_type == "interview",
                    )
                    .order_by(AdaptivePracticePlan.created_at.desc(), AdaptivePracticePlan.id.desc())
                )
            )
            return [_plan_json(session, plan) for plan in plans]

    def get(self, plan_id: int) -> dict[str, Any]:
        with self._session_factory() as session:
            plan = _visible_plan(session, plan_id)
            if plan is None:
                raise AdaptivePracticeNotFound()
            return _plan_json(session, plan)

    def start(
        self,
        *,
        proposal_id: int,
        focus_id: str,
        expected_source_fingerprint: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        request_fingerprint = sha256_text(
            canonical_json(
                {
                    "proposal_id": proposal_id,
                    "focus_id": focus_id,
                    "expected_source_fingerprint": expected_source_fingerprint,
                }
            )
        )
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            existing = session.scalar(
                select(AdaptivePracticePlan).where(
                    AdaptivePracticePlan.start_idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.start_input_fingerprint != request_fingerprint:
                    raise AdaptivePracticeConflict("adaptive practice idempotency input changed")
                visible = _visible_plan(session, existing.id)
                if visible is None:
                    raise AdaptivePracticeNotFound()
                return _plan_json(session, visible), False
            proposal = session.get(InterviewReviewProposal, proposal_id)
            if proposal is None:
                raise AdaptivePracticeNotFound()
            context = _visible_context(session, proposal)
            if context is None:
                raise AdaptivePracticeNotFound()
            note, event, application = context
            item = next(
                (candidate for candidate in _proposal_focuses(proposal) if candidate.get("id") == focus_id),
                None,
            )
            if item is None:
                raise AdaptivePracticeNotFound()
            recommendation = _recommendation(proposal, item, note, event, application)
            if recommendation is None:
                raise AdaptivePracticeConflict("adaptive practice source changed")
            if recommendation["source_fingerprint"] != expected_source_fingerprint:
                raise AdaptivePracticeConflict("adaptive practice source changed")
            plan = AdaptivePracticePlan(
                application_id=application.id,
                application_event_id=event.id,
                interview_note_id=note.id,
                interview_review_proposal_id=proposal.id,
                focus_id=focus_id,
                start_idempotency_key=idempotency_key,
                start_input_fingerprint=request_fingerprint,
                source_fingerprint=expected_source_fingerprint,
                source_path=recommendation["source_path"],
                source_excerpt=recommendation["source_excerpt"],
                source_hash=sha256_text(
                    str(getattr(note, _PATH_TO_FIELD[recommendation["source_path"]], ""))
                ),
                drill_kind=recommendation["drill_kind"],
                title=recommendation["title"],
                observation=recommendation["observation"],
                reason=recommendation["reason"],
                prompt=recommendation["prompt"],
            )
            session.add(plan)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                duplicate = session.scalar(
                    select(AdaptivePracticePlan).where(
                        AdaptivePracticePlan.interview_review_proposal_id == proposal_id,
                        AdaptivePracticePlan.focus_id == focus_id,
                    )
                )
                if duplicate is not None:
                    raise AdaptivePracticeConflict("adaptive practice already started") from exc
                raise AdaptivePracticeConflict("adaptive practice could not be started") from exc
            session.refresh(plan)
            return _plan_json(session, plan), True

    def complete(
        self,
        *,
        plan_id: int,
        expected_revision: int,
        response_text: str,
        reflection_text: str,
        self_assessment: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        response = response_text.strip()
        reflection = reflection_text.strip()
        if not response or len(response) > 8000 or len(reflection) > 4000:
            raise AdaptivePracticeValidationError("adaptive practice response is invalid")
        if self_assessment not in _ASSESSMENTS:
            raise AdaptivePracticeValidationError("adaptive practice assessment is invalid")
        fingerprint = sha256_text(
            canonical_json(
                {
                    "plan_id": plan_id,
                    "expected_revision": expected_revision,
                    "response_text": response,
                    "reflection_text": reflection,
                    "self_assessment": self_assessment,
                }
            )
        )
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            plan = _visible_plan(session, plan_id)
            if plan is None:
                raise AdaptivePracticeNotFound()
            if plan.completion_idempotency_key == idempotency_key:
                if plan.completion_fingerprint != fingerprint:
                    raise AdaptivePracticeConflict("adaptive practice completion idempotency input changed")
                return _plan_json(session, plan), False
            if plan.status != "in_progress" or plan.revision != expected_revision:
                raise AdaptivePracticeConflict("adaptive practice revision changed")
            other = session.scalar(
                select(AdaptivePracticePlan).where(
                    AdaptivePracticePlan.completion_idempotency_key == idempotency_key
                )
            )
            if other is not None:
                raise AdaptivePracticeConflict("adaptive practice completion idempotency input changed")
            plan.response_text = response
            plan.reflection_text = reflection
            plan.self_assessment = self_assessment
            plan.completion_idempotency_key = idempotency_key
            plan.completion_fingerprint = fingerprint
            plan.status = "completed"
            plan.revision += 1
            plan.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(plan)
            return _plan_json(session, plan), True


def _proposal_focuses(proposal: InterviewReviewProposal) -> list[dict[str, Any]]:
    try:
        payload = json.loads(proposal.proposal_json)
    except (TypeError, ValueError):
        return []
    values = payload.get("practice_focuses") if isinstance(payload, dict) else None
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _visible_context(
    session: Session, proposal: InterviewReviewProposal
) -> tuple[InterviewNote, ApplicationEvent, Application] | None:
    if proposal.note_id is None or proposal.application_event_id is None:
        return None
    note = session.get(InterviewNote, proposal.note_id)
    event = session.get(ApplicationEvent, proposal.application_event_id)
    if note is None or event is None or note.application_id is None:
        return None
    application = session.get(Application, note.application_id)
    if (
        application is None
        or application.deleted_at is not None
        or note.application_event_id != event.id
        or event.application_id != application.id
        or event.event_type != "interview"
    ):
        return None
    return note, event, application


def _recommendation(
    proposal: InterviewReviewProposal,
    item: dict[str, Any],
    note: InterviewNote,
    event: ApplicationEvent,
    application: Application,
) -> dict[str, Any] | None:
    focus_id = item.get("id")
    observation = item.get("text")
    refs = item.get("evidence_refs")
    if not isinstance(focus_id, str) or not isinstance(observation, str) or not observation.strip():
        return None
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("source") != "interview_note":
            continue
        path = ref.get("path")
        excerpt = ref.get("excerpt")
        if path not in _PATH_TO_FIELD or not isinstance(excerpt, str) or not excerpt.strip():
            continue
        current = str(getattr(note, _PATH_TO_FIELD[path], ""))
        if excerpt not in current:
            continue
        drill_kind, title, reason, prompt = _DRILLS[path]
        source_fingerprint = sha256_text(
            canonical_json(
                {
                    "proposal_id": proposal.id,
                    "proposal_hash": proposal.proposal_hash,
                    "focus_id": focus_id,
                    "source_path": path,
                    "source_excerpt": excerpt,
                    "source_value_hash": sha256_text(current),
                    "note_id": note.id,
                    "event_id": event.id,
                }
            )
        )
        return {
            "proposal_id": proposal.id,
            "focus_id": focus_id,
            "application_id": application.id,
            "application_event_id": event.id,
            "interview_note_id": note.id,
            "company_name": application.company_name,
            "position_name": application.position_name,
            "drill_kind": drill_kind,
            "title": title,
            "observation": observation.strip(),
            "reason": reason,
            "prompt": prompt,
            "source_path": path,
            "source_excerpt": excerpt,
            "source_fingerprint": source_fingerprint,
        }
    return None


def _visible_plan(session: Session, plan_id: int) -> AdaptivePracticePlan | None:
    return session.scalar(
        select(AdaptivePracticePlan)
        .join(InterviewNote, InterviewNote.id == AdaptivePracticePlan.interview_note_id)
        .join(ApplicationEvent, ApplicationEvent.id == AdaptivePracticePlan.application_event_id)
        .join(Application, Application.id == AdaptivePracticePlan.application_id)
        .where(
            AdaptivePracticePlan.id == plan_id,
            Application.deleted_at.is_(None),
            InterviewNote.application_id == AdaptivePracticePlan.application_id,
            InterviewNote.application_event_id == AdaptivePracticePlan.application_event_id,
            ApplicationEvent.application_id == AdaptivePracticePlan.application_id,
            ApplicationEvent.event_type == "interview",
        )
    )


def _source_status(session: Session, plan: AdaptivePracticePlan) -> str:
    note = session.get(InterviewNote, plan.interview_note_id)
    event = session.get(ApplicationEvent, plan.application_event_id)
    if note is None or event is None or note.application_id != plan.application_id:
        return "missing"
    field = _PATH_TO_FIELD.get(plan.source_path)
    if field is None:
        return "missing"
    current = str(getattr(note, field, ""))
    return "current" if sha256_text(current) == plan.source_hash else "changed"


def _plan_json(session: Session, plan: AdaptivePracticePlan) -> dict[str, Any]:
    application = session.get(Application, plan.application_id)
    return {
        "id": plan.id,
        "application_id": plan.application_id,
        "application_event_id": plan.application_event_id,
        "interview_note_id": plan.interview_note_id,
        "proposal_id": plan.interview_review_proposal_id,
        "focus_id": plan.focus_id,
        "company_name": application.company_name if application is not None else "",
        "position_name": application.position_name if application is not None else "",
        "drill_kind": plan.drill_kind,
        "title": plan.title,
        "observation": plan.observation,
        "reason": plan.reason,
        "prompt": plan.prompt,
        "source_path": plan.source_path,
        "source_excerpt": plan.source_excerpt,
        "source_fingerprint": plan.source_fingerprint,
        "source_status": _source_status(session, plan),
        "status": plan.status,
        "revision": plan.revision,
        "response_text": plan.response_text,
        "reflection_text": plan.reflection_text,
        "self_assessment": plan.self_assessment,
        "created_at": _utc(plan.created_at),
        "completed_at": _utc(plan.completed_at),
    }


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
