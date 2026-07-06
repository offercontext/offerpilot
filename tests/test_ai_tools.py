import json

from offerpilot.ai.tools import application_tool_registry
from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def test_application_read_tools_return_json(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(
        ApplicationCreate(company_name="ByteDance", position_name="Backend", status="interview")
    )
    registry = application_tool_registry(repo)

    listed = json.loads(registry["list_applications"]["handler"](json.dumps({"status": "interview"})))
    detail = json.loads(registry["get_application"]["handler"](json.dumps({"id": created.id})))

    assert listed[0]["company_name"] == "ByteDance"
    assert detail["id"] == created.id


def test_application_write_tools_are_marked_and_mutate_when_executed(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    assert registry["create_application"]["write"] is True
    assert registry["update_application_status"]["write"] is True

    updated = json.loads(
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "offer"})
        )
    )

    assert updated["status"] == "offer"
    assert repo.get(created.id).status == "offer"  # type: ignore[union-attr]

