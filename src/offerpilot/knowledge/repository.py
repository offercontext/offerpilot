"""Knowledge 持久化 Repository。

封装 SQLAlchemy 会话，提供：
- Source 创建/查询/状态更新（lifecycle/extraction/brief 独立）。
- Origin 追加（每次导入一条）。
- Snapshot 幂等 upsert（按 source_id+extractor_version 唯一）。
- Evidence 批量插入（含稳定 opaque ID 生成）。
- FTS 单事务重建。
- Evidence 搜索（FTS5 MATCH + bm25）。
- Job 持久化与状态机。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import (
    KnowledgeEvidence,
    KnowledgeExtractionSnapshot,
    KnowledgeJob,
    KnowledgeSource,
    KnowledgeSourceOrigin,
)


@dataclass(frozen=True)
class SourceRecord:
    id: int
    source_hash: str
    source_kind: str
    display_title: str
    title_hint: str
    main_filename: str
    main_media_type: str
    main_relative_path: str
    manifest_json: str
    total_bytes: int
    token_count: int
    lifecycle: str
    extraction_status: str
    extraction_error_code: str
    extraction_error_message: str
    brief_status: str
    brief_block_reason: str
    brief_error_code: str
    brief_error_message: str
    active_snapshot_id: Optional[int]
    active_brief_id: Optional[int]
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SourceOriginRecord:
    id: int
    source_id: int
    import_method: str
    original_filename: str
    origin_url: str
    imported_at: datetime


@dataclass(frozen=True)
class SourceSnapshotRecord:
    id: int
    source_id: int
    extractor_version: str
    parser_version: str
    normalization_version: str
    tokenizer_version: str
    encoding: str
    detection_method: str
    digest: str
    canonical_text: str
    structure_manifest: str
    token_count: int
    char_count: int
    created_at: datetime


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    source_id: int
    snapshot_id: int
    kind: str
    block_kind: str
    ordinal: int
    heading_path: list[str]
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    canonical_excerpt: str
    search_text: str
    content_hash: str
    asset_id: Optional[int]
    previous_evidence_id: Optional[str]
    next_evidence_id: Optional[str]


@dataclass(frozen=True)
class JobRecord:
    id: int
    kind: str
    queue: str
    source_id: Optional[int]
    snapshot_id: Optional[int]
    stage: str
    status: str
    progress: int
    retry_count: int
    error_code: str
    error_message: str
    canceled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EvidenceSearchHit:
    evidence_id: str
    source_id: int
    snapshot_id: int
    block_kind: str
    heading_path: list[str]
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    canonical_excerpt: str
    snippet: str
    score: float


@dataclass
class SourceCreateInput:
    source_hash: str
    source_kind: str
    title_hint: str
    main_filename: str
    main_media_type: str
    main_relative_path: str
    manifest_json: str
    total_bytes: int
    token_count: int


@dataclass
class OriginCreateInput:
    source_id: int
    import_method: str
    original_filename: str = ""
    origin_url: str = ""


@dataclass
class SnapshotCreateInput:
    source_id: int
    extractor_version: str
    parser_version: str
    normalization_version: str
    tokenizer_version: str
    encoding: str
    detection_method: str
    canonical_text: str
    structure_manifest: str
    digest: str
    token_count: int
    char_count: int


@dataclass
class EvidenceDraftInput:
    block_kind: str
    heading_path: Sequence[str]
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    canonical_excerpt: str
    search_text: str
    content_hash: str
    locator: str


@dataclass
class JobCreateInput:
    kind: str
    queue: str
    source_id: Optional[int] = None
    snapshot_id: Optional[int] = None
    stage: str = ""


def _to_source_record(row: KnowledgeSource) -> SourceRecord:
    return SourceRecord(
        id=row.id,
        source_hash=row.source_hash,
        source_kind=row.source_kind,
        display_title=row.display_title,
        title_hint=row.title_hint,
        main_filename=row.main_filename,
        main_media_type=row.main_media_type,
        main_relative_path=row.main_relative_path,
        manifest_json=row.manifest_json,
        total_bytes=row.total_bytes,
        token_count=row.token_count,
        lifecycle=row.lifecycle,
        extraction_status=row.extraction_status,
        extraction_error_code=row.extraction_error_code,
        extraction_error_message=row.extraction_error_message,
        brief_status=row.brief_status,
        brief_block_reason=row.brief_block_reason,
        brief_error_code=row.brief_error_code,
        brief_error_message=row.brief_error_message,
        active_snapshot_id=row.active_snapshot_id,
        active_brief_id=row.active_brief_id,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_origin_record(row: KnowledgeSourceOrigin) -> SourceOriginRecord:
    return SourceOriginRecord(
        id=row.id,
        source_id=row.source_id,
        import_method=row.import_method,
        original_filename=row.original_filename,
        origin_url=row.origin_url,
        imported_at=row.imported_at,
    )


def _to_snapshot_record(row: KnowledgeExtractionSnapshot) -> SourceSnapshotRecord:
    return SourceSnapshotRecord(
        id=row.id,
        source_id=row.source_id,
        extractor_version=row.extractor_version,
        parser_version=row.parser_version,
        normalization_version=row.normalization_version,
        tokenizer_version=row.tokenizer_version,
        encoding=row.encoding,
        detection_method=row.detection_method,
        digest=row.digest,
        canonical_text=row.canonical_text,
        structure_manifest=row.structure_manifest,
        token_count=row.token_count,
        char_count=row.char_count,
        created_at=row.created_at,
    )


def _to_evidence_record(row: KnowledgeEvidence) -> EvidenceRecord:
    heading_path_json = row.heading_path_json or "[]"
    try:
        heading_path_value: Any = json.loads(heading_path_json)
    except json.JSONDecodeError:
        heading_path_value = []
    heading_path = (
        [str(item) for item in heading_path_value]
        if isinstance(heading_path_value, list)
        else []
    )
    return EvidenceRecord(
        id=row.id,
        source_id=row.source_id,
        snapshot_id=row.snapshot_id,
        kind=row.kind,
        block_kind=row.block_kind,
        ordinal=row.ordinal,
        heading_path=heading_path,
        char_start=row.char_start,
        char_end=row.char_end,
        line_start=row.line_start,
        line_end=row.line_end,
        canonical_excerpt=row.canonical_excerpt,
        search_text=row.search_text,
        content_hash=row.content_hash,
        asset_id=row.asset_id,
        previous_evidence_id=row.previous_evidence_id,
        next_evidence_id=row.next_evidence_id,
    )


def _to_job_record(row: KnowledgeJob) -> JobRecord:
    return JobRecord(
        id=row.id,
        kind=row.kind,
        queue=row.queue,
        source_id=row.source_id,
        snapshot_id=row.snapshot_id,
        stage=row.stage,
        status=row.status,
        progress=row.progress,
        retry_count=row.retry_count,
        error_code=row.error_code,
        error_message=row.error_message,
        canceled=row.canceled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass(frozen=True)
class EvidencePage:
    items: list[EvidenceRecord] = field(default_factory=list)
    next_cursor: Optional[int] = None


class KnowledgeRepository:
    """Knowledge 表族的 SQL 访问层。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # Source

    def create_source(self, data: SourceCreateInput) -> SourceRecord:
        with self._session_factory() as session:
            model = KnowledgeSource(
                source_hash=data.source_hash,
                source_kind=data.source_kind,
                display_title="",
                title_hint=data.title_hint,
                main_filename=data.main_filename,
                main_media_type=data.main_media_type,
                main_relative_path=data.main_relative_path,
                manifest_json=data.manifest_json,
                total_bytes=data.total_bytes,
                token_count=data.token_count,
                lifecycle="active",
                extraction_status="pending",
                extraction_error_code="",
                extraction_error_message="",
                brief_status="not_started",
                brief_block_reason="",
                brief_error_code="",
                brief_error_message="",
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return _to_source_record(model)

    def get_source(self, source_id: int) -> Optional[SourceRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeSource, source_id)
            if row is None or row.deleted_at is not None:
                return None
            return _to_source_record(row)

    def get_source_by_hash(self, source_hash: str) -> Optional[SourceRecord]:
        with self._session_factory() as session:
            stmt = select(KnowledgeSource).where(
                KnowledgeSource.source_hash == source_hash,
                KnowledgeSource.deleted_at.is_(None),
            )
            row = session.scalars(stmt).first()
            return _to_source_record(row) if row is not None else None

    def list_sources(self) -> list[SourceRecord]:
        with self._session_factory() as session:
            stmt = (
                select(KnowledgeSource)
                .where(KnowledgeSource.deleted_at.is_(None))
                .order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id.desc())
            )
            return [_to_source_record(row) for row in session.scalars(stmt)]

    def update_source_state(
        self,
        source_id: int,
        *,
        extraction_status: Optional[str] = None,
        extraction_error_code: Optional[str] = None,
        extraction_error_message: Optional[str] = None,
        brief_status: Optional[str] = None,
        brief_block_reason: Optional[str] = None,
        brief_error_code: Optional[str] = None,
        brief_error_message: Optional[str] = None,
        active_snapshot_id: Optional[int] = None,
    ) -> Optional[SourceRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeSource, source_id)
            if row is None or row.deleted_at is not None:
                return None
            if extraction_status is not None:
                row.extraction_status = extraction_status
            if extraction_error_code is not None:
                row.extraction_error_code = extraction_error_code
            if extraction_error_message is not None:
                row.extraction_error_message = extraction_error_message
            if brief_status is not None:
                row.brief_status = brief_status
            if brief_block_reason is not None:
                row.brief_block_reason = brief_block_reason
            if brief_error_code is not None:
                row.brief_error_code = brief_error_code
            if brief_error_message is not None:
                row.brief_error_message = brief_error_message
            if active_snapshot_id is not None:
                row.active_snapshot_id = active_snapshot_id
            session.commit()
            session.refresh(row)
            return _to_source_record(row)

    def set_display_title(self, source_id: int, display_title: str) -> Optional[SourceRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeSource, source_id)
            if row is None or row.deleted_at is not None:
                return None
            row.display_title = display_title
            session.commit()
            session.refresh(row)
            return _to_source_record(row)

    def update_main_relative_path(
        self, source_id: int, main_relative_path: str
    ) -> Optional[SourceRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeSource, source_id)
            if row is None or row.deleted_at is not None:
                return None
            row.main_relative_path = main_relative_path
            session.commit()
            session.refresh(row)
            return _to_source_record(row)

    # Origin

    def append_origin(self, data: OriginCreateInput) -> SourceOriginRecord:
        with self._session_factory() as session:
            model = KnowledgeSourceOrigin(
                source_id=data.source_id,
                import_method=data.import_method,
                original_filename=data.original_filename,
                origin_url=data.origin_url,
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return _to_origin_record(model)

    def list_origins(self, source_id: int) -> list[SourceOriginRecord]:
        with self._session_factory() as session:
            stmt = (
                select(KnowledgeSourceOrigin)
                .where(KnowledgeSourceOrigin.source_id == source_id)
                .order_by(KnowledgeSourceOrigin.imported_at.desc(), KnowledgeSourceOrigin.id.desc())
            )
            return [_to_origin_record(row) for row in session.scalars(stmt)]

    # Snapshot

    def get_snapshot_by_version(
        self, source_id: int, extractor_version: str
    ) -> Optional[SourceSnapshotRecord]:
        with self._session_factory() as session:
            stmt = select(KnowledgeExtractionSnapshot).where(
                KnowledgeExtractionSnapshot.source_id == source_id,
                KnowledgeExtractionSnapshot.extractor_version == extractor_version,
            )
            row = session.scalars(stmt).first()
            return _to_snapshot_record(row) if row is not None else None

    def get_snapshot(self, snapshot_id: int) -> Optional[SourceSnapshotRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeExtractionSnapshot, snapshot_id)
            return _to_snapshot_record(row) if row is not None else None

    # Job

    def create_job(self, data: JobCreateInput) -> JobRecord:
        with self._session_factory() as session:
            model = KnowledgeJob(
                kind=data.kind,
                queue=data.queue,
                source_id=data.source_id,
                snapshot_id=data.snapshot_id,
                stage=data.stage,
                status="pending",
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            return _to_job_record(model)

    def get_job(self, job_id: int) -> Optional[JobRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeJob, job_id)
            return _to_job_record(row) if row is not None else None

    def list_jobs_for_source(self, source_id: int) -> list[JobRecord]:
        with self._session_factory() as session:
            stmt = (
                select(KnowledgeJob)
                .where(KnowledgeJob.source_id == source_id)
                .order_by(KnowledgeJob.created_at.desc(), KnowledgeJob.id.desc())
            )
            return [_to_job_record(row) for row in session.scalars(stmt)]

    def update_job(
        self,
        job_id: int,
        *,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[JobRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeJob, job_id)
            if row is None:
                return None
            if status is not None:
                row.status = status
            if stage is not None:
                row.stage = stage
            if progress is not None:
                row.progress = progress
            if error_code is not None:
                row.error_code = error_code
            if error_message is not None:
                row.error_message = error_message
            session.commit()
            session.refresh(row)
            return _to_job_record(row)

    # Evidence

    def list_evidence(
        self,
        source_id: int,
        snapshot_id: Optional[int] = None,
        *,
        after_ordinal: Optional[int] = None,
        limit: int = 50,
    ) -> EvidencePage:
        with self._session_factory() as session:
            effective_snapshot = snapshot_id
            if effective_snapshot is None:
                source = session.get(KnowledgeSource, source_id)
                if source is None or source.active_snapshot_id is None:
                    return EvidencePage()
                effective_snapshot = source.active_snapshot_id
            stmt = select(KnowledgeEvidence).where(
                KnowledgeEvidence.snapshot_id == effective_snapshot
            )
            if after_ordinal is not None:
                stmt = stmt.where(KnowledgeEvidence.ordinal > after_ordinal)
            stmt = stmt.order_by(KnowledgeEvidence.ordinal.asc()).limit(limit + 1)
            rows = list(session.scalars(stmt))
            next_cursor: Optional[int] = None
            if len(rows) > limit:
                rows = rows[:limit]
                next_cursor = rows[-1].ordinal
            return EvidencePage(
                items=[_to_evidence_record(row) for row in rows],
                next_cursor=next_cursor,
            )

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        with self._session_factory() as session:
            row = session.get(KnowledgeEvidence, evidence_id)
            return _to_evidence_record(row) if row is not None else None

    def search_evidence(
        self,
        query: str,
        *,
        source_ids: Optional[Sequence[int]] = None,
        include_archived: bool = False,
        limit: int = 10,
    ) -> list[EvidenceSearchHit]:
        if not query.strip():
            return []
        clamped_limit = max(1, min(50, limit))
        with self._session_factory() as session:
            params: dict[str, Any] = {
                "query": query,
                "limit": clamped_limit,
            }
            sql = (
                "SELECT fts.evidence_id, fts.source_id, fts.heading_path, fts.content, "
                "bm25(knowledge_evidence_fts) AS score "
                "FROM knowledge_evidence_fts fts "
                "JOIN knowledge_sources ks ON ks.id = fts.source_id "
                "WHERE knowledge_evidence_fts MATCH :query "
            )
            if source_ids:
                placeholders = ",".join(f":sid_{i}" for i in range(len(source_ids)))
                sql += f"AND fts.source_id IN ({placeholders}) "
                for i, sid in enumerate(source_ids):
                    params[f"sid_{i}"] = sid
            if not include_archived:
                sql += "AND ks.lifecycle = 'active' AND ks.deleted_at IS NULL "
            sql += "ORDER BY score ASC LIMIT :limit"
            rows = session.execute(text(sql), params).fetchall()

            hits: list[EvidenceSearchHit] = []
            for row in rows:
                fts_evidence_id = row[0]
                score = row[4] if len(row) > 4 else 0.0
                ev_row = session.get(KnowledgeEvidence, str(fts_evidence_id))
                if ev_row is None:
                    continue
                hits.append(
                    EvidenceSearchHit(
                        evidence_id=ev_row.id,
                        source_id=ev_row.source_id,
                        snapshot_id=ev_row.snapshot_id,
                        block_kind=ev_row.block_kind,
                        heading_path=json.loads(ev_row.heading_path_json or "[]")
                        if ev_row.heading_path_json
                        else [],
                        char_start=ev_row.char_start,
                        char_end=ev_row.char_end,
                        line_start=ev_row.line_start,
                        line_end=ev_row.line_end,
                        canonical_excerpt=ev_row.canonical_excerpt,
                        snippet=_build_snippet(query, ev_row.canonical_excerpt),
                        score=float(score),
                    )
                )
            return hits


def _build_snippet(query: str, content: str, *, window: int = 80) -> str:
    if not content:
        return ""
    needle = query.strip()
    if not needle:
        return content[:window]
    pos = content.lower().find(needle.lower())
    if pos == -1:
        return content[:window]
    start = max(0, pos - window // 4)
    end = min(len(content), pos + len(needle) + window)
    snippet = content[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet


def make_evidence_id(
    *,
    snapshot_digest: str,
    extractor_version: str,
    locator: str,
    content_hash: str,
) -> str:
    payload = f"{snapshot_digest}|{extractor_version}|{locator}|{content_hash}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"ev_{digest}"


def commit_extraction(
    session: Session,
    *,
    snapshot_input: SnapshotCreateInput,
    evidence_drafts: Iterable[EvidenceDraftInput],
    source_id: int,
    source_title: str,
    extractor_version: str,
) -> tuple[KnowledgeExtractionSnapshot, list[KnowledgeEvidence]]:
    """单事务提交：Snapshot + Evidence + FTS + Source 状态切换。

    调用方负责包在 Begin/commit 中。Spec §9 要求 Snapshot/Evidence/FTS/extracted 状态
    在同一事务中可见，任一失败回滚后旧 Snapshot 仍可用，首次失败时 Source 不可搜索。

    幂等：Spec §7.2 同版本重跑 upsert，不覆盖、不立即删除。若 Snapshot 已存在且 digest
    一致，直接复用现有 Evidence 行（包括 FTS），不重复写入。
    """
    existing_snapshot = session.execute(
        select(KnowledgeExtractionSnapshot).where(
            KnowledgeExtractionSnapshot.source_id == snapshot_input.source_id,
            KnowledgeExtractionSnapshot.extractor_version == snapshot_input.extractor_version,
        )
    ).scalars().first()

    if existing_snapshot is not None:
        if existing_snapshot.digest == snapshot_input.digest:
            existing_evidence = (
                session.execute(
                    select(KnowledgeEvidence).where(
                        KnowledgeEvidence.snapshot_id == existing_snapshot.id
                    ).order_by(KnowledgeEvidence.ordinal.asc())
                )
                .scalars()
                .all()
            )
            source_row = session.get(KnowledgeSource, source_id)
            if source_row is not None:
                source_row.active_snapshot_id = existing_snapshot.id
                source_row.extraction_status = "extracted"
                source_row.extraction_error_code = ""
                source_row.extraction_error_message = ""
            return existing_snapshot, list(existing_evidence)
        # extractor 版本相同但 digest 不同：内部不一致，应当创建新版本而非覆盖。
        # KI-02 范围内不会发生（extractor 版本与 digest 同步演进）。
        raise RuntimeError(
            "source_integrity_mismatch: snapshot digest drift within same extractor version"
        )

    snapshot_row = KnowledgeExtractionSnapshot(
        source_id=snapshot_input.source_id,
        extractor_version=snapshot_input.extractor_version,
        parser_version=snapshot_input.parser_version,
        normalization_version=snapshot_input.normalization_version,
        tokenizer_version=snapshot_input.tokenizer_version,
        encoding=snapshot_input.encoding,
        detection_method=snapshot_input.detection_method,
        canonical_text=snapshot_input.canonical_text,
        structure_manifest=snapshot_input.structure_manifest,
        digest=snapshot_input.digest,
        token_count=snapshot_input.token_count,
        char_count=snapshot_input.char_count,
    )
    session.add(snapshot_row)
    session.flush()

    drafts = list(evidence_drafts)
    created: list[KnowledgeEvidence] = []
    previous_id: Optional[str] = None
    for index, draft in enumerate(drafts):
        evidence_id = make_evidence_id(
            snapshot_digest=snapshot_input.digest,
            extractor_version=extractor_version,
            locator=draft.locator,
            content_hash=draft.content_hash,
        )
        heading_path_json = json.dumps(list(draft.heading_path), ensure_ascii=False)
        evidence_row = KnowledgeEvidence(
            id=evidence_id,
            source_id=source_id,
            snapshot_id=snapshot_row.id,
            kind="text",
            block_kind=draft.block_kind,
            ordinal=index + 1,
            heading_path_json=heading_path_json,
            char_start=draft.char_start,
            char_end=draft.char_end,
            line_start=draft.line_start,
            line_end=draft.line_end,
            canonical_excerpt=draft.canonical_excerpt,
            search_text=draft.search_text,
            content_hash=draft.content_hash,
            asset_id=None,
            previous_evidence_id=previous_id,
            next_evidence_id=None,
        )
        session.add(evidence_row)
        session.flush()
        created.append(evidence_row)
        if previous_id is not None:
            prev = session.get(KnowledgeEvidence, previous_id)
            if prev is not None:
                prev.next_evidence_id = evidence_id
        previous_id = evidence_id

    for evidence_row in created:
        session.execute(
            text(
                """
                INSERT INTO knowledge_evidence_fts (
                    evidence_id, source_id, source_title, heading_path, content
                ) VALUES (:eid, :sid, :stitle, :hpath, :content)
                """
            ),
            {
                "eid": evidence_row.id,
                "sid": evidence_row.source_id,
                "stitle": source_title,
                "hpath": evidence_row.heading_path_json,
                "content": evidence_row.search_text or evidence_row.canonical_excerpt,
            },
        )

    source_row = session.get(KnowledgeSource, source_id)
    if source_row is not None:
        source_row.active_snapshot_id = snapshot_row.id
        source_row.extraction_status = "extracted"
        source_row.extraction_error_code = ""
        source_row.extraction_error_message = ""

    return snapshot_row, created
