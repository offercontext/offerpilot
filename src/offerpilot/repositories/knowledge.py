from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument


@dataclass
class KnowledgeBaseCreate:
    name: str
    description: str = ""


@dataclass
class KnowledgeDocumentCreate:
    knowledge_base_id: int
    title: str
    content: str = ""
    tags: list[str] | None = None
    source_type: str = "manual"
    source_name: str = ""


class KnowledgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_base(self, data: KnowledgeBaseCreate) -> KnowledgeBase:
        base = KnowledgeBase(name=data.name, description=data.description)
        with self._session_factory() as session:
            session.add(base)
            session.commit()
            session.refresh(base)
            return base

    def list_bases(self) -> list[KnowledgeBase]:
        statement = select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get_base(self, base_id: int) -> Optional[KnowledgeBase]:
        with self._session_factory() as session:
            return session.get(KnowledgeBase, base_id)

    def update_base(self, base_id: int, data: KnowledgeBaseCreate) -> Optional[KnowledgeBase]:
        with self._session_factory() as session:
            base = session.get(KnowledgeBase, base_id)
            if base is None:
                return None
            base.name = data.name
            base.description = data.description
            session.commit()
            session.refresh(base)
            return base

    def delete_base(self, base_id: int) -> bool:
        with self._session_factory() as session:
            base = session.get(KnowledgeBase, base_id)
            if base is None:
                return False
            session.delete(base)
            session.commit()
            return True

    def create_document(self, data: KnowledgeDocumentCreate) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            knowledge_base_id=data.knowledge_base_id,
            title=data.title,
            content=data.content,
            source_type=data.source_type or "manual",
            source_name=data.source_name,
        )
        doc.tags = data.tags or []
        with self._session_factory() as session:
            session.add(doc)
            session.flush()
            _refresh_chunks(session, doc.id, doc.knowledge_base_id, doc.content)
            session.commit()
            session.refresh(doc)
            return doc

    def list_documents(self, knowledge_base_id: int = 0, query: str = "") -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument)
        if knowledge_base_id > 0:
            statement = statement.where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
        if query.strip():
            like = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    KnowledgeDocument.title.like(like),
                    KnowledgeDocument.content.like(like),
                    KnowledgeDocument._tags.like(like),
                )
            )
        statement = statement.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get_document(self, document_id: int) -> Optional[KnowledgeDocument]:
        with self._session_factory() as session:
            return session.get(KnowledgeDocument, document_id)

    def update_document(
        self,
        document_id: int,
        data: KnowledgeDocumentCreate,
    ) -> Optional[KnowledgeDocument]:
        with self._session_factory() as session:
            doc = session.get(KnowledgeDocument, document_id)
            if doc is None:
                return None
            doc.knowledge_base_id = data.knowledge_base_id
            doc.title = data.title
            doc.content = data.content
            doc.tags = data.tags or []
            doc.source_type = data.source_type or doc.source_type
            doc.source_name = data.source_name
            _refresh_chunks(session, doc.id, doc.knowledge_base_id, doc.content)
            session.commit()
            session.refresh(doc)
            return doc

    def delete_document(self, document_id: int) -> bool:
        with self._session_factory() as session:
            doc = session.get(KnowledgeDocument, document_id)
            if doc is None:
                return False
            session.delete(doc)
            session.commit()
            return True

    def search(self, query: str, knowledge_base_id: int = 0, limit: int = 5) -> list[dict[str, Any]]:
        limit = min(max(limit or 5, 1), 10)
        terms = _search_patterns(query)
        if not terms:
            return []
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
        )
        if knowledge_base_id > 0:
            statement = statement.where(KnowledgeChunk.knowledge_base_id == knowledge_base_id)
        statement = statement.where(
            or_(
                *[
                    or_(
                        KnowledgeChunk.content.like(f"%{term}%"),
                        KnowledgeDocument.title.like(f"%{term}%"),
                    )
                    for term in terms
                ]
            )
        )
        statement = statement.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.chunk_index.asc()).limit(
            limit
        )
        with self._session_factory() as session:
            rows = session.execute(statement).all()
            return [
                {
                    "knowledge_base_id": base.id,
                    "knowledge_base_name": base.name,
                    "document_id": doc.id,
                    "document_title": doc.title,
                    "chunk_id": chunk.id,
                    "snippet": chunk.content,
                    "score": 0.0,
                }
                for chunk, doc, base in rows
            ]


def _refresh_chunks(session: Session, document_id: int, knowledge_base_id: int, content: str) -> None:
    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
    for index, chunk in enumerate(_chunk_content(content)):
        session.add(
            KnowledgeChunk(
                document_id=document_id,
                knowledge_base_id=knowledge_base_id,
                chunk_index=index,
                content=chunk,
            )
        )


def _chunk_content(content: str) -> list[str]:
    stripped = content.strip()
    if not stripped:
        return []
    chunks = [part.strip() for part in stripped.split("\n\n") if part.strip()]
    return chunks or [stripped]


def _search_patterns(query: str) -> list[str]:
    seen: set[str] = set()
    patterns: list[str] = []
    for term in [query.strip(), *query.split()]:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            patterns.append(term)
    return patterns
