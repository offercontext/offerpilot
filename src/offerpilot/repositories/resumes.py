from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Resume, ResumeMatch


@dataclass
class ResumeCreate:
    name: str = ""
    file_path: str = ""
    parsed_data: str = ""
    parse_status: str = "text-ready"
    title: str = ""
    is_master: bool | None = None
    parent_resume_id: int | None = None
    source: str = "manual"
    source_file_path: str = ""
    content_json: dict[str, Any] | str | None = None


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
        title = data.title or data.name
        name = data.name or title
        file_path = data.file_path or data.source_file_path
        source_file_path = data.source_file_path or file_path
        content_json = _compact_json(data.content_json)
        resume = Resume(
            name=name,
            file_path=file_path,
            parsed_data=data.parsed_data,
            parse_status=data.parse_status or "text-ready",
            title=title,
            is_master=False,
            parent_resume_id=data.parent_resume_id,
            source=data.source or "manual",
            source_file_path=source_file_path,
            content_json=content_json,
        )
        with self._session_factory() as session:
            resume.is_master = (
                data.is_master
                if data.is_master is not None
                else not _has_active_resume(session)
            )
            if resume.is_master:
                _clear_other_masters(session)
            session.add(resume)
            session.commit()
            session.refresh(resume)
            return resume

    def list(self) -> list[Resume]:
        statement = (
            select(Resume)
            .where(Resume.deleted_at.is_(None))
            .order_by(Resume.created_at.desc(), Resume.id.desc())
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, resume_id: int) -> Optional[Resume]:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None or resume.deleted_at is not None:
                return None
            return resume

    def count_active_masters(self) -> int:
        statement = select(Resume.id).where(
            Resume.deleted_at.is_(None),
            Resume.is_master.is_(True),
        )
        with self._session_factory() as session:
            return len(list(session.scalars(statement)))

    def delete(self, resume_id: int) -> None:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is not None and resume.deleted_at is None:
                was_master = bool(resume.is_master)
                resume.deleted_at = datetime.now(timezone.utc)
                if was_master:
                    replacement = session.scalar(
                        select(Resume)
                        .where(Resume.deleted_at.is_(None), Resume.is_master.is_(False))
                        .order_by(Resume.id.asc())
                        .limit(1)
                    )
                    if replacement is not None:
                        replacement.is_master = True
                session.commit()

    def update(self, resume_id: int, changes: dict[str, Any]) -> Optional[Resume]:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None or resume.deleted_at is not None:
                return None
            if "title" in changes:
                resume.title = str(changes["title"] or "")
                resume.name = resume.title
            if "name" in changes:
                resume.name = str(changes["name"] or "")
                if not resume.title:
                    resume.title = resume.name
            if "content_json" in changes:
                resume.content_json = _compact_json(changes["content_json"])
            if "is_master" in changes:
                resume.is_master = bool(changes["is_master"])
                if resume.is_master:
                    _clear_other_masters(session, keep_id=resume.id)
            if "source" in changes:
                resume.source = str(changes["source"] or "manual")
            if "source_file_path" in changes:
                resume.source_file_path = str(changes["source_file_path"] or "")
                resume.file_path = resume.source_file_path
            if "parsed_data" in changes:
                resume.parsed_data = str(changes["parsed_data"] or "")
            if "parse_status" in changes:
                resume.parse_status = str(changes["parse_status"] or "pending")
            session.commit()
            session.refresh(resume)
            return resume

    def copy(self, resume_id: int, *, title: str = "") -> Optional[Resume]:
        with self._session_factory() as session:
            original = session.get(Resume, resume_id)
            if original is None or original.deleted_at is not None:
                return None
            source = "sample_copy" if original.source == "sample" else "manual"
            copied = Resume(
                name=title or f"{original.title or original.name} Copy",
                title=title or f"{original.title or original.name} Copy",
                parsed_data=original.parsed_data,
                parse_status=original.parse_status,
                is_master=False,
                parent_resume_id=original.id,
                source=source,
                content_json=original.content_json,
            )
            session.add(copied)
            session.commit()
            session.refresh(copied)
            return copied

    def update_text(self, resume_id: int, text: str, status: str) -> bool:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None or resume.deleted_at is not None:
                return False
            resume.parsed_data = text
            resume.parse_status = status
            resume.content_json = _compact_json({**_json_object(resume.content_json), "raw_text": text})
            session.commit()
            return True

    def update_file(self, resume_id: int, file_path: str) -> Optional[Resume]:
        with self._session_factory() as session:
            resume = session.get(Resume, resume_id)
            if resume is None or resume.deleted_at is not None:
                return None
            resume.file_path = file_path
            resume.source_file_path = file_path
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
            .join(Resume, Resume.id == ResumeMatch.resume_id)
            .where(ResumeMatch.resume_id == resume_id)
            .where(Resume.deleted_at.is_(None))
            .order_by(ResumeMatch.created_at.desc())
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))


def _compact_json(value: dict[str, Any] | str | None) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return "{}"
        return json.dumps(parsed if isinstance(parsed, dict) else {}, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_active_resume(session: Session) -> bool:
    statement = select(Resume.id).where(Resume.deleted_at.is_(None)).limit(1)
    return session.scalar(statement) is not None


def _clear_other_masters(session: Session, keep_id: int | None = None) -> None:
    statement = select(Resume).where(Resume.is_master.is_(True))
    if keep_id is not None:
        statement = statement.where(Resume.id != keep_id)
    for resume in session.scalars(statement):
        resume.is_master = False
