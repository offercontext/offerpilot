from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import OpportunityFitReview
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


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
                "requirement": "Kubernetes preferred",
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
        return Assistant(
            content=json.dumps(_triage() if self.calls == 1 else _deep(), ensure_ascii=False)
        )


def _ready(tmp_path, model=None):
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model or ReviewModel()))
    application = client.post(
        "/api/applications",
        json={"company_name": "Acme", "position_name": "Backend", "notes": "private note"},
    ).json()
    resume = client.post(
        "/api/resumes",
        json={
            "title": "Backend Resume",
            "text": "Built APIs",
            "content_json": {"raw_text": "Built APIs", "skills": ["Python"]},
        },
    ).json()
    return client, application, resume


def test_api_creates_lists_and_deep_reviews_without_snapshot_leak(tmp_path) -> None:
    client, application, resume = _ready(tmp_path)
    path = f"/api/applications/{application['id']}/opportunity-fit-reviews"
    payload = {
        "resume_id": resume["id"],
        "jd_text": "Kubernetes preferred",
        "jd_source_label": "Recruiter copy",
        "candidate_assertions": ["I can work in Shanghai."],
        "idempotency_key": "d4b4b5e8-0a3a-4a3e-8e4d-6bc7a04d36b0",
    }

    created = client.post(path, json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["triage"]["recommendation"] == "hold"
    assert body["summary"]["text"].startswith("Evidence-backed review recommendation:")
    assert body["summary"]["evidence_refs"]
    assert "source_snapshot_json" not in body
    assert body["source"]["candidate_assertions"][0]["text"] == "I can work in Shanghai."

    replay = client.post(path, json=payload)
    assert replay.status_code == 200
    assert replay.json()["id"] == body["id"]

    listed = client.get(path)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]
    assert listed.json()[0]["summary"]["evidence_refs"]

    detail = client.get(f"{path}/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["source"]["resume"]["title"] == "Backend Resume"
    assert detail.json()["source"]["jd"]["text"] == "Kubernetes preferred"

    deep = client.post(f"{path}/{body['id']}/deep-review")
    assert deep.status_code == 201
    assert deep.json()["deep_review"]["recommended_path"] == "clarify_first"

    deep_replay = client.post(f"{path}/{body['id']}/deep-review")
    assert deep_replay.status_code == 200
    assert deep_replay.json()["id"] == body["id"]


def test_api_validates_jd_resume_and_assertion_limits(tmp_path) -> None:
    client, application, resume = _ready(tmp_path)
    path = f"/api/applications/{application['id']}/opportunity-fit-reviews"
    base = {
        "resume_id": resume["id"],
        "jd_source_label": "copy",
        "candidate_assertions": [],
        "idempotency_key": "f6f71c9f-6e8d-4c9f-9d5f-1cc3d9687382",
    }

    assert client.post(path, json={**base, "jd_text": " "}).status_code == 422
    assert client.post(path, json={**base, "jd_text": "JD", "candidate_assertions": ["x"] * 11}).status_code == 422
    assert client.post(path, json={**base, "jd_text": "JD", "candidate_assertions": ["x" * 501]}).status_code == 422
    assert client.post(path, json={**base, "jd_text": "JD", "resume_id": 999}).status_code == 404


def test_api_returns_stable_502_without_record_for_unverifiable_model(tmp_path) -> None:
    class InvalidModel:
        def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            return Assistant(content=json.dumps({"summary": "bad", "extra": True}))

    client, application, resume = _ready(tmp_path, InvalidModel())
    response = client.post(
        f"/api/applications/{application['id']}/opportunity-fit-reviews",
        json={
            "resume_id": resume["id"],
            "jd_text": "JD",
            "jd_source_label": "copy",
            "candidate_assertions": [],
            "idempotency_key": "26b4dd35-75e6-4d3f-8806-3cb7bc9f3e2e",
        },
    )
    assert response.status_code == 502
    assert response.json() == {
        "error_code": "opportunity_fit_unverifiable",
        "error": "AI output could not be verified. Please retry.",
    }
    with session_factory_for_data_dir(tmp_path)() as session:
        assert list(session.scalars(select(OpportunityFitReview))) == []


def test_api_rederives_legacy_summary_without_frontend_crash(tmp_path) -> None:
    client, application, resume = _ready(tmp_path)
    path = f"/api/applications/{application['id']}/opportunity-fit-reviews"
    created = client.post(
        path,
        json={
            "resume_id": resume["id"],
            "jd_text": "Kubernetes preferred",
            "jd_source_label": "copy",
            "candidate_assertions": [],
            "idempotency_key": "26b4dd35-75e6-4d3f-8806-3cb7bc9f3e2e",
        },
    )
    assert created.status_code == 201
    review_id = created.json()["id"]
    with session_factory_for_data_dir(tmp_path)() as session:
        review = session.get(OpportunityFitReview, review_id)
        assert review is not None
        triage = json.loads(review.triage_json)
        triage["summary"] = {
            "text": "Unsupported candidate guarantee",
            "evidence_refs": [
                {"source": "resume", "path": "/invented", "excerpt": "forged"}
            ],
        }
        review.triage_json = json.dumps(triage)
        session.commit()

    detail = client.get(f"{path}/{review_id}")
    assert detail.status_code == 200
    assert detail.json()["summary"]["text"] != "Unsupported candidate guarantee"
    assert detail.json()["triage"]["summary"]["evidence_refs"]


def test_api_does_not_retry_provider_failure(tmp_path) -> None:
    class ProviderFailure:
        calls = 0

        def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise RuntimeError("provider unavailable")

    model = ProviderFailure()
    client, application, resume = _ready(tmp_path, model)
    response = client.post(
        f"/api/applications/{application['id']}/opportunity-fit-reviews",
        json={
            "resume_id": resume["id"],
            "jd_text": "JD",
            "jd_source_label": "copy",
            "candidate_assertions": [],
            "idempotency_key": "26b4dd35-75e6-4d3f-8806-3cb7bc9f3e2e",
        },
    )
    assert response.status_code == 502
    assert model.calls == 1


def test_api_hides_soft_deleted_application(tmp_path) -> None:
    client, application, resume = _ready(tmp_path)
    ApplicationsRepository(session_factory_for_data_dir(tmp_path)).delete(application["id"])

    path = f"/api/applications/{application['id']}/opportunity-fit-reviews"
    assert client.get(path).status_code == 404
    assert client.post(
        path,
        json={
            "resume_id": resume["id"],
            "jd_text": "JD",
            "jd_source_label": "copy",
            "candidate_assertions": [],
            "idempotency_key": "1b9f9d39-dfbd-464e-8bb0-4a50b09b5e5c",
        },
    ).status_code == 404


def test_api_rejects_non_human_application_source(tmp_path) -> None:
    client, _application, resume = _ready(tmp_path)
    applications = ApplicationsRepository(session_factory_for_data_dir(tmp_path))
    created = applications.create(
        ApplicationCreate(company_name="AI Created", position_name="Backend", source="ai")
    )
    path = f"/api/applications/{created.id}/opportunity-fit-reviews"
    response = client.post(
        path,
        json={
            "resume_id": resume["id"],
            "jd_text": "JD",
            "jd_source_label": "copy",
            "candidate_assertions": [],
            "idempotency_key": "1b9f9d39-dfbd-464e-8bb0-4a50b09b5e5c",
        },
    )
    assert response.status_code == 404
