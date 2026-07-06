import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class JSONModel:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return Assistant(
            content=json.dumps(
                {
                    "resume_advice": {
                        "summary": "Strong Go fit",
                        "highlights": ["Go"],
                        "rewrite_bullets": ["Built APIs"],
                        "gaps": [],
                        "notes": "",
                    },
                    "messages": [
                        {
                            "type": "recruiter_email",
                            "title": "Intro",
                            "body": "Hello",
                            "notes": "",
                        }
                    ],
                    "checklist": [{"id": "select_resume", "label": "Select resume", "done": False}],
                }
            )
        )


def test_get_application_material_kit_missing(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    app = client.post(
        "/api/applications",
        json={"company_name": "Acme", "position_name": "Backend"},
    ).json()

    response = client.get(f"/api/applications/{app['id']}/material-kit")

    assert response.status_code == 404
    assert response.json() == {"error": "Material kit not found"}


def test_generate_update_and_conflict_material_kit(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, chat_model=JSONModel()))
    app = client.post(
        "/api/applications",
        json={"company_name": "Acme", "position_name": "Backend"},
    ).json()
    resume = client.post(
        "/api/resumes",
        json={"name": "Backend", "text": "Built Go APIs"},
    ).json()

    missing_resume = client.post(
        f"/api/applications/{app['id']}/material-kit/generate",
        json={"jd_text": "Go backend JD"},
    )
    assert missing_resume.status_code == 400
    assert missing_resume.json() == {"error": "resume_id is required"}

    created_response = client.post(
        f"/api/applications/{app['id']}/material-kit/generate",
        json={"resume_id": resume["id"], "jd_text": "Go backend JD"},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "draft"
    assert created["resume_id"] == resume["id"]
    assert json.loads(created["content_json"])["resume_advice"]["summary"] == "Strong Go fit"

    conflict = client.post(
        f"/api/applications/{app['id']}/material-kit/generate",
        json={"resume_id": resume["id"], "jd_text": "Go backend JD"},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"error": "Material kit already exists"}

    updated_response = client.put(
        f"/api/material-kits/{created['id']}",
        json={"status": "ready", "content_json": {"checklist": [{"id": "x", "done": True}]}},
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["status"] == "ready"
    assert json.loads(updated["content_json"]) == {"checklist": [{"id": "x", "done": True}]}
