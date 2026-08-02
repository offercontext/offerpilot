from __future__ import annotations

import json

import pytest

from offerpilot.ai.offer_negotiation import (
    OFFER_NEGOTIATION_FIELDS,
    OfferNegotiationModelError,
    build_offer_negotiation_snapshot,
    generate_offer_negotiation_proposal,
    safe_empty_offer_negotiation_proposal,
    validate_offer_negotiation,
)
from offerpilot.ai.types import Assistant


class FakeModel:
    supports_json_schema = False

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list] = []

    def complete(self, messages, tools, response_format=None):
        self.calls.append([messages, response_format])
        return Assistant(content=self.responses.pop(0), provider_blocks={"request_id": "req-1"})


def _snapshot(*, dimension_order: list[int] | None = None) -> dict:
    dimensions = [
        {"id": 2, "label": "成长空间", "value_text": None},
        {"id": 1, "label": "通勤", "value_text": "地铁 35 分钟"},
    ]
    if dimension_order is not None:
        by_id = {item["id"]: item for item in dimensions}
        dimensions = [by_id[item] for item in dimension_order]
    return build_offer_negotiation_snapshot(
        offer={
            "id": 9,
            "company_name": "星云数据",
            "position_name": "后端工程师",
            "status": "pending",
            "base_monthly": 28000,
            "months_per_year": 12,
            "signing_bonus": 0,
            "equity": "期权待确认",
            "perks": "餐补",
            "deadline": "2026-09-01",
            "notes": "用户备注",
            "assessment": "待核实",
        },
        dimensions=dimensions,
        user_brief={"goal": "争取入职时间", "concerns": "通勤", "scenario": "电话沟通"},
        idempotency_key="A" * 16,
    )


def _item(
    source: str = "offer_snapshot",
    path: str = "/offer_snapshot/company_name",
    excerpt: str = "星云数据",
    item_id: str = "item-1",
) -> dict:
    return {
        "id": item_id,
        "text": "准备确认公司信息",
        "rationale": "依据当前 Offer 记录",
        "evidence_refs": [{"source": source, "path": path, "excerpt": excerpt}],
    }


def _valid_payload() -> dict:
    return {
        "proposal_status": "normal",
        "communication_goals": [_item(item_id="goal-1")],
        "clarification_questions": [_item(path="/offer_snapshot/position_name", excerpt="后端工程师", item_id="question-1")],
        "talking_points": [_item(path="/offer_snapshot/base_monthly", excerpt="28000", item_id="point-1")],
        "preparation_checks": [_item(source="user_brief", path="/user_brief/goal", excerpt="争取入职时间", item_id="check-1")],
    }


def test_snapshot_dimension_order_is_canonical_and_missing_values_have_no_evidence_path() -> None:
    first = _snapshot(dimension_order=[2, 1])
    second = _snapshot(dimension_order=[1, 2])
    assert first == second
    assert first["offer_snapshot"]["dimensions"] == [
        {"path_id": "dimension_001", "label": "通勤", "value_text": "地铁 35 分钟"},
        {"path_id": "dimension_002", "label": "成长空间", "value_text": None},
    ]
    assert "dimensions" not in first


def test_snapshot_uses_versioned_offer_fields_without_assessment() -> None:
    snapshot = _snapshot()
    assert snapshot["snapshot_version"] == 1
    assert snapshot["offer_snapshot"]["status"] == "pending"
    assert "assessment" not in snapshot["offer_snapshot"]


def test_provider_projection_omits_missing_dimension_label_and_value() -> None:
    model = FakeModel([json.dumps(_valid_payload(), ensure_ascii=False)])
    generate_offer_negotiation_proposal(model, _snapshot())
    prompt = "\n".join(message.content for message in model.calls[0][0])
    assert '"value_text":null' not in prompt
    assert '"label":"鎴愰暱绌洪棿"' not in prompt


