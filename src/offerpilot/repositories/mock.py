from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import MockSession


@dataclass
class MockSessionCreate:
    conversation_id: int
    title: str
    role: str
    application_id: Optional[int] = None
    company: str = ""
    round_type: str = "technical"
    difficulty: str = "medium"
    question_count: int = 5
    duration_min: int = 0
    question_source: str = "mixed"
    knowledge_base_id: Optional[int] = None


class MockSessionsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: MockSessionCreate) -> MockSession:
        session_model = MockSession(
            conversation_id=data.conversation_id,
            application_id=data.application_id,
            title=data.title,
            role=data.role,
            company=data.company,
            round_type=data.round_type or "technical",
            difficulty=data.difficulty or "medium",
            question_count=data.question_count or 5,
            duration_min=data.duration_min,
            question_source=data.question_source or "mixed",
            knowledge_base_id=data.knowledge_base_id,
            status="in_progress",
        )
        with self._session_factory() as session:
            session.add(session_model)
            session.commit()
            session.refresh(session_model)
            return session_model

    def list(self, status: str = "") -> list[MockSession]:
        statement = select(MockSession)
        if status:
            statement = statement.where(MockSession.status == status)
        statement = statement.order_by(MockSession.started_at.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, session_id: int) -> Optional[MockSession]:
        with self._session_factory() as session:
            return session.get(MockSession, session_id)

    def finish(self, session_id: int, feedback: dict[str, object], feedback_json: str) -> Optional[MockSession]:
        with self._session_factory() as session:
            session_model = session.get(MockSession, session_id)
            if session_model is None:
                return None
            session_model.status = "completed"
            session_model.ended_at = datetime.now(timezone.utc)
            session_model.score_overall = _score(feedback, "score_overall")
            session_model.score_communication = _score(feedback, "score_communication")
            session_model.score_depth = _score(feedback, "score_depth")
            session_model.score_structure = _score(feedback, "score_structure")
            session_model.score_confidence = _score(feedback, "score_confidence")
            session_model.feedback = feedback_json
            session.commit()
            session.refresh(session_model)
            return session_model

    def abort(self, session_id: int) -> Optional[MockSession]:
        with self._session_factory() as session:
            session_model = session.get(MockSession, session_id)
            if session_model is None:
                return None
            session_model.status = "aborted"
            session_model.ended_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(session_model)
            return session_model


def _score(feedback: dict[str, object], key: str) -> int:
    value = feedback.get(key)
    return int(value) if isinstance(value, int | float) else 0
