from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.application_status import normalize_application_status
from offerpilot.models import Application


@dataclass
class ApplicationCreate:
    company_name: str
    position_name: str
    job_url: str = ""
    status: str = "applied"
    source: str = "cli"
    notes: str = ""
    applied_at: Optional[datetime] = None


class ApplicationsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: ApplicationCreate) -> Application:
        applied_at = data.applied_at or datetime.now(timezone.utc)
        app = Application(
            company_name=data.company_name,
            position_name=data.position_name,
            job_url=data.job_url,
            status=normalize_application_status(data.status),
            source=data.source or "cli",
            notes=data.notes,
            applied_at=applied_at,
        )
        with self._session_factory() as session:
            session.add(app)
            session.commit()
            session.refresh(app)
            return app

    def list(self, status: str = "") -> list[Application]:
        statement = select(Application)
        if status:
            statement = statement.where(Application.status == normalize_application_status(status))
        statement = statement.order_by(Application.applied_at.desc())
        with self._session_factory() as session:
            return [_normalize_model_status(item) for item in session.scalars(statement)]

    def get(self, app_id: int) -> Optional[Application]:
        with self._session_factory() as session:
            return session.get(Application, app_id)

    def update_full(self, app_id: int, data: ApplicationCreate) -> Optional[Application]:
        with self._session_factory() as session:
            app = session.get(Application, app_id)
            if app is None:
                return None
            app.company_name = data.company_name
            app.position_name = data.position_name
            app.job_url = data.job_url
            app.status = normalize_application_status(data.status)
            app.source = data.source or app.source
            app.notes = data.notes
            session.commit()
            session.refresh(app)
            return app

    def delete(self, app_id: int) -> None:
        with self._session_factory() as session:
            app = session.get(Application, app_id)
            if app is not None:
                session.delete(app)
                session.commit()

    def dashboard(self) -> dict[str, Any]:
        apps = self.list()
        board: dict[str, list[Application]] = {}
        for app in apps:
            board.setdefault(app.status, []).append(app)
        return {"total": len(apps), "board": board}


def _normalize_model_status(app: Application) -> Application:
    app.status = normalize_application_status(app.status)
    return app

