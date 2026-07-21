from __future__ import annotations

import copy
import json

import pytest

from offerpilot.ai.opportunity_fit_reviews import (
    OpportunityFitModelError,
    generate_deep_review,
    generate_triage,
    validate_deep_review,
    validate_triage,
)
from offerpilot.ai.types import Assistant


def snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "application": {"id": 42, "company_name": "Acme", "position_name": "Backend Engineer"},
        "resume": {
            "id": 7,
            "title": "Backend Resume",
            "content_json": {
                "experience": [{"highlights": ["Built APIs", "Reviewed code"]}],
                "skills": ["Python"],
                "raw_text": "Built APIs. Reviewed code.",
            },
            "sha256": "resume-hash",
        },
        "jd": {
            "source_label": "Recruiter page copy",
            "text": "Must build reliable APIs. Kubernetes production experience preferred.",
            "sha256": "jd-hash",
        },
        "candidate_assertions": [
            {"index": 0, "text": "I can work full-time in Shanghai."},
        ],
    }


def triage_payload() -> dict[str, object]:
    return {
        "summary": "The role aligns with existing API work, but location needs confirmation.",
        "recommendation": "hold",
        "hard_constraints": [
            {
                "id": "location",
                "requirement": "Shanghai office",
                "status": "unknown",
                "explanation": "The JD mentions the location, but the materials do not establish availability.",
                "evidence_refs": [
                    {
                        "source": "jd",
                        "path": "/text",
                        "excerpt": "Must build reliable APIs. Kubernetes production experience preferred.",
                    }
                ],
            }
        ],
        "fit_signals": [
            {
                "id": "api",
                "statement": "Existing API implementation experience is directly relevant.",
                "evidence_refs": [
                    {
                        "source": "resume",
                        "path": "/experience/0/highlights/0",
                        "excerpt": "Built APIs",
                    }
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
                    {
                        "source": "jd",
                        "path": "/text",
                        "excerpt": "Must build reliable APIs. Kubernetes production experience preferred.",
                    },
                    {
                        "source": "resume",
                        "path": "/raw_text",
                        "excerpt": "Built APIs. Reviewed code.",
                    }
                ],
            }
        ],
        "deadline": {"status": "not_stated", "text": "", "evidence_refs": []},
        "next_questions": ["Can you accept working from the Shanghai office?"],
    }


def deep_review_payload() -> dict[str, object]:
    return {
        "strengths": [
            {
                "id": "api",
                "statement": "Existing API work is a relevant strength.",
                "evidence_refs": [
                    {
                        "source": "resume",
                        "path": "/experience/0/highlights/0",
                        "excerpt": "Built APIs",
                    }
                ],
            }
        ],
        "gaps_to_address": [
            {
                "id": "kubernetes",
                "statement": "Kubernetes production experience remains unconfirmed.",
                "evidence_refs": [
                    {
                        "source": "resume",
                        "path": "/raw_text",
                        "excerpt": "Built APIs. Reviewed code.",
                    }
                ],
            }
        ],
        "questions_to_clarify": [
            {
                "id": "location",
                "statement": "Confirm whether Shanghai office work is acceptable.",
                "evidence_refs": [],
            }
        ],
        "recommended_path": "clarify_first",
        "next_actions": [
            {
                "id": "assertion",
                "label": "补充事实",
                "kind": "add_assertion",
            }
        ],
    }


class ScriptedModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.prompts.append(messages[-1].content)
        response = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, str):
            return Assistant(content=response)
        return Assistant(content=json.dumps(response, ensure_ascii=False))


def test_valid_triage_is_strictly_validated() -> None:
    result = validate_triage(triage_payload(), snapshot())
    assert result.payload["recommendation"] == "hold"


def test_valid_deep_review_is_strictly_validated() -> None:
    result = validate_deep_review(deep_review_payload(), snapshot())
    assert result.payload["recommended_path"] == "clarify_first"


def test_deep_review_rejects_uncited_gap() -> None:
    payload = deep_review_payload()
    payload["gaps_to_address"][0]["evidence_refs"] = []
    with pytest.raises(OpportunityFitModelError):
        validate_deep_review(payload, snapshot())


def test_triage_rejects_extra_fields_and_invalid_recommendation() -> None:
    payload = triage_payload()
    payload["extra"] = "no"
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["recommendation"] = "maybe"
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())


