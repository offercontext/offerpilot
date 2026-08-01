from __future__ import annotations

import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class FakeModel:
    supports_json_schema = False

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[list] = []

    def complete(self, messages, tools, response_format=None):
        self.calls.append([messages, response_format])
        if self.error is not None:
            raise self.error
        return Assistant(content=self.responses.pop(0), provider_blocks={"request_id": "req-1"})


def _offer(client: TestClient) -> dict:
    response = client.post(
        "/api/offers",
        json={
            "company_name": "星云数据",
            "position_name": "后端工程师",
            "base_monthly": 28000,
            "months_per_year": 12,
            "signing_bonus": 0,
        },
    )
    assert response.status_code == 201
    return response.json()


def _payload() -> dict:
    item = {
        "text": "确认岗位信息",
        "rationale": "依据冻结 Offer",
        "evidence_refs": [
            {"source": "offer_snapshot", "path": "/offer_snapshot/company_name", "excerpt": "星云数据"}
        ],
    }
    return {
        "proposal_status": "normal",
        "communication_goals": [{**item, "id": "goal-1"}],
        "clarification_questions": [
            {
                **item,
                "id": "question-1",
                "evidence_refs": [
                    {"source": "user_brief", "path": "/user_brief/goal", "excerpt": "争取入职时间"}
                ],
            }
        ],
        "talking_points": [
            {
                **item,
                "id": "point-1",
                "evidence_refs": [
                    {"source": "offer_snapshot", "path": "/offer_snapshot/base_monthly", "excerpt": "28000"}
                ],
            }
        ],
        "preparation_checks": [{**item, "id": "check-1"}],
    }


def _request(client: TestClient, key: str = "A" * 16) -> object:
    return client.post(
        "/api/offers/1/negotiation/proposals",
        json={
            "idempotency_key": key,
            "dimension_ids": [],
            "goal": "争取入职时间",
            "concerns": "通勤",
            "scenario": "电话沟通",
        },
    )


def test_generation_replay_is_immutable_and_payload_has_no_database_ids(tmp_path) -> None:
    model = FakeModel([json.dumps(_payload(), ensure_ascii=False)])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    _offer(client)
    response = _request(client)
    assert response.status_code == 201
    body = response.json()
    assert body["proposal_status"] == "normal"
    assert "input_snapshot" not in body
    assert '"id":' not in model.calls[0][0][1].content

    replay = _request(client)
    assert replay.status_code == 200
    assert replay.json()["id"] == body["id"]
    assert len(model.calls) == 1


def test_semantic_failure_is_502_and_same_key_does_not_call_again(tmp_path) -> None:
    invalid = _payload()
    invalid["communication_goals"][0]["evidence_refs"][0]["source"] = "attacker"
    model = FakeModel([json.dumps(invalid, ensure_ascii=False), json.dumps(_payload(), ensure_ascii=False)])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    _offer(client)
    response = _request(client, "B" * 16)
    assert response.status_code == 502
    assert response.json()["error_code"] == "offer_negotiation_unverifiable"
    replay = _request(client, "B" * 16)
    assert replay.status_code == 502
    assert replay.json()["error_code"] == "offer_negotiation_unverifiable"
    assert len(model.calls) == 1


def test_provider_error_preserves_attempt_and_key(tmp_path) -> None:
    model = FakeModel(error=TimeoutError("provider timeout"))
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    _offer(client)
    response = _request(client, "C" * 16)
    assert response.status_code == 502
    assert response.json()["error_code"] == "offer_negotiation_provider_error"
    pending = _request(client, "C" * 16)
    assert pending.status_code == 202
    assert pending.json()["attempt_status"] == "provider_unknown"
    assert len(model.calls) == 1


def test_history_is_readable_after_offer_delete(tmp_path) -> None:
    model = FakeModel([json.dumps(_payload(), ensure_ascii=False)])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    offer = _offer(client)
    response = _request(client, "D" * 16)
    proposal_id = response.json()["id"]
    assert client.delete(f"/api/offers/{offer['id']}").status_code in {200, 204}
    history = client.get(f"/api/offer-negotiation/proposals/{proposal_id}")
    assert history.status_code == 200
    assert history.json()["source_changed"] is True


def test_confirmation_is_hitl_idempotent_and_history_retains_brief(tmp_path) -> None:
    model = FakeModel([json.dumps(_payload(), ensure_ascii=False)])
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    offer = _offer(client)
    generated = _request(client, "E" * 16)
    proposal_id = generated.json()["id"]
    confirm_payload = {
        "confirmation_key": "F" * 16,
        "selected_blocks": ["goal-1", "point-1"],
        "edited_content": {"goal-1": "我想确认入职时间"},
    }
    confirmed = client.post(
        f"/api/offer-negotiation/proposals/{proposal_id}/confirm", json=confirm_payload
    )
    assert confirmed.status_code == 201
    replay = client.post(
        f"/api/offer-negotiation/proposals/{proposal_id}/confirm", json=confirm_payload
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == confirmed.json()["id"]
    assert client.put(
        f"/api/offers/{offer['id']}",
        json={
            "company_name": "星云数据",
            "position_name": "后端工程师",
            "base_monthly": 28000,
            "months_per_year": 12,
            "signing_bonus": 0,
            "notes": "更新后的备注",
        },
    ).status_code == 200
    history = client.get(f"/api/offer-negotiation/proposals/{proposal_id}")
    assert history.status_code == 200
    assert history.json()["source_changed"] is True
    assert history.json()["brief"]["selected_blocks"] == ["goal-1", "point-1"]
