from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import ApplicationMaterialKit


@dataclass
class MaterialKitCreate:
    application_id: int
    resume_id: Optional[int] = None
    jd_analysis_id: Optional[int] = None
    jd_snapshot: str = ""
    status: str = "draft"
    content_json: str = "{}"


class MaterialKitsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: MaterialKitCreate) -> ApplicationMaterialKit:
        kit = ApplicationMaterialKit(
            application_id=data.application_id,
            resume_id=data.resume_id,
            jd_analysis_id=data.jd_analysis_id,
            jd_snapshot=data.jd_snapshot,
            status=data.status or "draft",
            content_json=data.content_json or "{}",
        )
        with self._session_factory() as session:
            session.add(kit)
            session.commit()
            session.refresh(kit)
            return kit

    def get(self, kit_id: int) -> Optional[ApplicationMaterialKit]:
        with self._session_factory() as session:
            return session.get(ApplicationMaterialKit, kit_id)

    def get_by_application(self, application_id: int) -> Optional[ApplicationMaterialKit]:
        statement = select(ApplicationMaterialKit).where(
            ApplicationMaterialKit.application_id == application_id
        )
        with self._session_factory() as session:
            return session.scalar(statement)

    def update(self, kit_id: int, data: MaterialKitCreate) -> Optional[ApplicationMaterialKit]:
        with self._session_factory() as session:
            kit = session.get(ApplicationMaterialKit, kit_id)
            if kit is None:
                return None
            kit.resume_id = data.resume_id
            kit.jd_analysis_id = data.jd_analysis_id
            kit.jd_snapshot = data.jd_snapshot
            kit.status = data.status or "draft"
            kit.content_json = data.content_json or "{}"
            session.commit()
            session.refresh(kit)
            return kit
