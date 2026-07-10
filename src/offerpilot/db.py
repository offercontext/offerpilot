import json
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Base

SessionFactory = sessionmaker[Session]


def init_database(db_path: Path) -> SessionFactory:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_size=1,
        max_overflow=0,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    _reset_incompatible_v01_tables(engine)
    Base.metadata.create_all(engine)
    _ensure_schema_migrations(engine)
    _record_migration(engine, "0001_base_schema", "Create current application tables")

    chat_migrations = [
        _ensure_column(engine, "conversations", "mode", "TEXT DEFAULT 'general'"),
        _ensure_column(engine, "conversations", "context_type", "TEXT DEFAULT 'workspace'"),
        _ensure_column(engine, "conversations", "context_ref", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pinned_at", "DATETIME"),
        _ensure_column(engine, "conversations", "archived_at", "DATETIME"),
        _ensure_column(engine, "conversations", "pending_tool_call_id", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_tool_name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_args", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_human", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_tool_call_id", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_tool_name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_args", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_human", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_question", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "last_write_undo_json", "TEXT DEFAULT ''"),
        _ensure_column(engine, "chat_messages", "provider_blocks", "TEXT DEFAULT ''"),
    ]
    if any(chat_migrations):
        _record_migration(engine, "0002_chat_state_columns", "Add durable chat state columns")

    resume_migrations = [
        _ensure_column(engine, "resumes", "name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "file_path", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parsed_data", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parse_status", "TEXT DEFAULT 'pending'"),
        _ensure_column(engine, "resumes", "title", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "is_master", "INTEGER DEFAULT 0"),
        _ensure_column(engine, "resumes", "parent_resume_id", "INTEGER"),
        _ensure_column(engine, "resumes", "source", "TEXT DEFAULT 'manual'"),
        _ensure_column(engine, "resumes", "source_file_path", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "content_json", "TEXT DEFAULT '{}'"),
        _ensure_column(engine, "resumes", "deleted_at", "DATETIME"),
    ]
    resume_backfilled = _backfill_resume_v01(engine)
    if any(resume_migrations):
        _record_migration(engine, "0003_resume_content_columns", "Add resume content columns")
        _record_migration(engine, "0004_resume_v01_columns", "Add resume v0.1 columns")
    elif resume_backfilled:
        _record_migration(engine, "0004_resume_v01_columns", "Add resume v0.1 columns")

    application_migrations = [
        _ensure_column(engine, "applications", "first_pending_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_applied_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_written_test_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_interview_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_offer_at", "DATETIME"),
        _ensure_column(engine, "applications", "closed_reason", "TEXT DEFAULT ''"),
        _ensure_column(engine, "applications", "closed_at", "DATETIME"),
        _ensure_column(engine, "applications", "deleted_at", "DATETIME"),
    ]
    application_backfilled = _backfill_application_lifecycle(engine)
    if any(application_migrations) or application_backfilled:
        _record_migration(
            engine,
            "0005_application_lifecycle_columns",
            "Add application lifecycle and soft-delete columns",
        )
    _ensure_knowledge_fts(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _reset_incompatible_v01_tables(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        knowledge_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(knowledge_documents)")).fetchall()}
            if "knowledge_documents" in tables
            else set()
        )
        application_event_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(application_events)")).fetchall()}
            if "application_events" in tables
            else set()
        )
        question_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(questions)")).fetchall()}
            if "questions" in tables
            else set()
        )
        conversation_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)")).fetchall()}
            if "conversations" in tables
            else set()
        )
        mock_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(mock_sessions)")).fetchall()}
            if "mock_sessions" in tables
            else set()
        )
        reset_knowledge = "knowledge_bases" in tables or (
            "knowledge_documents" in tables
            and ("knowledge_base_id" in knowledge_columns or "doc_kind" not in knowledge_columns)
        )
        reset_application_events = "application_events" in tables and (
            "subtype" not in application_event_columns
            or "tags" not in application_event_columns
            or "duration_minutes" not in application_event_columns
            or "remind_at" not in application_event_columns
        )
        reset_questions = "questions" in tables and (
            "knowledge_base_id" in question_columns or "topic" not in question_columns
        )
        reset_conversations = "conversations" in tables and "offer_id" in conversation_columns
        reset_mock_sessions = "mock_sessions" in tables and "knowledge_base_id" in mock_columns
        drop_tables: list[str] = []
        if "events" in tables:
            drop_tables.append("events")
        if reset_application_events:
            drop_tables.append("application_events")
        if reset_knowledge:
            drop_tables.extend(
                [
                    "knowledge_chunks_fts",
                    "knowledge_chunks",
                    "knowledge_documents",
                    "knowledge_bases",
                ]
            )
        if reset_questions:
            drop_tables.extend(["question_reviews", "questions"])
        if reset_conversations:
            drop_tables.extend(["chat_messages", "mock_sessions", "conversations"])
        elif reset_mock_sessions:
            drop_tables.append("mock_sessions")
        if not drop_tables:
            return
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in drop_tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def session_factory_for_data_dir(data_dir: Path) -> SessionFactory:
    return init_database(data_dir / "data.db")


