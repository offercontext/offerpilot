from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from offerpilot.models import InterviewNote, MockInterviewAttempt, MockInterviewTurn, Resume
from offerpilot.repositories.json_contract import canonical_json, sha256_text


class StoryValidationError(ValueError):
    """Raised when Story content or selected candidate evidence is invalid."""


@dataclass(frozen=True)
class StorySourceSnapshot:
    sources: list[dict[str, str]]
    source_fingerprint: str


_NOTE_FIELDS = {
    "/questions": "questions",
    "/self_reflection": "self_reflection",
    "/difficulty_points": "difficulty_points",
    "/mood": "mood",
}
_ALLOWED_SOURCE_KINDS = {"resume_version", "interview_note", "mock_turn"}
_FACT_GAP_CODES = {"missing_result"}
_BLOCK_KINDS = {"situation", "task", "action", "result", "reflection"}


def canonical_story_content(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize user content and allocate version-local stable target IDs."""

    title = raw.get("title")
    if not isinstance(title, str):
        raise StoryValidationError("title must be a string")
    blocks_raw = raw.get("blocks", [])
    labels_raw = raw.get("capability_labels", [])
    questions_raw = raw.get("applicable_questions", [])
    gaps_raw = raw.get("fact_gap_codes", [])
    if not all(isinstance(value, list) for value in (blocks_raw, labels_raw, questions_raw, gaps_raw)):
        raise StoryValidationError("story collections must be arrays")

    block_counts: dict[str, int] = {}
    blocks: list[dict[str, str]] = []
    for item in blocks_raw:
        if not isinstance(item, Mapping):
            raise StoryValidationError("block must be an object")
        kind = item.get("kind")
        value = item.get("text")
        fact_mode = item.get("fact_mode")
        if kind not in _BLOCK_KINDS or not isinstance(value, str) or not isinstance(fact_mode, str):
            raise StoryValidationError("block is invalid")
        if kind == "reflection":
            if fact_mode != "user_view":
                raise StoryValidationError("reflection must be user_view")
        elif fact_mode != "evidence_backed":
            raise StoryValidationError("STAR block must be evidence_backed")
        block_counts[kind] = block_counts.get(kind, 0) + 1
        blocks.append(
            {
                "id": f"{kind}_{block_counts[kind]:03d}",
                "kind": kind,
                "text": value,
                "fact_mode": fact_mode,
            }
        )

    def _items(values: list[Any], prefix: str) -> list[dict[str, str]]:
        if not all(isinstance(value, str) for value in values):
            raise StoryValidationError(f"{prefix} items must be strings")
        return [{"id": f"{prefix}_{index:03d}", "text": value} for index, value in enumerate(values, 1)]

    if not all(isinstance(code, str) and code in _FACT_GAP_CODES for code in gaps_raw):
        raise StoryValidationError("fact gap code is invalid")
    if len(set(gaps_raw)) != len(gaps_raw):
        raise StoryValidationError("fact gap code is duplicated")
    return {
        "title": {"id": "title", "text": title},
        "blocks": blocks,
        "capability_labels": _items(labels_raw, "capability"),
        "applicable_questions": _items(questions_raw, "question"),
        "fact_gap_codes": list(gaps_raw),
    }


def materialize_selected_sources(
    session: Session,
    selections: list[dict[str, Any]],
    assertions: list[str],
) -> StorySourceSnapshot:
    """Resolve only explicit phase-one source selections into frozen leaf evidence."""

    sources: list[dict[str, str]] = []
    for selection in selections:
        if not isinstance(selection, Mapping):
            raise StoryValidationError("source selection must be an object")
        kind = selection.get("source_kind")
        source_id = selection.get("source_id")
        path = selection.get("path")
        if kind not in _ALLOWED_SOURCE_KINDS:
            raise StoryValidationError("source kind is invalid")
        if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
            raise StoryValidationError("source id is invalid")
        if not isinstance(path, str):
            raise StoryValidationError("source path is invalid")
        if kind == "resume_version":
            sources.append(_materialize_resume(session, source_id, path))
        elif kind == "interview_note":
            sources.append(_materialize_note(session, source_id, path))
        else:
            sources.append(_materialize_mock_turn(session, source_id, path))

    for index, statement in enumerate(assertions, 1):
        if not isinstance(statement, str) or not statement.strip():
            raise StoryValidationError("assertion is invalid")
        sources.append(
            {
                "source_kind": "user_assertion",
                "source_stable_id": f"assertion_{index:03d}",
                "source_version_or_snapshot": "pending_confirmation",
                "path": "/statement",
                "excerpt": statement,
                "source_fingerprint": sha256_text(statement),
            }
        )

    sources.sort(key=lambda item: (item["source_kind"], item["source_stable_id"], item["path"]))
    return StorySourceSnapshot(
        sources=sources,
        source_fingerprint=sha256_text(canonical_json(sources)),
    )


def _materialize_resume(session: Session, resume_id: int, path: str) -> dict[str, str]:
    pointer = _resume_content_pointer(path)
    resume = session.get(Resume, resume_id)
    if resume is None or resume.deleted_at is not None:
        raise StoryValidationError("resume source is missing")
    try:
        payload = json.loads(resume.content_json)
    except (TypeError, ValueError) as exc:
        raise StoryValidationError("resume source is invalid") from exc
    value = _resolve_json_pointer(payload, pointer)
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError("resume source path is invalid")
    return {
        "source_kind": "resume_version",
        "source_stable_id": str(resume.id),
        "source_version_or_snapshot": sha256_text(canonical_json(payload)),
        "path": path,
        "excerpt": value,
        "source_fingerprint": sha256_text(value),
    }


def _materialize_note(session: Session, note_id: int, path: str) -> dict[str, str]:
    field = _NOTE_FIELDS.get(path)
    note = session.get(InterviewNote, note_id)
    if field is None:
        raise StoryValidationError("interview note path is invalid")
    if note is None:
        raise StoryValidationError("interview note source is missing")
    value = getattr(note, field)
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError("interview note path is invalid")
    return {
        "source_kind": "interview_note",
        "source_stable_id": str(note.id),
        "source_version_or_snapshot": sha256_text(canonical_json({field: value})),
        "path": path,
        "excerpt": value,
        "source_fingerprint": sha256_text(value),
    }


def _materialize_mock_turn(session: Session, attempt_id: int, path: str) -> dict[str, str]:
    parts = path.split("/")
    if len(parts) != 4 or parts[:2] != ["", "turns"] or not parts[2].isdigit() or len(parts[2]) != 3:
        raise StoryValidationError("mock turn path is invalid")
    field = {"question": "question_text", "answer": "answer_text"}.get(parts[3])
    if field is None:
        raise StoryValidationError("mock turn path is invalid")
    attempt = session.get(MockInterviewAttempt, attempt_id)
    if (
        attempt is None
        or attempt.cancelled_at is not None
        or attempt.completed_at is None
        or attempt.attempt_status not in {"feedback_ready", "confirmed"}
    ):
        raise StoryValidationError("mock turn source is invalid")
    turn = session.scalar(
        select(MockInterviewTurn)
        .where(MockInterviewTurn.attempt_id == attempt_id)
        .where(MockInterviewTurn.turn_no == int(parts[2]))
    )
    if turn is None or turn.turn_status != "answered":
        raise StoryValidationError("mock turn source is invalid")
    value = getattr(turn, field)
    if not isinstance(value, str) or not value.strip():
        raise StoryValidationError("mock turn source is invalid")
    return {
        "source_kind": "mock_turn",
        "source_stable_id": f"{attempt.id}:{turn.turn_no:03d}",
        "source_version_or_snapshot": attempt.transcript_fingerprint,
        "path": path,
        "excerpt": value,
        "source_fingerprint": sha256_text(value),
    }


def _resolve_json_pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise StoryValidationError("resume source path is invalid")
    current = value
    for token in pointer[1:].split("/"):
        token = _decode_json_pointer_token(token)
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif (
            isinstance(current, list)
            and token.isdigit()
            and (token == "0" or not token.startswith("0"))
            and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            raise StoryValidationError("resume source path is invalid")
    return current


def _resume_content_pointer(path: str) -> str:
    prefix = "/content_json"
    if not path.startswith(f"{prefix}/"):
        raise StoryValidationError("resume source path is invalid")
    pointer = path[len(prefix) :]
    for token in pointer[1:].split("/"):
        _decode_json_pointer_token(token)
    return pointer


def _decode_json_pointer_token(token: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(token):
        char = token[index]
        if char != "~":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise StoryValidationError("resume source path is invalid")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)
