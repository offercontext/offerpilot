from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.types import Message
from offerpilot.ai.workflows import parse_json_reply

INTERVIEW_REVIEW_UNGROUNDED_SUMMARY_V1 = (
    "本次复盘记录不足以形成有依据的表现判断，请先补充待澄清问题。"
)
INTERVIEW_REVIEW_UNGROUNDED_QUESTIONS_V1 = (
    "请补充本次面试中未记录的具体问题与回答。",
    "请补充你希望进一步澄清的内容。",
    "请补充你希望下次练习的具体场景。",
)
MAX_REVIEW_ITEMS = 10
MAX_EVIDENCE_REFS = 5

_NOTE_FIELDS = (
    "company",
    "position",
    "round",
    "date",
    "questions",
    "self_reflection",
    "difficulty_points",
    "mood",
)
_EVENT_FIELDS = (
    "id",
    "application_id",
    "event_type",
    "subtype",
    "round",
    "scheduled_at",
    "duration_minutes",
    "status",
)
_NOTE_EVIDENCE_PATHS = {f"/{field}" for field in _NOTE_FIELDS[4:]}
_TOP_LEVEL_FIELDS = {
    "summary",
    "observations",
    "clarifications",
    "practice_focuses",
    "next_questions",
}
_SUMMARY_FIELDS = {"text", "evidence_refs"}
_OBSERVATION_FIELDS = {"id", "text", "evidence_refs"}
_QUESTION_FIELDS = {"id", "question", "evidence_refs"}


class InterviewReviewModelError(ValueError):
    def __init__(self, message: str, *, failure_category: str = "unverifiable") -> None:
        super().__init__(message)
        self.failure_category = failure_category


class _InterviewReviewProviderError(Exception):
    pass


def build_interview_review_snapshot(note: Any, event: Any) -> dict[str, Any]:
    return {
        "note": {field: _model_value(note, field) for field in _NOTE_FIELDS},
        "event": {field: _snapshot_value(_model_value(event, field)) for field in _EVENT_FIELDS},
    }


