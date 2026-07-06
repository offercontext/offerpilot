from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Resume, ResumeMatch


@dataclass
class ResumeCreate:
    name: str = ""
    file_path: str = ""
    parsed_data: str = ""
    parse_status: str = "text-ready"


@dataclass
class ResumeMatchCreate:
    resume_id: int
    jd_text: str
    result: str
    application_id: Optional[int] = None


class ResumesRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: ResumeCreate) -> Resume:
        resume = Resume(
            name=data.name,
            file_path=data.file_path,
            parsed_data=data.parsed_data,
            parse_status=data.parse_status or "text-ready",
        )
        with self._session_factory() as session:
            session.add(resume)
            session.commit()
            session.refresh(resume)
            return resume

    def list(self) -> list[Resume]:
        statement = select(Resume).order_by(Resume.created_at.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, resume_id: int) -> Optional[Resume]:
        with self._session_factory() as session:
            return session.get(Resume, resume_id)

    def delete(self, resume_id: int) -> None:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is not None:
                session.delete(resume)
                session.commit()

    def update_text(self, resume_id: int, text: str, status: str) -> bool:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None:
                return False
            resume.parsed_data = text
            resume.parse_status = status
            session.commit()
            return True

    def update_file(self, resume_id: int, file_path: str) -> Optional[Resume]:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None:
                return None
            resume.file_path = file_path
            session.commit()
            session.refresh(resume)
            return resume

    def create_match(self, data: ResumeMatchCreate) -> ResumeMatch:
        match = ResumeMatch(
            resume_id=data.resume_id,
            application_id=data.application_id,
            jd_text=data.jd_text,
            result=data.result,
        )
        with self._session_factory() as session:
            session.add(match)
            session.commit()
            session.refresh(match)
            return match

    def list_matches(self, resume_id: int) -> List[ResumeMatch]:
        statement = (
            select(ResumeMatch)
            .where(ResumeMatch.resume_id == resume_id)
            .order_by(ResumeMatch.created_at.desc())
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))
