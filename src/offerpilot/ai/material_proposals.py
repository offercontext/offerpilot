from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.workflows import complete_json

ALLOWED_PATH_PREFIXES = (
    ("career_intent", "target_roles"),
    ("experience",),
    ("projects",),
    ("skills",),
    ("raw_text",),
)
EVIDENCE_SOURCES = {"resume", "evidence_bundle", "user_assertion"}


class MaterialProposalModelError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedProposal:
    proposal: dict[str, Any]
    content: dict[str, Any]


def validate_material_proposal(
    payload: dict[str, Any], source_snapshot: dict[str, Any]
) -> ValidatedProposal:
    if not isinstance(payload, dict):
        raise MaterialProposalModelError("model output must be a JSON object")
    summary = payload.get("summary")
    changes = payload.get("changes")
    if not isinstance(summary, str) or not summary.strip():
        raise MaterialProposalModelError("summary must be a non-empty string")
    if not isinstance(changes, list):
        raise MaterialProposalModelError("changes must be an array")

    resume = source_snapshot.get("resume")
    if not isinstance(resume, dict) or not isinstance(resume.get("content_json"), dict):
        raise MaterialProposalModelError("source resume content is unavailable")
    content = copy.deepcopy(resume["content_json"])
    normalized_changes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: list[tuple[str, ...]] = []
    for raw_change in changes:
        if not isinstance(raw_change, dict):
            raise MaterialProposalModelError("each change must be an object")
        change_id = raw_change.get("id")
        path = raw_change.get("path")
        before = raw_change.get("before")
        after = raw_change.get("after")
        rationale = raw_change.get("rationale")
        refs = raw_change.get("evidence_refs")
        if (
            not isinstance(change_id, str)
            or not isinstance(path, str)
            or not isinstance(before, str)
            or not isinstance(after, str)
            or not isinstance(rationale, str)
        ):
            raise MaterialProposalModelError("change fields must be strings")
        if not change_id or change_id in seen_ids:
            raise MaterialProposalModelError("change ids must be non-empty and unique")
        if not after.strip():
            raise MaterialProposalModelError("change after must be non-empty")
        pointer = _parse_allowed_pointer(path)
        if pointer in seen_paths or any(_overlaps(pointer, other) for other in seen_paths):
            raise MaterialProposalModelError("change paths must not overlap")
        current = _get_pointer(resume["content_json"], pointer)
        if not isinstance(current, str) or current != before:
            raise MaterialProposalModelError("change before does not match the frozen resume")
        if not isinstance(refs, list) or not refs:
            raise MaterialProposalModelError("each change needs evidence_refs")
        for ref in refs:
            _validate_evidence_ref(ref, source_snapshot, pointer)
        _set_pointer(content, pointer, after)
        seen_ids.add(change_id)
        seen_paths.append(pointer)
        normalized_changes.append(
            {
                "id": change_id,
                "path": path,
                "before": before,
                "after": after,
                "rationale": rationale,
                "evidence_refs": [dict(ref) for ref in refs],
            }
        )

    return ValidatedProposal(
        proposal={"summary": summary.strip(), "changes": normalized_changes},
        content=content,
    )


def generate_material_proposal(
    model: ChatModel,
    source_snapshot: dict[str, Any],
    instructions: str,
) -> ValidatedProposal:
    try:
        result = complete_json(
            model,
            system=_material_proposal_system(),
            user=_material_proposal_prompt(source_snapshot, instructions),
        )
        return validate_material_proposal(result, source_snapshot)
    except MaterialProposalModelError:
        raise
    except Exception as exc:
        raise MaterialProposalModelError("model output could not be parsed") from exc


def _parse_allowed_pointer(path: str) -> tuple[str, ...]:
    if not path.startswith("/") or path == "/":
        raise MaterialProposalModelError("path is not allowed")
    parts = tuple(_decode_pointer_part(part) for part in path[1:].split("/"))
    if parts == ("raw_text",):
        return parts
    if len(parts) == 3 and parts[0] in {"experience", "projects"} and _is_canonical_index(parts[1]):
        if parts[2] != "highlights":
            raise MaterialProposalModelError("path is not allowed")
        raise MaterialProposalModelError("highlight index is required")
    if len(parts) == 4 and parts[0] in {"experience", "projects"}:
        if parts[2] != "highlights" or not _is_canonical_index(parts[1]) or not _is_canonical_index(parts[3]):
            raise MaterialProposalModelError("path is not allowed")
        return parts
    if len(parts) == 3 and parts[:2] == ("career_intent", "target_roles"):
        if not _is_canonical_index(parts[2]):
            raise MaterialProposalModelError("path is not allowed")
        return parts
    if len(parts) == 2 and parts[0] == "skills" and _is_canonical_index(parts[1]):
        return parts
    raise MaterialProposalModelError("path is not allowed")