def validate_interview_review(
    payload: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    _assert_finite_json(payload)
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise InterviewReviewModelError("invalid top-level fields")
    note = snapshot.get("note")
    if not isinstance(note, dict) or any(not isinstance(note.get(field), str) for field in _NOTE_FIELDS):
        raise InterviewReviewModelError("invalid interview note snapshot")

    summary = payload["summary"]
    if not isinstance(summary, dict) or set(summary) != _SUMMARY_FIELDS:
        raise InterviewReviewModelError("invalid summary shape")
    summary_text = summary.get("text")
    summary_refs = _validate_text_and_refs(summary_text, summary.get("evidence_refs"), snapshot)
    if not summary_refs and summary_text != INTERVIEW_REVIEW_UNGROUNDED_SUMMARY_V1:
        raise InterviewReviewModelError("summary requires evidence")

    normalized: dict[str, Any] = {
        "summary": {"text": summary_text, "evidence_refs": summary_refs},
        "observations": [],
        "clarifications": [],
        "practice_focuses": [],
        "next_questions": [],
    }
    seen_ids: set[str] = set()
    for field in ("observations", "clarifications", "practice_focuses", "next_questions"):
        items = payload[field]
        if not isinstance(items, list) or len(items) > MAX_REVIEW_ITEMS:
            raise InterviewReviewModelError(f"{field} exceeds the item limit")
        for item in items:
            expected_fields = _QUESTION_FIELDS if field in {"clarifications", "next_questions"} else _OBSERVATION_FIELDS
            if not isinstance(item, dict) or set(item) != expected_fields:
                raise InterviewReviewModelError(f"invalid {field} item shape")
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id.strip() or item_id in seen_ids:
                raise InterviewReviewModelError("review item ids must be unique non-empty strings")
            seen_ids.add(item_id)
            text_key = "question" if field in {"clarifications", "next_questions"} else "text"
            text_value = item.get(text_key)
            refs = _validate_text_and_refs(text_value, item.get("evidence_refs"), snapshot)
            if not refs and text_value not in INTERVIEW_REVIEW_UNGROUNDED_QUESTIONS_V1:
                raise InterviewReviewModelError(f"{field} item requires evidence")
            normalized[field].append(
                {"id": item_id, text_key: text_value, "evidence_refs": refs}
            )

    if _note_is_empty(note):
        if (
            summary_text != INTERVIEW_REVIEW_UNGROUNDED_SUMMARY_V1
            or summary_refs
            or normalized["observations"]
            or normalized["practice_focuses"]
        ):
            raise InterviewReviewModelError("empty review notes cannot produce observations")
        for field in ("clarifications", "next_questions"):
            if any(item["evidence_refs"] for item in normalized[field]):
                raise InterviewReviewModelError("empty review notes cannot have evidence")

    return normalized


def generate_interview_review_proposal(
    model: ChatModel, snapshot: dict[str, Any]
) -> dict[str, Any]:
    system = _interview_review_system()
    prompt = _interview_review_prompt(snapshot)
    for attempt in range(2):
        user = prompt if attempt == 0 else _interview_review_repair_prompt(snapshot)
        try:
            assistant = model.complete(
                [Message(role="system", content=system), Message(role="user", content=user)],
                [],
            )
        except Exception as exc:
            raise InterviewReviewModelError(
                "model provider request failed", failure_category="provider_error"
            ) from exc
        try:
            payload = parse_json_reply(
                assistant.content,
                allow_fenced=False,
                reject_non_finite=True,
                reject_duplicate_keys=True,
            )
            return validate_interview_review(payload, snapshot)
        except InterviewReviewModelError:
            if attempt == 0:
                continue
            raise InterviewReviewModelError(
                "model output could not be verified", failure_category="unverifiable"
            )
        except Exception:
            if attempt == 0:
                continue
            raise InterviewReviewModelError(
                "model output could not be verified", failure_category="unverifiable"
            )
    raise AssertionError("interview review retry loop must return or raise")


def _validate_text_and_refs(
    text_value: Any, raw_refs: Any, snapshot: dict[str, Any]
) -> list[dict[str, str]]:
    if not isinstance(text_value, str) or not text_value.strip():
        raise InterviewReviewModelError("review text must be a non-empty string")
    if not isinstance(raw_refs, list) or len(raw_refs) > MAX_EVIDENCE_REFS:
        raise InterviewReviewModelError("evidence_refs exceeds the limit")
    refs: list[dict[str, str]] = []
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, dict) or set(raw_ref) != {"source", "path", "excerpt"}:
            raise InterviewReviewModelError("invalid evidence reference shape")
        if raw_ref.get("source") != "interview_note":
            raise InterviewReviewModelError("invalid evidence source")
        path = raw_ref.get("path")
        excerpt = raw_ref.get("excerpt")
        if (
            not isinstance(path, str)
            or path not in _NOTE_EVIDENCE_PATHS
            or not isinstance(excerpt, str)
            or not excerpt.strip()
        ):
            raise InterviewReviewModelError("invalid evidence reference")
        value = snapshot["note"].get(path[1:])
        if not isinstance(value, str) or excerpt not in value:
            raise InterviewReviewModelError("evidence excerpt does not match snapshot")
        refs.append({"source": "interview_note", "path": path, "excerpt": excerpt})
    return refs


def _note_is_empty(note: dict[str, str]) -> bool:
    return all(not note[field].strip() for field in _NOTE_FIELDS[4:])


def _assert_finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise InterviewReviewModelError("non-finite JSON value")
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite_json(item)


def _model_value(model: Any, field: str) -> Any:
    return getattr(model, field, None)


def _snapshot_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.isoformat().replace("+00:00", "Z")
    return value


def _interview_review_system() -> str:
    return """You review one user's saved interview note. Return raw JSON only, never Markdown fences.
Use only the supplied frozen note fields as evidence. Event metadata is context only and is never evidence.
Do not infer ability, weakness, interviewer judgment, external facts, or anything not written in the note.
The exact top-level fields are summary, observations, clarifications, practice_focuses, next_questions.
Summary, observations, and practice_focuses require non-empty evidence_refs unless using the exact safe summary.
Every question needs evidence_refs unless it is one exact fixed safe question supplied by the contract.
Each evidence reference must be exactly {"source":"interview_note","path":"...","excerpt":"..."}.
Return only the strict JSON object matching the contract and never add fields."""


def _interview_review_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "Generate an evidence-gated interview review proposal from this frozen snapshot. "
        "Use exact contiguous excerpts from note fields and return a safe empty proposal when needed.\n"
        f"Frozen snapshot:\n{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


def _interview_review_repair_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "The previous output failed safe validation. Failure category: invalid_change_shape. "
        "Return only raw JSON for the same frozen snapshot and contract. Do not explain, "
        "repeat the invalid output, add fields, or use new sources.\n"
        f"Frozen snapshot:\n{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )
