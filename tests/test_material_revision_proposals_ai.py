from __future__ import annotations

import json

import pytest

from offerpilot.ai.material_proposals import (
    MaterialProposalModelError,
    validate_material_proposal,
)
from offerpilot.ai.workflows import parse_json_reply


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "application": {"id": 7, "company_name": "Acme", "position_name": "Backend"},
        "material_kit": {"id": 3, "jd_snapshot": "FastAPI backend", "content_json": {}},
        "resume": {
            "id": 11,
            "title": "Backend Resume",
            "parsed_data": "Built APIs",
            "content_json": {
                "experience": [{"company": "Acme Labs", "highlights": ["Built APIs", "Reviewed code"]}],
                "skills": ["Python"],
                "raw_text": "Built APIs",
            },
        },
        "latest_evidence_bundle": None,
        "user_assertions": [{"id": "assertion-1", "text": "I led the migration."}],
    }


def _payload() -> dict[str, object]:
    return {
        "summary": "Tailor the backend experience.",
        "changes": [
            {
                "id": "change-fastapi",
                "path": "/experience/0/highlights/0",
                "before": "Built APIs",
                "after": "Built FastAPI APIs for internal workflow automation",
                "rationale": "Make the existing API experience specific.",
                "evidence_refs": [
                    {
                        "source": "resume",
                        "path": "/experience/0/highlights/0",
                        "excerpt": "Built APIs",
                    },
                    {
                        "source": "resume",
                        "path": "/experience/0/company",
                        "excerpt": "Acme Labs",
                    }
                ],
            }
        ],
    }


def test_validator_derives_content_from_only_cited_resume_changes() -> None:
    validated = validate_material_proposal(_payload(), _snapshot())

    assert validated.proposal["summary"] == "Tailor the backend experience."
    assert validated.content["experience"][0]["highlights"][0] == (
        "Built FastAPI APIs for internal workflow automation"
    )
    assert validated.content["experience"][0]["highlights"][1] == "Reviewed code"


@pytest.mark.parametrize(
    "change_patch",
    [
        {"path": "/experience/0/company"},
        {"path": "/experience/0/highlights/-"},
        {"path": "/experience/00/highlights/0"},
        {"path": "/experience/١/highlights/0"},
        {"path": "/experience/0/highlights/0", "before": "Other"},
        {"path": "/experience/0/highlights/0", "evidence_refs": []},
    ],
)
def test_validator_rejects_unauthorized_or_unverifiable_changes(change_patch: dict[str, object]) -> None:
    payload = _payload()
    change = dict(payload["changes"][0])  # type: ignore[index]
    change.update(change_patch)
    payload["changes"] = [change]

    with pytest.raises(MaterialProposalModelError):
        validate_material_proposal(payload, _snapshot())


def test_validator_rejects_duplicate_ids_and_overlapping_paths() -> None:
    payload = _payload()
    second = dict(payload["changes"][0])  # type: ignore[index]
    second["id"] = "change-second"
    second["path"] = "/experience/0/highlights/0"
    payload["changes"] = [payload["changes"][0], second]  # type: ignore[list-item]

    with pytest.raises(MaterialProposalModelError):
        validate_material_proposal(payload, _snapshot())


def test_validator_accepts_empty_changes_without_inventing_content() -> None:
    validated = validate_material_proposal({"summary": "No safe changes.", "changes": []}, _snapshot())

    assert validated.content == _snapshot()["resume"]["content_json"]  # type: ignore[index]


def test_validator_rejects_non_object_model_output() -> None:
    with pytest.raises(MaterialProposalModelError):
        validate_material_proposal(json.loads("[]"), _snapshot())


@pytest.mark.parametrize(
    "path",
    ["/jd/text", "/application/company_name", "/application/position_name"],
)
def test_validator_rejects_jd_and_application_evidence_bundle_paths(path: str) -> None:
    snapshot = _snapshot()
    snapshot["latest_evidence_bundle"] = {
        "id": 4,
        "bundle_sha256": "bundle",
        "snapshot": {
            "jd": {"text": "FastAPI backend"},
            "application": {"company_name": "Acme", "position_name": "Backend"},
        },
    }
    payload = _payload()
    change = dict(payload["changes"][0])  # type: ignore[index]
    change["evidence_refs"] = [{"source": "evidence_bundle", "path": path, "excerpt": "Acme"}]
    if path == "/jd/text":
        change["evidence_refs"][0]["excerpt"] = "FastAPI backend"  # type: ignore[index]
    payload["changes"] = [change]

    with pytest.raises(MaterialProposalModelError):
        validate_material_proposal(payload, snapshot)


def test_validator_rejects_empty_evidence_excerpt() -> None:
    snapshot = _snapshot()
    snapshot["resume"]["content_json"]["skills"] = [""]  # type: ignore[index]
    payload = {
        "summary": "Fill a missing skill.",
        "changes": [
            {
                "id": "change-empty-skill",
                "path": "/skills/0",
                "before": "",
                "after": "Kubernetes",
                "rationale": "Use only an explicit candidate fact.",
                "evidence_refs": [
                    {"source": "resume", "path": "/skills/0", "excerpt": ""}
                ],
            }
        ],
    }

    with pytest.raises(MaterialProposalModelError):
        validate_material_proposal(payload, snapshot)


def test_strict_json_parser_rejects_fenced_markdown() -> None:
    with pytest.raises(RuntimeError):
        parse_json_reply("```json\n{}\n```", allow_fenced=False)


def test_general_json_parser_preserves_legacy_fenced_json_support() -> None:
    assert parse_json_reply("```json\n{}\n```") == {}
