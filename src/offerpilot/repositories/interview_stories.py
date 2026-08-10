from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import (
    InterviewNote,
    InterviewStory,
    InterviewStoryProposalAttempt,
    InterviewStoryUserAssertion,
    InterviewStoryVersion,
    InterviewStoryVersionEvidenceLink,
    MockInterviewAttempt,
    MockInterviewTurn,
    Resume,
)
from offerpilot.repositories.json_contract import canonical_json, sha256_text


class StoryValidationError(ValueError):
    """Raised when Story content or selected candidate evidence is invalid."""


class StoryNotFoundError(StoryValidationError):
    """Raised when a requested Story is not available."""


class StoryConflictError(StoryValidationError):
    """Raised when an immutable Story pointer or lifecycle CAS is stale."""


class StorySourceConflictError(StoryConflictError):
    """Raised when a frozen source changed or is no longer materializable."""


@dataclass(frozen=True)
class StorySourceSnapshot:
    sources: list[dict[str, str]]
    source_fingerprint: str


@dataclass(frozen=True)
class CanonicalStoryLink:
    target_kind: str
    target_id: str
    source_kind: str
    source_stable_id: str
    source_version_or_snapshot: str
    source_path: str
    text_location: str
    excerpt: str
    source_fingerprint: str
    link_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "source_kind": self.source_kind,
            "source_stable_id": self.source_stable_id,
            "source_version_or_snapshot": self.source_version_or_snapshot,
            "source_path": self.source_path,
            "text_location": self.text_location,
            "excerpt": self.excerpt,
            "source_fingerprint": self.source_fingerprint,
            "link_hash": self.link_hash,
        }


_NOTE_FIELDS = {
    "/questions": "questions",
    "/self_reflection": "self_reflection",
    "/difficulty_points": "difficulty_points",
    "/mood": "mood",
}
_ALLOWED_SOURCE_KINDS = {"resume_version", "interview_note", "mock_turn"}
_FACT_GAP_CODES = {"missing_result"}
_BLOCK_KINDS = {"situation", "task", "action", "result", "reflection"}
_TARGET_KINDS = {"title", "block", "capability_label", "applicable_question"}
_MAX_EVIDENCE_EXCERPT_CHARS = 800
_MAX_EVIDENCE_LINKS_PER_TARGET = 8
_MAX_TITLE_CHARS = 200
_MAX_BLOCKS = 12
_MAX_BLOCK_TEXT_CHARS = 4_000
_MAX_SHORT_ITEMS = 12
_MAX_SHORT_TEXT_CHARS = 300
_MAX_FACT_GAPS = 1
_STORY_VERSION_SCHEMA = "interview-story-v1"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_STORY_LEASE_SECONDS = 30
_STORY_HEARTBEAT_SECONDS = 10