@pytest.mark.parametrize(
    ("source", "path", "excerpt"),
    [
        ("user_brief", "/offer_snapshot/company_name", "星云数据"),
        ("offer_snapshot", "/offer_snapshot/dimensions/dimension_001/label", "通勤"),
        ("offer_snapshot", "/user_brief/goal", "争取入职时间"),
    ],
)
def test_evidence_source_has_a_fixed_path_allowlist(source: str, path: str, excerpt: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["evidence_refs"] = [
        {"source": source, "path": path, "excerpt": excerpt}
    ]
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "unknown_evidence_ref"


def test_numeric_evidence_requires_exact_ascii_representation() -> None:
    snapshot = _snapshot()
    valid = _valid_payload()
    assert validate_offer_negotiation(valid, snapshot)["proposal_status"] == "normal"
    for excerpt in ["28,000", "28000 元", "二万八", "8000"]:
        invalid = _valid_payload()
        invalid["talking_points"][0]["evidence_refs"][0]["excerpt"] = excerpt
        with pytest.raises(OfferNegotiationModelError) as error:
            validate_offer_negotiation(invalid, snapshot)
        assert error.value.validation_category == "excerpt_mismatch"


def test_structure_failure_repairs_once_and_validates_final_evidence() -> None:
    model = FakeModel(["{", json.dumps(_valid_payload(), ensure_ascii=False)])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2
    assert "星云数据" not in model.calls[1][0][1].content
    assert "invalid_json" in model.calls[1][0][1].content


def test_semantic_evidence_failure_is_not_repaired() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"][0] = {
        "source": "attacker",
        "path": "/offer_snapshot/company_name",
        "excerpt": "星云数据",
    }
    model = FakeModel([json.dumps(invalid, ensure_ascii=False), json.dumps(_valid_payload(), ensure_ascii=False)])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "unknown_evidence_ref"
    assert len(model.calls) == 1
    assert error.value.provider_request_id.startswith("request-redacted-")
    assert "req-1" not in error.value.provider_request_id


