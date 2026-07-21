from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from offerpilot.ai.types import Assistant
from offerpilot.db import init_database
from offerpilot.models import OpportunityFitReview
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.opportunity_fit_reviews import (
    OpportunityFitReviewNotFound,
    OpportunityFitReviewsRepository,
)
from offerpilot.repositories.resumes import ResumeCreate, ResumesRepository


def _triage() -> dict[str, object]:
    return {
        "recommendation": "hold",
        "hard_constraints": [
            {
                "id": "location",
                "requirement": "Shanghai office",
                "status": "unknown",
                "explanation": "Availability is not in the resume.",
                "evidence_refs": [
                    {"source": "jd", "path": "/text", "excerpt": "Kubernetes preferred"}
                ],
            }
        ],
        "fit_signals": [
            {
                "id": "api",
                "statement": "Existing API work is relevant.",
                "evidence_refs": [
                    {"source": "resume", "path": "/raw_text", "excerpt": "Built APIs"}
                ],
            }
        ],
        "gaps": [
            {
                "id": "kubernetes",
                "requirement": "Kubernetes production experience",
                "kind": "preferred",
                "candidate_status": "unknown",
                "evidence_refs": [
                    {"source": "jd", "path": "/text", "excerpt": "Kubernetes preferred"},
                    {"source": "resume", "path": "/raw_text", "excerpt": "Built APIs"}
                ],
            }
        ],
        "deadline": {"status": "not_stated", "text": "", "evidence_refs": []},
        "next_questions": ["Can you work in Shanghai?"],
    }


def _deep() -> dict[str, object]:
    return {
        "strengths": [
            {
                "id": "api",
                "statement": "API implementation is a strength.",
                "evidence_refs": [
                    {"source": "resume", "path": "/raw_text", "excerpt": "Built APIs"}
                ],
            }
        ],
        "gaps_to_address": [
            {
                "id": "kubernetes",
                "statement": "Kubernetes experience needs confirmation.",
                "evidence_refs": [
                    {"source": "resume", "path": "/raw_text", "excerpt": "Built APIs"}
                ],
            }
        ],
        "questions_to_clarify": [
            {"id": "location", "statement": "Confirm Shanghai availability.", "evidence_refs": []}
        ],
        "recommended_path": "clarify_first",
        "next_actions": [
            {"id": "assertion", "label": "补充事实", "kind": "add_assertion"}
        ],
    }


class ReviewModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        payload = _triage() if self.calls % 2 == 1 else _deep()
        return Assistant(content=json.dumps(payload, ensure_ascii=False))


def _ready(tmp_path):
    factory = init_database(tmp_path / "data.db")
    applications = ApplicationsRepository(factory)
    resumes = ResumesRepository(factory)
    application = applications.create(
        ApplicationCreate(company_name="Acme", position_name="Backend", notes="private note")
    )
    resume = resumes.create(
        ResumeCreate(
            title="Backend Resume",
            parsed_data="Built APIs",
            content_json={"raw_text": "Built APIs", "skills": ["Python"]},
        )
    )
    return factory, application, resume


def test_create_triage_persists_minimal_immutable_snapshot_and_is_idempotent(tmp_path) -> None:
    factory, application, resume = _ready(tmp_path)
    repository = OpportunityFitReviewsRepository(factory)
    model = ReviewModel()

    review, created = repository.create_triage(
        application.id,
        resume.id,
        "Kubernetes preferred",
        "Recruiter copy",
        ["I can work in Shanghai."],
        "d4b4b5e8-0a3a-4a3e-8e4d-6bc7a04d36b0",
        model,
    )

    assert created is True
    stored = json.loads(review.source_snapshot_json)
    assert stored["application"] == {
        "id": application.id,
        "company_name": "Acme",
        "position_name": "Backend",
    }
    assert stored["resume"]["content_json"]["raw_text"] == "Built APIs"
    assert stored["candidate_assertions"] == [{"index": 0, "text": "I can work in Shanghai."}]
    assert "notes" not in stored["application"]

    replay, replay_created = repository.create_triage(
        application.id,
        resume.id,
        "different JD",
        "different source",
        [],
        "d4b4b5e8-0a3a-4a3e-8e4d-6bc7a04d36b0",
        model,
    )
    assert replay_created is False
    assert replay.id == review.id
    assert model.calls == 1


def test_create_triage_does_not_leave_record_when_application_deleted_during_model_call(tmp_path) -> None:
    factory, application, resume = _ready(tmp_path)
    repository = OpportunityFitReviewsRepository(factory)

    class DeletesApplicationModel(ReviewModel):
        def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            ApplicationsRepository(factory).delete(application.id)
            return super().complete(messages, tools)

    with pytest.raises(OpportunityFitReviewNotFound):
        repository.create_triage(
            application.id,
            resume.id,
            "Kubernetes preferred",
            "copy",
            [],
            "26b4dd35-75e6-4d3f-8806-3cb7bc9f3e2e",
            DeletesApplicationModel(),
        )

    with factory() as session:
        assert list(session.scalars(select(OpportunityFitReview))) == []


def test_deep_review_reads_saved_snapshot_and_is_idempotent(tmp_path) -> None:
    factory, application, resume = _ready(tmp_path)
    repository = OpportunityFitReviewsRepository(factory)
    model = ReviewModel()
    review, _created = repository.create_triage(
        application.id,
        resume.id,
        "Kubernetes preferred",
        "copy",
        [],
        "1b9f9d39-dfbd-464e-8bb0-4a50b09b5e5c",
        model,
    )

    first, created = repository.create_deep_review(application.id, review.id, model)
    replay, replay_created = repository.create_deep_review(application.id, review.id, model)

    assert created is True
    assert replay_created is False
    assert first.id == replay.id == review.id
    assert json.loads(first.deep_review_json or "{}")["recommended_path"] == "clarify_first"
    assert model.calls == 2


def test_hidden_application_and_resume_are_not_readable(tmp_path) -> None:
    factory, application, resume = _ready(tmp_path)
    repository = OpportunityFitReviewsRepository(factory)
    ApplicationsRepository(factory).delete(application.id)

    with pytest.raises(OpportunityFitReviewNotFound):
        repository.create_triage(application.id, resume.id, "JD", "copy", [], "f6f71c9f-6e8d-4c9f-9d5f-1cc3d9687382", ReviewModel())
