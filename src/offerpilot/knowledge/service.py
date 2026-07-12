"""Knowledge Ingest 编排服务。

实现 Spec §6 上传协议：
1. Preflight（解码 + Markdown/Text 解析 + token 上限 + 5MiB 上限）+ hash
2. 去重检查
3. staging 写入
4. final 目录创建 + 原子 rename
5. SQLite 单事务：create_source + origin + job + snapshot + evidence + FTS + extracted
6. 返回 202

KI-03 范围：
- 支持 ``.md``、``.txt`` 文件，以及粘贴正文（视为虚拟 ``main.md``）。
- 编码矩阵：UTF-8 / UTF-8 BOM / UTF-16LE BE BOM / 高置信 GBK·GB18030，禁止
  ``errors='ignore'`` 或 ``errors='replace'``。
- 固定 product tokenizer（cl100k_base）+ 64,000 token 上限与 5MiB 字节上限同时执行。
- 错误返回实际值与允许值。

KI-02 同步触发 Extraction；KI-07 替换为持久队列。事务失败时 final 目录可能残留无数据库
记录的孤儿原件，由启动恢复负责清理（KI-07 实现完整恢复）。
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from offerpilot.knowledge.encoding import (
    DecodedContent,
    EncodingError,
    decode_source_bytes,
)
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    MAX_FILE_BYTES,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    ExtractionError,
    MarkdownExtraction,
    MarkdownExtractor,
    compute_source_hash,
)
from offerpilot.knowledge.repository import (
    EvidenceDraftInput,
    JobCreateInput,
    KnowledgeRepository,
    OriginCreateInput,
    SnapshotCreateInput,
    SourceRecord,
    commit_extraction,
)
from offerpilot.knowledge.tokenizer import max_token_limit
from offerpilot.models import KnowledgeJob, KnowledgeSource, KnowledgeSourceOrigin


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Spec §4.1 支持的输入文件类型。粘贴正文统一作为虚拟 ``main.md``。
_SUPPORTED_TEXT_EXTENSIONS = (".md", ".markdown", ".mdx", ".txt")
_PASTE_DEFAULT_FILENAME = "main.md"


@dataclass(frozen=True)
class IngestRequest:
    filename: str
    content_bytes: bytes
    title_hint: str = ""
    import_method: str = "file"
    origin_url: str = ""


@dataclass(frozen=True)
class IngestResult:
    source: SourceRecord
    job_id: int
    deduplicated: bool
    extraction_failed: bool
    extraction_error_code: str
    extraction_error_message: str


class IngestError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class KnowledgeIngestService:
    """Source 上传 + Extraction 编排。"""

    def __init__(
        self,
        repository: KnowledgeRepository,
        data_dir: Path,
        session_factory: "sessionmaker[Session]",
        extractor: Optional[MarkdownExtractor] = None,
    ) -> None:
        self._repository = repository
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._extractor = extractor or MarkdownExtractor()

    def ingest(self, request: IngestRequest) -> IngestResult:
        filename = request.filename.strip()
        if not filename:
            raise IngestError("unsupported_type", "缺少文件名")
        is_paste = request.import_method == "paste"
        if not is_paste and not _has_supported_extension(filename):
            raise IngestError(
                "unsupported_type",
                "当前只支持 .md / .txt 文件或粘贴正文；Bundle 由后续版本扩展",
            )
        safe_filename = _safe_filename(filename if not is_paste else _PASTE_DEFAULT_FILENAME)
        if not safe_filename:
            raise IngestError("unsupported_type", "文件名仅含不支持的字符")

        size = len(request.content_bytes)
        if size == 0:
            raise IngestError("unsupported_type", "原文为空，无法解析")
        if size > MAX_FILE_BYTES:
            raise IngestError(
                "source_too_large",
                (
                    f"原文 {size} 字节超出上限 {MAX_FILE_BYTES} 字节；"
                    "请按主题拆分资料后再上传"
                ),
            )

        try:
            decoded = decode_source_bytes(request.content_bytes)
        except EncodingError as exc:
            raise IngestError(exc.code, exc.message) from exc

        extraction = self._run_extraction(decoded)
        token_count_value = extraction.token_count
        token_limit = max_token_limit()
        if token_count_value > token_limit:
            raise IngestError(
                "source_too_large",
                (
                    f"原文 {token_count_value} tokens 超出上限 {token_limit} tokens；"
                    "请按主题拆分资料后再上传"
                ),
            )

        source_hash = compute_source_hash(request.content_bytes)
        existing = self._repository.get_source_by_hash(source_hash)
        if existing is not None:
            self._repository.append_origin(
                OriginCreateInput(
                    source_id=existing.id,
                    import_method=request.import_method,
                    original_filename=request.filename,
                    origin_url=request.origin_url,
                )
            )
            job = self._repository.create_job(
                JobCreateInput(
                    kind="extract",
                    queue="extraction",
                    source_id=existing.id,
                    stage="deduplicated",
                )
            )
            self._repository.update_job(
                job.id,
                status="succeeded",
                stage="deduplicated",
                progress=100,
            )
            return IngestResult(
                source=existing,
                job_id=job.id,
                deduplicated=True,
                extraction_failed=False,
                extraction_error_code="",
                extraction_error_message="",
            )

        staging_dir = self._data_dir / "knowledge" / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        upload_id = secrets.token_urlsafe(12)
        staging_source_dir = staging_dir / upload_id
        staging_source_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_source_dir / safe_filename
        staging_path.write_bytes(request.content_bytes)

        manifest = {
            "kind": "text" if safe_filename.lower().endswith(".txt") else "markdown",
            "main_filename": safe_filename,
            "total_bytes": size,
            "source_hash": source_hash,
            "extractor_version": EXTRACTOR_VERSION,
            "encoding": decoded.encoding,
            "detection_method": decoded.detection_method,
            "tokenizer_version": extraction.tokenizer_version,
            "token_count": token_count_value,
        }
        manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)

        title_hint = (
            request.title_hint
            or _derive_title_from_extraction(extraction)
            or _derive_title_from_filename(safe_filename)
        ).strip()

        drafts = [
            EvidenceDraftInput(
                block_kind=draft.block_kind,
                heading_path=tuple(draft.heading_path),
                char_start=draft.char_start,
                char_end=draft.char_end,
                line_start=draft.line_start,
                line_end=draft.line_end,
                canonical_excerpt=draft.canonical_excerpt,
                search_text=draft.search_text,
                content_hash=draft.content_hash,
                locator=draft.locator,
            )
            for draft in extraction.evidence_drafts
        ]

        snapshot_input_template = SnapshotCreateInput(
            source_id=0,
            extractor_version=EXTRACTOR_VERSION,
            parser_version=PARSER_VERSION,
            normalization_version=NORMALIZATION_VERSION,
            tokenizer_version=extraction.tokenizer_version,
            encoding=extraction.encoding,
            detection_method=extraction.detection_method,
            canonical_text=extraction.canonical_text,
            structure_manifest=extraction.structure_manifest,
            digest=extraction.digest,
            token_count=token_count_value,
            char_count=extraction.char_count,
        )

        source_kind = "markdown"
        main_media_type = "text/markdown"
        if safe_filename.lower().endswith(".txt"):
            source_kind = "text"
            main_media_type = "text/plain"

        source_id, job_id = self._commit_new_source(
            source_hash=source_hash,
            source_kind=source_kind,
            main_media_type=main_media_type,
            safe_filename=safe_filename,
            title_hint=title_hint,
            manifest_json=manifest_json,
            size=size,
            token_count=token_count_value,
            request=request,
            staging_path=staging_path,
            staging_source_dir=staging_source_dir,
            snapshot_input_template=snapshot_input_template,
            drafts=drafts,
        )

        refreshed_source = self._repository.get_source(source_id)
        refreshed_job = self._repository.get_job(job_id)
        if refreshed_source is None or refreshed_job is None:
            raise IngestError(
                "source_integrity_mismatch",
                "事务提交后无法读取 Source / Job",
            )

        return IngestResult(
            source=refreshed_source,
            job_id=refreshed_job.id,
            deduplicated=False,
            extraction_failed=False,
            extraction_error_code="",
            extraction_error_message="",
        )

    def _run_extraction(self, decoded: DecodedContent) -> MarkdownExtraction:
        """Spec §7.1：固定版本 AST 解析，捕获 Extraction/Encoding 错误。"""

        try:
            return self._extractor.extract(
                decoded.text,
                encoding=decoded.encoding,
                detection_method=decoded.detection_method,
            )
        except ExtractionError as exc:
            raise IngestError(exc.code, exc.message) from exc

    def _commit_new_source(
        self,
        *,
        source_hash: str,
        source_kind: str,
        main_media_type: str,
        safe_filename: str,
        title_hint: str,
        manifest_json: str,
        size: int,
        token_count: int,
        request: IngestRequest,
        staging_path: Path,
        staging_source_dir: Path,
        snapshot_input_template: SnapshotCreateInput,
        drafts: list[EvidenceDraftInput],
    ) -> tuple[int, int]:
        """单事务创建 Source/Origin/Job + rename + Snapshot/Evidence/FTS。

        Spec §6 / §9：数据库提交前完成 final rename；事务失败时无任何 DB 行可见，
        final 目录残留由启动恢复清理。
        """

        with self._session_factory() as session:
            with session.begin():
                source_row = KnowledgeSource(
                    source_hash=source_hash,
                    source_kind=source_kind,
                    display_title="",
                    title_hint=title_hint,
                    main_filename=safe_filename,
                    main_media_type=main_media_type,
                    main_relative_path="",
                    manifest_json=manifest_json,
                    total_bytes=size,
                    token_count=token_count,
                    lifecycle="active",
                    extraction_status="processing",
                    extraction_error_code="",
                    extraction_error_message="",
                    brief_status="not_started",
                    brief_block_reason="",
                    brief_error_code="",
                    brief_error_message="",
                )
                session.add(source_row)
                session.flush()
                source_id = source_row.id

                final_relative_path = (
                    f"knowledge/sources/{source_id}/{safe_filename}"
                )
                source_row.main_relative_path = final_relative_path

                final_dir = self._data_dir / "knowledge" / "sources" / str(source_id)
                final_dir.mkdir(parents=True, exist_ok=True)
                final_path = final_dir / safe_filename
                try:
                    staging_path.replace(final_path)
                except OSError as exc:
                    _safe_cleanup(staging_source_dir)
                    _safe_cleanup(final_dir)
                    raise IngestError(
                        "source_integrity_mismatch",
                        "原件无法落到正式目录",
                    ) from exc
                try:
                    staging_source_dir.rmdir()
                except OSError:
                    pass

                session.add(
                    KnowledgeSourceOrigin(
                        source_id=source_id,
                        import_method=request.import_method,
                        original_filename=request.filename,
                        origin_url=request.origin_url,
                    )
                )

                job_row = KnowledgeJob(
                    kind="extract",
                    queue="extraction",
                    source_id=source_id,
                    stage="extracting",
                    status="running",
                )
                session.add(job_row)
                session.flush()
                job_id = job_row.id

                snapshot_input_resolved = SnapshotCreateInput(
                    source_id=source_id,
                    extractor_version=snapshot_input_template.extractor_version,
                    parser_version=snapshot_input_template.parser_version,
                    normalization_version=snapshot_input_template.normalization_version,
                    tokenizer_version=snapshot_input_template.tokenizer_version,
                    encoding=snapshot_input_template.encoding,
                    detection_method=snapshot_input_template.detection_method,
                    canonical_text=snapshot_input_template.canonical_text,
                    structure_manifest=snapshot_input_template.structure_manifest,
                    digest=snapshot_input_template.digest,
                    token_count=snapshot_input_template.token_count,
                    char_count=snapshot_input_template.char_count,
                )

                title_for_search = title_hint or safe_filename
                commit_extraction(
                    session,
                    snapshot_input=snapshot_input_resolved,
                    evidence_drafts=drafts,
                    source_id=source_id,
                    source_title=title_for_search,
                    extractor_version=EXTRACTOR_VERSION,
                )

                job_row.status = "succeeded"
                job_row.stage = "extracted"
                job_row.progress = 100

        return source_id, job_id


def _has_supported_extension(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(ext) for ext in _SUPPORTED_TEXT_EXTENSIONS)


def _safe_filename(name: str) -> str:
    collapsed = _SAFE_FILENAME_RE.sub("-", name).strip("-._")
    if not collapsed:
        return ""
    if len(collapsed.encode("utf-8")) > 255:
        collapse_base = collapsed.rsplit(".", 1)[0]
        suffix = collapsed.rsplit(".", 1)[1] if "." in collapsed else ""
        collapse_base = collapse_base[: 200]
        collapsed = f"{collapse_base}.{suffix}" if suffix else collapse_base
    return collapsed


def _derive_title_from_extraction(extraction: MarkdownExtraction) -> str:
    for draft in extraction.evidence_drafts:
        if draft.heading_path:
            return draft.heading_path[0][:120]
    for draft in extraction.evidence_drafts:
        if draft.canonical_excerpt.strip():
            return draft.canonical_excerpt.strip()[:120]
    return ""


def _derive_title_from_filename(filename: str) -> str:
    for ext in _SUPPORTED_TEXT_EXTENSIONS:
        if filename.lower().endswith(ext):
            return filename[: -len(ext)]
    return filename.removesuffix(".md")


def _safe_cleanup(target: Path) -> None:
    try:
        if target.is_dir():
            for child in target.iterdir():
                if child.is_dir():
                    _safe_cleanup(child)
                else:
                    child.unlink(missing_ok=True)
            target.rmdir()
        else:
            target.unlink(missing_ok=True)
    except OSError:
        pass
