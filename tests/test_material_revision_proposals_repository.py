from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from offerpilot.ai.types import Assistant
from offerpilot.db import init_database
from offerpilot.models import ApplicationEvent, ApplicationMaterialKit, Resume
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.material_kits import MaterialKitCreate, MaterialKitsRepository
from offerpilot.repositories.material_revision_proposals import (
    MaterialProposalConflictError,
    MaterialProposalValidationError,
    MaterialRevisionProposalsRepository,
)
from offerpilot.repositories.resumes import ResumeCreate, ResumesRepository


class ProposalModel:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return Assistant(
            content=json.dumps(
                {
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
                                }
                            ],
                        },
                        {
                            "id": "change-assertion",
                            "path": "/raw_text",
                            "before": "Built APIs",
                            "after": "Built APIs; I led the migration.",
                            "rationale": "Include the user's explicit assertion.",
                            "evidence_refs": [
                                {
                                    "source": "user_assertion",
                                    "path": "/user_assertions/0/text",
                                    "excerpt": "I led the migration.",
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )


def _ready(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(session_factory)
    resumes = ResumesRepository(session_factory)
    kits = MaterialKitsRepository(session_factory)
    app = applications.create(ApplicationCreate(company_name="Acme", position_name="Backend"))
    resume = resumes.create(
        ResumeCreate(
            title="Backend Resume",
            parsed_data="Built APIs",
            content_json={
                "experience": [{"highlights": ["Built APIs"]}],
                "raw_text": "Built APIs",
            },
        )
    )
    kit = kits.create(
        MaterialKitCreate(
            application_id=app.id,
            resume_id=resume.id,
            jd_snapshot="FastAPI backend",
            content_json=json.dumps({"requirements": ["FastAPI"]}),
        )
    )
    return session_factory, app, resume, kit


def test_repository_generates_and_accepts_one_child_resume_transactionally(tmp_path) -> None:
    session_factory, app, resume, kit = _ready(tmp_path)
    repository = MaterialRevisionProposalsRepository(session_factory)

    proposal = repository.create_generated(
        app.id,
        "Highlight backend API experience",
        ["I led the migration."],
        ProposalModel(),
    )
    assert proposal.status == "draft"
    assert json.loads(proposal.source_snapshot_json)["resume"]["id"] == resume.id

    accepted, child, created = repository.accept(
        app.id,
        proposal.id,
        proposal.proposal_sha256,
        ["change-fastapi"],
    )

    assert created is True
    assert accepted.status == "accepted"
    assert child.parent_resume_id == resume.id
    assert child.is_master is False
    assert child.title == "Backend Resume · Acme Backend"
    assert json.loads(child.content_json)["experience"][0]["highlights"] == [
        "Built FastAPI APIs for internal workflow automation"
    ]
    with session_factory() as session:
        kit_row = session.get(ApplicationMaterialKit, kit.id)
        source_row = session.get(Resume, resume.id)
        events = list(session.scalars(select(ApplicationEvent)))
    assert kit_row is not None and kit_row.resume_id == child.id
    assert source_row is not None and json.loads(source_row.content_json)["raw_text"] == "Built APIs"
    assert [(event.subtype, event.tags) for event in events] == [
        ("material_proposal_accepted", ["material_proposal", f"proposal:{proposal.id}", f"resume:{child.id}"])
    ]


def test_repository_accepts_empty_selection_only_as_validation_error_and_replays_accept(tmp_path) -> None:
    session_factory, app, _resume, _kit = _ready(tmp_path)
    repository = MaterialRevisionProposalsRepository(session_factory)
    proposal = repository.create_generated(app.id, "", ["I led the migration."], ProposalModel())

    with pytest.raises(MaterialProposalValidationError):
        repository.accept(app.id, proposal.id, proposal.proposal_sha256, [])

    accepted, child, created = repository.accept(
        app.id, proposal.id, proposal.proposal_sha256, ["change-fastapi"]
    )
    replayed, same_child, replay_created = repository.accept(
        app.id, proposal.id, "stale", ["change-assertion"]
    )

    assert created is True
    assert replay_created is False
    assert replayed.id == accepted.id
    assert same_child.id == child.id


def test_repository_source_drift_has_no_partial_writes(tmp_path) -> None:
    session_factory, app, resume, _kit = _ready(tmp_path)
    repository = MaterialRevisionProposalsRepository(session_factory)
    proposal = repository.create_generated(app.id, "", ["I led the migration."], ProposalModel())
    ResumesRepository(session_factory).update(resume.id, {"title": "Changed"})

    with pytest.raises(MaterialProposalConflictError):
        repository.accept(app.id, proposal.id, proposal.proposal_sha256, ["change-fastapi"])

    with session_factory() as session:
        assert session.scalar(select(Resume).where(Resume.parent_resume_id == resume.id)) is None
        assert list(session.scalars(select(ApplicationEvent))) == []


def test_repository_reject_is_idempotent_but_accept_after_reject_conflicts(tmp_path) -> None:
    session_factory, app, _resume, _kit = _ready(tmp_path)
    repository = MaterialRevisionProposalsRepository(session_factory)
    proposal = repository.create_generated(app.id, "", ["I led the migration."], ProposalModel())

    rejected = repository.reject(app.id, proposal.id)
    replayed = repository.reject(app.id, proposal.id)

    assert rejected.id == replayed.id
    assert rejected.status == "rejected"
    with pytest.raises(MaterialProposalConflictError):
        repository.accept(app.id, proposal.id, proposal.proposal_sha256, ["change-fastapi"])
