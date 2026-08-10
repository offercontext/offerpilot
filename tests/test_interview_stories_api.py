from __future__ import annotations


def _note(client) -> dict:
    response = client.post(
        "/api/notes",
        json={
            "company": "星云数据",
            "position": "后端工程师",
            "questions": "你如何排查线上延迟？",
            "self_reflection": "我应该更早同步风险。",
        },
    )
    assert response.status_code == 201
    return response.json()


def _payload(note_id: int) -> dict:
    source = {
        "source_kind": "interview_note",
        "source_id": note_id,
        "source_path": "/questions",
        "excerpt": "你如何排查线上延迟？",
    }
    content = {
        "title": "线上延迟排查",
        "blocks": [{"kind": "situation", "text": "线上出现延迟", "fact_mode": "evidence_backed"}],
        "capability_labels": ["故障排查"],
        "applicable_questions": ["说一次故障处理"],
        "fact_gap_codes": ["missing_result"],
    }
    links = [
        {"target_kind": "title", "target_id": "title", **source},
        {"target_kind": "block", "target_id": "situation_001", **source},
        {"target_kind": "capability_label", "target_id": "capability_001", **source},
        {"target_kind": "applicable_question", "target_id": "question_001", **source},
    ]
    return {
        "content": content,
        "evidence_links": links,
        "selections": [{"source_kind": "interview_note", "source_id": note_id, "path": "/questions"}],
        "assertions": [],
        "expected_current_version_id": None,
    }


def test_manual_story_api_creates_reads_archives_and_restores_without_ai(app_client) -> None:
    note = _note(app_client)
    created = app_client.post("/api/interview-stories", json=_payload(note["id"]))

    assert created.status_code == 201
    story = created.json()
    assert story["title"] == "线上延迟排查"
    assert app_client.get("/api/interview-stories").json()[0]["id"] == story["id"]
    assert app_client.get(f"/api/interview-stories/{story['id']}/versions").json()[0]["version_number"] == 1
    assert app_client.get(
        f"/api/interview-stories/{story['id']}/versions/{story['current_version_id']}"
    ).status_code == 200

    archived = app_client.post(
        f"/api/interview-stories/{story['id']}/archive",
        json={"expected_story_revision": 1},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    restored = app_client.post(
        f"/api/interview-stories/{story['id']}/restore",
        json={"expected_story_revision": 2},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_story_api_rejects_extra_fields_and_never_creates_an_attempt_before_confirmation(app_client) -> None:
    note = _note(app_client)
    payload = _payload(note["id"])
    payload["unexpected"] = True
    response = app_client.post("/api/interview-stories", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_story_invalid_request"
    proposal = app_client.post(
        "/api/interview-story-proposals",
        json={"idempotency_key": "only-this-key-is-not-enough"},
    )
    assert proposal.status_code == 422