def canonical_story_content(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize user content and allocate version-local stable target IDs."""

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE_CHARS:
        raise StoryValidationError("title is invalid")
    blocks_raw = raw.get("blocks", [])
    labels_raw = raw.get("capability_labels", [])
    questions_raw = raw.get("applicable_questions", [])
    gaps_raw = raw.get("fact_gap_codes", [])
    if not all(isinstance(value, list) for value in (blocks_raw, labels_raw, questions_raw, gaps_raw)):
        raise StoryValidationError("story collections must be arrays")

    if len(blocks_raw) > _MAX_BLOCKS or len(labels_raw) > _MAX_SHORT_ITEMS or len(questions_raw) > _MAX_SHORT_ITEMS or len(gaps_raw) > _MAX_FACT_GAPS:
        raise StoryValidationError("story content exceeds limits")

    block_counts: dict[str, int] = {}
    blocks: list[dict[str, str]] = []
    for item in blocks_raw:
        if not isinstance(item, Mapping):
            raise StoryValidationError("block must be an object")
        kind = item.get("kind")
        value = item.get("text")
        fact_mode = item.get("fact_mode")
        if (
            kind not in _BLOCK_KINDS
            or not isinstance(value, str)
            or not value.strip()
            or len(value) > _MAX_BLOCK_TEXT_CHARS
            or not isinstance(fact_mode, str)
        ):
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
        if not all(isinstance(value, str) and value.strip() and len(value) <= _MAX_SHORT_TEXT_CHARS for value in values):
            raise StoryValidationError(f"{prefix} items must be strings")
        return [{"id": f"{prefix}_{index:03d}", "text": value} for index, value in enumerate(values, 1)]

    if not all(isinstance(code, str) and code in _FACT_GAP_CODES for code in gaps_raw):
        raise StoryValidationError("fact gap code is invalid")
    if len(set(gaps_raw)) != len(gaps_raw):
        raise StoryValidationError("fact gap code is duplicated")
    has_result = any(block["kind"] == "result" for block in blocks)
    if has_result != (gaps_raw == []):
        raise StoryValidationError("result and fact gap are inconsistent")
    return {
        "title": {"id": "title", "text": title},
        "blocks": blocks,
        "capability_labels": _items(labels_raw, "capability"),
        "applicable_questions": _items(questions_raw, "question"),
        "fact_gap_codes": list(gaps_raw),
    }


def validate_story_evidence_links(
    content: Mapping[str, Any],
    links: list[dict[str, Any]],
    snapshot: StorySourceSnapshot,
) -> list[CanonicalStoryLink]:
    """Bind every non-empty Story target to exact, frozen candidate evidence.

    Callers may only reference a source leaf emitted by
    :func:`materialize_selected_sources`; clients cannot substitute a source,
    path, snapshot fingerprint, or fabricated excerpt.
    """

    expected_targets = _evidence_targets(content)
    target_fact_modes = _target_fact_modes(content)
    catalog = {
        _source_identity(item): item
        for item in snapshot.sources
    }
    canonical: list[CanonicalStoryLink] = []
    linked_targets: set[tuple[str, str]] = set()
    link_counts: dict[tuple[str, str], int] = {}
    for raw in links:
        if not isinstance(raw, Mapping):
            raise StoryValidationError("evidence link must be an object")
        full_allowed = {
            "target_kind",
            "target_id",
            "source_kind",
            "source_stable_id",
            "source_version_or_snapshot",
            "source_path",
            "excerpt",
            "text_location",
        }
        client_allowed = {
            "target_kind",
            "target_id",
            "source_kind",
            "source_id",
            "source_path",
            "excerpt",
            "text_location",
        }
        fields = set(raw)
        if fields - full_allowed and fields - client_allowed:
            raise StoryValidationError("evidence link has extra fields")
        target_kind = raw.get("target_kind")
        target_id = raw.get("target_id")
        if (
            target_kind not in _TARGET_KINDS
            or not isinstance(target_id, str)
            or (target_kind, target_id) not in expected_targets
        ):
            raise StoryValidationError("evidence link target is invalid")
        source_kind = raw.get("source_kind")
        source_stable_id = raw.get("source_stable_id", raw.get("source_id"))
        source_version_or_snapshot = raw.get("source_version_or_snapshot")
        source_path = raw.get("source_path")
        excerpt = raw.get("excerpt")
        text_location = raw.get("text_location", "")
        if not isinstance(source_kind, str):
            raise StoryValidationError("evidence link shape is invalid")
        if isinstance(source_stable_id, int) and not isinstance(source_stable_id, bool):
            source_stable_id = str(source_stable_id)
        if not isinstance(source_stable_id, str):
            raise StoryValidationError("evidence link shape is invalid")
        if not isinstance(source_path, str):
            raise StoryValidationError("evidence link shape is invalid")
        if not isinstance(excerpt, str):
            raise StoryValidationError("evidence link shape is invalid")
        if not isinstance(text_location, str):
            raise StoryValidationError("evidence link shape is invalid")
        if excerpt == "":
            raise StoryValidationError("evidence link shape is invalid")
        if not excerpt.strip():
            raise StoryValidationError("evidence excerpt is invalid")
        if len(excerpt) > _MAX_EVIDENCE_EXCERPT_CHARS:
            raise StoryValidationError("evidence excerpt exceeds limit")
        if source_version_or_snapshot is None:
            source = next(
                (
                    entry
                    for entry in snapshot.sources
                    if entry["source_kind"] == source_kind
                    and entry["source_stable_id"] == source_stable_id
                    and entry["path"] == source_path
                ),
                None,
            )
            source_version_or_snapshot = source["source_version_or_snapshot"] if source else None
        if not isinstance(source_version_or_snapshot, str):
            raise StoryValidationError("evidence link shape is invalid")
        source = catalog.get((source_kind, source_stable_id, source_version_or_snapshot, source_path))
        if source is None:
            raise StoryValidationError("evidence source is invalid")
        if excerpt not in source["excerpt"]:
            raise StoryValidationError("evidence excerpt is invalid")
        target = (target_kind, target_id)
        if source_kind == "user_assertion" and target_fact_modes.get(target) != "user_view":
            raise StoryValidationError("user assertion cannot support an evidence-backed target")
        link_counts[target] = link_counts.get(target, 0) + 1
        if link_counts[target] > _MAX_EVIDENCE_LINKS_PER_TARGET:
            raise StoryValidationError("evidence link count exceeds limit")
        payload = {
            "target_kind": target_kind,
            "target_id": target_id,
            "source_kind": source_kind,
            "source_stable_id": source_stable_id,
            "source_version_or_snapshot": source_version_or_snapshot,
            "source_path": source_path,
            "text_location": text_location,
            "excerpt": excerpt,
            "source_fingerprint": source["source_fingerprint"],
        }
        canonical.append(CanonicalStoryLink(**payload, link_hash=sha256_text(canonical_json(payload))))
        linked_targets.add((target_kind, target_id))

    missing = expected_targets - linked_targets
    if missing:
        raise StoryValidationError("story targets require evidence")
    canonical.sort(
        key=lambda item: (
            item.target_kind,
            item.target_id,
            item.source_kind,
            item.source_stable_id,
            item.source_path,
            item.excerpt,
        )
    )
    return canonical


def derive_story_source_states(
    session: Session,
    version: InterviewStoryVersion,
) -> list[dict[str, str]]:
    """Derive (but never persist) current/changed/missing source state."""

    links = list(
        session.scalars(
            select(InterviewStoryVersionEvidenceLink)
            .where(InterviewStoryVersionEvidenceLink.story_version_id == version.id)
            .order_by(InterviewStoryVersionEvidenceLink.id.asc())
        )
    )
    states: list[dict[str, str]] = []
    for link in links:
        base = {
            "target_kind": link.target_kind,
            "target_id": link.target_id,
            "source_kind": link.source_kind,
            "source_stable_id": link.source_stable_id,
            "source_version_or_snapshot": link.source_version_or_snapshot,
            "source_path": link.source_path,
            "excerpt": link.excerpt,
        }
        if link.source_kind == "user_assertion":
            states.append({**base, "state": "frozen_user_assertion"})
            continue
        try:
            source = _revalidate_persisted_source(session, link)
        except StoryValidationError as exc:
            state = "missing" if "missing" in str(exc) else "changed"
        else:
            state = (
                "current"
                if (
                    source["source_fingerprint"] == link.source_fingerprint
                    and source["excerpt"] == link.excerpt
                    and source["source_version_or_snapshot"] == link.source_version_or_snapshot
                )
                else "changed"
            )
        states.append({**base, "state": state})
    return states


def story_request_fingerprint(
    *,
    target_story_id: int | None,
    expected_current_version_id: int | None,
    expected_story_revision: int | None,
    selections: list[dict[str, Any]],
    assertions: list[str],
) -> str:
    """Hash canonical user-selected input, never client-supplied snapshots."""

    for field, value in (
        ("target story id", target_story_id),
        ("expected current version id", expected_current_version_id),
        ("expected story revision", expected_story_revision),
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise StoryValidationError(f"{field} is invalid")
    normalized_selections: list[dict[str, Any]] = []
    for item in selections:
        if not isinstance(item, Mapping):
            raise StoryValidationError("source selection must be an object")
        if set(item) != {"source_kind", "source_id", "path"}:
            raise StoryValidationError("source selection shape is invalid")
        normalized_selections.append(dict(item))
    if not all(isinstance(statement, str) for statement in assertions):
        raise StoryValidationError("assertion is invalid")
    payload = {
        "schema": _STORY_VERSION_SCHEMA,
        "target_story_id": target_story_id,
        "expected_current_version_id": expected_current_version_id,
        "expected_story_revision": expected_story_revision,
        "selections": sorted(
            normalized_selections,
            key=lambda item: (str(item["source_kind"]), str(item["source_id"]), str(item["path"])),
        ),
        "assertions": list(assertions),
    }
    return sha256_text(canonical_json(payload))


def _manual_request_fingerprint(
    *,
    target_story_id: int | None,
    content: Mapping[str, Any],
    evidence_links: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    assertions: list[str],
    expected_current_version_id: int | None,
    expected_story_revision: int | None,
) -> str:
    """Bind an explicit manual save to the exact user-confirmed payload."""

    if not all(isinstance(item, Mapping) for item in evidence_links):
        raise StoryValidationError("evidence link must be an object")
    payload = {
        "operation": "manual_save",
        "target_story_id": target_story_id,
        "expected_current_version_id": expected_current_version_id,
        "expected_story_revision": expected_story_revision,
        "content": dict(content),
        "evidence_links": sorted(
            [dict(item) for item in evidence_links],
            key=canonical_json,
        ),
        "selections": _canonical_selections(selections),
        "assertions": list(assertions),
    }
    return sha256_text(canonical_json(payload))


@dataclass(frozen=True)
class StoryProposalClaim:
    attempt_id: int
    input_snapshot: dict[str, Any]
    source_snapshot: StorySourceSnapshot
    source_fingerprint: str
    should_call_provider: bool
    pending: bool
    generation_revision: int
    provider_call_token: str
    attempt_status: str


@dataclass(frozen=True)
class StoryConfirmation:
    story_id: int
    version_id: int
    created: bool


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
    if (
        len(parts) != 4
        or parts[:2] != ["", "turns"]
        or len(parts[2]) != 3
        or not _is_three_ascii_digits(parts[2])
    ):
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
            and _is_canonical_array_index(token)
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


def _is_canonical_array_index(value: str) -> bool:
    # Keep the lexical RFC 6901 rule narrow *and* bounded before callers use
    # int(value). Python rejects unbounded decimal conversions on modern
    # runtimes; a path must fail as invalid instead of leaking ValueError.
    return value == "0" or (
        bool(value)
        and len(value) <= 18
        and value[0] in "123456789"
        and all(char in "0123456789" for char in value[1:])
    )


def _is_three_ascii_digits(value: str) -> bool:
    return len(value) == 3 and all(char in "0123456789" for char in value)


def _escape_json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _resume_string_leaves(value: Any, pointer: str = "/content_json") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(pointer, value)] if value.strip() else []
    if isinstance(value, dict):
        leaves: list[tuple[str, str]] = []
        for key in sorted(value):
            if isinstance(key, str):
                leaves.extend(_resume_string_leaves(value[key], f"{pointer}/{_escape_json_pointer_token(key)}"))
        return leaves
    if isinstance(value, list):
        leaves = []
        for index, item in enumerate(value):
            leaves.extend(_resume_string_leaves(item, f"{pointer}/{index}"))
        return leaves
    return []


def _source_preview(value: str) -> str:
    # Prefix only, preserving original code points and never adding an ellipsis:
    # it remains a valid contiguous excerpt if the user chooses it manually.
    return value[:240]


def _source_identity(source: Mapping[str, str]) -> tuple[str, str, str, str]:
    return (
        source["source_kind"],
        source["source_stable_id"],
        source["source_version_or_snapshot"],
        source["path"],
    )


def _evidence_targets(content: Mapping[str, Any]) -> set[tuple[str, str]]:
    title = content.get("title")
    if not isinstance(title, Mapping) or not isinstance(title.get("id"), str) or not isinstance(title.get("text"), str):
        raise StoryValidationError("canonical story title is invalid")
    targets: set[tuple[str, str]] = set()
    if title["text"].strip():
        targets.add(("title", title["id"]))
    collections = (
        ("blocks", "block"),
        ("capability_labels", "capability_label"),
        ("applicable_questions", "applicable_question"),
    )
    for field, target_kind in collections:
        values = content.get(field)
        if not isinstance(values, list):
            raise StoryValidationError("canonical story content is invalid")
        for item in values:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
                raise StoryValidationError("canonical story content is invalid")
            if item["text"].strip():
                targets.add((target_kind, item["id"]))
    if not targets:
        raise StoryValidationError("story must contain an evidence target")
    return targets


def _target_fact_modes(content: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """Return the fact mode for every stable evidence target."""

    modes = {target: "evidence_backed" for target in _evidence_targets(content)}
    blocks = content.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, Mapping) and isinstance(block.get("id"), str):
                modes[("block", block["id"])] = str(block.get("fact_mode", "evidence_backed"))
    return modes


def _revalidate_persisted_source(
    session: Session,
    link: InterviewStoryVersionEvidenceLink,
) -> dict[str, str]:
    if link.source_kind == "resume_version":
        try:
            resume_id = int(link.source_stable_id)
        except ValueError as exc:
            raise StoryValidationError("resume source is missing") from exc
        return _materialize_resume(session, resume_id, link.source_path)
    if link.source_kind == "interview_note":
        try:
            note_id = int(link.source_stable_id)
        except ValueError as exc:
            raise StoryValidationError("interview note source is missing") from exc
        return _materialize_note(session, note_id, link.source_path)
    if link.source_kind == "mock_turn":
        attempt_id, separator, _turn_no = link.source_stable_id.partition(":")
        if not separator:
            raise StoryValidationError("mock turn source is missing")
        try:
            return _materialize_mock_turn(session, int(attempt_id), link.source_path)
        except ValueError as exc:
            raise StoryValidationError("mock turn source is missing") from exc
    raise StoryValidationError("story source is missing")


class InterviewStoriesRepository:
    """Own immutable Story Versions and their explicitly selected evidence."""

    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def list_stories(self, *, status: str = "active", query: str = "") -> list[dict[str, Any]]:
        if status not in {"active", "archived", "all"}:
            raise StoryValidationError("story status is invalid")
        with self._session_factory() as session:
            statement = select(InterviewStory).order_by(InterviewStory.updated_at.desc(), InterviewStory.id.desc())
            if status != "all":
                statement = statement.where(InterviewStory.status == status)
            rows = list(session.scalars(statement))
            normalized_query = query.strip().casefold()
            if normalized_query:
                rows = [row for row in rows if normalized_query in row.title.casefold()]
            return [self._story_summary(session, row) for row in rows]

    def list_source_candidates(self, *, review_note_id: int | None = None) -> dict[str, Any]:
        """Return bounded, read-only candidates for the explicit Story picker.

        The response is deliberately a selection aid, not a provider snapshot:
        it contains only canonical identities plus a bounded literal prefix.  The
        selected leaves are always materialized again in the short claim
        transaction before they can reach a model or a Version.
        """

        if review_note_id is not None:
            _require_positive_int("review note id", review_note_id)
        with self._session_factory() as session:
            notes_statement = select(InterviewNote).order_by(InterviewNote.id.desc())
            if review_note_id is not None:
                notes_statement = notes_statement.where(InterviewNote.id == review_note_id)
            notes = [
                {
                    "id": note.id,
                    "label": " · ".join(part for part in (note.company, note.position) if part),
                    "leaves": [
                        {"path": path, "preview": _source_preview(value)}
                        for path, field in _NOTE_FIELDS.items()
                        if isinstance((value := getattr(note, field)), str) and value.strip()
                    ],
                }
                for note in session.scalars(notes_statement)
            ]
            # A saved-review handoff is intentionally narrow: it must not turn
            # into a picker for unrelated candidate sources.
            if review_note_id is not None:
                return {"resumes": [], "interview_notes": notes, "mock_turns": []}

            resumes = []
            for resume in session.scalars(
                select(Resume).where(Resume.deleted_at.is_(None)).order_by(Resume.id.desc())
            ):
                try:
                    payload = json.loads(resume.content_json)
                except (TypeError, ValueError):
                    continue
                leaves = [
                    {"path": path, "preview": _source_preview(value)}
                    for path, value in _resume_string_leaves(payload)
                    if path.startswith("/content_json/")
                ]
                if leaves:
                    resumes.append({"id": resume.id, "label": resume.title or resume.name or f"Resume {resume.id}", "leaves": leaves})

            mock_turns = []
            attempts = session.scalars(
                select(MockInterviewAttempt)
                .where(MockInterviewAttempt.cancelled_at.is_(None))
                .where(MockInterviewAttempt.completed_at.is_not(None))
                .where(MockInterviewAttempt.attempt_status.in_({"feedback_ready", "confirmed"}))
                .order_by(MockInterviewAttempt.id.desc())
            )
            for attempt in attempts:
                for turn in session.scalars(
                    select(MockInterviewTurn)
                    .where(MockInterviewTurn.attempt_id == attempt.id)
                    .where(MockInterviewTurn.turn_status == "answered")
                    .order_by(MockInterviewTurn.turn_no.asc())
                ):
                    leaves = []
                    for name, value in (("question", turn.question_text), ("answer", turn.answer_text)):
                        if isinstance(value, str) and value.strip():
                            leaves.append({"path": f"/turns/{turn.turn_no:03d}/{name}", "preview": _source_preview(value)})
                    if leaves:
                        mock_turns.append({
                            "attempt_id": attempt.id,
                            "turn_no": turn.turn_no,
                            "label": f"模拟面试 #{attempt.id} · 第 {turn.turn_no} 题",
                            "leaves": leaves,
                        })
            return {"resumes": resumes, "interview_notes": notes, "mock_turns": mock_turns}

    def get_story(self, story_id: int) -> dict[str, Any] | None:
        with self._session_factory() as session:
            story = session.get(InterviewStory, story_id)
            return self._story_payload(session, story) if story is not None else None

    def get_version(self, story_id: int, version_id: int) -> dict[str, Any] | None:
        with self._session_factory() as session:
            version = session.get(InterviewStoryVersion, version_id)
            if version is None or version.story_id != story_id:
                return None
            return self._version_payload(session, version)

    def list_versions(self, story_id: int) -> list[dict[str, Any]] | None:
        with self._session_factory() as session:
            if session.get(InterviewStory, story_id) is None:
                return None
            versions = list(
                session.scalars(
                    select(InterviewStoryVersion)
                    .where(InterviewStoryVersion.story_id == story_id)
                    .order_by(InterviewStoryVersion.version_number.desc())
                )
            )
            return [
                {
                    "id": version.id,
                    "version_number": version.version_number,
                    "origin_kind": version.origin_kind,
                    "confirmed_at": version.confirmed_at.isoformat() if version.confirmed_at else None,
                    "source_fingerprint": version.source_fingerprint,
                }
                for version in versions
            ]

    def create_manual_story(
        self,
        *,
        content: Mapping[str, Any],
        evidence_links: list[dict[str, Any]],
        selections: list[dict[str, Any]],
        assertions: list[str],
        expected_current_version_id: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_exact_null("new story current version id", expected_current_version_id)
        request_fingerprint = _manual_request_fingerprint(
            target_story_id=None,
            content=content,
            evidence_links=evidence_links,
            selections=selections,
            assertions=assertions,
            expected_current_version_id=expected_current_version_id,
            expected_story_revision=None,
        )
        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                replay = self._replay_manual_save(session, idempotency_key, request_fingerprint)
                if replay is not None:
                    session.commit()
                    return replay
                canonical = canonical_story_content(content)
                snapshot = materialize_selected_sources(session, selections, assertions)
                canonical_links = validate_story_evidence_links(canonical, evidence_links, snapshot)
                story = InterviewStory(title=canonical["title"]["text"], status="active", story_revision=1)
                session.add(story)
                session.flush()
                version = self._insert_version(
                    session,
                    story=story,
                    version_number=1,
                    canonical=canonical,
                    snapshot=snapshot,
                    canonical_links=canonical_links,
                    assertions=assertions,
                    origin_kind="manual",
                )
                story.current_version_id = version.id
                self._record_manual_save(
                    session,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    story=story,
                    version=version,
                    snapshot=snapshot,
                )
                session.commit()
                return self._story_payload(session, story)
            except Exception:
                session.rollback()
                raise

    def create_manual_version(
        self,
        *,
        story_id: int,
        content: Mapping[str, Any],
        evidence_links: list[dict[str, Any]],
        selections: list[dict[str, Any]],
        assertions: list[str],
        expected_current_version_id: int | None,
        expected_story_revision: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_positive_int("expected current version id", expected_current_version_id)
        _require_positive_int("expected story revision", expected_story_revision)
        request_fingerprint = _manual_request_fingerprint(
            target_story_id=story_id,
            content=content,
            evidence_links=evidence_links,
            selections=selections,
            assertions=assertions,
            expected_current_version_id=expected_current_version_id,
            expected_story_revision=expected_story_revision,
        )
        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                replay = self._replay_manual_save(session, idempotency_key, request_fingerprint)
                if replay is not None:
                    session.commit()
                    return replay
                story = self._require_active_story(session, story_id)
                self._check_story_cas(story, expected_current_version_id, expected_story_revision)
                canonical = canonical_story_content(content)
                snapshot = materialize_selected_sources(session, selections, assertions)
                canonical_links = validate_story_evidence_links(canonical, evidence_links, snapshot)
                version_number = int(
                    session.scalar(
                        select(InterviewStoryVersion.version_number)
                        .where(InterviewStoryVersion.story_id == story.id)
                        .order_by(InterviewStoryVersion.version_number.desc())
                    )
                    or 0
                ) + 1
                version = self._insert_version(
                    session,
                    story=story,
                    version_number=version_number,
                    canonical=canonical,
                    snapshot=snapshot,
                    canonical_links=canonical_links,
                    assertions=assertions,
                    origin_kind="manual",
                )
                story.current_version_id = version.id
                story.story_revision += 1
                story.title = canonical["title"]["text"]
                story.updated_at = datetime.now(timezone.utc)
                self._record_manual_save(
                    session,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    story=story,
                    version=version,
                    snapshot=snapshot,
                )
                session.commit()
                return self._story_payload(session, story)
            except Exception:
                session.rollback()
                raise

    def archive(self, *, story_id: int, expected_story_revision: int | None) -> dict[str, Any]:
        return self._change_lifecycle(
            story_id=story_id,
            expected_story_revision=expected_story_revision,
            desired_status="archived",
        )

    def restore(self, *, story_id: int, expected_story_revision: int | None) -> dict[str, Any]:
        return self._change_lifecycle(
            story_id=story_id,
            expected_story_revision=expected_story_revision,
            desired_status="active",
        )

    def claim_proposal(
        self,
        *,
        target_story_id: int | None,
        expected_current_version_id: int | None,
        expected_story_revision: int | None,
        selections: list[dict[str, Any]],
        assertions: list[str],
        idempotency_key: str,
        entrypoint: str,
        entry_context: dict[str, Any] | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> StoryProposalClaim:
        """Claim one fenced Provider attempt from explicitly selected source leaves."""

        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise StoryValidationError("idempotency key is invalid")
        if entrypoint not in {"ui", "pilot"}:
            raise StoryValidationError("story entrypoint is invalid")
        now = _now(now_factory)
        request_fingerprint = story_request_fingerprint(
            target_story_id=target_story_id,
            expected_current_version_id=expected_current_version_id,
            expected_story_revision=expected_story_revision,
            selections=selections,
            assertions=assertions,
        )
        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                existing = session.scalar(
                    select(InterviewStoryProposalAttempt).where(
                        InterviewStoryProposalAttempt.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    payload = _attempt_input_payload(existing)
                    if payload.get("request_fingerprint") != request_fingerprint:
                        raise StoryConflictError("story idempotency input changed")
                    return self._replay_or_takeover_attempt(
                        session=session,
                        attempt=existing,
                        payload=payload,
                        now=now,
                    )
                self._validate_target_story_for_claim(
                    session,
                    target_story_id=target_story_id,
                    expected_current_version_id=expected_current_version_id,
                    expected_story_revision=expected_story_revision,
                )
                snapshot = materialize_selected_sources(session, selections, assertions)
                token = uuid4().hex
                input_snapshot = {
                    "schema": _STORY_VERSION_SCHEMA,
                    "request_fingerprint": request_fingerprint,
                    "target_story_id": target_story_id,
                    "expected_current_version_id": expected_current_version_id,
                    "expected_story_revision": expected_story_revision,
                    "selections": _canonical_selections(selections),
                    "assertions": list(assertions),
                    "sources": snapshot.sources,
                }
                attempt = InterviewStoryProposalAttempt(
                    target_story_id=target_story_id,
                    idempotency_key=idempotency_key,
                    entrypoint=entrypoint,
                    entry_context_json=canonical_json(entry_context or {}),
                    attempt_status="generating",
                    generation_revision=1,
                    provider_call_token=token,
                    provider_lease_until=_as_naive_utc(now + timedelta(seconds=_STORY_LEASE_SECONDS)),
                    input_snapshot_json=canonical_json(input_snapshot),
                    source_fingerprint=snapshot.source_fingerprint,
                )
                session.add(attempt)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.scalar(
                        select(InterviewStoryProposalAttempt).where(
                            InterviewStoryProposalAttempt.idempotency_key == idempotency_key
                        )
                    )
                    if existing is None:
                        raise
                    payload = _attempt_input_payload(existing)
                    if payload.get("request_fingerprint") != request_fingerprint:
                        raise StoryConflictError("story idempotency input changed")
                    return self._replay_or_takeover_attempt(
                        session=session,
                        attempt=existing,
                        payload=payload,
                        now=now,
                    )
                return StoryProposalClaim(
                    attempt_id=attempt.id,
                    input_snapshot=input_snapshot,
                    source_snapshot=snapshot,
                    source_fingerprint=snapshot.source_fingerprint,
                    should_call_provider=True,
                    pending=False,
                    generation_revision=attempt.generation_revision,
                    provider_call_token=token,
                    attempt_status=attempt.attempt_status,
                )
            except Exception:
                session.rollback()
                raise

    def complete_proposal(
        self,
        *,
        attempt_id: int,
        generation_revision: int,
        provider_call_token: str,
        proposal: dict[str, Any],
    ) -> bool:
        """Final fencing CAS: token/revision own the result, not lease freshness."""

        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                attempt = session.get(InterviewStoryProposalAttempt, attempt_id)
                if not _owned_attempt(attempt, generation_revision, provider_call_token):
                    session.commit()
                    return False
                if attempt is None:
                    session.commit()
                    return False
                payload = _attempt_input_payload(attempt)
                snapshot = _snapshot_from_attempt(payload, attempt.source_fingerprint)
                selections = payload.get("selections")
                assertions = payload.get("assertions")
                if not isinstance(selections, list) or not isinstance(assertions, list):
                    attempt.attempt_status = "invalidated"
                    attempt.provider_call_token = ""
                    session.commit()
                    return False
                try:
                    current = materialize_selected_sources(session, selections, assertions)
                except StoryValidationError as exc:
                    attempt.attempt_status = "invalidated"
                    attempt.provider_call_token = ""
                    session.commit()
                    raise StorySourceConflictError("story source changed") from exc
                if current.source_fingerprint != attempt.source_fingerprint:
                    attempt.attempt_status = "invalidated"
                    attempt.provider_call_token = ""
                    session.commit()
                    return False
                # Re-run strict validation server side.  The only alternate form
                # is the already-normalized server result returned by the local
                # generator; clients never reach this repository method directly.
                if proposal.get("proposal_status") == "normal":
                    raw_content = proposal.get("content")
                    raw_links = proposal.get("evidence_links")
                    if not isinstance(raw_content, dict) or not isinstance(raw_links, list):
                        raise StoryValidationError("story proposal is invalid")
                    content = canonical_story_content(_manual_content_from_canonical(raw_content))
                    checked = {
                        "proposal_status": "normal",
                        "content": content,
                        "evidence_links": [
                            item.as_dict()
                            for item in validate_story_evidence_links(
                                content,
                                [_client_link_fields(item) for item in raw_links],
                                snapshot,
                            )
                        ],
                    }
                elif proposal.get("proposal_status") == "safe_empty":
                    from offerpilot.ai.interview_stories import safe_empty_interview_story_proposal

                    if proposal != safe_empty_interview_story_proposal():
                        raise StoryValidationError("story proposal is invalid")
                    checked = proposal
                else:
                    from offerpilot.ai.interview_stories import validate_interview_story_proposal

                    checked = validate_interview_story_proposal(proposal, snapshot)
                status = "safe_empty" if checked["proposal_status"] == "safe_empty" else "ready"
                attempt.attempt_status = status
                attempt.proposal_json = canonical_json(checked)
                attempt.proposal_hash = sha256_text(attempt.proposal_json)
                attempt.failure_category = ""
                attempt.provider_call_token = ""
                session.commit()
                return True
            except StoryValidationError:
                session.rollback()
                raise
            except Exception:
                session.rollback()
                raise

    def mark_provider_unknown(
        self, *, attempt_id: int, generation_revision: int, provider_call_token: str, category: str
    ) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                update(InterviewStoryProposalAttempt)
                .where(InterviewStoryProposalAttempt.id == attempt_id)
                .where(InterviewStoryProposalAttempt.attempt_status == "generating")
                .where(InterviewStoryProposalAttempt.generation_revision == generation_revision)
                .where(InterviewStoryProposalAttempt.provider_call_token == provider_call_token)
                .values(attempt_status="provider_unknown", provider_call_token="", failure_category=category)
            )
            session.commit()
            return int(getattr(result, "rowcount", 0) or 0) == 1

    def mark_contract_failed(
        self, *, attempt_id: int, generation_revision: int, provider_call_token: str, category: str
    ) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                update(InterviewStoryProposalAttempt)
                .where(InterviewStoryProposalAttempt.id == attempt_id)
                .where(InterviewStoryProposalAttempt.attempt_status == "generating")
                .where(InterviewStoryProposalAttempt.generation_revision == generation_revision)
                .where(InterviewStoryProposalAttempt.provider_call_token == provider_call_token)
                .values(attempt_status="contract_failed", provider_call_token="", failure_category=category)
            )
            session.commit()
            return int(getattr(result, "rowcount", 0) or 0) == 1

    def get_attempt(self, attempt_id: int) -> dict[str, Any] | None:
        with self._session_factory() as session:
            attempt = session.get(InterviewStoryProposalAttempt, attempt_id)
            return _attempt_payload(attempt) if attempt is not None else None

    def confirm_attempt(
        self,
        *,
        attempt_id: int,
        confirmation_token: str,
        content: Mapping[str, Any],
        evidence_links: list[dict[str, Any]],
        expected_current_version_id: int | None,
        expected_story_revision: int | None,
    ) -> StoryConfirmation:
        if not isinstance(confirmation_token, str) or not _IDEMPOTENCY_KEY.fullmatch(confirmation_token):
            raise StoryValidationError("confirmation token is invalid")
        confirmation_hash = sha256_text(confirmation_token)
        payload_hash = sha256_text(canonical_json({"content": content, "evidence_links": evidence_links}))
        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                attempt = session.get(InterviewStoryProposalAttempt, attempt_id)
                if attempt is None:
                    raise StoryNotFoundError("story proposal is missing")
                if attempt.attempt_status == "confirmed" and attempt.confirmation_token_hash == confirmation_hash:
                    if attempt.confirmation_payload_hash != payload_hash or not attempt.confirmed_story_id or not attempt.confirmed_story_version_id:
                        raise StoryConflictError("confirmation input changed")
                    session.commit()
                    return StoryConfirmation(attempt.confirmed_story_id, attempt.confirmed_story_version_id, False)
                if attempt.attempt_status != "ready":
                    raise StoryConflictError("story proposal cannot be confirmed")
                input_payload = _attempt_input_payload(attempt)
                if (
                    input_payload.get("expected_current_version_id") != expected_current_version_id
                    or input_payload.get("expected_story_revision") != expected_story_revision
                ):
                    raise StoryConflictError("story proposal confirmation CAS changed")
                selections = input_payload.get("selections")
                assertions = input_payload.get("assertions")
                if not isinstance(selections, list) or not isinstance(assertions, list):
                    raise StoryConflictError("story proposal snapshot is invalid")
                try:
                    snapshot = materialize_selected_sources(session, selections, assertions)
                except StoryValidationError as exc:
                    raise StorySourceConflictError("story source changed") from exc
                if snapshot.source_fingerprint != attempt.source_fingerprint:
                    raise StoryConflictError("story source changed")
                canonical = canonical_story_content(content)
                links = validate_story_evidence_links(canonical, evidence_links, snapshot)
                target_story_id = attempt.target_story_id
                if target_story_id is None:
                    if expected_current_version_id is not None or expected_story_revision is not None:
                        raise StoryConflictError("new story confirmation CAS is invalid")
                    story = InterviewStory(title=canonical["title"]["text"], status="active", story_revision=1)
                    session.add(story)
                    session.flush()
                    version_number = 1
                else:
                    story = self._require_active_story(session, target_story_id)
                    self._check_story_cas(story, expected_current_version_id, expected_story_revision)
                    version_number = int(
                        session.scalar(
                            select(InterviewStoryVersion.version_number)
                            .where(InterviewStoryVersion.story_id == story.id)
                            .order_by(InterviewStoryVersion.version_number.desc())
                        )
                        or 0
                    ) + 1
                version = self._insert_version(
                    session,
                    story=story,
                    version_number=version_number,
                    canonical=canonical,
                    snapshot=snapshot,
                    canonical_links=links,
                    assertions=assertions,
                    origin_kind="proposal",
                )
                story.current_version_id = version.id
                story.title = canonical["title"]["text"]
                if target_story_id is not None:
                    story.story_revision += 1
                attempt.attempt_status = "confirmed"
                attempt.confirmation_token_hash = confirmation_hash
                attempt.confirmation_payload_hash = payload_hash
                attempt.confirmed_story_id = story.id
                attempt.confirmed_story_version_id = version.id
                attempt.confirmed_at = datetime.now(timezone.utc)
                session.commit()
                return StoryConfirmation(story.id, version.id, True)
            except Exception:
                session.rollback()
                raise

    def start_heartbeat(
        self,
        *,
        attempt_id: int,
        generation_revision: int,
        provider_call_token: str,
        now_factory: Callable[[], datetime] | None = None,
        waiter: threading.Event | None = None,
    ) -> "_StoryLeaseHeartbeat":
        heartbeat = _StoryLeaseHeartbeat(
            self._session_factory,
            attempt_id=attempt_id,
            generation_revision=generation_revision,
            provider_call_token=provider_call_token,
            now_factory=now_factory,
            waiter=waiter,
        )
        heartbeat.start()
        return heartbeat

    def _replay_or_takeover_attempt(
        self,
        *,
        session: Session,
        attempt: InterviewStoryProposalAttempt,
        payload: dict[str, Any],
        now: datetime,
    ) -> StoryProposalClaim:
        snapshot = _snapshot_from_attempt(payload, attempt.source_fingerprint)
        if attempt.attempt_status == "generating" and _lease_is_live(attempt.provider_lease_until, now):
            session.commit()
            return StoryProposalClaim(
                attempt.id, payload, snapshot, attempt.source_fingerprint, False, True,
                attempt.generation_revision, attempt.provider_call_token, attempt.attempt_status,
            )
        if attempt.attempt_status in {"generating", "provider_unknown"}:
            token = uuid4().hex
            attempt.attempt_status = "generating"
            attempt.generation_revision += 1
            attempt.provider_call_token = token
            attempt.provider_lease_until = _as_naive_utc(now + timedelta(seconds=_STORY_LEASE_SECONDS))
            attempt.failure_category = ""
            session.commit()
            return StoryProposalClaim(
                attempt.id, payload, snapshot, attempt.source_fingerprint, True, False,
                attempt.generation_revision, token, attempt.attempt_status,
            )
        session.commit()
        return StoryProposalClaim(
            attempt.id, payload, snapshot, attempt.source_fingerprint, False, False,
            attempt.generation_revision, attempt.provider_call_token, attempt.attempt_status,
        )

    @staticmethod
    def _validate_target_story_for_claim(
        session: Session,
        *,
        target_story_id: int | None,
        expected_current_version_id: int | None,
        expected_story_revision: int | None,
    ) -> None:
        if target_story_id is None:
            _require_exact_null("new story current version id", expected_current_version_id)
            _require_exact_null("new story revision", expected_story_revision)
            return
        _require_positive_int("expected current version id", expected_current_version_id)
        _require_positive_int("expected story revision", expected_story_revision)
        story = InterviewStoriesRepository._require_active_story(session, target_story_id)
        InterviewStoriesRepository._check_story_cas(
            story, expected_current_version_id, expected_story_revision
        )

    def _change_lifecycle(
        self, *, story_id: int, expected_story_revision: int | None, desired_status: str
    ) -> dict[str, Any]:
        _require_positive_int("expected story revision", expected_story_revision)
        with self._session_factory() as session:
            try:
                _begin_immediate(session)
                story = session.get(InterviewStory, story_id)
                if story is None:
                    raise StoryNotFoundError("story is missing")
                if story.story_revision != expected_story_revision:
                    raise StoryConflictError("story revision is stale")
                if story.status == desired_status:
                    session.commit()
                    return self._story_payload(session, story)
                story.status = desired_status
                story.archived_at = datetime.now(timezone.utc) if desired_status == "archived" else None
                story.story_revision += 1
                story.updated_at = datetime.now(timezone.utc)
                session.commit()
                return self._story_payload(session, story)
            except Exception:
                session.rollback()
                raise

    def _replay_manual_save(
        self,
        session: Session,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise StoryValidationError("idempotency key is invalid")
        existing = session.scalar(
            select(InterviewStoryProposalAttempt).where(
                InterviewStoryProposalAttempt.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            return None
        payload = _attempt_input_payload(existing)
        if (
            payload.get("operation") != "manual_save"
            or payload.get("request_fingerprint") != request_fingerprint
            or existing.attempt_status != "confirmed"
            or existing.confirmed_story_id is None
            or existing.confirmed_story_version_id is None
        ):
            raise StoryConflictError("story idempotency input changed")
        story = session.get(InterviewStory, existing.confirmed_story_id)
        version = session.get(InterviewStoryVersion, existing.confirmed_story_version_id)
        if story is None or version is None or version.story_id != story.id:
            raise StoryConflictError("manual story replay is unavailable")
        return self._story_payload(session, story, version=version)

    @staticmethod
    def _record_manual_save(
        session: Session,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        story: InterviewStory,
        version: InterviewStoryVersion,
        snapshot: StorySourceSnapshot,
    ) -> None:
        payload = {"operation": "manual_save", "request_fingerprint": request_fingerprint}
        payload_json = canonical_json(payload)
        session.add(
            InterviewStoryProposalAttempt(
                target_story_id=story.id,
                idempotency_key=idempotency_key,
                entrypoint="ui",
                entry_context_json=canonical_json({"operation": "manual_save"}),
                attempt_status="confirmed",
                generation_revision=1,
                provider_call_token="",
                provider_lease_until=None,
                input_snapshot_json=payload_json,
                source_fingerprint=snapshot.source_fingerprint,
                proposal_json=canonical_json({"proposal_status": "manual"}),
                proposal_hash=sha256_text(canonical_json({"proposal_status": "manual"})),
                failure_category="",
                confirmation_token_hash=sha256_text(idempotency_key),
                confirmation_payload_hash=sha256_text(payload_json),
                confirmed_story_id=story.id,
                confirmed_story_version_id=version.id,
                confirmed_at=datetime.now(timezone.utc),
            )
        )

    @staticmethod
    def _require_active_story(session: Session, story_id: int) -> InterviewStory:
        story = session.get(InterviewStory, story_id)
        if story is None:
            raise StoryNotFoundError("story is missing")
        if story.status != "active":
            raise StoryConflictError("story is archived")
        return story

    @staticmethod
    def _check_story_cas(
        story: InterviewStory,
        expected_current_version_id: int | None,
        expected_story_revision: int | None,
    ) -> None:
        if (
            story.current_version_id != expected_current_version_id
            or story.story_revision != expected_story_revision
        ):
            raise StoryConflictError("story version is stale")

    @staticmethod
    def _insert_version(
        session: Session,
        *,
        story: InterviewStory,
        version_number: int,
        canonical: dict[str, Any],
        snapshot: StorySourceSnapshot,
        canonical_links: list[CanonicalStoryLink],
        assertions: list[str],
        origin_kind: str,
    ) -> InterviewStoryVersion:
        content_json = canonical_json(canonical)
        version = InterviewStoryVersion(
            story_id=story.id,
            version_number=version_number,
            content_json=content_json,
            content_hash=sha256_text(content_json),
            source_fingerprint=snapshot.source_fingerprint,
            origin_kind=origin_kind,
        )
        session.add(version)
        session.flush()
        assertion_ids: dict[str, str] = {}
        for index, statement in enumerate(assertions, 1):
            assertion = InterviewStoryUserAssertion(
                story_version_id=version.id,
                statement_text=statement,
                statement_hash=sha256_text(statement),
            )
            session.add(assertion)
            session.flush()
            assertion_ids[f"assertion_{index:03d}"] = str(assertion.id)
        for link in canonical_links:
            source_stable_id = assertion_ids.get(link.source_stable_id, link.source_stable_id)
            payload = link.as_dict() | {"source_stable_id": source_stable_id}
            # The link's persisted identity, including an assertion's real ID, is
            # what auditors later hash; never retain the temporary request ID.
            payload["link_hash"] = sha256_text(canonical_json({key: value for key, value in payload.items() if key != "link_hash"}))
            session.add(
                InterviewStoryVersionEvidenceLink(
                    story_version_id=version.id,
                    **payload,
                )
            )
        session.flush()
        return version

    def _story_summary(self, session: Session, story: InterviewStory) -> dict[str, Any]:
        version = session.get(InterviewStoryVersion, story.current_version_id) if story.current_version_id else None
        return {
            "id": story.id,
            "title": story.title,
            "status": story.status,
            "current_version_id": story.current_version_id,
            "story_revision": story.story_revision,
            "version_number": version.version_number if version else None,
            "source_states": derive_story_source_states(session, version) if version else [],
        }

    def _story_payload(
        self,
        session: Session,
        story: InterviewStory,
        *,
        version: InterviewStoryVersion | None = None,
    ) -> dict[str, Any]:
        payload = self._story_summary(session, story)
        if version is None:
            version = session.get(InterviewStoryVersion, story.current_version_id) if story.current_version_id else None
        payload["version"] = self._version_payload(session, version) if version else None
        return payload

    @staticmethod
    def _version_payload(session: Session, version: InterviewStoryVersion) -> dict[str, Any]:
        links = list(
            session.scalars(
                select(InterviewStoryVersionEvidenceLink)
                .where(InterviewStoryVersionEvidenceLink.story_version_id == version.id)
                .order_by(InterviewStoryVersionEvidenceLink.id.asc())
            )
        )
        assertions = list(
            session.scalars(
                select(InterviewStoryUserAssertion)
                .where(InterviewStoryUserAssertion.story_version_id == version.id)
                .order_by(InterviewStoryUserAssertion.id.asc())
            )
        )
        return {
            "id": version.id,
            "story_id": version.story_id,
            "version_number": version.version_number,
            "content": json.loads(version.content_json),
            "content_hash": version.content_hash,
            "source_fingerprint": version.source_fingerprint,
            "origin_kind": version.origin_kind,
            "evidence_links": [
                {
                    "target_kind": link.target_kind,
                    "target_id": link.target_id,
                    "source_kind": link.source_kind,
                    "source_stable_id": link.source_stable_id,
                    "source_version_or_snapshot": link.source_version_or_snapshot,
                    "source_path": link.source_path,
                    "text_location": link.text_location,
                    "excerpt": link.excerpt,
                    "source_fingerprint": link.source_fingerprint,
                    "link_hash": link.link_hash,
                }
                for link in links
            ],
            "assertions": [
                {"id": assertion.id, "statement": assertion.statement_text, "frozen": True}
                for assertion in assertions
            ],
            "source_states": derive_story_source_states(session, version),
        }


def _begin_immediate(session: Session) -> None:
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _require_positive_int(name: str, value: int | None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StoryValidationError(f"{name} is invalid")


def _require_exact_null(name: str, value: object) -> None:
    if value is not None:
        raise StoryValidationError(f"{name} must be null")


def _canonical_selections(selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item) for item in selections],
        key=lambda item: (str(item.get("source_kind")), str(item.get("source_id")), str(item.get("path"))),
    )


def _manual_content_from_canonical(content: dict[str, Any]) -> dict[str, Any]:
    title = content.get("title")
    blocks = content.get("blocks")
    labels = content.get("capability_labels")
    questions = content.get("applicable_questions")
    gaps = content.get("fact_gap_codes")
    if not isinstance(title, dict) or not isinstance(blocks, list) or not isinstance(labels, list) or not isinstance(questions, list) or not isinstance(gaps, list):
        raise StoryValidationError("story proposal is invalid")
    return {
        "title": title.get("text"),
        "blocks": [
            {key: block.get(key) for key in ("kind", "text", "fact_mode")}
            for block in blocks
            if isinstance(block, dict)
        ],
        "capability_labels": [item.get("text") for item in labels if isinstance(item, dict)],
        "applicable_questions": [item.get("text") for item in questions if isinstance(item, dict)],
        "fact_gap_codes": gaps,
    }


def _client_link_fields(link: Any) -> dict[str, Any]:
    if not isinstance(link, dict):
        raise StoryValidationError("story evidence link is invalid")
    allowed = {
        "target_kind",
        "target_id",
        "source_kind",
        "source_stable_id",
        "source_version_or_snapshot",
        "source_path",
        "excerpt",
        "text_location",
    }
    return {key: value for key, value in link.items() if key in allowed}


def _attempt_input_payload(attempt: InterviewStoryProposalAttempt) -> dict[str, Any]:
    try:
        parsed = json.loads(attempt.input_snapshot_json)
    except (TypeError, ValueError) as exc:
        raise StoryConflictError("story proposal snapshot is invalid") from exc
    if not isinstance(parsed, dict):
        raise StoryConflictError("story proposal snapshot is invalid")
    return parsed


def _snapshot_from_attempt(payload: dict[str, Any], fingerprint: str) -> StorySourceSnapshot:
    sources = payload.get("sources")
    if not isinstance(sources, list) or not all(isinstance(source, dict) for source in sources):
        raise StoryConflictError("story proposal snapshot is invalid")
    normalized = [dict(source) for source in sources]
    if not all(
        set(source) == {
            "source_kind",
            "source_stable_id",
            "source_version_or_snapshot",
            "path",
            "excerpt",
            "source_fingerprint",
        }
        and all(isinstance(value, str) for value in source.values())
        for source in normalized
    ):
        raise StoryConflictError("story proposal snapshot is invalid")
    return StorySourceSnapshot(sources=normalized, source_fingerprint=fingerprint)


def _attempt_payload(attempt: InterviewStoryProposalAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "target_story_id": attempt.target_story_id,
        "entrypoint": attempt.entrypoint,
        "attempt_status": attempt.attempt_status,
        "generation_revision": attempt.generation_revision,
        "source_fingerprint": attempt.source_fingerprint,
        "proposal": json.loads(attempt.proposal_json) if attempt.proposal_json else None,
        "failure_category": attempt.failure_category or None,
        "confirmed_story_id": attempt.confirmed_story_id,
        "confirmed_story_version_id": attempt.confirmed_story_version_id,
    }


def _now(now_factory: Any) -> datetime:
    value = now_factory() if now_factory is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise StoryValidationError("clock is invalid")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _as_naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _lease_is_live(value: datetime | None, now: datetime) -> bool:
    aware = _as_aware_utc(value)
    return aware is not None and aware > now


def _owned_attempt(
    attempt: InterviewStoryProposalAttempt | None,
    generation_revision: int,
    provider_call_token: str,
) -> bool:
    return bool(
        attempt is not None
        and attempt.attempt_status == "generating"
        and attempt.generation_revision == generation_revision
        and attempt.provider_call_token == provider_call_token
    )


class _StoryLeaseHeartbeat:
    """Best-effort lease renewal using a new short Session for each tick."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        attempt_id: int,
        generation_revision: int,
        provider_call_token: str,
        now_factory: Callable[[], datetime] | None,
        waiter: threading.Event | None,
    ) -> None:
        self._session_factory = session_factory
        self._attempt_id = attempt_id
        self._generation_revision = generation_revision
        self._provider_call_token = provider_call_token
        self._now_factory = now_factory
        self._stop = waiter or threading.Event()
        self._thread = threading.Thread(target=self._run, name="interview-story-lease", daemon=True)
        self.heartbeat_count = 0
        self.confirmed_ownership_lost = False
        self.heartbeat_uncertain = False

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        if self._thread.is_alive():
            raise RuntimeError("interview story lease heartbeat did not stop")

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def tick(self) -> bool:
        """Renew once; lock errors remain uncertain rather than proving takeover."""

        for _attempt in range(2):
            try:
                with self._session_factory() as session:
                    now = _now(self._now_factory)
                    result = session.execute(
                        update(InterviewStoryProposalAttempt)
                        .where(InterviewStoryProposalAttempt.id == self._attempt_id)
                        .where(InterviewStoryProposalAttempt.attempt_status == "generating")
                        .where(InterviewStoryProposalAttempt.generation_revision == self._generation_revision)
                        .where(InterviewStoryProposalAttempt.provider_call_token == self._provider_call_token)
                        .values(provider_lease_until=_as_naive_utc(now + timedelta(seconds=_STORY_LEASE_SECONDS)))
                    )
                    session.commit()
                    if int(getattr(result, "rowcount", 0) or 0) == 0:
                        self.confirmed_ownership_lost = True
                        return False
                    self.heartbeat_count += 1
                    return True
            except SQLAlchemyError:
                continue
        self.heartbeat_uncertain = True
        return False

    def _run(self) -> None:
        while not self._stop.wait(_STORY_HEARTBEAT_SECONDS):
            if not self.tick():
                return
