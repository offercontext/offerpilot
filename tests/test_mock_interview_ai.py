import pytest

from offerpilot.ai.mock_interview import (
    SAFE_EMPTY_FEEDBACK,
    MockInterviewContractError,
    parse_mock_interview_json,
    validate_feedback,
)


def _snapshot():
    return {
        "jd": {"text": "需要 Python"},
        "resume": {"content_json": {"skills": ["Python"]}},
    }


def _turns():
    return [{"turn_no": 1, "question": "介绍项目", "answer": "我做过 Python 服务"}]


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
