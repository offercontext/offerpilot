from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Application, ApplicationEvent


@dataclass
class ApplicationEventCreate:
    application_id: int
    event_type: str
    scheduled_at: datetime
    duration_minutes: int
    subtype: str = ""
    tags: list[str] | None = None
    round: int = 0
    location: str = ""
    notes: str = ""
    remind_at: datetime | None = None
    status: str = "todo"


@dataclass
class ApplicationEventWithApplication:
    event: ApplicationEvent
    company_name: str
    position_name: str


class ApplicationEventsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: ApplicationEventCreate) -> ApplicationEvent:
        event = ApplicationEvent(
            application_id=data.application_id,
            event_type=data.event_type,
            subtype=data.subtype,
            round=data.round,
            scheduled_at=data.scheduled_at,
            duration_minutes=data.duration_minutes,
            location=data.location,
            notes=data.notes,
            remind_at=data.remind_at,
            status=data.status or "todo",
        )
        event.tags = data.tags or []
        with self._session_factory() as session:
            session.add(event)
            session.commit()
            session.refresh(event)
            return event

    def list(
        self,
        month: str = "",
        application_id: int = 0,
        event_type: str = "",
    ) -> list[ApplicationEventWithApplication]:
        statement = (
            select(ApplicationEvent, Application.company_name, Application.position_name)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(Application.deleted_at.is_(None))
            .order_by(ApplicationEvent.scheduled_at.asc(), ApplicationEvent.id.asc())
        )
        if month:
            bounds = _month_bounds(month)
            if bounds is not None:
                start, end = bounds
                statement = statement.where(ApplicationEvent.scheduled_at >= start)
                statement = statement.where(ApplicationEvent.scheduled_at < end)
        if application_id > 0:
            statement = statement.where(ApplicationEvent.application_id == application_id)
        if event_type:
            statement = statement.where(ApplicationEvent.event_type == event_type)

        with self._session_factory() as session:
            rows = session.execute(statement).all()
            return [
                ApplicationEventWithApplication(event=row[0], company_name=row[1], position_name=row[2])
                for row in rows
            ]

    def get(self, event_id: int) -> Optional[ApplicationEvent]:
        with self._session_factory() as session:
            return _get_visible_event(session, event_id)

    def update(self, event_id: int, data: ApplicationEventCreate) -> Optional[ApplicationEvent]:
        with self._session_factory() as session:
            event = _get_visible_event(session, event_id)
            if event is None:
                return None
            event.application_id = data.application_id
            event.event_type = data.event_type
            event.subtype = data.subtype
            event.tags = data.tags or []
            event.round = data.round
            event.scheduled_at = data.scheduled_at
            event.duration_minutes = data.duration_minutes
            event.location = data.location
            event.notes = data.notes
            event.remind_at = data.remind_at
            event.status = data.status or event.status
            session.commit()
            session.refresh(event)
            return event

    def delete(self, event_id: int) -> bool:
        with self._session_factory() as session:
            event = _get_visible_event(session, event_id)
            if event is None:
                return False
            session.delete(event)
            session.commit()
            return True


def _get_visible_event(session: Session, event_id: int) -> Optional[ApplicationEvent]:
    event = session.scalar(
        select(ApplicationEvent)
        .join(Application, Application.id == ApplicationEvent.application_id)
        .where(ApplicationEvent.id == event_id)
        .where(Application.deleted_at.is_(None))
    )
    return event

def duration_minutes(duration: str | int) -> int:
    if isinstance(duration, int):
        return duration
    return int(str(duration).removesuffix("m") or "0")


def _month_bounds(month: str) -> tuple[datetime, datetime] | None:
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return None
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end
