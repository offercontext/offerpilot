from __future__ import annotations

import copy
import json

import pytest

from offerpilot.ai.interview_preparation_proposals import (
    InterviewPreparationModelError,
    _repair_prompt,
    _system_prompt,
    generate_interview_preparation_proposal,
    safe_empty_interview_preparation_proposal,
    validate_interview_preparation,
)
from offerpilot.ai.types import Assistant


def test_provider_prompt_spells_out_evidence_reference_object_contract() -> None:
    prompt = _system_prompt()
    repair = _repair_prompt("invalid_item_shape")

    assert 'source","path","excerpt' in prompt
    assert "/jd/text" in prompt
    assert "/raw_text" in prompt
    assert "/knowledge_evidence/001" in prompt
    assert 'source","path","excerpt' in repair


def _snapshot() -> dict[str, object]:
    return {
        "event": {
            "id": 4,
            "application_id": 7,
            "event_type": "interview",
            "subtype": "technical",
            "round": 2,
            "scheduled_at": "2026-07-20T10:00:00Z",
            "duration_minutes": 45,
            "status": "todo",
        },
        "jd": {"text": "Build reliable APIs with Python and SQL."},
        "resume": {
            "id": 9,
            "content_json": {
                "experience": [{"highlights": ["Built reliable API services"]}],
                "skills": ["Python", "SQL"],
            },
        },
        "knowledge_evidence": [
            {
                "id": "evidence-1",
                "path": "/knowledge/evidence/evidence-1",
                "provider_path": "/knowledge_evidence/001",
                "excerpt": "A rollback is safe when the observable signal is defined first.",
            }
        ],
        "user_assertions": ["I led the migration personally."],
    }


def _ref(source: str, path: str, excerpt: str) -> dict[str, str]:
    return {"source": source, "path": path, "excerpt": excerpt}


def _proposal() -> dict[str, object]:
    return {
        "preparation_directions": [
            {
                "id": "direction-1",
                "text": "准备可靠 API 设计的取舍说明。",
                "evidence_refs": [
                    _ref("jd", "/jd/text", "Build reliable APIs with Python and SQL.")
                ],
            }
        ],
        "story_prompts": [
            {
                "id": "story-1",
                "text": "准备说明你构建 API 服务时的具体做法。",
                "evidence_refs": [
                    _ref("resume", "/experience/0/highlights/0", "Built reliable API services")
                ],
            }
        ],
        "review_points": [
            {
                "id": "review-1",
                "text": "复习如何先定义可观察的安全信号。",
                "evidence_refs": [
                    _ref(
                        "knowledge_evidence",
                        "/knowledge_evidence/001",
                        "A rollback is safe when the observable signal is defined first.",
                    )
                ],
            }
        ],
        "interviewer_questions": [
            {
                "id": "question-1",
                "text": "可以请面试官说明本岗位最关注的 API 可靠性场景吗？",
                "evidence_refs": [
                    _ref("jd", "/jd/text", "Build reliable APIs with Python and SQL.")
                ],
            }
        ],
        "items_to_clarify": [
            {
                "id": "clarify-1",
                "text": "需要确认岗位对 SQL 深度的具体期待。",
                "evidence_refs": [_ref("resume", "/skills/1", "SQL")],
            }
        ],
    }


class FakeModel:
    supports_json_schema = False

    def __init__(self, responses: list[object], error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.calls = 0
        self.messages: list[list[object]] = []
        self.response_formats: list[object] = []

    def complete(self, messages, tools, response_format=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.messages.append(messages)
        self.response_formats.append(response_format)
        if self.error is not None:
            raise self.error
        response = self.responses.pop(0)
        return Assistant(
            content=response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        )


def test_validator_accepts_five_evidence_gated_preparation_arrays() -> None:
    assert validate_interview_preparation(_proposal(), _snapshot()) == _proposal()


def test_validator_rejects_forged_refs_non_leaf_resume_and_unicode_rewrite() -> None:
    snapshot = _snapshot()
    payload = copy.deepcopy(_proposal())
    payload["story_prompts"][0]["evidence_refs"][0] = _ref(  # type: ignore[index]
        "resume", "/experience/0", "Built reliable API services"
    )
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, snapshot)
    assert exc_info.value.validation_category == "unknown_evidence_ref"

    payload = copy.deepcopy(_proposal())
    payload["review_points"][0]["evidence_refs"][0]["excerpt"] = (  # type: ignore[index]
        "A rollback is safe when the observable signal is defined first.\u00a0"
    )
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, snapshot)
    assert exc_info.value.validation_category == "excerpt_mismatch"


