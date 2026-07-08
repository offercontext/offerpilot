from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_knowledge_document_crud_and_search_in_single_library(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    assert client.get("/api/knowledge-bases").status_code == 404

    doc_response = client.post(
        "/api/knowledge-documents",
        json={
            "title": "Synchronized",
            "content": "monitor lock",
            "tags": ["java"],
        },
    )
    assert doc_response.status_code == 201
    doc = doc_response.json()
    assert doc["tags"] == ["java"]
    assert doc["source_type"] == "manual"
    assert doc["doc_kind"] == "wiki"
    assert doc["status"] == "confirmed"
    assert "knowledge_base_id" not in doc

    update_response = client.put(
        f"/api/knowledge-documents/{doc['id']}",
        json={
            "title": "Updated",
            "content": "happens before",
            "tags": ["jvm"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["source_type"] == "manual"

    search_response = client.get("/api/knowledge/search?q=happens")
    assert search_response.status_code == 200
    results = search_response.json()
    assert len(results) == 1
    assert results[0]["document_title"] == "Updated"
    assert "happens before" in results[0]["snippet"]
    delete_response = client.delete(f"/api/knowledge-documents/{doc['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Deleted"}


def test_knowledge_search_returns_ranked_source_chunks(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    client.post(
        "/api/knowledge-documents",
        json={
            "title": "General notes",
            "content": "network latency\n\ncache invalidation",
            "tags": ["systems"],
        },
    )
    client.post(
        "/api/knowledge-documents",
        json={
            "title": "Backpressure",
            "content": "reactive streams\n\nbackpressure demand signal",
            "tags": ["systems"],
        },
    )

    response = client.get("/api/knowledge/search?q=backpressure signal")

    assert response.status_code == 200
    results = response.json()
    assert results[0]["document_title"] == "Backpressure"
    assert results[0]["chunk_index"] == 1
    assert results[0]["score"] > 0
    assert results[0]["source_name"] == ""
    assert "knowledge_base_id" not in results[0]
    assert "backpressure demand signal" in results[0]["snippet"]


def test_knowledge_search_index_tracks_updates_and_deletes(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    doc = client.post(
        "/api/knowledge-documents",
        json={
            "title": "Mutable",
            "content": "stale token",
            "tags": [],
        },
    ).json()

    update_response = client.put(
        f"/api/knowledge-documents/{doc['id']}",
        json={
            "title": "Mutable",
            "content": "fresh token",
            "tags": [],
        },
    )
    old_search = client.get("/api/knowledge/search?q=stale")
    fresh_search = client.get("/api/knowledge/search?q=fresh")
    delete_response = client.delete(f"/api/knowledge-documents/{doc['id']}")
    deleted_search = client.get("/api/knowledge/search?q=fresh")

    assert update_response.status_code == 200
    assert old_search.json() == []
    assert fresh_search.json()[0]["document_id"] == doc["id"]
    assert delete_response.status_code == 200
    assert deleted_search.json() == []


def test_knowledge_import_validation(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    imported_response = client.post(
        "/api/knowledge-documents/import",
        files={"file": ("scheduler.md", b"goroutine scheduler", "text/markdown")},
    )
    assert imported_response.status_code == 201
    imported = imported_response.json()
    assert imported["title"] == "scheduler"
    assert imported["source_type"] == "markdown"
    assert imported["source_name"] == "scheduler.md"
    assert imported["tags"] == []

    bad_extension = client.post(
        "/api/knowledge-documents/import",
        files={"file": ("slides.pdf", b"not allowed", "application/pdf")},
    )
    assert bad_extension.status_code == 400
    assert bad_extension.json() == {"error": "only .md and .txt files are supported"}


def test_knowledge_validation_errors(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    missing_query = client.get("/api/knowledge/search?q=")
    assert missing_query.status_code == 400
    assert missing_query.json() == {"error": "query is required"}

    bad_doc = client.post(
        "/api/knowledge-documents",
        json={"title": "   ", "content": "x"},
    )
    assert bad_doc.status_code == 400
    assert bad_doc.json() == {"error": "title is required"}
