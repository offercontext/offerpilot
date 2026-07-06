from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Offer


@dataclass
class OfferCreate:
    company_name: str
    position_name: str
    application_id: Optional[int] = None
    status: str = "pending"
    base_monthly: int = 0
    months_per_year: int = 12
    signing_bonus: int = 0
    equity: str = ""
    perks: str = ""
    deadline: str = ""
    notes: str = ""
    assessment: str = ""


class OffersRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create(self, data: OfferCreate) -> Offer:
        offer = Offer(
            application_id=data.application_id,
            company_name=data.company_name,
            position_name=data.position_name,
            status=data.status or "pending",
            base_monthly=data.base_monthly,
            months_per_year=data.months_per_year or 12,
            signing_bonus=data.signing_bonus,
            equity=data.equity,
            perks=data.perks,
            deadline=data.deadline,
            notes=data.notes,
            assessment=data.assessment,
        )
        with self._session_factory() as session:
            session.add(offer)
            session.commit()
            session.refresh(offer)
            return offer

    def list(self, status: str = "") -> list[Offer]:
        statement = select(Offer)
        if status:
            statement = statement.where(Offer.status == status)
        statement = statement.order_by(Offer.created_at.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get(self, offer_id: int) -> Optional[Offer]:
        with self._session_factory() as session:
            return session.get(Offer, offer_id)

    def update(self, offer_id: int, data: OfferCreate) -> Optional[Offer]:
        with self._session_factory() as session:
            offer = session.get(Offer, offer_id)
            if offer is None:
                return None
            offer.company_name = data.company_name
            offer.position_name = data.position_name
            offer.status = data.status or "pending"
            offer.base_monthly = data.base_monthly
            offer.months_per_year = data.months_per_year or offer.months_per_year
            offer.signing_bonus = data.signing_bonus
            offer.equity = data.equity
            offer.perks = data.perks
            offer.deadline = data.deadline
            offer.notes = data.notes
            offer.assessment = data.assessment
            session.commit()
            session.refresh(offer)
            return offer

    def delete(self, offer_id: int) -> None:
        with self._session_factory() as session:
            offer = session.get(Offer, offer_id)
            if offer is not None:
                session.delete(offer)
                session.commit()
