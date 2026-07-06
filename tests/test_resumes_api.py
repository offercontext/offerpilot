from fastapi.testclient import TestClient

from offerpilot.api import create_app


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> "
            b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
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


def test_create_list_get_and_delete_resume(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    created_response = client.post(
        "/api/resumes",
        json={"name": "Backend resume", "text": "Python and systems"},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["name"] == "Backend resume"
    assert created["parsed_data"] == "Python and systems"
    assert created["parse_status"] == "text-ready"

    list_response = client.get("/api/resumes")
    assert list_response.status_code == 200
    assert [resume["id"] for resume in list_response.json()] == [created["id"]]

    get_response = client.get(f"/api/resumes/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]

    delete_response = client.delete(f"/api/resumes/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Deleted"}


def test_create_resume_requires_text(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post("/api/resumes", json={"name": "Empty"})

    assert response.status_code == 400
    assert response.json() == {"error": "text is required"}


def test_upload_resume_rejects_non_pdf(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/resumes/upload",
        files={"file": ("resume.docx", b"not a pdf", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "only .pdf files are supported"}


def test_upload_resume_saves_original_file_for_download(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    pdf_data = _pdf_with_text("Hello Resume Python")

    response = client.post(
        "/api/resumes/upload",
        files={"file": ("sample.pdf", pdf_data, "application/pdf")},
    )

    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["name"] == "sample"
    assert uploaded["file_path"] == f"resumes/{uploaded['id']}_sample.pdf"
    assert uploaded["parse_status"] == "text-ready"
    assert "Hello Resume Python" in uploaded["parsed_data"]

    download = client.get(f"/api/resumes/{uploaded['id']}/file")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content == pdf_data


def test_update_resume_text_and_missing_file_responses(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))
    created = client.post(
        "/api/resumes",
        json={"name": "Needs repair", "text": "old"},
    ).json()

    update = client.put(f"/api/resumes/{created['id']}/text", json={"text": "corrected"})

    assert update.status_code == 200
    assert update.json() == {"message": "Updated"}
    assert client.get(f"/api/resumes/{created['id']}").json()["parsed_data"] == "corrected"

    no_file = client.get(f"/api/resumes/{created['id']}/file")
    assert no_file.status_code == 404
    assert no_file.json() == {"error": "resume has no original file"}

    missing_update = client.put("/api/resumes/999/text", json={"text": "x"})
    assert missing_update.status_code == 404
    assert missing_update.json() == {"error": "Resume not found"}
