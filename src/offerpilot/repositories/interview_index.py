from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Application, ApplicationEvent, InterviewNote


@dataclass(frozen=True)
class InterviewIndexItem:
    application_id: int
    event_id: int
    company_name: str
    position_name: str
    scheduled_at: object
    note_id: int | None
    note_source_status: str | None


class InterviewIndexRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def list(self, *, limit: int = 50, cursor: str = "") -> tuple[list[InterviewIndexItem], str | None]:
        offset = _parse_cursor(cursor)
        statement = (
            select(ApplicationEvent, Application.company_name, Application.position_name, InterviewNote)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .outerjoin(InterviewNote, InterviewNote.application_event_id == ApplicationEvent.id)
            .where(Application.deleted_at.is_(None))
            .where(ApplicationEvent.event_type == "interview")
            .order_by(ApplicationEvent.scheduled_at.asc(), ApplicationEvent.id.asc())
            .offset(offset)
            .limit(limit + 1)
        )
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_item(row[0], row[1], row[2], row[3]) for row in rows]
        return items, str(offset + limit) if has_more else None

    def get(self, event_id: int) -> InterviewIndexItem | None:
        statement = (
            select(ApplicationEvent, Application.company_name, Application.position_name, InterviewNote)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .outerjoin(InterviewNote, InterviewNote.application_event_id == ApplicationEvent.id)
            .where(Application.deleted_at.is_(None))
            .where(ApplicationEvent.event_type == "interview")
            .where(ApplicationEvent.id == event_id)
        )
        with self._session_factory() as session:
            row = session.execute(statement).first()
        return None if row is None else _item(row[0], row[1], row[2], row[3])


def _parse_cursor(value: str) -> int:
    if not value:
        return 0
    try:
        offset = int(value)
    except ValueError as exc:
        raise ValueError("cursor must be a non-negative integer") from exc
    if offset < 0:
        raise ValueError("cursor must be a non-negative integer")
    return offset


def _item(event: ApplicationEvent, company_name: str, position_name: str, note: InterviewNote | None) -> InterviewIndexItem:
    scheduled_at = event.scheduled_at or datetime.min
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    return InterviewIndexItem(
        application_id=event.application_id,
        event_id=event.id,
        company_name=company_name,
        position_name=position_name,
        scheduled_at=scheduled_at,
        note_id=note.id if note is not None else None,
        note_source_status="current" if note is not None else None,
    )
