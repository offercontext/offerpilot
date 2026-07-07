import sqlite3

from offerpilot.db import init_database


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


def test_init_database_creates_idempotent_schema_migration_log(tmp_path):
    db_path = tmp_path / "data.db"

    init_database(db_path)
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(schema_migrations)")}
        rows = conn.execute(
            "SELECT version, description FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert {"version", "description", "applied_at"}.issubset(columns)
    assert rows.count(("0001_base_schema", "Create current application tables")) == 1


def test_legacy_additive_chat_migration_is_recorded(tmp_path):
    db_path = tmp_path / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE conversations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "title TEXT NOT NULL DEFAULT 'legacy',"
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
        versions = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert "0002_chat_state_columns" in versions
