from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.config import Config, SkillPackage, load_config, save_config


def test_skills_api_registers_untrusted_package(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.post(
        "/api/skills",
        json={
            "id": "resume-coach",
            "label": "Resume Coach",
            "version": "0.1.0",
            "source": "file:///skills/resume-coach",
        },
    )

    assert response.status_code == 201
    assert response.json()["packages"] == [
        {
            "id": "resume-coach",
            "label": "Resume Coach",
            "version": "0.1.0",
            "source": "file:///skills/resume-coach",
            "trusted": False,
            "enabled": False,
            "loaded": False,
        }
    ]
    assert response.json()["loaded"] == []


def test_skills_api_requires_trust_before_enable(tmp_path):
    save_config(
        tmp_path,
        Config(
            skills=[
                SkillPackage(
                    id="resume-coach",
                    label="Resume Coach",
                    source="file:///skills/resume-coach",
                    trusted=False,
                    enabled=False,
                )
            ]
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put("/api/skills/resume-coach", json={"enabled": True})

    assert response.status_code == 400
    assert response.json()["error"] == "skill must be trusted before enabling"


def test_skills_api_loads_only_trusted_enabled_packages(tmp_path):
    save_config(
        tmp_path,
        Config(
            skills=[
                SkillPackage(
                    id="resume-coach",
                    label="Resume Coach",
                    source="file:///skills/resume-coach",
                    trusted=False,
                    enabled=False,
                )
            ]
        ),
    )
    client = TestClient(create_app(data_dir=tmp_path))

    response = client.put("/api/skills/resume-coach", json={"trusted": True, "enabled": True})

    assert response.status_code == 200
    assert response.json()["loaded"] == ["resume-coach"]
    assert response.json()["packages"][0]["loaded"] is True

    cfg = load_config(tmp_path)
    assert cfg.skills[0].trusted is True
    assert cfg.skills[0].enabled is True
