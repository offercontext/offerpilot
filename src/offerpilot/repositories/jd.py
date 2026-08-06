from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import ApplicationJDVersion, JDAnalysis
from offerpilot.repositories.application_jd_versions import JDVersionConflictError


@dataclass
class JDAnalysisCreate:
    jd_source: str
    jd_text: str
    result: str
    application_id: Optional[int] = None
    jd_version_id: Optional[int] = None


class JDAnalysesRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: JDAnalysisCreate) -> JDAnalysis:
        analysis = JDAnalysis(
            application_id=data.application_id,
            jd_source=data.jd_source,
            jd_text=data.jd_text,
            result=data.result,
            jd_version_id=data.jd_version_id,
        )
        with self._session_factory() as session:
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            return analysis

    def create_for_current(self, data: JDAnalysisCreate) -> JDAnalysis:
        if data.application_id is None or data.jd_version_id is None:
            return self.create(data)
        with self._session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            current = session.scalar(
                select(ApplicationJDVersion)
                .where(ApplicationJDVersion.application_id == data.application_id)
                .order_by(desc(ApplicationJDVersion.version_number))
                .limit(1)
            )
            if current is None or current.id != data.jd_version_id:
                raise JDVersionConflictError("requested JD version is not current")
            analysis = JDAnalysis(
                application_id=data.application_id,
                jd_source=data.jd_source,
                jd_text=data.jd_text,
                result=data.result,
                jd_version_id=data.jd_version_id,
            )
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
