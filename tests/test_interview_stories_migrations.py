from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from offerpilot.db import init_database


STORY_TABLES = {
    "interview_stories",
    "interview_story_versions",
    "interview_story_version_evidence_links",
    "interview_story_user_assertions",
    "interview_story_proposal_attempts",
}


def _dispose(factory) -> None:  # type: ignore[no-untyped-def]
    factory.kw["bind"].dispose()


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_fresh_database_creates_story_phase_one_tables_and_records_0019(tmp_path: Path) -> None:
    db_path = tmp_path / "story.db"

    factory = init_database(db_path)
    with factory() as session:
        migrations = set(
            session.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
    _dispose(factory)

    tables = _table_names(db_path)

    assert STORY_TABLES <= tables
    assert "0019_interview_story_library" in migrations
    assert "interview_story_usage" not in tables


def test_story_migration_coexists_with_jd_0018_marker_and_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "jd-then-story.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migrations(version, description)
            VALUES ('0018_application_jd_versions', 'application JD versions');
            CREATE TABLE application_jd_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                jd_text TEXT NOT NULL
            );
            """
        )
        connection.commit()

    factory = init_database(db_path)
    with factory() as session:
        migrations = set(
            session.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
        jd_columns = {
            row[1]
            for row in session.execute(text("PRAGMA table_info(application_jd_versions)"))
        }
    _dispose(factory)

    assert STORY_TABLES <= _table_names(db_path)
    assert {"0018_application_jd_versions", "0019_interview_story_library"} <= migrations
    assert {"id", "application_id", "version_number", "jd_text"} <= jd_columns
