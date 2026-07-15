"""Knowledge 删除协议的故障注入测试。"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.db import init_database, session_factory_for_data_dir
from offerpilot.knowledge.repository import KnowledgeRepository
from offerpilot.knowledge.service import IngestRequest, KnowledgeIngestService


def _upload(client: TestClient, name: str, content: bytes) -> int:
    response = client.post(
        "/api/knowledge/sources",
        files={"file": (name, content, "text/markdown")},
    )
    assert response.status_code == 202
    return int(response.json()["source"]["id"])


def test_purge_does_not_delete_db_when_quarantine_move_fails(tmp_path, monkeypatch):
    session_factory = session_factory_for_data_dir(tmp_path)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, tmp_path, session_factory)
    result = service.ingest(
        IngestRequest(filename="doc.md", content_bytes=b"# title\n\nbody\n")
    )
    source_id = result.source.id
    source_dir = tmp_path / "knowledge" / "sources" / str(source_id)

    def fail_move(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr("offerpilot.knowledge.service.shutil.move", fail_move)
    assert service.purge_source(source_id) is None

    with sqlite3.connect(tmp_path / "data.db") as conn:
        row = conn.execute(
            "SELECT lifecycle FROM knowledge_sources WHERE id = ?", (source_id,)
        ).fetchone()
    assert row == ("deleting",)
    assert source_dir.is_dir()


def test_startup_recovery_handles_deleting_source_without_quarantine_root(tmp_path):
    session_factory = session_factory_for_data_dir(tmp_path)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, tmp_path, session_factory)
    result = service.ingest(
        IngestRequest(filename="doc.md", content_bytes=b"# title\n\nbody\n")
    )
    source_id = result.source.id
    assert repository.begin_delete(source_id) is not None
    quarantine_root = tmp_path / "knowledge" / "quarantine"
    assert not quarantine_root.exists()

    init_database(tmp_path / "data.db")

    with sqlite3.connect(tmp_path / "data.db") as conn:
        assert conn.execute(
            "SELECT id FROM knowledge_sources WHERE id = ?", (source_id,)
        ).fetchone() is None
    assert not (tmp_path / "knowledge" / "sources" / str(source_id)).exists()


def test_purge_removes_only_traces_referencing_deleted_source(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    deleted_id = _upload(client, "deleted.md", b"# deleted\n\nneedle-a\n")
    kept_id = _upload(client, "kept.md", b"# kept\n\nneedle-b\n")

    deleted_search = client.post(
        "/api/knowledge/evidence/search", json={"query": "needle-a"}
    )
    kept_search = client.post(
        "/api/knowledge/evidence/search", json={"query": "needle-b"}
    )
    assert deleted_search.status_code == 200
    assert kept_search.status_code == 200
    assert deleted_search.json()["hits"]
    assert kept_search.json()["hits"]

    assert client.delete(f"/api/knowledge/sources/{deleted_id}").status_code == 202

    with sqlite3.connect(tmp_path / "data.db") as conn:
        traces = conn.execute(
            "SELECT hits_json FROM knowledge_retrieval_traces"
        ).fetchall()
    assert traces
    assert all(f'"source_id": {deleted_id}' not in row[0] for row in traces)
    assert any(f'"source_id": {kept_id}' in row[0] for row in traces)


def test_get_source_hides_deleting_source(tmp_path):
    session_factory = session_factory_for_data_dir(tmp_path)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, tmp_path, session_factory)
    result = service.ingest(
        IngestRequest(filename="doc.md", content_bytes=b"# title\n\nbody\n")
    )
    assert repository.begin_delete(result.source.id) is not None
    assert repository.get_source(result.source.id) is None
