from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Application, Event


@dataclass
class EventCreate:
    application_id: int
    event_type: str
    scheduled_at: datetime
    duration_minutes: int
    round: int = 0
    location: str = ""
    notes: str = ""


@dataclass
class EventWithApplication:
    event: Event
    company_name: str
    position_name: str


class EventsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: EventCreate) -> Event:
        event = Event(
            application_id=data.application_id,
            event_type=data.event_type,
            round=data.round,
            scheduled_at=data.scheduled_at,
            duration=_duration_string(data.duration_minutes),
            location=data.location,
            notes=data.notes,
        )
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
    ) -> list[EventWithApplication]:
        statement = (
            select(Event, Application.company_name, Application.position_name)
            .join(Application, Application.id == Event.application_id)
            .order_by(Event.scheduled_at.asc(), Event.id.asc())
        )
        if month:
            statement = statement.where(Event.scheduled_at >= f"{month}-01")
        if application_id > 0:
            statement = statement.where(Event.application_id == application_id)
        if event_type:
            statement = statement.where(Event.event_type == event_type)

        with self._session_factory() as session:
            rows = session.execute(statement).all()
            return [
                EventWithApplication(event=row[0], company_name=row[1], position_name=row[2])
                for row in rows
            ]

    def get(self, event_id: int) -> Optional[Event]:
        with self._session_factory() as session:
            return session.get(Event, event_id)

    def update(self, event_id: int, data: EventCreate) -> Optional[Event]:
        with self._session_factory() as session:
            event = session.get(Event, event_id)
            if event is None:
                return None
            event.application_id = data.application_id
            event.event_type = data.event_type
            event.round = data.round
            event.scheduled_at = data.scheduled_at
            event.duration = _duration_string(data.duration_minutes)
            event.location = data.location
            event.notes = data.notes
            session.commit()
            session.refresh(event)
            return event

    def delete(self, event_id: int) -> bool:
        with self._session_factory() as session:
            event = session.get(Event, event_id)
            if event is None:
                return False
            session.delete(event)
            session.commit()
            return True


def _duration_string(minutes: int) -> str:
    return f"{minutes}m"


def duration_minutes(duration: str) -> int:
    return int(duration.removesuffix("m") or "0")

