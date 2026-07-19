from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import InterviewNote


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


class NotesRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: NoteCreate) -> InterviewNote:
        note = InterviewNote(
            application_id=data.application_id,
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
            session.add(note)
            session.commit()
            session.refresh(note)
            return note

    def list(self, application_id: int = 0) -> list[InterviewNote]:
        statement = select(InterviewNote)
        if application_id > 0:
            statement = statement.where(InterviewNote.application_id == application_id)
        statement = statement.order_by(InterviewNote.created_at.desc(), InterviewNote.id.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, note_id: int) -> Optional[InterviewNote]:
        with self._session_factory() as session:
            return session.get(InterviewNote, note_id)

    def update(self, note_id: int, data: NoteCreate) -> Optional[InterviewNote]:
        with self._session_factory() as session:
            note = session.get(InterviewNote, note_id)
            if note is None:
                return None
            note.company = data.company
            note.position = data.position
            note.round = data.round
            note.date = data.date
            note.questions = data.questions
            note.self_reflection = data.self_reflection
            note.difficulty_points = data.difficulty_points
            note.mood = data.mood
            session.commit()
            session.refresh(note)
            return note

    def delete(self, note_id: int) -> None:
        with self._session_factory() as session:
            note = session.get(InterviewNote, note_id)
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
        with self._session_factory() as session:
            result = session.execute(statement)
            session.commit()
            return getattr(result, "rowcount", 0) == 1
