from pathlib import Path
import sqlite3

from sqlalchemy import text

from offerpilot.db import init_database


def _write_legacy_mock_database(path: Path, *, with_named_indexes: bool = True) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, description TEXT NOT NULL);
            CREATE TABLE applications (id INTEGER PRIMARY KEY, company_name TEXT NOT NULL, position_name TEXT NOT NULL);
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'general'
            );
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE mock_sessions (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                application_id INTEGER,
                title TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress'
            );
            INSERT INTO conversations(id, title, mode) VALUES
                (1, '旧模拟', 'mock_interview'),
                (2, '普通聊天', 'general');
            INSERT INTO chat_messages(id, conversation_id, role, content) VALUES
                (1, 1, 'user', '旧模拟消息'),
                (2, 2, 'user', '普通聊天消息');
            INSERT INTO mock_sessions(id, conversation_id, title, role)
                VALUES (1, 1, '旧会话', '工程师');
            """
        )
        if with_named_indexes:
            connection.executescript(
                """
                CREATE INDEX idx_mock_sessions_conv ON mock_sessions(conversation_id);
                CREATE INDEX idx_mock_sessions_status ON mock_sessions(status);
                """
            )
        connection.commit()
    finally:
        connection.close()


def _table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()


def test_0016_drops_mock_rows_and_messages_but_preserves_normal_chat(tmp_path):
    path = tmp_path / "legacy.db"
    _write_legacy_mock_database(path)

    factory = init_database(path)

    with factory() as session:
        assert "mock_sessions" not in _table_names(path)
        assert session.execute(
            text("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = 1")
        ).scalar_one() == 0
        assert session.execute(
            text("SELECT content FROM chat_messages WHERE conversation_id = 2")
        ).scalar_one() == "普通聊天消息"
        assert session.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = '0016_event_bound_mock_interview'")
        ).scalar_one() == 1


def test_0016_handles_legacy_named_indexes_before_dropping_mock_table(tmp_path):
    path = tmp_path / "legacy.db"
    _write_legacy_mock_database(path, with_named_indexes=True)

    init_database(path)

    assert "mock_sessions" not in _table_names(path)


def test_0016_creates_new_tables_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    _write_legacy_mock_database(path)

    init_database(path)
    init_database(path)

    tables = _table_names(path)
    assert {
        "mock_interview_attempts",
        "mock_interview_turns",
        "mock_interview_feedback_proposals",
        "mock_interview_review_drafts",
    } <= tables


def test_0016_preserves_formal_interview_notes_but_creates_no_legacy_mock_data(tmp_path):
    path = tmp_path / "legacy.db"
    _write_legacy_mock_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE interview_notes (id INTEGER PRIMARY KEY, company TEXT NOT NULL, position TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO interview_notes(id, company, position) VALUES (1, '公司', '职位')"
        )
        connection.commit()
    finally:
        connection.close()

    factory = init_database(path)

    with factory() as session:
        assert session.execute(text("SELECT COUNT(*) FROM interview_notes WHERE id = 1")).scalar_one() == 1
        assert session.execute(text("SELECT COUNT(*) FROM mock_interview_attempts")).scalar_one() == 0