@pytest.mark.parametrize(
    ("source", "path", "excerpt"),
    [
        ("jd", "/jd/text", " \t"),
        ("resume", "/skills/0", "\n"),
        ("knowledge_evidence", "/knowledge_evidence/001", "  "),
    ],
)
def test_validator_rejects_blank_evidence_excerpts(
    source: str, path: str, excerpt: str
) -> None:
    payload = copy.deepcopy(_proposal())
    payload["preparation_directions"][0]["evidence_refs"][0] = _ref(  # type: ignore[index]
        source, path, excerpt
    )
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, _snapshot())
    assert exc_info.value.validation_category == "excerpt_mismatch"


def test_validator_rejects_duplicate_ids_across_arrays_and_noncanonical_array_pointer() -> None:
    payload = copy.deepcopy(_proposal())
    payload["story_prompts"][0]["id"] = payload["preparation_directions"][0]["id"]  # type: ignore[index]
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, _snapshot())
    assert exc_info.value.validation_category == "invalid_item_shape"

    payload = copy.deepcopy(_proposal())
    payload["story_prompts"][0]["evidence_refs"][0] = _ref(  # type: ignore[index]
        "resume", "/skills/00", "Python"
    )
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, _snapshot())
    assert exc_info.value.validation_category == "unknown_evidence_ref"


def test_validator_rejects_item_and_evidence_limits() -> None:
    payload = _proposal()
    payload["preparation_directions"] = [  # type: ignore[index]
        copy.deepcopy(payload["preparation_directions"][0]) for _ in range(9)  # type: ignore[index]
    ]
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, _snapshot())
    assert exc_info.value.validation_category == "limit_exceeded"

    payload = _proposal()
    payload["preparation_directions"][0]["evidence_refs"] = [  # type: ignore[index]
        _ref("jd", "/jd/text", "Build reliable APIs with Python and SQL.") for _ in range(6)
    ]
    with pytest.raises(InterviewPreparationModelError) as exc_info:
        validate_interview_preparation(payload, _snapshot())
    assert exc_info.value.validation_category == "limit_exceeded"


def test_generate_repairs_once_with_machine_failure_category() -> None:
    invalid = _proposal()
    invalid["preparation_directions"][0]["evidence_refs"] = []  # type: ignore[index]
    model = FakeModel([invalid, _proposal()])

    result = generate_interview_preparation_proposal(model, _snapshot())

    assert result == _proposal()
    assert model.calls == 2
    assert "missing_evidence_ref" in model.messages[1][-1].content
    assert "Built reliable API services" not in model.messages[1][-1].content


def test_provider_failure_is_called_once_and_not_repaired() -> None:
    model = FakeModel([], error=TimeoutError("private provider detail"))

    with pytest.raises(InterviewPreparationModelError) as exc_info:
        generate_interview_preparation_proposal(model, _snapshot())

    assert model.calls == 1
    assert exc_info.value.failure_category == "provider_error"


def test_two_invalid_outputs_return_validated_safe_empty_without_model_text() -> None:
    model = FakeModel(
        [
            {"preparation_directions": [{"text": "candidate secret"}]},
            {"unexpected": "raw model output"},
        ]
    )

    result = generate_interview_preparation_proposal(model, _snapshot())

    assert result == safe_empty_interview_preparation_proposal()
    assert model.calls == 2
    assert "candidate secret" not in json.dumps(result, ensure_ascii=False)