def _ensure_schema_migrations(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _record_migration(engine, version: str, description: str) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO schema_migrations (version, description)
                VALUES (:version, :description)
                """
            ),
            {"version": version, "description": description},
        )


def _ensure_column(engine, table: str, column: str, definition: str) -> bool:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if any(row[1] == column for row in rows):
            return False
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        return True


def _backfill_resume_v01(engine) -> bool:  # type: ignore[no-untyped-def]
    changed = False
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "resumes" not in tables:
            return False
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(resumes)")).fetchall()}
        required = {
            "id",
            "name",
            "file_path",
            "parsed_data",
            "title",
            "is_master",
            "source_file_path",
            "content_json",
            "deleted_at",
        }
        if not required.issubset(columns):
            return False

        result = conn.execute(
            text(
                """
                UPDATE resumes
                SET title = name
                WHERE deleted_at IS NULL
                  AND (title IS NULL OR trim(title) = '')
                  AND name IS NOT NULL
                  AND trim(name) != ''
                """
            )
        )
        changed = changed or bool(result.rowcount)

        result = conn.execute(
            text(
                """
                UPDATE resumes
                SET source_file_path = file_path
                WHERE deleted_at IS NULL
                  AND (source_file_path IS NULL OR trim(source_file_path) = '')
                  AND file_path IS NOT NULL
                  AND trim(file_path) != ''
                """
            )
        )
        changed = changed or bool(result.rowcount)

        rows = conn.execute(
            text(
                """
                SELECT id, parsed_data, content_json
                FROM resumes
                WHERE deleted_at IS NULL
                  AND parsed_data IS NOT NULL
                  AND trim(parsed_data) != ''
                """
            )
        ).fetchall()
        for resume_id, parsed_data, content_json in rows:
            if str(content_json or "").strip() not in {"", "{}"}:
                continue
            conn.execute(
                text("UPDATE resumes SET content_json = :content_json WHERE id = :id"),
                {
                    "id": resume_id,
                    "content_json": json.dumps(
                        {"raw_text": parsed_data},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            )
            changed = True

        master_rows = conn.execute(
            text(
                """
                SELECT id
                FROM resumes
                WHERE deleted_at IS NULL
                  AND is_master = 1
                ORDER BY id ASC
                """
            )
        ).fetchall()
        if not master_rows:
            first_active = conn.execute(
                text(
                    """
                    SELECT id
                    FROM resumes
                    WHERE deleted_at IS NULL
                    ORDER BY id ASC
                    LIMIT 1
                    """
                )
            ).fetchone()
            if first_active is not None:
                conn.execute(
                    text("UPDATE resumes SET is_master = 1 WHERE id = :id"),
                    {"id": first_active[0]},
                )
                changed = True
        elif len(master_rows) > 1:
            keep_id = master_rows[0][0]
            result = conn.execute(
                text(
                    """
                    UPDATE resumes
                    SET is_master = 0
                    WHERE deleted_at IS NULL
                      AND is_master = 1
                      AND id != :keep_id
                    """
                ),
                {"keep_id": keep_id},
            )
            changed = changed or bool(result.rowcount)
    return changed


def _backfill_application_lifecycle(engine) -> bool:  # type: ignore[no-untyped-def]
    changed = False
    field_by_status = {
        "pending": "first_pending_at",
        "applied": "first_applied_at",
        "written_test": "first_written_test_at",
        "interview": "first_interview_at",
        "offer": "first_offer_at",
        "closed": "closed_at",
    }
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "applications" not in tables:
            return False
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(applications)")).fetchall()}
        required = {
            "status",
            "applied_at",
            "created_at",
            "updated_at",
            "deleted_at",
            *field_by_status.values(),
        }
        if not required.issubset(columns):
            return False

        for status, field in field_by_status.items():
            result = conn.execute(
                text(
                    f"""
                    UPDATE applications
                    SET {field} = COALESCE(updated_at, applied_at, created_at, CURRENT_TIMESTAMP)
                    WHERE deleted_at IS NULL
                      AND status = :status
                      AND {field} IS NULL
                    """
                ),
                {"status": status},
            )
            changed = changed or bool(result.rowcount)
    return changed


def _ensure_knowledge_fts(engine) -> None:  # type: ignore[no-untyped-def]
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                    USING fts5(chunk_id, document_id, content)
                    """
                )
            )
    except Exception:
        # Some SQLite builds omit FTS5. Search falls back to knowledge_chunks.
        return
