from pathlib import Path
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Base

SessionFactory = sessionmaker[Session]
_GO_TIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?: (?P<offset>[+-]\d{4}) (?P<zone>[A-Z]+))?$"
)


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
    _ensure_column(engine, "chat_messages", "provider_blocks", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "name", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "file_path", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "parsed_data", "TEXT DEFAULT ''")
    _ensure_column(engine, "resumes", "parse_status", "TEXT DEFAULT 'pending'")
    _normalize_legacy_datetime_values(engine)
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


def _normalize_legacy_datetime_values(engine) -> None:  # type: ignore[no-untyped-def]
    datetime_columns = [
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]
    with engine.begin() as conn:
        for table, column in datetime_columns:
            rows = conn.execute(
                text(
                    f"SELECT id, {column} FROM {table} "
                    f"WHERE {column} LIKE '% UTC%' "
                    f"OR {column} LIKE '% CST%' "
                    f"OR {column} LIKE '% m=%'"
                )
            ).fetchall()
            for row_id, value in rows:
                normalized = _normalize_legacy_datetime(value)
                if normalized is not None:
                    conn.execute(
                        text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                        {"value": normalized, "id": row_id},
                    )


def _normalize_legacy_datetime(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.split(" m=", 1)[0].strip()
    match = _GO_TIME_RE.match(candidate)
    if match is None or match.group("offset") is None:
        return None

    fraction = (match.group("fraction") or "").ljust(6, "0")[:6]
    parsed = datetime.fromisoformat(f"{match.group('date')}T{match.group('time')}.{fraction}")
    offset = match.group("offset")
    sign = 1 if offset[0] == "+" else -1
    delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
    parsed = parsed.replace(tzinfo=timezone(sign * delta))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


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