def test_diagnostic_distinguishes_direct_safe_empty_from_contract_failure() -> None:
    diagnostics: list[dict[str, object]] = []
    model = FakeModel([safe_empty_interview_preparation_proposal()])

    result = generate_interview_preparation_proposal(
        model, _snapshot(), on_diagnostic=diagnostics.append
    )

    assert result == safe_empty_interview_preparation_proposal()
    assert diagnostics == [
        {
            "failure_category": None,
            "failure_categories": [],
            "repair_attempted": False,
            "retry_count": 0,
            "duration_ms": diagnostics[0]["duration_ms"],
            "provider_request_id_hash": "",
        }
    ]
    assert isinstance(diagnostics[0]["duration_ms"], int)


def test_diagnostic_records_repair_categories_and_provider_request_id_hash() -> None:
    class ProviderIdModel:
        supports_json_schema = False

        def __init__(self) -> None:
            self.responses = [{"unexpected": "raw model output"}, _proposal()]
            self.calls = 0

        def complete(self, messages, tools, response_format=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            return Assistant(
                content=json.dumps(self.responses.pop(0), ensure_ascii=False),
                provider_blocks={"request_id": "provider-request-id"},
            )

    diagnostics: list[dict[str, object]] = []
    result = generate_interview_preparation_proposal(
        ProviderIdModel(), _snapshot(), on_diagnostic=diagnostics.append
    )

    assert result == _proposal()
    assert diagnostics[0]["failure_category"] == "unexpected_field"
    assert diagnostics[0]["failure_categories"] == ["unexpected_field"]
    assert diagnostics[0]["repair_attempted"] is True
    assert diagnostics[0]["retry_count"] == 1
    assert diagnostics[0]["provider_request_id_hash"] == __import__("hashlib").sha256(
        b"provider-request-id"
    ).hexdigest()[:12]


def test_diagnostic_preserves_both_contract_failure_categories_without_raw_output() -> None:
    diagnostics: list[dict[str, object]] = []
    model = FakeModel(
        [
            {
                "preparation_directions": [{"text": "candidate secret"}],
                "story_prompts": [],
                "review_points": [],
                "interviewer_questions": [],
                "items_to_clarify": [],
            },
            {"unexpected": "raw model output"},
        ]
    )

    result = generate_interview_preparation_proposal(
        model, _snapshot(), on_diagnostic=diagnostics.append
    )

    encoded = json.dumps(diagnostics, ensure_ascii=False)
    assert result == safe_empty_interview_preparation_proposal()
    assert diagnostics[0]["failure_category"] == "unexpected_field"
    assert diagnostics[0]["failure_categories"] == [
        "invalid_item_shape",
        "unexpected_field",
    ]
    assert diagnostics[0]["repair_attempted"] is True
    assert diagnostics[0]["retry_count"] == 1
    assert "candidate secret" not in encoded
    assert "raw model output" not in encoded


def test_user_assertions_are_saved_in_snapshot_but_absent_from_provider_payload() -> None:
    model = FakeModel([_proposal()])

    generate_interview_preparation_proposal(model, _snapshot())

    provider_text = "\n".join(message.content for message in model.messages[0])
    assert "I led the migration personally." not in provider_text
    assert "Build reliable APIs with Python and SQL." in provider_text
    assert "A rollback is safe when the observable signal is defined first." in provider_text


def test_provider_payload_omits_internal_application_event_resume_and_note_ids() -> None:
    model = FakeModel([_proposal()])
    snapshot = _snapshot()
    generate_interview_preparation_proposal(model, snapshot)
    provider_text = "\n".join(message.content for message in model.messages[0])
    assert '"application_id"' not in provider_text
    assert '"event_id"' not in provider_text
    assert '"note_version_id"' not in provider_text
    assert "evidence-1" not in provider_text
    assert "/knowledge/evidence/evidence-1" not in provider_text
    assert '"id":4' not in provider_text
    assert '"id":9' not in provider_text


def test_json_schema_is_passed_only_for_explicit_true_capability() -> None:
    model = FakeModel([_proposal()])
    model.supports_json_schema = True

    generate_interview_preparation_proposal(model, _snapshot())

    assert model.response_formats[0]["type"] == "json_schema"  # type: ignore[index]

    unsupported = FakeModel([_proposal()])
    unsupported.supports_json_schema = "true"
    generate_interview_preparation_proposal(unsupported, _snapshot())
    assert unsupported.response_formats[0] is None
