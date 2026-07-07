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


def test_application_tool_schemas_require_detail_ids(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    registry = application_tool_registry(repo)

    get_schema = registry["get_application"]["schema"]
    update_schema = registry["update_application_status"]["schema"]

    assert get_schema["required"] == ["id"]
    assert update_schema["required"] == ["id", "status"]
    assert "id" in get_schema["properties"]
    assert "id" in update_schema["properties"]


def test_get_application_requires_id_with_readable_error(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    registry = application_tool_registry(repo)

    try:
        registry["get_application"]["handler"](json.dumps({}))
    except ValueError as exc:
        assert str(exc) == "get_application requires id"
    else:
        raise AssertionError("missing id should raise a readable error")


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


def test_application_status_tool_normalizes_legacy_status(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    updated = json.loads(
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "assessment"})
        )
    )

    assert updated["status"] == "written_test"
    assert repo.get(created.id).status == "written_test"  # type: ignore[union-attr]


def test_application_status_tool_rejects_invalid_status(tmp_path):
    repo = ApplicationsRepository(init_database(tmp_path / "data.db"))
    created = repo.create(ApplicationCreate(company_name="ByteDance", position_name="Backend"))
    registry = application_tool_registry(repo)

    try:
        registry["update_application_status"]["handler"](
            json.dumps({"id": created.id, "status": "onsite"})
        )
    except ValueError as exc:
        assert str(exc) == "invalid application status: onsite"
    else:
        raise AssertionError("invalid status should raise")

