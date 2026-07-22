from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Application, ApplicationEvent, InterviewNote


class NoteBindingError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class NoteCreate:
    company: str
    position: str = ""
    round: str = ""
    date: str = ""
    questions: str = ""
    self_reflection: str = ""
    difficulty_points: str = ""
    mood: str = ""
    application_id: int | None = None
    application_event_id: int | None = None


class _Unset:
    pass


UNSET = _Unset()


@dataclass
class NoteUpdate:
    company: str = ""
    position: str = ""
    round: str = ""
    date: str = ""
    questions: str = ""
    self_reflection: str = ""
    difficulty_points: str = ""
    mood: str = ""
    application_id: int | None | _Unset = UNSET
    application_event_id: int | None | _Unset = UNSET


class NotesRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: NoteCreate) -> InterviewNote:
        note = InterviewNote(
            application_id=data.application_id,
            application_event_id=data.application_event_id,
            company=data.company,
            position=data.position,
            round=data.round,
            date=data.date,
            questions=data.questions,
            self_reflection=data.self_reflection,
            difficulty_points=data.difficulty_points,
            mood=data.mood,
        )
        with self._session_factory() as session:
            self._validate_event_binding(session, data.application_id, data.application_event_id)
            session.add(note)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if data.application_event_id is not None:
                    raise NoteBindingError(409, "Interview event already has a note") from exc
                raise
            session.refresh(note)
            return note

    def list(self, application_id: int = 0) -> list[InterviewNote]:
        statement = (
            select(InterviewNote)
            .outerjoin(Application, Application.id == InterviewNote.application_id)
            .where(
                or_(
                    InterviewNote.application_id.is_(None),
                    Application.deleted_at.is_(None),
                )
            )
        )
        if application_id > 0:
            statement = statement.where(InterviewNote.application_id == application_id)
        statement = statement.order_by(InterviewNote.created_at.desc(), InterviewNote.id.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, note_id: int) -> Optional[InterviewNote]:
        with self._session_factory() as session:
            return session.scalar(self._visible_note_statement(note_id))

    def update(self, note_id: int, data: NoteUpdate) -> Optional[InterviewNote]:
        with self._session_factory() as session:
            note = session.scalar(self._visible_note_statement(note_id))
            if note is None:
                return None
            if data.application_id is not UNSET and data.application_id != note.application_id:
                raise NoteBindingError(422, "application_id cannot be changed")
            event_id = (
                note.application_event_id
                if data.application_event_id is UNSET
                else data.application_event_id
            )
            if event_id != note.application_event_id:
                self._validate_event_binding(session, note.application_id, event_id, note.id)
            note.company = data.company
            note.position = data.position
            note.round = data.round
            note.date = data.date
            note.questions = data.questions
            note.self_reflection = data.self_reflection
            note.difficulty_points = data.difficulty_points
            note.mood = data.mood
            note.application_event_id = event_id
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if event_id is not None:
                    raise NoteBindingError(409, "Interview event already has a note") from exc
                raise
            session.refresh(note)
            return note

    def delete(self, note_id: int) -> None:
        with self._session_factory() as session:
            note = session.scalar(self._visible_note_statement(note_id))
            if note is not None:
                session.delete(note)
                session.commit()

    def delete_if_matches(self, note_id: int, expected: dict[str, object]) -> bool:
        statement = (
            delete(InterviewNote)
            .where(InterviewNote.id == note_id)
            .where(InterviewNote.company == expected.get("company"))
            .where(InterviewNote.position == expected.get("position"))
            .where(InterviewNote.round == expected.get("round"))
            .where(InterviewNote.date == expected.get("date"))
            .where(InterviewNote.questions == expected.get("questions"))
            .where(InterviewNote.self_reflection == expected.get("self_reflection"))
            .where(InterviewNote.difficulty_points == expected.get("difficulty_points"))
            .where(InterviewNote.mood == expected.get("mood"))
        )
        application_id = expected.get("application_id")
        statement = (
            statement.where(InterviewNote.application_id.is_(None))
            if application_id is None
            else statement.where(InterviewNote.application_id == application_id)
        )
        visible_application = exists(
            select(Application.id)
            .where(Application.id == InterviewNote.application_id)
            .where(Application.deleted_at.is_(None))
        )
        statement = statement.where(
            or_(InterviewNote.application_id.is_(None), visible_application)
        )
        with self._session_factory() as session:
            result = session.execute(statement)
            session.commit()
            return getattr(result, "rowcount", 0) == 1

    @staticmethod
    def _visible_note_statement(note_id: int):
        return (
            select(InterviewNote)
            .outerjoin(Application, Application.id == InterviewNote.application_id)
            .where(InterviewNote.id == note_id)
            .where(
                or_(
                    InterviewNote.application_id.is_(None),
                    Application.deleted_at.is_(None),
                )
            )
        )

    @staticmethod
    def _validate_event_binding(
        session: Session,
        application_id: int | None,
        event_id: int | None,
        note_id: int | None = None,
    ) -> None:
        if event_id is None:
            return
        if application_id is None:
            raise NoteBindingError(422, "application_event_id requires an application")
        event = session.scalar(
            select(ApplicationEvent)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(ApplicationEvent.id == event_id)
            .where(Application.deleted_at.is_(None))
        )
        if event is None or event.event_type != "interview" or event.application_id != application_id:
            raise NoteBindingError(
                422,
                "application_event_id must reference an interview event for the application",
            )
        existing = session.scalar(
            select(InterviewNote.id)
            .where(InterviewNote.application_event_id == event_id)
            .where(InterviewNote.id != note_id if note_id is not None else True)
        )
        if existing is not None:
            raise NoteBindingError(409, "Interview event already has a note")
