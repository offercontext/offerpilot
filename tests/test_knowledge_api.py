from fastapi.testclient import TestClient

from offerpilot.api import create_app


def test_knowledge_base_document_crud_and_search(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    base_response = client.post(
        "/api/knowledge-bases",
        json={"name": "Java interview prep", "description": "core notes"},
    )
    assert base_response.status_code == 201
    base = base_response.json()

    doc_response = client.post(
        "/api/knowledge-documents",
        json={
            "knowledge_base_id": base["id"],
            "title": "Synchronized",
            "content": "monitor lock",
            "tags": ["java"],
        },
    )
    assert doc_response.status_code == 201
    doc = doc_response.json()
    assert doc["tags"] == ["java"]
    assert doc["source_type"] == "manual"

    update_response = client.put(
        f"/api/knowledge-documents/{doc['id']}",
        json={
            "knowledge_base_id": base["id"],
            "title": "Updated",
            "content": "happens before",
            "tags": ["jvm"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["source_type"] == "manual"

    search_response = client.get(f"/api/knowledge/search?q=happens&knowledge_base_id={base['id']}")
    assert search_response.status_code == 200
    results = search_response.json()
    assert len(results) == 1
    assert results[0]["document_title"] == "Updated"
    assert "happens before" in results[0]["snippet"]

    delete_response = client.delete(f"/api/knowledge-bases/{base['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Deleted"}


def test_knowledge_import_validation(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    base = client.post("/api/knowledge-bases", json={"name": "Go notes"}).json()

    imported_response = client.post(
        "/api/knowledge-documents/import",
        data={"knowledge_base_id": str(base["id"])},
        files={"file": ("scheduler.md", b"goroutine scheduler", "text/markdown")},
    )
    assert imported_response.status_code == 201
    imported = imported_response.json()
    assert imported["title"] == "scheduler"
    assert imported["source_type"] == "upload"
    assert imported["source_name"] == "scheduler.md"
    assert imported["tags"] == []

    bad_extension = client.post(
        "/api/knowledge-documents/import",
        data={"knowledge_base_id": str(base["id"])},
        files={"file": ("slides.pdf", b"not allowed", "application/pdf")},
    )
    assert bad_extension.status_code == 400
    assert bad_extension.json() == {"error": "only .md and .txt files are supported"}

    missing_base = client.post(
        "/api/knowledge-documents/import",
        files={"file": ("notes.txt", b"x", "text/plain")},
    )
    assert missing_base.status_code == 400
    assert missing_base.json() == {"error": "knowledge_base_id is required"}


def test_knowledge_validation_errors(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    empty_base = client.post("/api/knowledge-bases", json={"name": "   "})
    assert empty_base.status_code == 400
    assert empty_base.json() == {"error": "name is required"}

    missing_query = client.get("/api/knowledge/search?q=")
    assert missing_query.status_code == 400
    assert missing_query.json() == {"error": "query is required"}

    bad_doc = client.post(
        "/api/knowledge-documents",
        json={"knowledge_base_id": 999, "title": "Missing base", "content": "x"},
    )
    assert bad_doc.status_code == 404
    assert bad_doc.json() == {"error": "Knowledge base not found"}
