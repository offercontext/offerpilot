from sqlalchemy import text

from offerpilot.db import init_database


def test_adaptive_practice_schema_is_created_and_idempotent(tmp_path) -> None:
    first = init_database(tmp_path / "data.db")
    first.kw["bind"].dispose()
    second = init_database(tmp_path / "data.db")

    with second() as session:
        columns = {
            row[1]
            for row in session.execute(text("PRAGMA table_info(adaptive_practice_plans)"))
        }
        migrations = set(
            session.execute(text("SELECT version FROM schema_migrations")).scalars()
        )

    second.kw["bind"].dispose()
    assert {
        "id",
        "application_id",
        "application_event_id",
        "interview_note_id",
        "interview_review_proposal_id",
        "focus_id",
        "status",
        "revision",
        "source_path",
        "source_excerpt",
        "source_hash",
        "start_idempotency_key",
        "completion_idempotency_key",
        "response_text",
        "self_assessment",
    } <= columns
    assert "0021_adaptive_interview_practice" in migrations