def test_triage_rejects_jd_as_candidate_evidence() -> None:
    payload = triage_payload()
    payload["fit_signals"][0]["evidence_refs"][0] = {
        "source": "jd",
        "path": "/text",
        "excerpt": "Must build reliable APIs. Kubernetes production experience preferred.",
    }
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["hard_constraints"][0]["status"] = "met"
    payload["hard_constraints"][0]["evidence_refs"] = [
        {
            "source": "jd",
            "path": "/text",
            "excerpt": "Must build reliable APIs. Kubernetes production experience preferred.",
        }
    ]
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["gaps"][0]["candidate_status"] = "unmet"
    payload["gaps"][0]["evidence_refs"] = [
        {
            "source": "jd",
            "path": "/text",
            "excerpt": "Must build reliable APIs. Kubernetes production experience preferred.",
        }
    ]
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())


def test_triage_requires_jd_evidence_for_role_requirements() -> None:
    payload = triage_payload()
    payload["hard_constraints"][0]["evidence_refs"] = [
        {
            "source": "resume",
            "path": "/raw_text",
            "excerpt": "Built APIs. Reviewed code.",
        }
    ]
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["gaps"][0]["evidence_refs"] = [
        {
            "source": "resume",
            "path": "/raw_text",
            "excerpt": "Built APIs. Reviewed code.",
        }
    ]
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

def test_triage_rejects_invalid_resume_path_and_excerpt() -> None:
    payload = triage_payload()
    payload["fit_signals"][0]["evidence_refs"][0] = {
        "source": "resume",
        "path": "/experience/9/highlights/0",
        "excerpt": "Built APIs",
    }
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["fit_signals"][0]["evidence_refs"][0]["excerpt"] = "Invented"
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())


def test_triage_rejects_missing_evidence_for_asserted_fact() -> None:
    payload = triage_payload()
    payload["fit_signals"][0]["evidence_refs"] = []
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())


def test_triage_rejects_invalid_recommendation_semantics() -> None:
    payload = triage_payload()
    payload["recommendation"] = "advance"
    payload["hard_constraints"][0]["status"] = "unmet"
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())

    payload = triage_payload()
    payload["recommendation"] = "hold"
    payload["hard_constraints"] = []
    payload["next_questions"] = []
    with pytest.raises(OpportunityFitModelError):
        validate_triage(payload, snapshot())


def test_triage_rejects_fenced_and_non_finite_json() -> None:
    fence = chr(96) * 3
    model = ScriptedModel([f"{fence}json\n{{}}\n{fence}"])
    with pytest.raises(OpportunityFitModelError):
        generate_triage(model, snapshot())
    assert model.calls == 2

    class NonFiniteModel:
        calls = 0

        def complete(self, messages, tools):  # type: ignore[no-untyped-def]
            self.calls += 1
            return Assistant(
                content='{"summary":"x","recommendation":"hold","hard_constraints":[],"fit_signals":[],"gaps":[],"deadline":{"status":"not_stated","text":"","evidence_refs":[]},"next_questions":["x"],"value":NaN}'
            )

    non_finite = NonFiniteModel()
    with pytest.raises(OpportunityFitModelError):
        generate_triage(non_finite, snapshot())
    assert non_finite.calls == 2


def test_format_failure_is_repaired_once() -> None:
    invalid = copy.deepcopy(triage_payload())
    invalid["fit_signals"][0]["statement"] = 17
    model = ScriptedModel([invalid, triage_payload()])

    result = generate_triage(model, snapshot())

    assert result.payload["recommendation"] == "hold"
    assert model.calls == 2
    assert "invalid_change_shape" in model.prompts[1]
    assert "17" not in model.prompts[1]


def test_provider_failure_is_not_retried() -> None:
    model = ScriptedModel([RuntimeError("provider unavailable")])
    with pytest.raises(OpportunityFitModelError) as error:
        generate_triage(model, snapshot())
    assert error.value.failure_category == "provider_error"
    assert model.calls == 1


def test_deep_review_uses_one_repair_retry() -> None:
    invalid = copy.deepcopy(deep_review_payload())
    invalid["recommended_path"] = "send_application"
    model = ScriptedModel([invalid, deep_review_payload()])

    result = generate_deep_review(model, snapshot(), triage_payload())

    assert result.payload["recommended_path"] == "clarify_first"
    assert model.calls == 2


def test_model_prompts_include_snapshot_paths_but_not_unrelated_fields() -> None:
    model = ScriptedModel([triage_payload()])
    generate_triage(model, snapshot())

    prompt = model.prompts[0]
    assert "/experience/0/highlights/0" in prompt
    assert "Must build reliable APIs" in prompt
    assert "普通备注" not in prompt