@pytest.mark.parametrize(
    "text",
    [
        "请询问公司是否接受远程办公。",
        "接受或拒绝该 Offer 仍由用户自行决定。",
        "不应由系统替用户决定接受或拒绝 Offer。",
        "建议不要向招聘方透露当前底线。",
        "请不要忘记确认入职时间。",
        "建议选择电话沟通谈薪。",
        "建议选择和公司沟通谈薪。",
        "建议选择电话沟通方案。",
        "建议选择谈薪方案。",
        "建议选择这份 Offer 的谈薪场景。",
        "建议选择这份 Offer 的电话沟通方案。",
        "建议选择这份 Offer 的调研方案。",
        "建议选择与这份 Offer 相关的谈薪方案。",
        "建议选择与这份 Offer 相关的电话沟通方案。",
        "请确认录用通知中的入职时间。",
        "请说明接受或拒绝该 Offer 前需要确认哪些信息。",
        "请列出接受或拒绝 Offer 前需要询问的问题。",
        "建议说明：接受或拒绝仍由用户自行决定。",
        "建议接受或拒绝，最终由用户自行决定。",
    ],
)
def test_legal_negotiation_language_is_not_decision_language(text: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = text
    result = validate_offer_negotiation(payload, _snapshot())
    assert result["proposal_status"] == "normal"


@pytest.mark.parametrize(
    "text",
    [
        "建议接受该 Offer。",
        "你应该拒绝这个岗位。",
        "这份 Offer 是最优选择，请直接接受。",
        "建议你考虑接受该 Offer。",
        "你应该考虑拒绝这个岗位。",
        "接受这份 Offer 会更好。",
        "推荐你认真考虑拒绝这个 Offer。",
        "建议你优先考虑接受这份 Offer。",
        "最好仔细考虑后选择这个岗位。",
        "请直接接受这个 Offer。",
        "请你接受这个 Offer。",
        "请用户拒绝这个岗位。",
        "请立即接受这个 Offer。",
        "建议接受该 Offer。最终决定权由用户掌握。",
        "建议接受这个 Offer 并强调最终决定权由用户掌握。",
        "现在就接受这份 Offer。",
        "You should accept this Offer.",
        "I recommend signing this Offer.",
        "This Offer is worth accepting.",
        "This is the best Offer.",
        "You should consider accepting this Offer.",
        "I recommend taking this Offer.",
        "We recommend choosing this position.",
        "Please consider taking this job.",
        "Please confirm this Offer is the best.",
        "Please confirm this Offer is worth accepting.",
        "建议接受这个 Offer 作为首选方案。",
        "建议选择这个岗位作为首选。",
        "建议接受这个 Offer吧。",
        "建议签下这个 Offer。",
        "不要错过这个机会。",
        "值得接受这个 Offer。",
        "建议接受你拿到的 Offer。",
        "建议接受这家公司的 Offer。",
        "建议选择这家公司的岗位。",
        "建议拒绝目前的工作机会。",
        "请考虑拒绝目前这份 Offer。",
        "建议接受上述 Offer。",
    ],
)
def test_explicit_decision_recommendation_is_terminal(text: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = text
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "forbidden_decision_language"


def test_explicit_decision_language_is_terminal_and_not_repaired() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["text"] = "建议接受该 Offer。"
    model = FakeModel([json.dumps(invalid, ensure_ascii=False), json.dumps(_valid_payload(), ensure_ascii=False)])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "forbidden_decision_language"
    assert len(model.calls) == 1


def test_question_context_does_not_hide_an_unsupported_fact_assertion() -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = "请确认公司政策是否允许远程办公，公司政策规定所有人必须到岗。"
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "forbidden_decision_language"


@pytest.mark.parametrize(
    "text",
    [
        "请确认以下事实：公司政策规定所有人必须到岗。",
        "录用概率高达 90%。",
        "请确认：公司政策明确规定所有人必须到岗。",
        "市场薪酬通常是 30k。",
        "录用概率约为 90%。",
    ],
)
def test_unsupported_fact_assertion_is_terminal(text: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = text
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "forbidden_decision_language"


@pytest.mark.parametrize(
    "text",
    [
        "请确认：你应该接受这份 Offer。",
        "请确认：建议接受该 Offer。",
    ],
)
def test_question_prefix_does_not_hide_decision_recommendation(text: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = text
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "forbidden_decision_language"


def test_generation_prompt_explains_allowed_and_forbidden_decision_language() -> None:
    model = FakeModel([json.dumps(_valid_payload(), ensure_ascii=False)])
    generate_offer_negotiation_proposal(model, _snapshot())
    prompt = "\n".join(message.content for message in model.calls[0][0])
    assert "请询问公司是否接受远程办公" in prompt
    assert "接受或拒绝仍由用户自行决定" in prompt
    assert "建议接受该 Offer" in prompt
    assert "应该拒绝这个岗位" in prompt
    assert "You should accept this Offer." in prompt
    assert "建议选择电话沟通谈薪" in prompt


def test_safe_empty_has_exact_four_empty_arrays() -> None:
    empty = safe_empty_offer_negotiation_proposal()
    assert set(empty) == set(OFFER_NEGOTIATION_FIELDS)
    assert all(value == [] for key, value in empty.items() if key != "proposal_status")
    assert empty["proposal_status"] == "safe_empty"


def test_safe_empty_repair_emits_only_redacted_diagnostic() -> None:
    diagnostics: list[dict[str, object]] = []
    model = FakeModel(["{", "{"])
    result = generate_offer_negotiation_proposal(model, _snapshot(), on_diagnostic=diagnostics.append)
    assert result["proposal_status"] == "safe_empty"
    assert len(diagnostics) == 1
    assert diagnostics[0]["failure_category"] == "invalid_json"
    assert diagnostics[0]["repair_attempted"] is True
    assert diagnostics[0]["repair_count"] == 1
    assert diagnostics[0]["provider_request_id"].startswith("request-redacted-")


def test_generation_prompt_contains_stable_evidence_catalog_without_database_ids() -> None:
    model = FakeModel([json.dumps(_valid_payload(), ensure_ascii=False)])
    generate_offer_negotiation_proposal(model, _snapshot())
    system_prompt = model.calls[0][0][0].content
    assert '"source":"offer_snapshot"' in system_prompt
    assert '"path":"/offer_snapshot/company_name"' in system_prompt
    assert '"path":"/user_brief/goal"' in system_prompt
    catalog_text = system_prompt.split("evidence_catalog", 1)[1]
    assert '"id":' not in catalog_text


@pytest.mark.parametrize("field", ["goal", "concerns", "scenario"])
def test_snapshot_rejects_blank_user_brief(field: str) -> None:
    brief = {"goal": "目标", "concerns": "顾虑", "scenario": "电话"}
    brief[field] = " \t"
    with pytest.raises(ValueError):
        build_offer_negotiation_snapshot(
            offer={"company_name": "公司", "position_name": "岗位"},
            dimensions=[],
            user_brief=brief,
            idempotency_key="A" * 16,
        )


@pytest.mark.parametrize("field", ["text", "rationale"])
def test_length_limit_is_terminal_not_repairable(field: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0][field] = "x" * 601
    model = FakeModel([json.dumps(payload, ensure_ascii=False), json.dumps(_valid_payload(), ensure_ascii=False)])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "limit_exceeded"
    assert len(model.calls) == 1
