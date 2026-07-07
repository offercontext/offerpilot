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

    Base.metadata.create_all(engine)
    _ensure_schema_migrations(engine)
    _record_migration(engine, "0001_base_schema", "Create current application tables")

    chat_migrations = [
        _ensure_column(engine, "conversations", "offer_id", "INTEGER"),
        _ensure_column(engine, "conversations", "mode", "TEXT DEFAULT 'general'"),
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
                    USING fts5(chunk_id, document_id, knowledge_base_id, content)
                    """
                )
            )
    except Exception:
        # Some SQLite builds omit FTS5. Search falls back to knowledge_chunks.
        return
