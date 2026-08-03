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
        self.responses = list(responses)
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
            "assessment": "不得进入快照",
        },
        dimensions=dimensions,
        user_brief={"goal": "争取入职时间", "concerns": "通勤", "scenario": "电话沟通"},
        idempotency_key="A" * 16,
    )


def _item(
    *,
    topic: str = "offer_fact",
    source: str = "offer_snapshot",
    path: str = "/offer_snapshot/company_name",
    excerpt: str = "星云数据",
    item_id: str = "item-1",
) -> dict:
    return {
        "id": item_id,
        "topic": topic,
        "evidence_refs": [{"source": source, "path": path, "excerpt": excerpt}],
    }


def _valid_payload() -> dict:
    return {
        "proposal_status": "normal",
        "communication_goals": [
            _item(
                item_id="goal-1",
                topic="user_goal",
                source="user_brief",
                path="/user_brief/goal",
                excerpt="争取入职时间",
            )
        ],
        "clarification_questions": [
            _item(
                item_id="question-1",
                topic="offer_fact",
                path="/offer_snapshot/position_name",
                excerpt="后端工程师",
            )
        ],
        "talking_points": [
            _item(
                item_id="point-1",
                topic="offer_fact",
                path="/offer_snapshot/base_monthly",
                excerpt="28000",
            )
        ],
        "preparation_checks": [
            _item(
                item_id="check-1",
                topic="user_goal",
                source="user_brief",
                path="/user_brief/goal",
                excerpt="争取入职时间",
            )
        ],
    }


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_snapshot_dimension_order_is_canonical_and_missing_values_have_no_evidence_path() -> None:
    first = _snapshot(dimension_order=[2, 1])
    second = _snapshot(dimension_order=[1, 2])
    assert first == second
    assert first["offer_snapshot"]["dimensions"] == [
        {"path_id": "dimension_001", "label": "通勤", "value_text": "地铁 35 分钟"},
        {"path_id": "dimension_002", "label": "成长空间", "value_text": None},
    ]


def test_snapshot_uses_versioned_offer_fields_without_assessment() -> None:
    snapshot = _snapshot()
    assert snapshot["snapshot_version"] == 1
    assert snapshot["offer_snapshot"]["status"] == "pending"
    assert "assessment" not in snapshot["offer_snapshot"]


def test_provider_projection_omits_missing_dimension_label_and_value() -> None:
    model = FakeModel([_json(_valid_payload())])
    generate_offer_negotiation_proposal(model, _snapshot())
    prompt = "\n".join(message.content for message in model.calls[0][0])
    assert '"value_text":null' not in prompt
    assert '"label":"成长空间"' not in prompt


def test_evidence_catalog_omits_blank_values_but_preserves_nonblank_raw_text() -> None:
    snapshot = _snapshot()
    snapshot["offer_snapshot"]["notes"] = " \t"
    snapshot["offer_snapshot"]["equity"] = "   "
    snapshot["offer_snapshot"]["perks"] = "\n"
    snapshot["offer_snapshot"]["deadline"] = "  "
    snapshot["offer_snapshot"]["dimensions"][1]["value_text"] = " \t"
    model = FakeModel([_json(_valid_payload())])
    generate_offer_negotiation_proposal(model, snapshot)
    catalog = model.calls[0][0][0].content.split("evidence_catalog", 1)[1]
    assert "/offer_snapshot/notes" not in catalog
    assert "/offer_snapshot/equity" not in catalog
    assert "/offer_snapshot/perks" not in catalog
    assert "/offer_snapshot/deadline" not in catalog
    assert "dimension_002" not in catalog
    assert "地铁 35 分钟" in catalog


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
    for excerpt in ["28,000", "二万八", "8000"]:
        invalid = _valid_payload()
        invalid["talking_points"][0]["evidence_refs"][0]["excerpt"] = excerpt
        with pytest.raises(OfferNegotiationModelError) as error:
            validate_offer_negotiation(invalid, _snapshot())
        assert error.value.validation_category == "excerpt_mismatch"
    assert validate_offer_negotiation(_valid_payload(), _snapshot())["proposal_status"] == "normal"


def test_structure_failure_repairs_once_and_renders_server_text() -> None:
    model = FakeModel(["{", _json(_valid_payload())])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2
    assert "沟通请求" in result["communication_goals"][0]["text"]
    assert '"text"' not in model.calls[1][0][1].content


def test_semantic_evidence_failure_is_not_repaired() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"][0] = {
        "source": "attacker",
        "path": "/offer_snapshot/company_name",
        "excerpt": "星云数据",
    }
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "unknown_evidence_ref"
    assert len(model.calls) == 1
    assert error.value.provider_request_id.startswith("request-redacted-")


@pytest.mark.parametrize(
    "bad_ref",
    [
        "not-an-object",
        {},
        {"source": "offer_snapshot", "path": "/offer_snapshot/company_name", "excerpt": "星云数据", "extra": "x"},
        {"source": "offer_snapshot", "path": 1, "excerpt": "星云数据"},
        {"source": "offer_snapshot", "path": "/offer_snapshot/company_name", "excerpt": 1},
    ],
)
def test_evidence_object_shape_failure_repairs_once(bad_ref: object) -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"] = [bad_ref]
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2


@pytest.mark.parametrize("bad_refs", ["not-an-array", []])
def test_evidence_refs_shape_failure_repairs_once(bad_refs: object) -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"] = bad_refs
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2


