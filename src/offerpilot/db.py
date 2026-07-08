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
        _ensure_column(engine, "conversations", "pending_tool_call_id", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_tool_name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_args", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_human", "TEXT DEFAULT ''"),
        _ensure_column(engine, "chat_messages", "provider_blocks", "TEXT DEFAULT ''"),
    ]
    if any(chat_migrations):
        _record_migration(engine, "0002_chat_state_columns", "Add durable chat state columns")

    resume_migrations = [
        _ensure_column(engine, "resumes", "name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "file_path", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parsed_data", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parse_status", "TEXT DEFAULT 'pending'"),
    ]
    if any(resume_migrations):
        _record_migration(engine, "0003_resume_content_columns", "Add resume content columns")
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
