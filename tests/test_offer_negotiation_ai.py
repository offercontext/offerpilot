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
        "preparation_checks": [_item(path="/user_brief/goal", excerpt="争取入职时间", item_id="check-1")],
    }


def test_snapshot_dimension_order_is_canonical_and_missing_values_have_no_evidence_path() -> None:
    first = _snapshot(dimension_order=[2, 1])
    second = _snapshot(dimension_order=[1, 2])
    assert first == second
    assert first["dimensions"] == [
        {"path_id": "dimension_001", "label": "通勤", "value_text": "地铁 35 分钟"},
        {"path_id": "dimension_002", "label": "成长空间", "value_text": None},
    ]


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


def test_safe_empty_has_exact_four_empty_arrays() -> None:
    empty = safe_empty_offer_negotiation_proposal()
    assert set(empty) == set(OFFER_NEGOTIATION_FIELDS)
    assert all(value == [] for key, value in empty.items() if key != "proposal_status")
    assert empty["proposal_status"] == "safe_empty"