def test_evidence_refs_limit_is_terminal_without_repair() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"] = [
        {"source": "offer_snapshot", "path": "/offer_snapshot/company_name", "excerpt": "星云数据"}
    ] * 5
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "limit_exceeded"
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    ("topic", "path", "excerpt"),
    [
        ("user_goal", "/offer_snapshot/company_name", "星云数据"),
        ("user_concern", "/user_brief/goal", "争取入职时间"),
        ("user_scenario", "/offer_snapshot/company_name", "星云数据"),
        ("comparison_dimension", "/user_brief/concerns", "通勤"),
        ("offer_fact", "/user_brief/goal", "争取入职时间"),
    ],
)
def test_topic_requires_an_matching_evidence_anchor(topic: str, path: str, excerpt: str) -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["topic"] = topic
    invalid["communication_goals"][0]["evidence_refs"] = [
        {"source": "offer_snapshot" if path.startswith("/offer_") else "user_brief", "path": path, "excerpt": excerpt}
    ]
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(invalid, _snapshot())
    assert error.value.validation_category == "topic_evidence_mismatch"


def test_comparison_dimension_topic_accepts_only_dimension_value_anchor() -> None:
    valid = _valid_payload()
    valid["communication_goals"][0]["topic"] = "comparison_dimension"
    valid["communication_goals"][0]["evidence_refs"] = [
        {
            "source": "offer_snapshot",
            "path": "/offer_snapshot/dimensions/dimension_001/value_text",
            "excerpt": "地铁 35 分钟",
        }
    ]
    assert validate_offer_negotiation(valid, _snapshot())["proposal_status"] == "normal"


def test_array_field_selects_the_rendered_intent() -> None:
    result = validate_offer_negotiation(_valid_payload(), _snapshot())
    assert "沟通请求" in result["communication_goals"][0]["text"]
    assert "确认" in result["clarification_questions"][0]["text"]
    assert "表达" in result["talking_points"][0]["text"]
    assert "检查" not in result["talking_points"][0]["text"]
    assert "确认" in result["preparation_checks"][0]["text"]


def test_excerpt_over_limit_is_terminal_limit_exceeded() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"][0]["excerpt"] = "x" * 401
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "limit_exceeded"
    assert len(model.calls) == 1


def test_empty_excerpt_is_structural_and_repairs_once() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"][0]["excerpt"] = ""
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2


def test_whitespace_excerpt_is_semantic_and_not_repaired() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["evidence_refs"][0]["excerpt"] = " \t"
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "excerpt_mismatch"
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        "建议接受这份 Offer。",
        "我的建议如下；由你自行决定接受这份 Offer。",
        "这份 Offer 是首选。",
        "优先选这份 Offer。",
        "我更推荐这份 Offer。",
        "这份 Offer 性价比最高。",
        "I prefer this offer.",
        "Pick this offer.",
        "This offer should be your first choice.",
        "请确认公司政策允许哪些远程办公安排。",
        "公司政策允许远程办公？",
        "请核对公司制度要求的到岗天数。",
        "Does the company policy allow remote work?",
        "公司的政策规定所有人必须到岗。",
        "录用可能性高达 90%。",
        "获聘概率为 90%。",
    ],
)
def test_provider_free_form_language_is_never_accepted(text: str) -> None:
    payload = _valid_payload()
    payload["communication_goals"][0]["text"] = text
    with pytest.raises(OfferNegotiationModelError) as error:
        validate_offer_negotiation(payload, _snapshot())
    assert error.value.validation_category == "invalid_item_shape"


def test_removed_free_form_intent_is_a_shape_failure() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["intent"] = "recommend_accept"
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    result = generate_offer_negotiation_proposal(model, _snapshot())
    assert result["proposal_status"] == "normal"
    assert len(model.calls) == 2


def test_generation_prompt_declares_constrained_contract() -> None:
    model = FakeModel([_json(_valid_payload())])
    generate_offer_negotiation_proposal(model, _snapshot())
    prompt = "\n".join(message.content for message in model.calls[0][0])
    assert "prepare_question" not in prompt
    assert "communication_context" not in prompt
    assert "comparison_dimension" in prompt
    assert '"/offer_snapshot/company_name"' in prompt
    assert '"id":' not in prompt.split("evidence_catalog", 1)[1]


def test_native_schema_uses_the_same_constrained_provider_contract() -> None:
    model = FakeModel([_json(_valid_payload())])
    model.supports_json_schema = True
    generate_offer_negotiation_proposal(model, _snapshot())
    schema = model.calls[0][1]["json_schema"]["schema"]
    item_schema = schema["properties"]["communication_goals"]["items"]
    assert item_schema["required"] == ["id", "topic", "evidence_refs"]
    assert "intent" not in item_schema["properties"]
    assert "text" not in item_schema["properties"]
    assert "rationale" not in item_schema["properties"]


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


@pytest.mark.parametrize("field", ["goal", "concerns", "scenario"])
def test_snapshot_rejects_blank_user_brief(field: str) -> None:
    brief = {"goal": "目标", "concerns": "顾虑", "scenario": "电话"}
    brief[field] = " \t"
    with pytest.raises(ValueError):
        build_offer_negotiation_snapshot(
            offer={"company_name": "公司", "position_name": "职位"},
            dimensions=[],
            user_brief=brief,
            idempotency_key="A" * 16,
        )


def test_limit_exceeded_id_is_terminal_not_repairable() -> None:
    invalid = _valid_payload()
    invalid["communication_goals"][0]["id"] = "x" * 65
    model = FakeModel([_json(invalid), _json(_valid_payload())])
    with pytest.raises(OfferNegotiationModelError) as error:
        generate_offer_negotiation_proposal(model, _snapshot())
    assert error.value.validation_category == "limit_exceeded"
    assert len(model.calls) == 1