def _decode_pointer_part(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "~":
            result.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
            raise MaterialProposalModelError("path contains an invalid escape")
        result.append("~" if value[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def _is_canonical_index(value: str) -> bool:
    return value == "0" or (
        bool(value)
        and value[0] != "0"
        and all("0" <= character <= "9" for character in value)
    )


def _overlaps(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return left[: len(right)] == right or right[: len(left)] == left


def _get_pointer(root: Any, pointer: tuple[str, ...]) -> Any:
    value = root
    for part in pointer:
        if isinstance(value, dict):
            if part not in value:
                raise MaterialProposalModelError("path does not exist")
            value = value[part]
        elif isinstance(value, list) and _is_canonical_index(part):
            index = int(part)
            if index >= len(value):
                raise MaterialProposalModelError("path does not exist")
            value = value[index]
        else:
            raise MaterialProposalModelError("path does not exist")
    return value


def _set_pointer(root: Any, pointer: tuple[str, ...], value: str) -> None:
    parent = _get_pointer(root, pointer[:-1])
    key = pointer[-1]
    if isinstance(parent, dict) and key in parent:
        parent[key] = value
    elif isinstance(parent, list) and _is_canonical_index(key) and int(key) < len(parent):
        parent[int(key)] = value
    else:
        raise MaterialProposalModelError("path does not exist")


def _validate_evidence_ref(ref: Any, snapshot: dict[str, Any], change_pointer: tuple[str, ...]) -> None:
    if not isinstance(ref, dict):
        raise MaterialProposalModelError("evidence reference must be an object")
    source = ref.get("source")
    path = ref.get("path")
    excerpt = ref.get("excerpt")
    if source not in EVIDENCE_SOURCES or not isinstance(path, str) or not isinstance(excerpt, str):
        raise MaterialProposalModelError("evidence reference is invalid")
    if source == "resume":
        pointer = _parse_pointer(path)
        value = _get_pointer(snapshot["resume"]["content_json"], pointer)
    elif source == "user_assertion":
        pointer = _parse_assertion_pointer(path)
        value = _get_pointer(snapshot, pointer)
    else:
        bundle = snapshot.get("latest_evidence_bundle")
        if not isinstance(bundle, dict) or not isinstance(bundle.get("snapshot"), dict):
            raise MaterialProposalModelError("evidence bundle reference is unavailable")
        value = _get_pointer(bundle["snapshot"], _parse_pointer(path))
    if not isinstance(value, str) or value != excerpt:
        raise MaterialProposalModelError("evidence excerpt does not match the cited source")


def _parse_assertion_pointer(path: str) -> tuple[str, ...]:
    if not path.startswith("/user_assertions/"):
        raise MaterialProposalModelError("user assertion path is not allowed")
    parts = _parse_pointer(path)
    if len(parts) != 3 or parts[0] != "user_assertions" or not _is_canonical_index(parts[1]) or parts[2] != "text":
        raise MaterialProposalModelError("user assertion path is not allowed")
    return parts


def _parse_pointer(path: str) -> tuple[str, ...]:
    if not path.startswith("/") or path == "/":
        raise MaterialProposalModelError("evidence path is not allowed")
    return tuple(_decode_pointer_part(part) for part in path[1:].split("/"))


def _material_proposal_system() -> str:
    return (
        "You are an evidence-gated resume editor. Return only a JSON object with "
        "summary and changes. Every change must cite an exact internal source excerpt. "
        "The JD is only a rewrite direction, never a candidate-fact source. Do not invent "
        "numbers, dates, employers, roles, technologies, responsibilities, or outcomes. "
        "User assertions are explicitly supplied but are not platform-verified facts."
    )


def _material_proposal_prompt(source_snapshot: dict[str, Any], instructions: str) -> str:
    return (
        "Create a reviewable proposal from this frozen source snapshot. Empty changes are "
        "valid when no safe evidence-backed edit exists. Use only the allowed paths and "
        "the exact JSON shape described by the system message.\n"
        f"User instructions: {instructions.strip()}\n"
        f"Frozen source snapshot:\n{json.dumps(source_snapshot, ensure_ascii=False, sort_keys=True)}"
    )
