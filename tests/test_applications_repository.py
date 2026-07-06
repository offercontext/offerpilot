from datetime import datetime, timezone

from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def test_create_and_list_applications_ordered_by_applied_at(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)

    older = repo.create(
        ApplicationCreate(
            company_name="A",
            position_name="Backend",
            applied_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    newer = repo.create(
        ApplicationCreate(
            company_name="B",
            position_name="Frontend",
            applied_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
    )

    apps = repo.list()

    assert [app.id for app in apps] == [newer.id, older.id]
    assert apps[0].status == "applied"
    assert apps[0].source == "cli"


def test_filter_applications_by_status(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)
    repo.create(ApplicationCreate(company_name="A", position_name="Backend", status="interview"))
    repo.create(ApplicationCreate(company_name="B", position_name="Frontend", status="offer"))

    apps = repo.list(status="interview")

    assert len(apps) == 1
    assert apps[0].company_name == "A"


def test_update_full_replaces_application_fields(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)
    app = repo.create(ApplicationCreate(company_name="A", position_name="Backend", notes="first"))

    updated = repo.update_full(
        app.id,
        ApplicationCreate(
            company_name="B",
            position_name="Frontend",
            job_url="https://example.test",
            status="offer",
            notes="second",
            source="web",
        ),
    )

    assert updated.company_name == "B"
    assert updated.position_name == "Frontend"
    assert updated.job_url == "https://example.test"
    assert updated.status == "offer"
    assert updated.notes == "second"
    assert updated.source == "web"


def test_dashboard_groups_by_status(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    repo = ApplicationsRepository(session_factory)
    repo.create(ApplicationCreate(company_name="A", position_name="Backend", status="interview"))
    repo.create(ApplicationCreate(company_name="B", position_name="Frontend", status="offer"))

    dashboard = repo.dashboard()

    assert dashboard["total"] == 2
    assert len(dashboard["board"]["interview"]) == 1
    assert len(dashboard["board"]["offer"]) == 1

