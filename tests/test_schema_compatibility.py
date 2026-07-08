import json
import sqlite3

from offerpilot.db import init_database


def test_chat_messages_have_conversation_foreign_key(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()

    assert any(row[2] == "conversations" and row[3] == "conversation_id" for row in foreign_keys)


def test_application_events_have_application_foreign_key_and_event_columns(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(application_events)").fetchall()
        event_columns = {row[1] for row in conn.execute("PRAGMA table_info(application_events)")}
        legacy_events = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchall()

    assert any(row[2] == "applications" and row[3] == "application_id" for row in foreign_keys)
    assert {"event_type", "subtype", "tags", "round", "scheduled_at", "remind_at"}.issubset(
        event_columns
    )
    assert legacy_events == []


def test_interview_notes_application_foreign_key_sets_null(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(interview_notes)").fetchall()

    assert any(
        row[2] == "applications" and row[3] == "application_id" and row[6] == "SET NULL"
        for row in foreign_keys
    )


def test_knowledge_uses_single_library_documents_without_knowledge_bases(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        document_columns = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_documents)")}
        chunk_columns = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_chunks)")}

    assert "knowledge_bases" not in tables
    assert {"doc_kind", "status", "source_refs", "summary_type", "generation_meta"}.issubset(
        document_columns
    )
    assert "knowledge_base_id" not in document_columns
    assert "knowledge_base_id" not in chunk_columns


def test_init_database_adds_current_chat_context_columns(tmp_path):
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

    assert {"mode", "context_type", "context_ref"}.issubset(conversation_columns)
    assert "offer_id" not in conversation_columns
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


def test_current_chat_context_migration_is_recorded(tmp_path):
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
        conversation_columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}

    assert "0002_chat_state_columns" in versions
    assert {"context_type", "context_ref"}.issubset(conversation_columns)
    assert "offer_id" not in conversation_columns


def test_init_database_backfills_legacy_resume_v01_columns_idempotently(tmp_path):
    db_path = tmp_path / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO schema_migrations (version, description)
            VALUES ('0003_resume_content_columns', 'Add resume content columns')
            """
        )
        conn.execute(
            """
            CREATE TABLE resumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                parsed_data TEXT DEFAULT '',
                parse_status TEXT DEFAULT 'pending',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO resumes (name, file_path, parsed_data, parse_status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "Legacy Backend",
                "resumes/legacy_backend.pdf",
                "Legacy raw resume text",
                "text-ready",
                "2026-07-01 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO resumes (name, file_path, parsed_data, parse_status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "Legacy Frontend",
                "resumes/legacy_frontend.pdf",
                "Frontend raw text",
                "text-ready",
                "2026-07-02 10:00:00",
            ),
        )

    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, title, source_file_path, content_json, is_master
            FROM resumes
            ORDER BY id
            """
        ).fetchall()
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]

    assert rows[0][1] == "Legacy Backend"
    assert rows[0][2] == "resumes/legacy_backend.pdf"
    assert json.loads(rows[0][3]) == {"raw_text": "Legacy raw resume text"}
    assert rows[0][4] == 1
    assert rows[1][1] == "Legacy Frontend"
    assert rows[1][2] == "resumes/legacy_frontend.pdf"
    assert json.loads(rows[1][3]) == {"raw_text": "Frontend raw text"}
    assert rows[1][4] == 0
    assert sum(row[4] for row in rows) == 1
    assert versions.count("0003_resume_content_columns") == 1
    assert versions.count("0004_resume_v01_columns") == 1

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE resumes
            SET title = ?, source_file_path = ?, content_json = ?
            WHERE id = 1
            """,
            (
                "User Edited Title",
                "resumes/user-edited.pdf",
                json.dumps(
                    {"career_intent": {"target_roles": ["Backend Engineer"]}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )

    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows_after_second_init = conn.execute(
            """
            SELECT id, title, source_file_path, content_json, is_master
            FROM resumes
            ORDER BY id
            """
        ).fetchall()
        versions_after_second_init = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]

    assert rows_after_second_init[0] == (
        1,
        "User Edited Title",
        "resumes/user-edited.pdf",
        '{"career_intent":{"target_roles":["Backend Engineer"]}}',
        1,
    )
    assert rows_after_second_init[1] == rows[1]
    assert sum(row[4] for row in rows_after_second_init) == 1
    assert versions_after_second_init.count("0003_resume_content_columns") == 1
    assert versions_after_second_init.count("0004_resume_v01_columns") == 1


def test_init_database_collapses_multiple_active_resume_masters(tmp_path):
    db_path = tmp_path / "data.db"
    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO resumes (name, title, is_master, source, content_json)
            VALUES ('One', 'One', 1, 'manual', '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO resumes (name, title, is_master, source, content_json)
            VALUES ('Two', 'Two', 1, 'manual', '{}')
            """
        )

    init_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, is_master
            FROM resumes
            WHERE deleted_at IS NULL
            ORDER BY id
            """
        ).fetchall()

    assert rows == [(1, 1), (2, 0)]
