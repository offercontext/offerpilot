from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import JDAnalysis


@dataclass
class JDAnalysisCreate:
    jd_source: str
    jd_text: str
    result: str
    application_id: Optional[int] = None


class JDAnalysesRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: JDAnalysisCreate) -> JDAnalysis:
        analysis = JDAnalysis(
            application_id=data.application_id,
            jd_source=data.jd_source,
            jd_text=data.jd_text,
            result=data.result,
        )
        with self._session_factory() as session:
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            return analysis

    def list(self, application_id: int = 0) -> list[JDAnalysis]:
        statement = select(JDAnalysis)
        if application_id > 0:
            statement = statement.where(JDAnalysis.application_id == application_id)
        statement = statement.order_by(JDAnalysis.created_at.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, analysis_id: int) -> Optional[JDAnalysis]:
        with self._session_factory() as session:
            return session.get(JDAnalysis, analysis_id)
