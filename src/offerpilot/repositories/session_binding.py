from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def repository_session(
    factory: sessionmaker[Session],
    bound: Session | None,
) -> Iterator[Session]:
    if bound is not None:
        yield bound
        return
    with factory() as session:
        yield session


def finish_repository_write(session: Session, bound: Session | None) -> None:
    if bound is None:
        session.commit()
    else:
        session.flush()


def rollback_repository_write(session: Session, bound: Session | None) -> None:
    if bound is None:
        session.rollback()
