from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
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
    closed_reason: str = ""


class ApplicationsRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: ApplicationCreate) -> Application:
        now = datetime.now(timezone.utc)
        applied_at = data.applied_at or now
        status = normalize_application_status(data.status)
        closed_reason = data.closed_reason.strip() if status == "closed" else ""
        if status == "closed" and not closed_reason:
            raise ValueError("closed_reason is required when closing an application")
        app = Application(
            company_name=data.company_name,
            position_name=data.position_name,
            job_url=data.job_url,
            status=status,
            source=data.source or "cli",
            notes=data.notes,
            applied_at=applied_at,
            closed_reason=closed_reason,
        )
        _mark_first_status_timestamp(app, status, now)
        with self._session_factory() as session:
            session.add(app)
            session.commit()
            session.refresh(app)
            return app

    def list(self, status: str = "") -> list[Application]:
        statement = select(Application).where(Application.deleted_at.is_(None))
        if status:
            statement = statement.where(Application.status == normalize_application_status(status))
        statement = statement.order_by(Application.applied_at.desc())
        with self._session_factory() as session:
            return [_normalize_model_status(item) for item in session.scalars(statement)]

    def get(self, app_id: int) -> Optional[Application]:
        with self._session_factory() as session:
            app = session.get(Application, app_id)
            if app is None or app.deleted_at is not None:
                return None
            return _normalize_model_status(app)

    def update_full(self, app_id: int, data: ApplicationCreate) -> Optional[Application]:
        with self._session_factory() as session:
            app = session.get(Application, app_id)
            if app is None or app.deleted_at is not None:
                return None
            status = normalize_application_status(data.status)
            if app.status == "closed" and status != "closed":
                raise ValueError("closed application cannot be reopened")
            entering_closed = app.status != "closed" and status == "closed"
            closed_reason = data.closed_reason.strip()
            if status == "closed" and not entering_closed and not closed_reason:
                closed_reason = app.closed_reason
            if status == "closed" and not closed_reason:
                raise ValueError("closed_reason is required when closing an application")
            app.company_name = data.company_name
            app.position_name = data.position_name
            app.job_url = data.job_url
            app.status = status
            app.source = data.source or app.source
            app.notes = data.notes
            if status == "closed":
                app.closed_reason = closed_reason
            else:
                app.closed_reason = ""
            _mark_first_status_timestamp(app, status, datetime.now(timezone.utc))
            session.commit()
            session.refresh(app)
            return app

    def delete(self, app_id: int) -> None:
        with self._session_factory() as session:
            app = session.get(Application, app_id)
            if app is not None and app.deleted_at is None:
                app.deleted_at = datetime.now(timezone.utc)
                session.commit()

    def delete_if_matches(self, app_id: int, expected: dict[str, Any]) -> bool:
        applied_at = expected.get("applied_at")
        if isinstance(applied_at, str):
            applied_at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
        with self._session_factory() as session:
            result = session.execute(
                update(Application)
                .where(Application.id == app_id)
                .where(Application.deleted_at.is_(None))
                .where(Application.company_name == expected.get("company_name"))
                .where(Application.position_name == expected.get("position_name"))
                .where(Application.job_url == expected.get("job_url"))
                .where(Application.status == expected.get("status"))
                .where(Application.source == expected.get("source"))
                .where(Application.notes == expected.get("notes"))
                .where(Application.applied_at == applied_at)
                .where(Application.closed_reason == expected.get("closed_reason"))
                .values(deleted_at=datetime.now(timezone.utc))
            )
            session.commit()
            return getattr(result, "rowcount", 0) == 1

    def restore_status_if_matches(
        self,
        app_id: int,
        *,
        expected_status: str,
        expected_closed_reason: str,
        status: str,
        closed_reason: str,
    ) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                update(Application)
                .where(Application.id == app_id)
                .where(Application.deleted_at.is_(None))
                .where(Application.status == normalize_application_status(expected_status))
                .where(Application.closed_reason == expected_closed_reason)
                .values(
                    status=normalize_application_status(status),
                    closed_reason=closed_reason,
                )
            )
            session.commit()
            return getattr(result, "rowcount", 0) == 1

    def dashboard(self) -> dict[str, Any]:
        apps = self.list()
        board: dict[str, list[Application]] = {}
        for app in apps:
            board.setdefault(app.status, []).append(app)
        return {"total": len(apps), "board": board}


def _normalize_model_status(app: Application) -> Application:
    app.status = normalize_application_status(app.status)
    return app


def _mark_first_status_timestamp(app: Application, status: str, now: datetime) -> None:
    attr_by_status = {
        "pending": "first_pending_at",
        "applied": "first_applied_at",
        "written_test": "first_written_test_at",
        "interview": "first_interview_at",
        "offer": "first_offer_at",
        "closed": "closed_at",
    }
    attr = attr_by_status[status]
    if getattr(app, attr) is None:
        setattr(app, attr, now)
