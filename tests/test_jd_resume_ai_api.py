import json

from fastapi.testclient import TestClient

from offerpilot.ai.types import Assistant
from offerpilot.api import create_app


class JSONModel:
    def __init__(self, payloads: list[dict[str, object]]):
        self.payloads = list(payloads)
        self.messages: list[list[object]] = []

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.messages.append(messages)
        return Assistant(content=json.dumps(self.payloads.pop(0), ensure_ascii=False))


def _empty_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << >> /MediaBox [0 0 612 792] >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    xref = b"0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode() for offset in offsets
    )
    return (
        body
        + f"xref\n0 {len(objects) + 1}\n".encode()
        + xref
        + (
            f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )


def test_jd_analyze_requires_text_or_url_before_ai(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/jd/analyze", json={})

    assert response.status_code == 400
    assert response.json() == {"error": "jd_text or jd_url is required"}


def test_jd_analyze_returns_503_without_configured_ai(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/jd/analyze", json={"jd_text": "Backend JD"})

    assert response.status_code == 503
    assert "AI is not configured" in response.json()["error"]


def test_jd_analyze_persists_result_and_list_filters_by_application(tmp_path):
    model = JSONModel(
        [
            {
                "summary": "Backend role",
                "requirements": ["Python"],
                "tech_stack": ["FastAPI"],
                "experience_years": "3-5",
                "education": "本科",
                "highlights": ["AI"],
                "suggestions": ["准备系统设计"],
            }
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    app = client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend"},
    ).json()

    created_response = client.post(
        "/api/jd/analyze",
        json={"application_id": app["id"], "jd_text": "Python FastAPI Backend"},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["application_id"] == app["id"]
    assert created["jd_source"] == "text"
    assert created["result"]["summary"] == "Backend role"

    listed = client.get(f"/api/jd/analyses?application_id={app['id']}").json()
    assert len(listed) == 1
    assert listed[0]["jd_text"] == "Python FastAPI Backend"
    assert json.loads(listed[0]["result"])["summary"] == "Backend role"

    fetched = client.get(f"/api/jd/analyses/{created['id']}").json()
    assert fetched["id"] == created["id"]


def test_resume_match_persists_structured_result(tmp_path):
    model = JSONModel(
        [
            {
                "match_score": 86,
                "matched": ["Python"],
                "gaps": ["Kubernetes"],
                "suggestions": ["补充云原生项目"],
                "summary": "匹配度较高",
            }
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    resume = client.post(
        "/api/resumes",
        json={"name": "Backend resume", "text": "Python FastAPI"},
    ).json()

    created_response = client.post(
        f"/api/resumes/{resume['id']}/match",
        json={"jd_text": "Python Kubernetes"},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["resume_id"] == resume["id"]
    assert created["result"]["match_score"] == 86

    listed = client.get(f"/api/resumes/{resume['id']}/matches").json()
    assert len(listed) == 1
    assert json.loads(listed[0]["result"])["summary"] == "匹配度较高"


def test_resume_match_validates_resume_text_and_jd(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, chat_model=JSONModel([])))
    uploaded = client.post(
        "/api/resumes/upload",
        files={"file": ("sample.pdf", _empty_pdf(), "application/pdf")},
    ).json()

    missing_jd = client.post(f"/api/resumes/{uploaded['id']}/match", json={})
    assert missing_jd.status_code == 400
    assert missing_jd.json() == {"error": "Resume has no text content"}

    missing_resume = client.post("/api/resumes/999/match", json={"jd_text": "x"})
    assert missing_resume.status_code == 404
    assert missing_resume.json() == {"error": "Resume not found"}
