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
        "idempotency_key": "manual-story-api-key-0001",
    }


def test_manual_story_api_creates_reads_archives_and_restores_without_ai(app_client) -> None:
    note = _note(app_client)
    created = app_client.post("/api/interview-stories", json=_payload(note["id"]))

    assert created.status_code == 201
    story = created.json()
    replay = app_client.post("/api/interview-stories", json=_payload(note["id"]))
    assert replay.status_code == 201
    assert replay.json()["id"] == story["id"]
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


def test_story_write_endpoints_reject_malformed_nested_payloads_as_422(app_client) -> None:
    note = _note(app_client)
    malformed_create = _payload(note["id"])
    malformed_create["content"] = []
    assert app_client.post("/api/interview-stories", json=malformed_create).status_code == 422

    created = app_client.post("/api/interview-stories", json=_payload(note["id"])).json()
    malformed_version = _payload(note["id"])
    malformed_version["expected_current_version_id"] = created["current_version_id"]
    malformed_version["expected_story_revision"] = created["story_revision"]
    malformed_version["idempotency_key"] = "manual-story-malformed-version-01"
    malformed_version["evidence_links"] = ["not-an-evidence-object"]
    assert app_client.post(
        f"/api/interview-stories/{created['id']}/versions", json=malformed_version
    ).status_code == 422

    malformed_confirmation = {
        "confirmation_token": "story-malformed-confirm-token-01",
        "content": "not-an-object",
        "evidence_links": [],
        "expected_current_version_id": None,
        "expected_story_revision": None,
    }
    assert app_client.post(
        "/api/interview-story-proposals/999/confirm", json=malformed_confirmation
    ).status_code == 422


def test_story_confirmation_api_rejects_non_strict_cas_values_before_attempt_lookup(app_client) -> None:
    for expected_current_version_id, expected_story_revision in (
        (True, None),
        (1.0, None),
        ("1", None),
        (0, None),
        (None, True),
        (None, 1.0),
        (None, "1"),
        (None, 0),
    ):
        response = app_client.post(
            "/api/interview-story-proposals/999/confirm",
            json={
                "confirmation_token": "story-confirm-strict-cas-0001",
                "content": {},
                "evidence_links": [],
                "expected_current_version_id": expected_current_version_id,
                "expected_story_revision": expected_story_revision,
            },
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "interview_story_invalid_request"


def test_manual_story_api_rejects_non_null_or_non_integer_new_version_cas(app_client) -> None:
    note = _note(app_client)
    for value in (True, "1", 0, 1):
        payload = _payload(note["id"])
        payload["expected_current_version_id"] = value
        payload["idempotency_key"] = f"manual-story-invalid-cas-{str(value).lower()}-01"
        response = app_client.post("/api/interview-stories", json=payload)
        assert response.status_code == 422
        assert response.json()["error_code"] == "interview_story_invalid_request"


def test_story_proposal_api_accepts_only_a_scoped_review_note_context(app_client) -> None:
    note = _note(app_client)
    payload = {
        "target_story_id": None,
        "expected_current_version_id": None,
        "expected_story_revision": None,
        "selections": [{"source_kind": "interview_note", "source_id": note["id"], "path": "/questions"}],
        "assertions": ["I owned this incident."],
        "idempotency_key": "story-context-key-0001",
        "entry_context": {"review_note_id": 1, "untrusted_text": "do not persist"},
    }

    response = app_client.post("/api/pilot/interview-story-proposals", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_story_invalid_request"


def test_saved_review_story_proposal_rejects_unrelated_sources(app_client) -> None:
    note = _note(app_client)
    resume = app_client.post(
        "/api/resumes",
        json={"title": "筱哲的后端简历", "content_json": {"projects": [{"detail": "排查延迟"}]}},
    ).json()
    payload = {
        "target_story_id": None,
        "expected_current_version_id": None,
        "expected_story_revision": None,
        "selections": [
            {"source_kind": "interview_note", "source_id": note["id"], "path": "/questions"},
            {"source_kind": "resume_version", "source_id": resume["id"], "path": "/content_json/projects/0/detail"},
        ],
        "assertions": [],
        "idempotency_key": "story-scoped-source-key-01",
        "entry_context": {"review_note_id": note["id"]},
    }

    response = app_client.post("/api/pilot/interview-story-proposals", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "interview_story_invalid_request"


def test_story_source_picker_returns_only_bounded_explicit_candidates(app_client) -> None:
    note = _note(app_client)
    resume = app_client.post(
        "/api/resumes",
        json={
            "title": "筱哲的后端简历",
            "content_json": {"projects": [{"name": "延迟排查", "detail": "定位了缓存击穿"}]},
        },
    )
    assert resume.status_code == 201

    candidates = app_client.get("/api/interview-story-sources")
    assert candidates.status_code == 200
    payload = candidates.json()
    assert payload["resumes"][0]["id"] == resume.json()["id"]
    assert payload["resumes"][0]["leaves"][0]["path"].startswith("/content_json/")
    assert payload["interview_notes"][0]["id"] == note["id"]
    assert "preview" in payload["interview_notes"][0]["leaves"][0]

    scoped = app_client.get(f"/api/interview-story-sources?review_note_id={note['id']}")
    assert scoped.status_code == 200
    assert scoped.json()["resumes"] == []
    assert scoped.json()["interview_notes"] == [payload["interview_notes"][0]]
