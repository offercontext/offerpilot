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
    _ensure_column(engine, "conversations", "offer_id", "INTEGER")
    _ensure_column(engine, "conversations", "mode", "TEXT DEFAULT 'general'")
    _ensure_column(engine, "conversations", "pending_tool_call_id", "TEXT DEFAULT ''")
    _ensure_column(engine, "conversations", "pending_tool_name", "TEXT DEFAULT ''")
    _ensure_column(engine, "conversations", "pending_args", "TEXT DEFAULT ''")
    _ensure_column(engine, "conversations", "pending_human", "TEXT DEFAULT ''")
    _ensure_column(engine, "chat_messages", "provider_blocks", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "name", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "file_path", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "parsed_data", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "parse_status", "TEXT DEFAULT 'pending'")
    _ensure_knowledge_fts(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_factory_for_data_dir(data_dir: Path) -> SessionFactory:
    return init_database(data_dir / "data.db")


def _ensure_column(engine, table: str, column: str, definition: str) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if any(row[1] == column for row in rows):
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


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
