from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import KnowledgeChunk, KnowledgeDocument


@dataclass
class KnowledgeDocumentCreate:
    title: str
    content: str = ""
    tags: list[str] | None = None
    source_type: str = "manual"
    source_name: str = ""


class KnowledgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_document(self, data: KnowledgeDocumentCreate) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            title=data.title,
            content=data.content,
            source_type=data.source_type or "manual",
            source_name=data.source_name,
        )
        doc.tags = data.tags or []
        with self._session_factory() as session:
            session.add(doc)
            session.flush()
            _refresh_chunks(session, doc.id, doc.content)
            session.commit()
            session.refresh(doc)
            return doc

    def list_documents(self, query: str = "") -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument)
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
            doc.title = data.title
            doc.content = data.content
            doc.tags = data.tags or []
            doc.source_type = data.source_type or doc.source_type
            doc.source_name = data.source_name
            _refresh_chunks(session, doc.id, doc.content)
            session.commit()
            session.refresh(doc)
            return doc

    def delete_document(self, document_id: int) -> bool:
        with self._session_factory() as session:
            doc = session.get(KnowledgeDocument, document_id)
            if doc is None:
                return False
            _delete_fts_for_document(session, document_id)
            session.delete(doc)
            session.commit()
            return True

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        limit = min(max(limit or 5, 1), 10)
        terms = _search_patterns(query)
        if not terms:
            return []
        with self._session_factory() as session:
            fts_rows = _search_fts(session, query, limit * 3)
            lexical_rows = _search_lexical(session, terms, limit * 3)
        return _merge_ranked_results([fts_rows, lexical_rows], limit)


def _search_lexical(
    session: Session,
    terms: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    statement = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
    )
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
    statement = statement.order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.chunk_index.asc()).limit(limit)
    rows = session.execute(statement).all()
    return [_search_payload(chunk, doc) for chunk, doc in rows]


def _search_fts(
    session: Session,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    where = "knowledge_chunks_fts MATCH :query"
    params: dict[str, Any] = {"query": fts_query, "limit": limit}
    try:
        rows = session.execute(
            text(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.chunk_index AS chunk_index,
                    c.content AS snippet,
                    d.id AS document_id,
                    d.title AS document_title,
                    d.source_name AS source_name,
                    bm25(knowledge_chunks_fts) AS rank
                FROM knowledge_chunks_fts
                JOIN knowledge_chunks c ON c.id = knowledge_chunks_fts.chunk_id
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE {where}
                ORDER BY rank ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings()
    except Exception:
        return []
    return [
        {
            "document_id": int(row["document_id"]),
            "document_title": str(row["document_title"]),
            "source_name": str(row["source_name"] or ""),
            "chunk_id": int(row["chunk_id"]),
            "chunk_index": int(row["chunk_index"]),
            "snippet": str(row["snippet"]),
            "score": 0.0,
        }
        for row in rows
    ]


def _merge_ranked_results(result_sets: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for result_set in result_sets:
        for rank, row in enumerate(result_set, start=1):
            chunk_id = int(row["chunk_id"])
            if chunk_id not in merged:
                merged[chunk_id] = dict(row)
            merged[chunk_id]["score"] = float(merged[chunk_id]["score"]) + (1.0 / (60 + rank))
    ranked = sorted(
        merged.values(),
        key=lambda row: (-float(row["score"]), int(row["document_id"]), int(row["chunk_index"])),
    )
    for row in ranked:
        row["score"] = round(float(row["score"]), 6)
    return ranked[:limit]


def _search_payload(
    chunk: KnowledgeChunk,
    doc: KnowledgeDocument,
) -> dict[str, Any]:
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "source_name": doc.source_name,
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "snippet": chunk.content,
        "score": 0.0,
    }


def _refresh_chunks(session: Session, document_id: int, content: str) -> None:
    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
    _delete_fts_for_document(session, document_id)
    chunks: list[KnowledgeChunk] = []
    for index, chunk in enumerate(_chunk_content(content)):
        chunks.append(
            KnowledgeChunk(
                document_id=document_id,
                chunk_index=index,
                content=chunk,
            )
        )
    session.add_all(chunks)
    session.flush()
    _insert_fts_chunks(session, chunks)


def _insert_fts_chunks(session: Session, chunks: list[KnowledgeChunk]) -> None:
    if not chunks:
        return
    try:
        for chunk in chunks:
            session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunks_fts
                        (chunk_id, document_id, content)
                    VALUES (:chunk_id, :document_id, :content)
                    """
                ),
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "content": chunk.content,
                },
            )
    except Exception:
        return


def _delete_fts_for_document(session: Session, document_id: int) -> None:
    try:
        session.execute(
            text("DELETE FROM knowledge_chunks_fts WHERE document_id = :document_id"),
            {"document_id": document_id},
        )
    except Exception:
        return

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


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
    deduped = list(dict.fromkeys(token for token in tokens if token))
    return " OR ".join(f'"{token}"' for token in deduped)
