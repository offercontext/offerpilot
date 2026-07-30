import json

import pytest

from offerpilot.ai.mock_interview import (
    MOCK_INTERVIEW_FEEDBACK_SCHEMA,
    SAFE_EMPTY_FEEDBACK,
    MockInterviewContractError,
    MockInterviewUnverifiableError,
    build_mock_interview_evidence_catalog,
    generate_feedback,
    generate_question,
    parse_mock_interview_json,
    should_retry_mock_interview_format,
    validate_feedback,
)
from offerpilot.ai.types import Assistant


def _snapshot():
    return {
        "jd": {"text": "需要 Python"},
        "resume": {"content_json": {"skills": ["Python"]}},
    }


def _turns():
    return [{"turn_no": 1, "question": "介绍项目", "answer": "我做过 Python 服务"}]


class _QuestionRepairModel:
    supports_json_schema = False

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0
        self.messages = []

    def complete(self, messages, tools, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        return Assistant(content=next(self.outputs))


class _SchemaCaptureModel:
    supports_json_schema = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0
        self.response_formats = []

    def complete(self, messages, tools, **kwargs):
        self.calls += 1
        self.response_formats.append(kwargs.get("response_format"))
        return Assistant(content=next(self.outputs))


class _ProviderBlockModel:
    supports_json_schema = False

    def __init__(self, content, request_id):
        self.content = content
        self.request_id = request_id
        self.messages = []

    def complete(self, messages, tools, **kwargs):
        self.messages.append(messages)
        return Assistant(content=self.content, provider_blocks={"request_id": self.request_id})


def _valid_question():
    return (
        '{"question":"请分享一次经历？",'
        '"evidence_refs":[{"source":"turn","path":"/turns/001/answer",'
        '"excerpt":"我做过 Python 服务"}]}'
    )


def test_structural_evidence_error_is_repaired_once():
    model = _QuestionRepairModel([
        '{"question":"请分享一次经历？","evidence_refs":[null]}',
        _valid_question(),
    ])

    question = generate_question(model, _snapshot(), _turns())

    assert question == "请分享一次经历？"
    assert model.calls == 2
    repair_prompt = model.messages[1][0].content
    assert "evidence_ref_not_object" in repair_prompt
    assert "/jd/text" in repair_prompt
    assert "raw model output" not in repair_prompt


def test_repeated_structural_evidence_error_is_terminal():
    model = _QuestionRepairModel([
        '{"question":"Q","evidence_refs":[null]}',
        '{"question":"Q2","evidence_refs":[null]}',
    ])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_question(model, _snapshot(), _turns())

    assert error.value.category == "evidence_ref_not_object"
    assert error.value.diagnostic["failure_categories"] == [
        "evidence_ref_not_object", "evidence_ref_not_object"
    ]
    assert model.calls == 2


def test_semantic_evidence_failures_never_enter_format_repair():
    assert not should_retry_mock_interview_format("unknown_evidence_ref")
    assert not should_retry_mock_interview_format("excerpt_mismatch")
    assert not should_retry_mock_interview_format("limit_exceeded")
    assert not should_retry_mock_interview_format("missing_evidence_ref")


def test_repaired_shape_is_revalidated_for_forged_reference():
    model = _QuestionRepairModel([
        '{"question":"Q","evidence_refs":[null]}',
        '{"question":"Q2","evidence_refs":[{"source":"attacker","path":"/x","excerpt":"伪造"}]}',
    ])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_question(model, _snapshot(), _turns())

    assert error.value.category == "unknown_evidence_ref"
    assert model.calls == 2


def test_feedback_structural_evidence_error_is_repaired_once():
    invalid = _feedback(strengths=[{
        "id": "s1",
        "text": "回答引用了实际项目",
        "evidence_refs": [{"source": "turn", "path": "/turns/001/answer"}],
    }])
    model = _QuestionRepairModel([json.dumps(invalid, ensure_ascii=False), json.dumps(_feedback(), ensure_ascii=False)])

    proposal, diagnostic = generate_feedback(model, _snapshot(), _turns())

    assert proposal == _feedback()
    assert diagnostic["repair_count"] == 1
    assert model.calls == 2


def test_feedback_text_prompt_declares_complete_contract():
    model = _QuestionRepairModel([json.dumps(_feedback(), ensure_ascii=False)])

    generate_feedback(model, _snapshot(), _turns())

    prompt = model.messages[0][0].content
    for field in ("schema_version", "proposal_status", "strengths", "practice_points", "follow_up_questions", "next_practice_steps"):
        assert field in prompt
    assert "evidence_refs" in prompt
    assert "source" in prompt
    assert "safe_empty" in prompt
    assert "normal" in prompt


def test_feedback_prompt_requires_turn_evidence_for_observed_fields():
    model = _QuestionRepairModel([json.dumps(_feedback(), ensure_ascii=False)])

    generate_feedback(model, _snapshot(), _turns())

    prompt = model.messages[0][0].content
    for field in ("strengths", "practice_points", "next_practice_steps"):
        assert field in prompt
    assert 'source="turn"' in prompt
    assert "at least one completed-turn evidence reference" in prompt
    assert "safe_empty" in prompt


def test_feedback_native_schema_declares_complete_contract():
    model = _SchemaCaptureModel([json.dumps(_feedback(), ensure_ascii=False)])

    generate_feedback(model, _snapshot(), _turns())

    response_format = model.response_formats[0]
    assert response_format["json_schema"]["schema"] == MOCK_INTERVIEW_FEEDBACK_SCHEMA
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version", "proposal_status", "strengths", "practice_points",
        "follow_up_questions", "next_practice_steps",
    }
    item_schema = schema["properties"]["strengths"]["items"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == {"id", "text", "evidence_refs"}
    ref_schema = item_schema["properties"]["evidence_refs"]["items"]
    assert set(ref_schema["required"]) == {"source", "path", "excerpt"}


def test_feedback_repeated_structural_failure_is_terminal():
    invalid = json.dumps({**_feedback(), "extra": "raw model output"}, ensure_ascii=False)
    model = _QuestionRepairModel([invalid, invalid])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_feedback(model, _snapshot(), _turns())

    assert error.value.category == "unexpected_field"
    assert model.calls == 2


def test_missing_turn_evidence_is_repaired_once_when_second_response_adds_turn_ref():
    marker = "model-only-feedback-marker"
    first = _feedback(
        strengths=[{
            "id": "s1",
            "text": marker,
            "evidence_refs": [{
                "source": "jd",
                "path": "/jd/text",
                "excerpt": _snapshot()["jd"]["text"],
            }],
        }]
    )
    model = _QuestionRepairModel([
        json.dumps(first, ensure_ascii=False),
        json.dumps(_feedback(), ensure_ascii=False),
    ])

    proposal, diagnostic = generate_feedback(model, _snapshot(), _turns())

    assert proposal == _feedback()
    assert diagnostic["repair_count"] == 1
    assert model.calls == 2
    repair_messages = model.messages[1]
    repair_prompt = "\n".join(message.content for message in repair_messages)
    assert "missing_turn_evidence" in repair_prompt
    assert "at least one completed-turn evidence reference" in repair_prompt
    assert marker not in repair_prompt


def test_repaired_missing_turn_evidence_with_forged_turn_reference_fails():
    first = _feedback(
        strengths=[{
            "id": "s1",
            "text": "JD-only claim",
            "evidence_refs": [{
                "source": "jd",
                "path": "/jd/text",
                "excerpt": _snapshot()["jd"]["text"],
            }],
        }]
    )
    second = _feedback(
        strengths=[{
            "id": "s1",
            "text": "forged turn claim",
            "evidence_refs": [{
                "source": "turn",
                "path": "/turns/999/answer",
                "excerpt": "forged answer",
            }],
        }]
    )
    model = _QuestionRepairModel([
        json.dumps(first, ensure_ascii=False),
        json.dumps(second, ensure_ascii=False),
    ])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_feedback(model, _snapshot(), _turns())

    assert error.value.category == "unknown_evidence_ref"
    assert model.calls == 2


def test_semantic_feedback_reference_failure_is_not_repaired():
    forged = _feedback(
        strengths=[{
            "id": "s1",
            "text": "forged turn claim",
            "evidence_refs": [{
                "source": "turn",
                "path": "/turns/999/answer",
                "excerpt": "forged answer",
            }],
        }]
    )
    model = _QuestionRepairModel([json.dumps(forged, ensure_ascii=False)])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_feedback(model, _snapshot(), _turns())

    assert error.value.category == "unknown_evidence_ref"
    assert model.calls == 1


@pytest.mark.parametrize(
    ("reference", "category"),
    [
        ({"source": "turn", "path": "/turns/001/answer"}, "evidence_ref_missing_field"),
        ({"source": "turn", "path": 1, "excerpt": "回答"}, "evidence_ref_field_type"),
    ],
)
def test_evidence_reference_shape_failures_have_stable_categories(reference, category):
    model = _QuestionRepairModel([
        '{"question":"Q","evidence_refs":[' + str(reference).replace("'", '"') + ']}',
        '{"question":"Q2","evidence_refs":[' + str(reference).replace("'", '"') + ']}',
    ])

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_question(model, _snapshot(), _turns())

    assert error.value.category == category
    assert model.calls == 2


def test_evidence_catalog_uses_stable_escaped_paths_and_completed_turns_only():
    snapshot = {
        "jd": {"text": "需要 Python"},
        "resume": {
            "content_json": {
                "z": "Z",
                "a/b~c": "路径内容",
                "empty": "",
                "nested": ["第一项", {"answer": "第二项 🚀 e\u0301"}],
            }
        },
    }
    turns = [
        {"turn_no": 2, "question": "Q2", "answer": "完成回答"},
        {"turn_no": 3, "question": "Q3", "answer": "   "},
    ]

    catalog = build_mock_interview_evidence_catalog(snapshot, turns)

    assert catalog == [
        {"source": "jd", "path": "/jd/text", "value": "需要 Python"},
        {"source": "resume", "path": "/resume/content_json/a~1b~0c", "value": "路径内容"},
        {"source": "resume", "path": "/resume/content_json/nested/0", "value": "第一项"},
        {"source": "resume", "path": "/resume/content_json/nested/1/answer", "value": "第二项 🚀 e\u0301"},
        {"source": "resume", "path": "/resume/content_json/z", "value": "Z"},
        {"source": "turn", "path": "/turns/002/answer", "value": "完成回答"},
    ]


def test_provider_payload_contains_catalog_without_internal_ids_or_unfinished_turn():
    model = _QuestionRepairModel([_valid_question()])
    snapshot = {
        **_snapshot(),
        "application": {"id": 42, "company_name": "secret"},
    }
    turns = [
        {"turn_no": 1, "question": "Q1", "answer": "我做过 Python 服务"},
        {"turn_no": 2, "question": "Q2", "answer": ""},
    ]

    generate_question(model, snapshot, turns)

    payload = json.loads(model.messages[0][1].content)
    assert payload["evidence_catalog"][-1] == {
        "source": "turn", "path": "/turns/001/answer", "value": "我做过 Python 服务"
    }
    assert all("id" not in entry for entry in payload["evidence_catalog"])
    assert "secret" not in json.dumps(payload["evidence_catalog"], ensure_ascii=False)
    assert "Q2" not in json.dumps(payload["evidence_catalog"], ensure_ascii=False)


def test_contract_failure_redacts_provider_request_id():
    model = _ProviderBlockModel('{"unexpected":true}', "provider-request-123")

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_question(model, _snapshot(), _turns())

    assert error.value.diagnostic["provider_request_id"] == "request-redacted-488ab4c1c10b"
    assert "provider-request-123" not in str(error.value.diagnostic)


def test_feedback_contract_failure_redacts_provider_request_id():
    model = _ProviderBlockModel('{"unexpected":true}', "provider-request-123")

    with pytest.raises(MockInterviewUnverifiableError) as error:
        generate_feedback(model, _snapshot(), _turns())

    assert error.value.diagnostic["provider_request_id"] == "request-redacted-488ab4c1c10b"
    assert "provider-request-123" not in str(error.value.diagnostic)


def _feedback(**overrides):
    value = {
        "schema_version": "mock-interview-feedback-v1",
        "proposal_status": "normal",
        "strengths": [
            {
                "id": "s1",
                "text": "回答引用了实际项目",
                "evidence_refs": [{"source": "turn", "path": "/turns/001/answer", "excerpt": "我做过 Python 服务"}],
            }
        ],
        "practice_points": [],
        "follow_up_questions": [],
        "next_practice_steps": [],
    }
    value.update(overrides)
    return value


def test_question_contract_rejects_duplicate_keys_and_fenced_json():
    with pytest.raises(MockInterviewContractError, match="duplicate_key"):
        parse_mock_interview_json('{"text":"a","text":"b"}')
    with pytest.raises(MockInterviewContractError, match="invalid_json"):
        parse_mock_interview_json("```json\n{}\n```")


def test_feedback_contract_rejects_nonfinite_extra_blank_and_over_limit_values():
    with pytest.raises(MockInterviewContractError, match="invalid_json"):
        parse_mock_interview_json('{"value":NaN}')
    with pytest.raises(MockInterviewContractError, match="unexpected_field"):
        validate_feedback({**_feedback(), "extra": 1}, _snapshot(), _turns())
    with pytest.raises(MockInterviewContractError, match="blank_value"):
        validate_feedback({**_feedback(), "strengths": [{"id": "s1", "text": " ", "evidence_refs": []}]}, _snapshot(), _turns())
    with pytest.raises(MockInterviewContractError, match="limit_exceeded"):
        validate_feedback({**_feedback(), "practice_points": [_feedback()["strengths"][0]] * 9}, _snapshot(), _turns())


def test_strengths_and_practice_points_require_turn_answer_evidence():
    item = {"id": "s1", "text": "岗位要求 Python", "evidence_refs": [{"source": "jd", "path": "/jd/text", "excerpt": "需要 Python"}]}
    with pytest.raises(MockInterviewContractError, match="missing_turn_evidence"):
        validate_feedback({**_feedback(), "strengths": [item]}, _snapshot(), _turns())


def test_follow_up_fixed_question_requires_versioned_id_and_exact_text():
    fixed = {"id": "free", "text": "您希望进一步澄清哪一部分？", "evidence_refs": []}
    with pytest.raises(MockInterviewContractError, match="fixed_question"):
        validate_feedback({**_feedback(), "follow_up_questions": [fixed]}, _snapshot(), _turns())


def test_follow_up_context_question_requires_evidence():
    item = {"id": "q1", "text": "你在 Python 项目中做了什么？", "evidence_refs": []}
    with pytest.raises(MockInterviewContractError, match="evidence"):
        validate_feedback({**_feedback(), "follow_up_questions": [item]}, _snapshot(), _turns())


def test_next_practice_step_requires_turn_and_optional_source_refs():
    item = {"id": "n1", "text": "复习 Python", "evidence_refs": [{"source": "jd", "path": "/jd/text", "excerpt": "需要 Python"}]}
    with pytest.raises(MockInterviewContractError, match="missing_turn_evidence"):
        validate_feedback({**_feedback(), "next_practice_steps": [item]}, _snapshot(), _turns())


def test_resume_pointer_and_excerpt_must_resolve_to_frozen_string_leaf():
    item = {"id": "s1", "text": "回答引用了实际项目", "evidence_refs": [{"source": "resume", "path": "/resume/content_json/skills/0", "excerpt": "Go"}]}
    item["evidence_refs"].append({"source": "turn", "path": "/turns/001/answer", "excerpt": "Python"})
    with pytest.raises(MockInterviewContractError, match="excerpt_mismatch"):
        validate_feedback({**_feedback(), "strengths": [item]}, _snapshot(), _turns())


def test_safe_empty_has_exactly_four_empty_arrays():
    assert set(SAFE_EMPTY_FEEDBACK) == {
        "schema_version", "proposal_status", "strengths", "practice_points",
        "follow_up_questions", "next_practice_steps",
    }
    assert SAFE_EMPTY_FEEDBACK["proposal_status"] == "safe_empty"
    assert all(not SAFE_EMPTY_FEEDBACK[field] for field in (
        "strengths", "practice_points", "follow_up_questions", "next_practice_steps"
    ))
