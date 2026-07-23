from __future__ import annotations

from fastapi.testclient import TestClient

from offerpilot.api import create_app


def _create_note(client: TestClient) -> dict[str, object]:
    application = client.post(
        "/api/applications", json={"company_name": "Acme", "position_name": "Backend"}
    ).json()
    event = client.post(
        "/api/application-events",
        json={
            "application_id": application["id"],
            "event_type": "interview",
            "scheduled_at": "2026-07-20T10:00:00Z",
            "duration_minutes": 45,
        },
    ).json()
    return client.post(
        f"/api/applications/{application['id']}/notes",
        json={
            "application_event_id": event["id"],
            "questions": "设计一个缓存",
            "self_reflection": "我解释了淘汰策略",
            "difficulty_points": "说明一致性",
            "mood": "平稳",
        },
    ).json()


def _fragments() -> list[dict[str, object]]:
    return [
        {"fragment_id": "client-1", "path": "/questions", "start": 0, "end": 6, "text": "设计一个缓存"},
        {"fragment_id": "client-2", "path": "/self_reflection", "start": 0, "end": 8, "text": "我解释了淘汰策略"},
    ]


def _preview(client: TestClient, note_id: int, key: str = "attempt-1"):
    return client.post(
        f"/api/notes/{note_id}/knowledge-capture/preview",
        json={"attempt_key": key, "mode": "direct", "selected_fragments": _fragments()},
    )


def test_direct_preview_has_no_knowledge_rows_before_confirm(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    response = _preview(client, int(note["id"]))
    assert response.status_code == 200
    assert response.json()["preview_status"] == "direct_ready"
    assert client.get("/api/knowledge/notes").json() == {"items": []}


def test_confirm_requires_a_verified_preview_attempt(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    response = client.post(
        f"/api/notes/{note['id']}/knowledge-capture/preview",
        json={"attempt_key": "attempt-1", "mode": "direct", "selected_fragments": _fragments()},
    )
    assert response.status_code == 200
    # A fresh key cannot be used to bypass the direct/AI preview gate.
    response = client.post(
        f"/api/notes/{note['id']}/knowledge-capture/confirm",
        json={
            "attempt_key": "attempt-2",
            "note_fingerprint": response.json()["note_fingerprint"],
            "title": "绕过预览",
            "blocks": response.json()["preview"]["blocks"],
        },
    )
    assert response.status_code == 404


def test_confirm_creates_frozen_knowledge_and_is_idempotent(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    attempt = _preview(client, int(note["id"])).json()
    content = attempt["preview"]
    payload = {
        "attempt_key": attempt["attempt_key"],
        "note_fingerprint": attempt["note_fingerprint"],
        "title": "缓存面试复盘",
        "blocks": content["blocks"],
    }
    first = client.post(f"/api/notes/{note['id']}/knowledge-capture/confirm", json=payload)
    second = client.post(f"/api/notes/{note['id']}/knowledge-capture/confirm", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["version_id"] == first.json()["version_id"]
    listing = client.get("/api/knowledge/notes")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["origin_kind"] == "confirmed_interview_capture"


def test_note_edit_before_confirm_returns_409_without_knowledge_asset(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    attempt = _preview(client, int(note["id"])).json()
    updated = dict(note)
    updated["questions"] = "变化后的问题"
    assert client.put(f"/api/notes/{note['id']}", json=updated).status_code == 200
    response = client.post(
        f"/api/notes/{note['id']}/knowledge-capture/confirm",
        json={
            "attempt_key": attempt["attempt_key"],
            "note_fingerprint": attempt["note_fingerprint"],
            "title": "缓存面试复盘",
            "blocks": attempt["preview"]["blocks"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "interview_knowledge_source_changed"
    assert client.get("/api/knowledge/notes").json() == {"items": []}


def test_delete_unconfirmed_attempt_is_idempotent(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    attempt = _preview(client, int(note["id"])).json()
    path = f"/api/notes/{note['id']}/knowledge-capture/attempts/{attempt['attempt_key']}"
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 204
    assert client.get("/api/knowledge/notes").json() == {"items": []}


def test_delete_confirmed_attempt_returns_conflict(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    attempt = _preview(client, int(note["id"])).json()
    confirm = client.post(
        f"/api/notes/{note['id']}/knowledge-capture/confirm",
        json={
            "attempt_key": attempt["attempt_key"],
            "note_fingerprint": attempt["note_fingerprint"],
            "title": "缂撳瓨闈㈣瘯澶嶇洏",
            "blocks": attempt["preview"]["blocks"],
        },
    )
    assert confirm.status_code == 201
    path = f"/api/notes/{note['id']}/knowledge-capture/attempts/{attempt['attempt_key']}"
    response = client.delete(path)
    assert response.status_code == 409
    assert response.json()["error_code"] == "capture_attempt_confirmed"


def test_confirmed_knowledge_remains_auditable_after_event_deletion(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path))
    note = _create_note(client)
    attempt = _preview(client, int(note["id"])).json()
    confirm = client.post(
        f"/api/notes/{note['id']}/knowledge-capture/confirm",
        json={
            "attempt_key": attempt["attempt_key"],
            "note_fingerprint": attempt["note_fingerprint"],
            "title": "缂撳瓨闈㈣瘯澶嶇洏",
            "blocks": attempt["preview"]["blocks"],
        },
    )
    assert confirm.status_code == 201
    assert client.delete(f"/api/application-events/{note['application_event_id']}").status_code == 200
    items = client.get("/api/knowledge/notes").json()["items"]
    assert len(items) == 1
    assert items[0]["source_status"] == "source_changed"
    assert items[0]["content"]["blocks"]
