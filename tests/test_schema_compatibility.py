import sqlite3

from offerpilot.db import init_database
from offerpilot.repositories.applications import ApplicationsRepository


def test_chat_messages_have_conversation_foreign_key(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()

    assert any(row[2] == "conversations" and row[3] == "conversation_id" for row in foreign_keys)


def test_events_have_application_foreign_key(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(events)").fetchall()

    assert any(row[2] == "applications" and row[3] == "application_id" for row in foreign_keys)


def test_interview_notes_application_foreign_key_sets_null(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(interview_notes)").fetchall()

    assert any(
        row[2] == "applications" and row[3] == "application_id" and row[6] == "SET NULL"
        for row in foreign_keys
    )


def test_init_database_adds_legacy_chat_columns(tmp_path):
    db_path = tmp_path / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE conversations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "title TEXT NOT NULL DEFAULT '新对话',"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.execute(
            "CREATE TABLE chat_messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "conversation_id INTEGER NOT NULL,"
            "role TEXT NOT NULL,"
            "content TEXT DEFAULT '',"
            "tool_calls TEXT DEFAULT '',"
            "tool_call_id TEXT DEFAULT '',"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )

    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        conversation_columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}
        message_columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)")}

    assert {"offer_id", "mode"}.issubset(conversation_columns)
    assert "provider_blocks" in message_columns


def test_init_database_normalizes_go_datetime_strings(tmp_path):
    db_path = tmp_path / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE applications ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "company_name TEXT NOT NULL,"
            "position_name TEXT NOT NULL,"
            "job_url TEXT DEFAULT '',"
            "status TEXT NOT NULL DEFAULT 'applied',"
            "source TEXT NOT NULL DEFAULT 'cli',"
            "notes TEXT DEFAULT '',"
            "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.execute(
            "INSERT INTO applications "
            "(company_name, position_name, applied_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "Acme",
                "Backend",
                "2026-07-01 07:00:00 +0000 UTC",
                "2026-06-30 00:04:42.5044807 +0800 CST m=+682.629707701",
                "2026-06-30 00:04:42.5044807 +0800 CST m=+682.629707701",
            ),
        )

    session_factory = init_database(db_path)
    apps = ApplicationsRepository(session_factory).list()

    assert apps[0].company_name == "Acme"
    assert apps[0].created_at.isoformat() == "2026-06-29T16:04:42.504480"
