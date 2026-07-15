"""Knowledge Job Worker / Runner。

KI-07 范围：
- ``ExtractionWorker.execute`` 从持久队列消费一个 Extract Job，重新构建
  Snapshot/Evidence/FTS，并保留 Spec §6 / §9 的单事务提交语义。
- ``KnowledgeJobRunner`` 提供 ``tick_extraction`` / ``tick_brief`` / ``retry_extract``
  方法，按 Spec §12 单并发 FIFO 调度。不启动后台线程，由测试或未来 CLI 驱动。

KI-09 范围：
- ``BriefWorker.execute`` 实现 Brief generation + 程序校验 + 独立 Validator + 一次
  受约束修复 + 单事务提交当前 Brief。
- ``KnowledgeJobRunner.tick_brief`` 替换 KI-07 占位实现，从队列消费 brief Job 后
  委托给 ``BriefWorker``。

Spec §12 关键约束：
- Extraction queue 同时承载 Source 永久删除等本地维护 Job；Delete Job 由本类消费。
- Brief queue 并发固定为 1；与 Extraction queue 可以并行。
- 迟到的旧 lease 结果因 owner/Attempt 不匹配而拒绝提交（``complete_job`` 验证
  ``attempt_token``）。
- pending Job 立即 cancel；running 本地任务在安全点检查 ``is_job_canceled`` 并停止。
- 已发出的模型调用即使无法中止，其返回也不能在取消后提交（``complete_job`` 在
  ``status != running`` 时返回 ``False``）。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import random
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional

from litellm import completion as litellm_completion
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.config import AIProviderProfile, Config
from offerpilot.knowledge.brief import (
    BRIEF_LANGUAGE,
    BRIEF_MIN_CONTEXT_WINDOW,
    BRIEF_PROMPT_VERSION,
    BRIEF_SCHEMA_VERSION,
    BriefPayload,
    BriefSchemaError,
    SectionCoveragePlan,
    build_generation_prompt,
    build_repair_prompt,
    build_section_coverage_plan,
    build_validation_prompt,
    collect_brief_statement_blocks,
    parse_brief_payload,
    parse_support_decision,
    validate_brief_against_evidence,
    _extract_all_json_objects,
)
from offerpilot.knowledge.encoding import DecodedContent, decode_source_bytes
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    METADATA_EXTRACTION_VERSION,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    MarkdownExtractor,
    compute_bundle_source_hash,
    compute_source_hash,
)
from offerpilot.knowledge.repository import (
    AssetCreateInput,
    BriefAttemptCreateInput,
    EvidenceDraftInput,
    EvidenceRecord,
    JobRecord,
    KnowledgeBriefAttemptError,
    KnowledgeRepository,
    SnapshotCreateInput,
    SourceRecord,
    commit_extraction,
)
from offerpilot.knowledge.tokenizer import max_token_limit
from offerpilot.models import KnowledgeJob, KnowledgeSource


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecodedMarkdown(DecodedContent):
    """兼容旧类型名；KI-03 之后请直接使用 ``DecodedContent``。"""


def decode_markdown_bytes(raw_bytes: bytes) -> Optional[DecodedMarkdown]:
    """兼容 KI-02 接口的薄包装。新代码请直接使用 ``decode_source_bytes``。

    返回 ``None`` 表示编码识别失败；新 ``decode_source_bytes`` 会抛 ``EncodingError``。
    """

    try:
        result = decode_source_bytes(raw_bytes)
    except Exception:
        return None
    return DecodedMarkdown(
        text=result.text,
        encoding=result.encoding,
        detection_method=result.detection_method,
    )


@dataclass(frozen=True)
class JobExecutionResult:
    """``ExtractionWorker.execute`` 返回。

    ``accepted`` 表示 lease 仍有效且 Job 未取消，``complete_job`` 已被调用。
    ``rejected`` 表示 lease 已过期或 token 不匹配，worker 应停止。
    """

    job_id: int
    accepted: bool
    status: str
    error_code: str
    error_message: str


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """将 SQLite 返回的 naive 时间按 UTC 解释，避免 lease 判断抛出类型错误。"""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_data_path(
    data_dir: Path,
    relative_path: str,
    expected_dir: Optional[Path] = None,
) -> Optional[Path]:
    """解析 Source/Asset 路径，并拒绝绝对路径和目录穿越。

    ``expected_dir`` 用于把路径进一步限制在当前 Source（或其 assets 子目录）内；
    仅限制到 data_dir 会允许被篡改的 SQLite 路径指向另一个 Source 的原件。
    """

    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None
    root = data_dir.resolve()
    resolved = (data_dir / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    if expected_dir is not None:
        try:
            resolved.relative_to(expected_dir.resolve())
        except (OSError, ValueError):
            return None
    return resolved


def _remove_path(path: Path) -> None:
    """删除 Worker 管辖的文件/目录而不跟随符号链接。"""

    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except OSError:
        # SQLite 已提交后只能等待下一次启动恢复继续清理。
        pass


def _job_record_is_active(
    job: Optional[JobRecord],
    *,
    attempt_token: str,
    lease_owner: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """检查提交前的 Job lease/cancel 门禁。

    该检查用于 Worker 在提交事务之前快速拒绝迟到结果；真正的事务内检查在
    ``_commit_extraction_if_active`` 中再次执行。
    """

    if job is None or job.status != "running" or job.canceled:
        return False
    if job.attempt_token != attempt_token:
        return False
    if lease_owner is not None and job.lease_owner != lease_owner:
        return False
    expires_at = _as_utc(job.lease_expires_at)
    if expires_at is not None and expires_at <= (now or datetime.now(timezone.utc)):
        return False
    return True


class ExtractionWorker:
    """Spec §6 / §12：从队列消费 Extract Job，重新构建 Snapshot/Evidence/FTS。

    Extraction 由本类在持久队列中完成；本类还负责在成功提交后触发 Brief 入队。
    主要用途：
    1. KI-07 持久队列调度（``KnowledgeJobRunner.tick_extraction`` 调用）。
    2. 未来手动重试 / 恢复路径。
    3. 单元测试幂等性验证。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        data_dir: Path,
        session_factory: sessionmaker[Session],
        extractor: Optional[MarkdownExtractor] = None,
        on_extraction_succeeded: Optional[Callable[[int], Any]] = None,
    ) -> None:
        self._repository = repository
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._extractor = extractor or MarkdownExtractor()
        self._on_extraction_succeeded = on_extraction_succeeded

    def can_decode(self, source: "object") -> bool:
        source_id = getattr(source, "id", None)
        expected_dir = (
            self._data_dir / "knowledge" / "sources" / str(source_id)
            if source_id is not None
            else None
        )
        path = _resolve_data_path(
            self._data_dir,
            str(getattr(source, "main_relative_path", "")),
            expected_dir,
        )
        if path is None or not path.is_file():
            return False
        return decode_markdown_bytes(path.read_bytes()) is not None

    def verify_source_integrity(self, source: SourceRecord) -> Optional[str]:
        """Spec §6：Worker 每次读取正式 Source 时核验 manifest/hash。

        返回 ``None`` 表示通过；返回字符串为 ``source_integrity_mismatch`` 错误细节。
        校验项：
        - 主文件存在且大小匹配 ``total_bytes``。
        - manifest 中 ``source_hash`` 与重新计算的 hash 一致。
        """
        source_dir = self._data_dir / "knowledge" / "sources" / str(source.id)
        main_path = _resolve_data_path(
            self._data_dir,
            source.main_relative_path,
            source_dir,
        )
        if main_path is None:
            return "main file path is outside data directory"
        if not main_path.is_file():
            return "main file missing"
        raw_bytes = main_path.read_bytes()
        if len(raw_bytes) != source.total_bytes:
            return (
                f"main file size mismatch: expected {source.total_bytes}, "
                f"got {len(raw_bytes)}"
            )
        try:
            manifest = json.loads(source.manifest_json or "{}")
        except json.JSONDecodeError:
            manifest = {}
        expected_hash = str(manifest.get("source_hash") or "")
        if not expected_hash:
            return "manifest missing source_hash"

        bundle = manifest.get("bundle")
        if isinstance(bundle, dict):
            # Bundle hash 必须覆盖主文件、每个附件的原始字节和逻辑路径。
            # 仅比较主文件会让附件被替换后仍被错误地视为完整 Source。
            raw_assets = self._repository.list_assets(source.id)
            expected_names = bundle.get("asset_logical_names")
            if not isinstance(expected_names, list):
                return "bundle manifest missing asset names"
            expected_name_set = {str(name) for name in expected_names}
            actual_name_set = {asset.logical_name for asset in raw_assets}
            if actual_name_set != expected_name_set:
                return "bundle asset manifest mismatch"
            assets: list[tuple[str, bytes]] = []
            for asset in raw_assets:
                asset_path = _resolve_data_path(
                    self._data_dir,
                    asset.relative_path,
                    source_dir / "assets",
                )
                if asset_path is None:
                    return f"asset path is outside data directory: {asset.logical_name}"
                if not asset_path.is_file():
                    return f"asset file missing: {asset.logical_name}"
                content = asset_path.read_bytes()
                if len(content) != asset.bytes_size:
                    return f"asset size mismatch: {asset.logical_name}"
                digest = hashlib.sha256(content).hexdigest()
                if digest != asset.sha256:
                    return f"asset hash mismatch: {asset.logical_name}"
                assets.append((asset.logical_name, content))
            actual_hash = compute_bundle_source_hash(raw_bytes, assets)
        else:
            actual_hash = compute_source_hash(raw_bytes)
        if actual_hash != expected_hash:
            return (
                f"source_hash mismatch: expected {expected_hash}, got {actual_hash}"
            )
        return None

    def _mark_extraction_failed(
        self, source: SourceRecord, *, code: str, message: str
    ) -> None:
        """首次 Extraction 失败时同步暴露 Source 错误。

        已有 active Snapshot 的重试失败必须保留 ``extracted`` 和旧 Evidence；只有
        尚无可用 Snapshot 的 Source 才切换为 ``failed``。
        """
        if source.extraction_status == "extracted" and source.active_snapshot_id is not None:
            return
        self._repository.update_source_state(
            source.id,
            extraction_status="failed",
            extraction_error_code=code,
            extraction_error_message=message[:500],
        )

    def _asset_inputs_for_source(
        self, source: SourceRecord
    ) -> tuple[AssetCreateInput, ...]:
        """从不可变 Asset 元数据构造 Snapshot 提交所需的输入。

        Asset 行由首次 ingest 创建，重建时只能复用其逻辑路径和 hash，不能从
        Worker 重新推导展示路径或创建第二份文件。
        """

        manifest = json.loads(source.manifest_json or "{}")
        if not isinstance(manifest.get("bundle"), dict):
            return ()
        records = self._repository.list_assets(source.id)
        return tuple(
            AssetCreateInput(
                logical_name=asset.logical_name,
                media_type=asset.media_type,
                relative_path=asset.relative_path,
                bytes_size=asset.bytes_size,
                sha256=asset.sha256,
                width=asset.width,
                height=asset.height,
            )
            for asset in records
        )

    def _commit_extraction_if_active(
        self,
        *,
        job: JobRecord,
        attempt_token: str,
        lease_owner: str,
        snapshot_input: SnapshotCreateInput,
        evidence_drafts: list[EvidenceDraftInput],
        source_title: str,
        asset_inputs: tuple[AssetCreateInput, ...],
    ) -> bool:
        """在同一事务内复核 lease/cancel 后提交 Extraction 产物。

        ``complete_job`` 只能在产物提交之后验证 token，单独调用会留下“取消后仍
        发布产物”的窗口。这里直接读取 Job/Source 行并把校验与
        ``commit_extraction`` 放进同一个事务，避免该窗口。
        """

        moment = datetime.now(timezone.utc)
        with self._session_factory() as session:
            with session.begin():
                job_row = session.get(KnowledgeJob, job.id)
                if job_row is None:
                    return False
                job_view = JobRecord(
                    id=job_row.id,
                    kind=job_row.kind,
                    queue=job_row.queue,
                    source_id=job_row.source_id,
                    snapshot_id=job_row.snapshot_id,
                    stage=job_row.stage,
                    status=job_row.status,
                    progress=job_row.progress,
                    retry_count=job_row.retry_count,
                    next_retry_at=job_row.next_retry_at,
                    error_code=job_row.error_code,
                    error_message=job_row.error_message,
                    canceled=bool(job_row.canceled),
                    lease_owner=job_row.lease_owner,
                    lease_expires_at=job_row.lease_expires_at,
                    heartbeat_at=job_row.heartbeat_at,
                    attempt_token=job_row.attempt_token,
                    created_at=job_row.created_at,
                    updated_at=job_row.updated_at,
                )
                if not _job_record_is_active(
                    job_view,
                    attempt_token=attempt_token,
                    lease_owner=lease_owner,
                    now=moment,
                ):
                    return False
                source_row = session.get(KnowledgeSource, snapshot_input.source_id)
                if source_row is None or source_row.lifecycle == "deleting":
                    return False
                commit_extraction(
                    session,
                    snapshot_input=snapshot_input,
                    evidence_drafts=evidence_drafts,
                    source_id=snapshot_input.source_id,
                    source_title=source_title,
                    extractor_version=EXTRACTOR_VERSION,
                    asset_inputs=asset_inputs,
                )
                # Evidence 提交与 Extraction Job 终态必须属于同一事务。若先提交
                # Evidence、再单独 complete_job，进程可能在两次事务之间崩溃，留下
                # 可检索产物但仍是 running 的 Job，重启后会重复 claim。
                job_row.status = "succeeded"
                job_row.stage = "extracted"
                job_row.progress = 100
                job_row.error_code = ""
                job_row.error_message = ""
                job_row.lease_expires_at = None
                job_row.updated_at = moment
        return True

    def _execute_delete(
        self,
        job: JobRecord,
        *,
        attempt_token: str,
        lease_owner: str,
    ) -> JobExecutionResult:
        """消费 Delete Job，完成 quarantine → SQLite → 物理清理协议。

        文件系统 rename 与 SQLite 提交无法共享一个事务，因此每个顺序点都必须可由
        启动恢复重做：rename 前崩溃由 deleting Source 重试，提交后崩溃由孤儿
        quarantine 清理。请求线程不调用此方法。
        """

        if not _job_record_is_active(
            job, attempt_token=attempt_token, lease_owner=lease_owner
        ):
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status=job.status,
                error_code="job_lease_mismatch",
                error_message="Delete Job lease 已失效",
            )
        source_id = job.source_id
        if source_id is None:
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="source_missing",
                error_code="source_integrity_mismatch",
                error_message="Delete Job 缺少 source_id",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message="Delete Job 缺少 source_id",
            )

        source = self._repository.get_deleting_source(source_id)
        if source is None:
            # 启动恢复可能已经完成了同一删除并清理了 Source/Job。此时不能再写入
            # 任何新行，也不能把一个已完成的删除报告为普通 Source 缺失错误。
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="succeeded",
                error_code="",
                error_message="",
            )

        knowledge_root = self._data_dir / "knowledge"
        source_dir = knowledge_root / "sources" / str(source_id)
        sources_root = knowledge_root / "sources"
        quarantine_root = knowledge_root / "quarantine"
        quarantine_dir = quarantine_root / str(source_id)
        try:
            if knowledge_root.is_symlink() or sources_root.is_symlink():
                raise OSError("Source 根目录不能是符号链接")
            quarantine_root.mkdir(parents=True, exist_ok=True)
            if quarantine_root.is_symlink():
                raise OSError("quarantine 根目录不能是符号链接")
            if source_dir.is_symlink() or quarantine_dir.is_symlink():
                raise OSError("Source/quarantine 目录不能是符号链接")
            if not quarantine_dir.exists() and source_dir.exists():
                # 两个目录位于同一 data_dir 下，Path.replace 使用原子 rename；不使用
                # copy+unlink，避免删除事务期间出现半份原件。
                source_dir.replace(quarantine_dir)
        except OSError as exc:
            self._repository.update_job(
                job.id,
                stage="quarantine_retry",
                error_code="source_filesystem_error",
                error_message=str(exc)[:500],
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="running",
                error_code="source_filesystem_error",
                error_message=str(exc)[:500],
            )

        # rename 后可能正好跨过 lease 到期或被外部恢复路径接管；失去 lease 的
        # Worker 不能继续提交 SQLite 删除事务。quarantine 保留给下一次恢复重试。
        if not _job_record_is_active(
            self._repository.get_job(job.id),
            attempt_token=attempt_token,
            lease_owner=lease_owner,
        ):
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status="failed",
                error_code="job_lease_mismatch",
                error_message="Delete Job 在提交前 lease 已失效",
            )

        try:
            committed = self._repository.complete_purge(source_id)
        except Exception as exc:  # noqa: BLE001 - 下次 lease/启动恢复重试
            self._repository.update_job(
                job.id,
                stage="purge_retry",
                error_code="delete_commit_failed",
                error_message=str(exc)[:500],
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="running",
                error_code="delete_commit_failed",
                error_message=str(exc)[:500],
            )

        if not committed:
            # 另一个恢复路径已经删除了 DB 行；删除请求本身仍然已经完成。
            committed = True

        # SQLite 已提交后物理删除失败不能回滚数据库；启动恢复会继续清理孤儿目录。
        for path in (quarantine_dir, source_dir):
            _remove_path(path)
        return JobExecutionResult(
            job_id=job.id,
            accepted=True,
            status="succeeded",
            error_code="",
            error_message="",
        )

    def execute(
        self,
        job: JobRecord,
        *,
        attempt_token: str,
        lease_owner: str,
    ) -> JobExecutionResult:
        """执行一个 Extract Job。

        步骤：
        1. 验证 attempt_token 与 lease_owner 匹配（迟到 lease 拒绝）。
        2. 检查 canceled。
        3. 读取 Source + 校验 manifest/hash。
        4. 重新执行 Extraction（commit_extraction 幂等）。
        5. complete_job(status=succeeded | failed)。
        """
        if job.attempt_token != attempt_token or job.lease_owner != lease_owner:
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status=job.status,
                error_code="job_lease_mismatch",
                error_message="attempt_token or lease_owner mismatch",
            )
        if job.status != "running":
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status=job.status,
                error_code="job_not_running",
                error_message=f"job status is {job.status}, expected running",
            )
        if job.kind == "delete":
            return self._execute_delete(
                job,
                attempt_token=attempt_token,
                lease_owner=lease_owner,
            )
        if self._repository.is_job_canceled(job.id):
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="canceled",
                stage="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )

        source = self._repository.get_source(job.source_id or 0)
        if source is None:
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="source_missing",
                error_code="source_integrity_mismatch",
                error_message="Source 不存在或已被删除",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message="Source 不存在或已被删除",
            )

        integrity_error = self.verify_source_integrity(source)
        if integrity_error is not None:
            self._mark_extraction_failed(
                source, code="source_integrity_mismatch", message=integrity_error
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="integrity_check",
                error_code="source_integrity_mismatch",
                error_message=integrity_error,
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message=integrity_error,
            )

        try:
            main_path = _resolve_data_path(
                self._data_dir,
                source.main_relative_path,
                self._data_dir / "knowledge" / "sources" / str(source.id),
            )
            if main_path is None:
                raise ValueError("main file path is outside data directory")
            raw_bytes = main_path.read_bytes()
            decoded = decode_source_bytes(raw_bytes)
            extraction = self._extractor.extract(
                decoded.text,
                encoding=decoded.encoding,
                detection_method=decoded.detection_method,
            )
        except Exception as exc:
            self._mark_extraction_failed(
                source, code="extraction_failed", message=str(exc)
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="extraction_failed",
                error_code="extraction_failed",
                error_message=str(exc)[:500],
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="extraction_failed",
                error_message=str(exc)[:500],
            )

        if self._repository.is_job_canceled(job.id):
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="canceled",
                stage="canceled",
                error_code="job_canceled",
                error_message="用户在 Extraction 后取消",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="canceled",
                error_code="job_canceled",
                error_message="用户在 Extraction 后取消",
            )

        token_count_value = extraction.token_count
        token_limit = max_token_limit()
        if token_count_value > token_limit:
            self._mark_extraction_failed(
                source,
                code="source_too_large",
                message=(
                    f"原文 {token_count_value} tokens 超出上限 {token_limit} tokens"
                ),
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="token_limit",
                error_code="source_too_large",
                error_message=(
                    f"原文 {token_count_value} tokens 超出上限 {token_limit} tokens"
                ),
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_too_large",
                error_message=(
                    f"原文 {token_count_value} tokens 超出上限 {token_limit} tokens"
                ),
            )

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
                kind="asset" if draft.block_kind == "image" else "text",
                logical_name=str(draft.extra.get("logical_name", "")),
                alt_text=str(draft.extra.get("alt_text", "")),
            )
            for draft in extraction.evidence_drafts
        ]
        snapshot_input = SnapshotCreateInput(
            source_id=source.id,
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
            metadata_extraction_version=METADATA_EXTRACTION_VERSION,
            provenance_title=extraction.provenance.title,
            provenance_author=extraction.provenance.author,
            provenance_url=extraction.provenance.url,
            provenance_published_at=extraction.provenance.published_at,
        )
        # Spec KBR-02：单字段非法只忽略+安全警告。warnings 只含字段名与原因，不含
        # Source 正文，符合隐私边界（普通日志不打印 Source/Evidence 正文）。
        if extraction.provenance.warnings:
            _LOGGER.warning(
                "knowledge source %s provenance fields ignored: %s",
                source.id,
                "; ".join(extraction.provenance.warnings),
            )
        title_for_search = source.display_title or source.title_hint or source.main_filename
        try:
            asset_inputs = self._asset_inputs_for_source(source)
            # 主文件或附件可能在 Extraction 期间被外部进程替换；提交前再次校验
            # 完整 manifest，避免把已漂移的 Bundle 写成新的 active Snapshot。
            integrity_error = self.verify_source_integrity(source)
            if integrity_error is not None:
                raise ValueError(integrity_error)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._mark_extraction_failed(
                source, code="source_integrity_mismatch", message=str(exc)
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="integrity_check",
                error_code="source_integrity_mismatch",
                error_message=str(exc)[:500],
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message=str(exc)[:500],
            )
        try:
            committed = self._commit_extraction_if_active(
                job=job,
                attempt_token=attempt_token,
                lease_owner=lease_owner,
                snapshot_input=snapshot_input,
                evidence_drafts=drafts,
                source_title=title_for_search,
                asset_inputs=asset_inputs,
            )
            if not committed:
                error_code = (
                    "job_canceled"
                    if self._repository.is_job_canceled(job.id)
                    else "job_lease_mismatch"
                )
                status = "canceled" if error_code == "job_canceled" else "failed"
                ok, _ = self._repository.complete_job(
                    job.id,
                    attempt_token=attempt_token,
                    status=status,
                    stage="canceled" if status == "canceled" else "commit_conflict",
                    error_code=error_code,
                    error_message=(
                        "用户取消" if status == "canceled" else "提交时 lease 已失效"
                    ),
                )
                return JobExecutionResult(
                    job_id=job.id,
                    accepted=ok,
                    status=status,
                    error_code=error_code,
                    error_message=(
                        "用户取消" if status == "canceled" else "提交时 lease 已失效"
                    ),
                )
        except Exception as exc:
            self._mark_extraction_failed(
                source, code="extraction_failed", message=str(exc)
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=attempt_token,
                status="failed",
                stage="commit_failed",
                error_code="extraction_failed",
                error_message=str(exc)[:500],
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="extraction_failed",
                error_message=str(exc)[:500],
            )

        # ``_commit_extraction_if_active`` 已在同一事务内将 Job 标记 succeeded；
        # 这里不能再次开启独立事务，否则会重新引入提交窗口。
        ok = True
        if self._on_extraction_succeeded is not None and job.source_id is not None:
            try:
                self._on_extraction_succeeded(job.source_id)
            except Exception as exc:  # noqa: BLE001 - Brief 入队失败需持久化可见
                self._repository.update_source_state(
                    job.source_id,
                    brief_status="failed",
                    brief_block_reason="",
                    brief_error_code="brief_enqueue_failed",
                    brief_error_message=str(exc)[:500] or "Brief Job 入队失败",
                )
        return JobExecutionResult(
            job_id=job.id,
            accepted=ok,
            status="succeeded",
            error_code="",
            error_message="",
        )


def _hash_main_bytes(raw_bytes: bytes) -> str:
    """保留旧内部调用方的单文件 hash 兼容函数。"""

    return compute_source_hash(raw_bytes)


# ---------------------------------------------------------------------------
# KI-09 Brief generation / validation
# ---------------------------------------------------------------------------


BriefModelClient = Callable[..., Any]

# KI-10 / Spec §11.4：Provider 层重试与退避参数。
# 每个 Provider 最多调用 3 次（首次 + 2 次自动重试）；退避优先 Retry-After，否则 2s/10s。
BRIEF_PROVIDER_MAX_ATTEMPTS = 3
BRIEF_RETRY_BACKOFF_SECONDS = (2.0, 10.0)
BRIEF_RETRY_MAX_DELAY_SECONDS = 60.0  # Retry-After 上限，避免 Provider 要求过长等待

# Spec §13 / §11.4：Brief Provider 错误归类。permanent（auth/model）不重试不切 fallback；
# transient（timeout/ratelimit/5xx）重试且可在耗尽后切 fallback。内容质量错误
# （brief_schema_invalid 等）由程序校验产生，不走 Provider 重试/failover 路径。
BRIEF_PROVIDER_TRANSIENT_ERRORS = frozenset({"provider_transient_error"})

# Brief 单次模型调用超时（秒）。litellm 默认 600s 过长——配合后台 heartbeat，
# 超过此值的卡死调用转为 transient error 走 retry/failover，而非无限阻塞到 lease 过期。
BRIEF_MODEL_TIMEOUT_SECONDS = 270
# 后台 heartbeat：LLM 同步阻塞调用期间每 N 秒续约外层 queue lease，防止单次
# generation/validator 调用超过 lease 时长被并行 recover 回收。
BRIEF_HEARTBEAT_INTERVAL_SECONDS = 30.0
BRIEF_HEARTBEAT_LEASE_SECONDS = 120


def _is_transient(error_code: str) -> bool:
    return error_code in BRIEF_PROVIDER_TRANSIENT_ERRORS


def _extract_retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Spec §11.4 优先使用 Retry-After。

    litellm 异常族未统一导出响应头，尝试常见属性；解析失败返回 ``None``。
    """
    for attr in ("retry_after", "response_headers", "headers"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(max(0.0, value))
        candidate: Optional[str] = None
        if isinstance(value, dict):
            for key in ("Retry-After", "retry-after", "RetryAfter"):
                if key in value:
                    candidate = value[key]
                    break
        elif isinstance(value, str):
            candidate = value
        if candidate is None:
            continue
        try:
            return float(max(0.0, float(candidate)))
        except (TypeError, ValueError):
            return None
    return None


def _retry_delay_seconds(exc: BaseException, attempt_index: int) -> float:
    """Spec §11.4：Retry-After 优先；否则 2s/10s 退避 + 少量抖动。

    ``attempt_index`` 从 1 开始（即将进行的第几次重试）。
    """
    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is not None:
        return min(retry_after, BRIEF_RETRY_MAX_DELAY_SECONDS)
    # attempt_index 1 → 第 1 次重试退避 2s；attempt_index 2 → 10s。
    idx = max(1, min(attempt_index, len(BRIEF_RETRY_BACKOFF_SECONDS)))
    base = BRIEF_RETRY_BACKOFF_SECONDS[idx - 1]
    jitter = random.uniform(0.0, 0.25)
    return base + jitter


def _provider_label(provider: AIProviderProfile) -> str:
    return f"{provider.id}/{provider.model}"


@dataclass(frozen=True)
class BriefGenerationResult:
    """``BriefWorker.execute`` 单次 generation 返回。"""

    payload: BriefPayload
    validation_report_json: str
    support_results: list[dict[str, Any]]
    token_input_count: int
    token_output_count: int
    latency_ms: int
    # KI-10 / Spec §11.3：实际成功 Provider（可能为 fallback）与 Provider 层重试总次数。
    actual_provider_id: str = ""
    actual_provider_model: str = ""
    provider_retry_count: int = 0
    # Spec §10.3：到达当前 Brief 所经历的 repair 次数（含 support repair）。
    repair_count: int = 0


@dataclass
class _RetryState:
    """Spec §11.4 Provider 层重试进度的可变累积器。

    ``total_retries`` 跨 primary/fallback 与 generation/validation 累计，持久化到
    Attempt.provider_retry_count，保证重启后不从零开始。实际成功 Provider 由
    ``_run_generation_with_repair`` 单独跟踪并传给 validation 与 commit。
    """

    attempt_id: int
    total_retries: int = 0
    next_retry_at: Optional[datetime] = None
    last_error_code: str = ""

    def bump(
        self,
        repository: KnowledgeRepository,
        *,
        error_code: str,
        error_message: str,
        delay_seconds: float,
        sleeper: Callable[[float], None],
    ) -> None:
        """持久化重试进度并执行退避 sleep。"""
        self.total_retries += 1
        self.last_error_code = error_code
        self.next_retry_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay_seconds
        )
        repository.bump_brief_attempt_retry(
            self.attempt_id,
            provider_retry_count=self.total_retries,
            next_retry_at=self.next_retry_at,
            error_code=error_code,
            error_message=error_message,
        )
        sleeper(delay_seconds)


class BriefWorker:
    """Spec §10 / §11.1 / §10.3 / §11.3 / §11.4：单 Source Brief 生成与校验。

    KI-09 已交付：固定 JSON Schema、单次 generation + 一次 repair、程序校验、
    独立 Validator、单事务提交当前 Brief。

    KI-10 在此之上：
    - Provider 层重试（Spec §11.4）：每个 Provider 最多 3 次，只重试 transient，
      Retry-After 优先，否则 2s/10s 退避；重试计数与 next_retry_at 持久化。
    - fallback（Spec §11.3）：只有 transient 基础设施失败切到已配置 fallback；
      鉴权 / 模型不存在 / 上下文超限 / 非法 JSON / 内容质量失败不切。
    - 重建失败保留旧 Brief（Spec §10.4）。
    - Provider/Prompt/Schema/Snapshot 变化由 service 层标记 outdated，本 worker
      不自动重建。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        config: Config,
        *,
        model_client: Optional[BriefModelClient] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        heartbeat_interval_seconds: float = BRIEF_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._repository = repository
        self._config = config
        self._model_client = model_client or litellm_completion
        # Spec §11.4 退避 sleep；测试注入同步 no-op 以避免真实等待。
        self._sleep = sleeper or time.sleep
        # heartbeat 间隔，测试注入小值避免真实 30s 等待。
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    def update_config(self, config: Config) -> None:
        """同步设置更新后的 Provider 配置，不重建运行时线程。"""

        self._config = config

    # ------------------------------------------------------------------
    # Provider 适配
    # ------------------------------------------------------------------

    def _candidate_provider(
        self, profile: Optional[AIProviderProfile]
    ) -> Optional[AIProviderProfile]:
        """Spec §4.2 / §11.2：校验单个 profile 是否满足 96K context 与启用状态。

        ``context_window == 0`` 视为未知，不得根据模型名称猜测；不满足直接淘汰。
        """
        if profile is None or not profile.enabled or not profile.api_key:
            return None
        if profile.context_window < BRIEF_MIN_CONTEXT_WINDOW:
            return None
        return profile

    def resolve_provider(self) -> Optional[AIProviderProfile]:
        """Spec §4.2 / §11.2：返回满足 96K context 的 active Provider（primary）。

        - ``context_window == 0`` 视为未知，按 Spec §4.2 不得根据模型名称猜测。
        - ``context_window < BRIEF_MIN_CONTEXT_WINDOW`` 视为不足窗口，拒绝发出请求。
        """
        return self._candidate_provider(self._config.active_provider())

    def resolve_fallback_provider(self) -> Optional[AIProviderProfile]:
        """Spec §11.3：返回满足 96K context 的 fallback Provider 候选。

        fallback 必须与 active 不同；否则返回 ``None``，避免 self-failover。
        """
        fallback = self._config.fallback_provider()
        candidate = self._candidate_provider(fallback)
        if candidate is None:
            return None
        active = self._config.active_provider()
        if active is not None and candidate.id == active.id:
            return None
        return candidate

    def provider_block_reason(self) -> str:
        """Spec §11.2：active 与 fallback 都不满足 96K 时返回稳定 block reason。"""
        primary = self.resolve_provider()
        fallback = self.resolve_fallback_provider()
        if primary is not None or fallback is not None:
            return ""
        # 两者均不可用：区分"未配置 api_key"与"上下文窗口不足"。
        active = self._config.active_provider()
        any_api_key = bool(active and active.api_key) or any(
            profile.api_key for profile in self._config.provider_profiles()
        )
        if not any_api_key:
            return "provider_unavailable"
        return "provider_context_too_small"

    def _refresh_outer_lease(self, job: JobRecord) -> bool:
        """在 Brief 长调用前复核并延长外层 queue Job lease。"""

        current = self._repository.get_job(job.id)
        if not _job_record_is_active(
            current,
            attempt_token=job.attempt_token,
            lease_owner=job.lease_owner,
        ):
            return False
        refreshed = self._repository.heartbeat_job(
            job.id,
            attempt_token=job.attempt_token,
            lease_duration_seconds=120,
        )
        return _job_record_is_active(
            refreshed,
            attempt_token=job.attempt_token,
            lease_owner=job.lease_owner,
        )

    def _outer_lease_active(self, job_id: int, attempt_token: str) -> bool:
        return _job_record_is_active(
            self._repository.get_job(job_id),
            attempt_token=attempt_token,
        )

    def _renew_outer_lease(self, job_id: int, attempt_token: str) -> bool:
        if not self._outer_lease_active(job_id, attempt_token):
            return False
        refreshed = self._repository.heartbeat_job(
            job_id,
            attempt_token=attempt_token,
            lease_duration_seconds=120,
        )
        return _job_record_is_active(refreshed, attempt_token=attempt_token)

    @contextmanager
    def _outer_lease_heartbeat(
        self, job_id: int, attempt_token: str
    ) -> Generator[None, None, None]:
        """在 Brief generation/validator 长调用期间周期续约外层 queue lease。

        litellm 同步阻塞调用期间主线程无法到达安全点续约，lease 会在时长到达后被
        并行 recover 回收（标记 failed、attempt 终结）。本守护线程每
        ``BRIEF_HEARTBEAT_INTERVAL_SECONDS`` 续约一次，让 lease 扛住任意长的模型调用。
        主线程在安全点仍会检测 cancel/lease 失效并退出，二者不冲突。
        """

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, attempt_token, stop_event),
            name=f"brief-heartbeat-{job_id}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=5.0)

    def _heartbeat_loop(
        self, job_id: int, attempt_token: str, stop_event: threading.Event
    ) -> None:
        """守护线程主体：周期续约 lease，失效或取消时自行退出。"""

        while not stop_event.wait(self._heartbeat_interval_seconds):
            try:
                refreshed = self._repository.heartbeat_job(
                    job_id,
                    attempt_token=attempt_token,
                    lease_duration_seconds=BRIEF_HEARTBEAT_LEASE_SECONDS,
                )
            except Exception:  # noqa: BLE001 - heartbeat 失败不杀主流程
                _LOGGER.debug(
                    "Brief heartbeat failed for job %s", job_id, exc_info=True
                )
                continue
            if refreshed is None:
                # lease 已失效或 job 被 cancel/抢走，停止续约；主线程安全点会处理退出。
                return

    # ------------------------------------------------------------------
    # 主入口：消费一个 brief Job
    # ------------------------------------------------------------------

    def execute(self, job: JobRecord) -> JobExecutionResult:
        """Spec §10.3 / §10.4：从队列消费一个 brief Job。

        步骤：
        1. 校验 Job 来源与 Source 状态。
        2. 校验 Provider 96K context（不满足直接 failed + block reason）。
        3. 调用 generation；通过 Schema/citation/coverage/support 全部门禁后单事务提交。
        4. 失败一次允许一次受约束修复；第二次失败标记 Attempt failed。
        """
        if job.kind != "brief":
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_kind_mismatch",
                error_code="brief_kind_mismatch",
                error_message=f"Job kind={job.kind} 不是 brief",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="brief_kind_mismatch",
                error_message=f"Job kind={job.kind} 不是 brief",
            )
        if not self._refresh_outer_lease(job):
            canceled = self._repository.is_job_canceled(job.id)
            error_code = "job_canceled" if canceled else "job_lease_mismatch"
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status="canceled" if canceled else "failed",
                error_code=error_code,
                error_message="用户取消" if canceled else "Brief queue lease 已失效",
            )
        if self._repository.is_job_canceled(job.id):
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="canceled",
                stage="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )
        source_id = job.source_id
        if source_id is None:
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="source_missing",
                error_code="source_integrity_mismatch",
                error_message="Brief Job 缺少 source_id",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message="Brief Job 缺少 source_id",
            )
        source = self._repository.get_source(source_id)
        if source is None or source.lifecycle == "deleting":
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="source_missing",
                error_code="source_integrity_mismatch",
                error_message="Source 不存在或处于 deleting",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="source_integrity_mismatch",
                error_message="Source 不存在或处于 deleting",
            )
        if (
            job.snapshot_id is not None
            and source.active_snapshot_id != job.snapshot_id
        ):
            # Snapshot 代际切换后，旧 pending/running Job 不能读取新 Snapshot；
            # Repository 会在 Extraction 提交时优先终结它，但这里仍保留执行前
            # 门禁，覆盖进程间竞态和旧库恢复场景。
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_snapshot_stale",
                error_code="brief_snapshot_stale",
                error_message="Source active Snapshot 已更新",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="brief_snapshot_stale",
                error_message="Source active Snapshot 已更新",
            )
        if source.active_snapshot_id is None or source.extraction_status != "extracted":
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="extraction_required",
                error_code="extraction_required",
                error_message="Source 尚未完成 Extraction",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code="extraction_required",
                error_message="Source 尚未完成 Extraction",
            )

        primary_provider = self.resolve_provider()
        fallback_provider = self.resolve_fallback_provider()
        if primary_provider is None and fallback_provider is None:
            block_reason = self.provider_block_reason() or "provider_unavailable"
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_provider_unavailable",
                error_code=block_reason,
                error_message=(
                    "未配置满足 Brief 96K context 的 Provider，请先在设置中配置"
                ),
            )
            self._repository.update_source_state(
                source_id,
                brief_status="pending",
                brief_block_reason=block_reason,
                brief_error_code=block_reason,
                brief_error_message=(
                    "未配置满足 Brief 96K context 的 Provider，请先在设置中配置"
                ),
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code=block_reason,
                error_message="Brief Provider 不可用",
            )
        # KI-10 / Spec §11.2：active 不满足 96K 但 fallback 满足时，用 fallback 作为
        # primary（无第二个 failover 候选）；两者都满足时 active=primary、fallback=候选。
        if primary_provider is None:
            generation_primary = fallback_provider
            generation_fallback: Optional[AIProviderProfile] = None
        else:
            generation_primary = primary_provider
            generation_fallback = fallback_provider
        assert generation_primary is not None

        snapshot_id = source.active_snapshot_id
        assert snapshot_id is not None
        try:
            attempt_record, brief_job_id, attempt_token = (
                self._repository.create_brief_attempt(
                    BriefAttemptCreateInput(
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        provider_id=generation_primary.id,
                        provider_model=generation_primary.model,
                        provider_base_url=generation_primary.base_url,
                        context_window=generation_primary.context_window,
                        max_output_tokens=generation_primary.max_output_tokens,
                        prompt_version=BRIEF_PROMPT_VERSION,
                        schema_version=BRIEF_SCHEMA_VERSION,
                        language=BRIEF_LANGUAGE,
                        fallback_provider_id=(
                            generation_fallback.id if generation_fallback else ""
                        ),
                        fallback_provider_model=(
                            generation_fallback.model if generation_fallback else ""
                        ),
                    )
                )
            )
        except KnowledgeBriefAttemptError as exc:
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_attempt_conflict",
                error_code=exc.code,
                error_message=exc.message,
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="failed",
                error_code=exc.code,
                error_message=exc.message,
            )

        # 关联：通过 brief queue Job 的 attempt_token 与 Attempt 同时操作的另一个
        # brief Job（``create_brief_attempt`` 内部复用原始 queue Job）。
        # Attempt 与 Brief/Job 终态由 Repository 在同一事务提交，避免先发布 Attempt
        # 失败再用第二个 complete_job 覆盖状态。
        attempt_id = attempt_record.id

        if self._repository.is_job_canceled(job.id):
            self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="job_canceled",
                error_message="用户在 Brief generation 之前取消",
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="canceled",
                stage="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="canceled",
                error_code="job_canceled",
                error_message="用户取消",
            )

        evidence_rows = self._load_evidence(source_id, snapshot_id)
        if not evidence_rows:
            failed, _, _ = self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="brief_support_invalid",
                error_message="Source 缺少可引用的文本 Evidence",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=failed,
                status="failed",
                error_code="brief_support_invalid",
                error_message="Source 缺少可引用的文本 Evidence",
            )

        coverage_plan = build_section_coverage_plan(evidence_rows)
        title_for_prompt = (
            source.display_title or source.title_hint or source.main_filename
        )

        with self._outer_lease_heartbeat(job.id, job.attempt_token):
            generation_result, failure = self._run_generation_with_repair(
                attempt_id=attempt_id,
                brief_job_id=brief_job_id,
                attempt_token=attempt_token,
                primary_provider=generation_primary,
                fallback_provider=generation_fallback,
                source_title=title_for_prompt,
                evidence_rows=evidence_rows,
                coverage_plan=coverage_plan,
                outer_job_id=job.id,
                outer_attempt_token=job.attempt_token,
            )
        if generation_result is None or failure is not None:
            # 已经在 helper 内部 fail_brief_attempt，直接退出。
            error_code = failure[0] if failure else "brief_generation_failed"
            error_message = failure[1] if failure else "Brief generation 未通过门禁"
            if error_code in {"job_canceled", "job_lease_mismatch"}:
                # lease/cancel 安全点可能发生在模型调用返回之后；尽力终结内部
                # Attempt，失败时由启动恢复处理遗留 processing Attempt。
                self._repository.fail_brief_attempt(
                    attempt_id,
                    job_id=brief_job_id,
                    attempt_token=attempt_token,
                    error_code=error_code,
                    error_message=error_message,
                )
            if error_code == "job_canceled":
                status = "canceled"
            else:
                status = "failed"
            completed, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status=status,
                stage=error_code,
                error_code=error_code,
                error_message=error_message,
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=completed,
                status=status,
                error_code=error_code,
                error_message=error_message,
            )

        support_results = generation_result.support_results
        non_supported = [
            item for item in support_results if item["decision"] != "supported"
        ]
        if non_supported:
            failed, _, _ = self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="brief_support_invalid",
                error_message=self._format_support_failure(non_supported),
                validation_report_json=generation_result.validation_report_json,
                candidate_payload_json=generation_result.payload.model_dump_json(),
                token_input_count=generation_result.token_input_count,
                token_output_count=generation_result.token_output_count,
                latency_ms=generation_result.latency_ms,
                repair_count=generation_result.repair_count,
                actual_provider_id=generation_result.actual_provider_id,
                actual_provider_model=generation_result.actual_provider_model,
                provider_retry_count=generation_result.provider_retry_count,
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=failed,
                status="failed",
                error_code="brief_support_invalid",
                error_message=self._format_support_failure(non_supported),
            )

        outer_active = self._refresh_outer_lease(job)
        if not outer_active or self._repository.is_job_canceled(job.id):
            canceled = self._repository.is_job_canceled(job.id)
            cancel_code = "job_canceled" if canceled else "job_lease_mismatch"
            self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code=cancel_code,
                error_message=(
                    "用户在 Brief 校验通过后、提交前取消"
                    if canceled
                    else "Brief 校验通过后外层 queue lease 已失效"
                ),
            )
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="canceled" if canceled else "failed",
                stage="canceled" if canceled else "commit_conflict",
                error_code=cancel_code,
                error_message="用户取消" if canceled else "Brief lease 已失效",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=ok,
                status="canceled" if canceled else "failed",
                error_code=cancel_code,
                error_message="用户取消" if canceled else "Brief lease 已失效",
            )

        if not self._outer_lease_active(job.id, job.attempt_token):
            self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="job_lease_mismatch",
                error_message="Brief 提交前外层 queue lease 已失效",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status="failed",
                error_code="job_lease_mismatch",
                error_message="Brief 提交前外层 queue lease 已失效",
            )

        ok, _, _ = self._repository.commit_brief_attempt_success(
            attempt_id,
            job_id=brief_job_id,
            attempt_token=attempt_token,
            payload_json=generation_result.payload.model_dump_json(
                by_alias=False, exclude_none=False
            ),
            validation_report_json=generation_result.validation_report_json,
            token_input_count=generation_result.token_input_count,
            token_output_count=generation_result.token_output_count,
            latency_ms=generation_result.latency_ms,
            actual_provider_id=generation_result.actual_provider_id,
            actual_provider_model=generation_result.actual_provider_model,
            provider_retry_count=generation_result.provider_retry_count,
        )
        if not ok:
            # lease 失效或 attempt_token 不匹配（迟到结果）；保留 Attempt 状态不变。
            self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_commit_conflict",
                error_code="job_lease_mismatch",
                error_message="Brief 提交时 lease 已失效",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=False,
                status="failed",
                error_code="job_lease_mismatch",
                error_message="Brief 提交时 lease 已失效",
            )
        ok, _ = self._repository.complete_job(
            job.id,
            attempt_token=job.attempt_token,
            status="succeeded",
            stage="brief_ready",
            progress=100,
        )
        return JobExecutionResult(
            job_id=job.id,
            accepted=ok,
            status="succeeded",
            error_code="",
            error_message="",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_evidence(
        self, source_id: int, snapshot_id: int
    ) -> list[EvidenceRecord]:
        """Spec §10.2：generation 单次读取完整 Source 文本 Evidence。"""
        items: list[EvidenceRecord] = []
        cursor: Optional[int] = None
        while True:
            page = self._repository.list_evidence(
                source_id,
                snapshot_id=snapshot_id,
                after_ordinal=cursor,
                limit=200,
            )
            items.extend(page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return items

    def _run_generation_with_repair(
        self,
        *,
        attempt_id: int,
        brief_job_id: int,
        attempt_token: str,
        primary_provider: AIProviderProfile,
        fallback_provider: Optional[AIProviderProfile],
        source_title: str,
        evidence_rows: list[EvidenceRecord],
        coverage_plan: SectionCoveragePlan,
        outer_job_id: Optional[int] = None,
        outer_attempt_token: str = "",
    ) -> tuple[Optional[BriefGenerationResult], Optional[tuple[str, str]]]:
        """Spec §10.3 / §11.3 / §11.4：generation + 程序校验；失败允许一次 repair。

        KI-10：generation 与 repair 均通过 ``_call_model_with_failover`` 调用，
        primary transient 失败可切 fallback；内容质量失败（schema/citation/coverage）
        不切换 Provider。实际成功 Provider 写入 ``actual_provider_*`` 供 validation 与
        Attempt 持久化。

        返回 ``(generation_result, failure)``：
        - 成功：``(BriefGenerationResult, None)``。
        - 失败：``(None, (error_code, error_message))``，已调用 ``fail_brief_attempt``。
        """
        evidence_ids = {row.id for row in evidence_rows}
        repair_count = 0
        candidate_payload_dict: Optional[dict[str, Any]] = None
        last_issues: list[str] = []
        retry_state = _RetryState(attempt_id=attempt_id)
        actual_provider = primary_provider

        while True:
            if (
                outer_job_id is not None
                and not self._renew_outer_lease(outer_job_id, outer_attempt_token)
            ):
                return None, (
                    "job_canceled"
                    if self._repository.is_job_canceled(outer_job_id)
                    else "job_lease_mismatch",
                    "Brief generation 前 queue lease 已失效或已取消",
                )
            if candidate_payload_dict is None:
                messages = build_generation_prompt(
                    source_title=source_title,
                    evidence_rows=evidence_rows,
                    coverage_plan=coverage_plan,
                )
            else:
                messages = build_repair_prompt(
                    source_title=source_title,
                    evidence_rows=evidence_rows,
                    coverage_plan=coverage_plan,
                    candidate_payload=candidate_payload_dict,
                    validation_issues=last_issues,
                )

            try:
                (
                    raw_text,
                    token_in,
                    token_out,
                    latency_ms,
                    actual_provider,
                ) = self._call_model_with_failover(
                    primary_provider,
                    fallback_provider,
                    messages,
                    state=retry_state,
                )
            except BriefModelCallError as exc:
                self._repository.fail_brief_attempt(
                    attempt_id,
                    job_id=brief_job_id,
                    attempt_token=attempt_token,
                    error_code=exc.code,
                    error_message=exc.message,
                    repair_count=repair_count,
                    actual_provider_id=actual_provider.id,
                    actual_provider_model=actual_provider.model,
                    provider_retry_count=retry_state.total_retries,
                )
                return None, (exc.code, exc.message)

            try:
                brief = parse_brief_payload(raw_text)
            except BriefSchemaError as exc:
                if repair_count >= 1:
                    self._repository.fail_brief_attempt(
                        attempt_id,
                        job_id=brief_job_id,
                        attempt_token=attempt_token,
                        error_code=exc.code,
                        error_message=exc.message,
                        candidate_payload_json="",
                        validation_report_json=json.dumps(
                            {
                                "stage": "schema_invalid",
                                "issues": [exc.message],
                                "repair_count": repair_count,
                            },
                            ensure_ascii=False,
                        ),
                        repair_count=repair_count,
                        token_input_count=token_in,
                        token_output_count=token_out,
                        latency_ms=latency_ms,
                        actual_provider_id=actual_provider.id,
                        actual_provider_model=actual_provider.model,
                        provider_retry_count=retry_state.total_retries,
                    )
                    return None, (exc.code, exc.message)
                repair_count += 1
                last_issues = [exc.message]
                candidate_payload_dict = {"_invalid_raw": raw_text[:400]}
                continue

            report = validate_brief_against_evidence(
                brief, evidence_ids=evidence_ids, expected_sections=coverage_plan
            )
            if not (report.citation_ok and report.coverage_ok):
                error_code = (
                    "brief_citation_invalid"
                    if not report.citation_ok
                    else "brief_coverage_invalid"
                )
                if repair_count >= 1:
                    self._repository.fail_brief_attempt(
                        attempt_id,
                        job_id=brief_job_id,
                        attempt_token=attempt_token,
                        error_code=error_code,
                        error_message="; ".join(report.issues)[:500],
                        candidate_payload_json=brief.model_dump_json(),
                        validation_report_json=json.dumps(
                            {
                                "stage": "programmatic_invalid",
                                "issues": report.issues,
                                "repair_count": repair_count,
                            },
                            ensure_ascii=False,
                        ),
                        repair_count=repair_count,
                        token_input_count=token_in,
                        token_output_count=token_out,
                        latency_ms=latency_ms,
                        actual_provider_id=actual_provider.id,
                        actual_provider_model=actual_provider.model,
                        provider_retry_count=retry_state.total_retries,
                    )
                    return None, (error_code, "; ".join(report.issues)[:500])
                repair_count += 1
                candidate_payload_dict = brief.model_dump(mode="json")
                last_issues = list(report.issues)
                continue

            # Spec §10.3：schema/citation/coverage 全通过后做 support validation。
            # support 失败同样属于"首次校验失败允许一次受约束修复"——repair prompt 的
            # "删除/收缩/重新引用"约束正适合 partial/unsupported statement。
            support_results = self._run_support_validation(
                brief=brief,
                evidence_index={row.id: row for row in evidence_rows},
                provider=actual_provider,
                fallback=(
                    fallback_provider
                    if fallback_provider is not None
                    and fallback_provider.id != actual_provider.id
                    else None
                ),
                retry_state=retry_state,
                outer_job_id=outer_job_id,
                outer_attempt_token=outer_attempt_token,
            )
            if (
                outer_job_id is not None
                and not self._renew_outer_lease(outer_job_id, outer_attempt_token)
            ):
                return None, (
                    "job_canceled"
                    if self._repository.is_job_canceled(outer_job_id)
                    else "job_lease_mismatch",
                    "Brief support 校验后 queue lease 已失效或已取消",
                )
            validation_report_payload = {
                "stage": "support_validation",
                "support_results": support_results,
                "repair_count": repair_count,
                "programmatic_issues": last_issues,
            }
            validation_report_json = json.dumps(
                validation_report_payload, ensure_ascii=False
            )
            non_supported = [
                item for item in support_results if item["decision"] != "supported"
            ]
            # 第二次 support 失败与全门禁通过共用同一 generation_result；区别只在
            # non_supported 非空且已用完 repair 时，由外层记录 brief_support_invalid
            # 并保留 Evidence 可搜索（Spec §8）。
            result = BriefGenerationResult(
                payload=brief,
                validation_report_json=validation_report_json,
                support_results=support_results,
                token_input_count=token_in,
                token_output_count=token_out,
                latency_ms=latency_ms,
                actual_provider_id=actual_provider.id,
                actual_provider_model=actual_provider.model,
                provider_retry_count=retry_state.total_retries,
                repair_count=repair_count,
            )
            if non_supported:
                if repair_count >= 1:
                    return result, None
                # 首次 support 失败：受约束 repair。
                repair_count += 1
                candidate_payload_dict = brief.model_dump(mode="json")
                last_issues = [
                    self._format_one_support_issue(item) for item in non_supported
                ]
                continue

            # 全部门禁通过。
            return result, None

    def _run_support_validation(
        self,
        *,
        brief: BriefPayload,
        evidence_index: dict[str, EvidenceRecord],
        provider: AIProviderProfile,
        fallback: Optional[AIProviderProfile],
        retry_state: "_RetryState",
        outer_job_id: Optional[int] = None,
        outer_attempt_token: str = "",
    ) -> list[dict[str, Any]]:
        """Spec §10.3 独立 Validator：逐条 statement 判定 supported/partial/...

        KI-10：Validator 调用也走 Provider 重试（Spec §11.4 仍适用）。网络/超时/限流
        /5xx 等基础设施失败可切换固定 fallback；Validator 的非法 JSON、unsupported
        等内容判定属于质量结论，不切换 Provider。Validator 调用共享同一
        ``retry_state``，保证诊断完整。
        """
        results: list[dict[str, Any]] = []
        current_provider = provider
        current_fallback = fallback
        for block_name, statement, evidence_ids in collect_brief_statement_blocks(
            brief
        ):
            if (
                outer_job_id is not None
                and not self._renew_outer_lease(outer_job_id, outer_attempt_token)
            ):
                # 让调用方在下一安全点将外层 Job 标记 canceled；不再发起新的
                # Validator 请求，也不把迟到模型结果写入当前 Brief。
                return results
            cited = [
                self._evidence_for_prompt(evidence_index.get(eid))
                for eid in evidence_ids
                if eid in evidence_index
            ]
            if not cited:
                results.append(
                    {
                        "block": block_name,
                        "decision": "unsupported",
                        "reason": "citation 不属于当前 Source/Snapshot",
                    }
                )
                continue
            try:
                (
                    raw_text,
                    _,
                    _,
                    _,
                    validator_provider,
                ) = self._call_model_with_failover(
                    current_provider,
                    current_fallback,
                    build_validation_prompt(statement=statement, cited_evidence=cited),
                    state=retry_state,
                )
                current_provider = validator_provider
                if (
                    current_fallback is not None
                    and validator_provider.id == current_fallback.id
                ):
                    # fallback 已成为当前 Validator Provider，后续 statement
                    # 不再把同一 profile 当作自己的 failover 候选。
                    current_fallback = None
                decision = parse_support_decision(raw_text)
            except BriefSchemaError as exc:
                results.append(
                    {
                        "block": block_name,
                        "decision": "unsupported",
                        "reason": f"Validator 输出无法解析：{exc.message}",
                    }
                )
                continue
            except BriefModelCallError as exc:
                results.append(
                    {
                        "block": block_name,
                        "decision": "unsupported",
                        "reason": f"Validator 调用失败：{exc.code}",
                    }
                )
                continue
            results.append(
                {
                    "block": block_name,
                    "decision": decision.decision,
                    "reason": decision.reason,
                }
            )
        return results

    def _evidence_for_prompt(self, evidence: Optional[EvidenceRecord]) -> dict[str, Any]:
        if evidence is None:
            return {"id": "", "section": "", "kind": "text", "excerpt": ""}
        heading = " / ".join(evidence.heading_path) if evidence.heading_path else "(文档顶层)"
        return {
            "id": evidence.id,
            "section": heading,
            "kind": evidence.kind,
            "excerpt": evidence.canonical_excerpt if evidence.kind != "asset" else "",
            "alt_text": evidence.search_text if evidence.kind == "asset" else "",
        }

    def _format_one_support_issue(self, item: dict[str, Any]) -> str:
        """Spec §10.3 单条 support 失败项，repair validation_issues 与聚合 failure 共用。"""
        return f"{item.get('block')}: {item.get('decision')} ({item.get('reason')})"

    def _format_support_failure(self, items: list[dict[str, Any]]) -> str:
        summary = "; ".join(
            self._format_one_support_issue(item) for item in items[:5]
        )
        return f"Brief 存在 {len(items)} 条 statement 未通过 support 校验：{summary}"

    def _call_model_once(
        self, provider: AIProviderProfile, messages: list[dict[str, str]]
    ) -> tuple[str, int, int, int]:
        """Spec §11 / §18：单次调用 litellm.completion，返回 (text, in, out, ms)。

        不持久化原始响应；只保留稳定错误类别与 token/延时元数据。重试与 failover 由
        ``_call_model_with_retry`` / ``_call_model_with_failover`` 包装。

        错误归类（Spec §11.4）：
        - ``provider_auth_invalid``：401/403 鉴权失败（permanent，不重试不切换）。
        - ``provider_model_unavailable``：404 模型不存在 / 上下文超限（permanent）。
        - ``provider_transient_error``：超时 / 连接 / 限流 / 5xx（重试，可切换 fallback）。
        """
        started = time.monotonic()
        payload: dict[str, Any] = {
            "model": _litellm_model_name(provider),
            "messages": messages,
            "api_key": provider.api_key,
            "timeout": BRIEF_MODEL_TIMEOUT_SECONDS,
        }
        api_base = _litellm_api_base(provider)
        if api_base:
            payload["api_base"] = api_base
        try:
            response = self._model_client(**payload)
        except Exception as exc:  # noqa: BLE001 - litellm 错误族未导出统一基类
            code = _classify_model_error(exc)
            raise BriefModelCallError(
                code,
                f"Provider 调用失败：{type(exc).__name__}",
                retry_after=_extract_retry_after_seconds(exc),
            ) from exc
        _dump_raw_response(provider, response)
        latency_ms = int((time.monotonic() - started) * 1000)
        message = _first_choice_message(response)
        content = str(_get(message, "content") or "")
        token_in = int(_get(response, "usage.prompt_tokens") or 0)
        token_out = int(_get(response, "usage.completion_tokens") or 0)
        return content, token_in, token_out, latency_ms

    def _call_model_with_retry(
        self,
        provider: AIProviderProfile,
        messages: list[dict[str, str]],
        *,
        state: "_RetryState",
    ) -> tuple[str, int, int, int]:
        """Spec §11.4：单 Provider 最多 ``BRIEF_PROVIDER_MAX_ATTEMPTS`` 次调用。

        只重试 transient 错误；permanent 错误立即抛出。每次 transient 失败后：
        1. 通过 ``state.bump`` 持久化累计重试计数与 ``next_retry_at``（重启保留）。
        2. 按 Retry-After / 2s/10s 退避 sleep。
        """
        last_error: Optional[BriefModelCallError] = None
        for attempt_index in range(1, BRIEF_PROVIDER_MAX_ATTEMPTS + 1):
            try:
                return self._call_model_once(provider, messages)
            except BriefModelCallError as exc:
                last_error = exc
                if not _is_transient(exc.code):
                    raise  # permanent：不重试
                if attempt_index >= BRIEF_PROVIDER_MAX_ATTEMPTS:
                    raise  # 该 Provider 重试预算耗尽
                delay = _retry_delay_seconds(exc, attempt_index)
                state.bump(
                    self._repository,
                    error_code=exc.code,
                    error_message=(
                        f"Provider {_provider_label(provider)} 第 {attempt_index} 次"
                        f"调用失败（{exc.code}），{delay:.1f}s 后重试"
                    ),
                    delay_seconds=delay,
                    sleeper=self._sleep,
                )
        # 不可达：循环要么 return，要么 raise。
        assert last_error is not None
        raise last_error

    def _call_model_with_failover(
        self,
        primary: AIProviderProfile,
        fallback: Optional[AIProviderProfile],
        messages: list[dict[str, str]],
        *,
        state: "_RetryState",
    ) -> tuple[str, int, int, int, AIProviderProfile]:
        """Spec §11.3 / §11.4：primary 重试耗尽后切 fallback。

        - 只有 transient 错误切换 fallback；permanent（鉴权 / 模型 / 上下文超限）立即抛出。
        - fallback 必须已由 ``resolve_fallback_provider`` 校验 96K；此处不再重复。
        - 返回 ``(text, in, out, ms, actual_provider)``，actual 可能是 fallback。
        """
        try:
            text, tin, tout, ms = self._call_model_with_retry(
                primary, messages, state=state
            )
            return text, tin, tout, ms, primary
        except BriefModelCallError as exc:
            if not _is_transient(exc.code) or fallback is None:
                raise
            text, tin, tout, ms = self._call_model_with_retry(
                fallback, messages, state=state
            )
            return text, tin, tout, ms, fallback


class BriefModelCallError(Exception):
    """Spec §13 Brief Provider 调用失败的稳定错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


def _classify_model_error(exc: BaseException) -> str:
    """Spec §11.4 错误分类：区分永久性 vs 暂时性失败。

    KI-10 会在此函数基础上实现自动重试；KI-09 仅给出稳定 code 便于记录。
    """
    name = type(exc).__name__.lower()
    message = str(exc).lower() if str(exc) else ""
    status_code = _provider_status_code(exc)
    if status_code in {401, 403}:
        return "provider_auth_invalid"
    if status_code == 404:
        return "provider_model_unavailable"
    if status_code in {408, 409, 425, 429} or status_code >= 500:
        return "provider_transient_error"
    if 400 <= status_code < 500:
        return "provider_request_invalid"
    if "authentication" in name or "auth" in name or "401" in message or "403" in message:
        return "provider_auth_invalid"
    context_error_markers = (
        "context window",
        "context length",
        "context_length",
        "maximum context",
        "max context",
        "context limit",
        "context exceeded",
        "token limit",
        "too many tokens",
        "input too long",
        "prompt too long",
        "上下文超限",
        "上下文窗口",
        "上下文长度",
        "token 超限",
        "输入过长",
    )
    if (
        "notfound" in name
        or "not_found" in name
        or "404" in message
        or any(marker in message for marker in context_error_markers)
    ):
        return "provider_model_unavailable"
    if "rate" in name or "rate_limit" in message or "429" in message:
        return "provider_transient_error"
    if "timeout" in name or "timeout" in message:
        return "provider_transient_error"
    return "provider_transient_error"


def _provider_status_code(exc: BaseException) -> int:
    """从常见 Provider 异常结构提取 HTTP 状态码。"""

    candidates: list[Any] = [
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ]
    for candidate in candidates:
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if 100 <= value <= 599:
            return value
    match = re.search(r"\b([45]\d{2})\b", str(exc))
    return int(match.group(1)) if match else 0


def _litellm_model_name(provider: AIProviderProfile) -> str:
    if "/" in provider.model:
        return provider.model
    if provider.provider in {"openai", "openai_compatible", "litellm_proxy"}:
        return f"openai/{provider.model}"
    if provider.provider:
        return f"{provider.provider}/{provider.model}"
    return provider.model


def _litellm_api_base(provider: AIProviderProfile) -> str:
    if provider.provider == "anthropic":
        return ""
    return provider.base_url.rstrip("/")


def _first_choice_message(response: Any) -> Any:
    choices = _get(response, "choices") or []
    if not choices:
        return {}
    return _get(choices[0], "message") or {}


def _get(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dump_raw_response(provider: AIProviderProfile, response: Any) -> None:
    """临时诊断：把 litellm 原始 response 的 message 原样写入日志，排查推理模型
    content 提取问题（``reasoning_content`` 是否被合并进 ``content``、思考草稿是否
    含 JSON 候选）。

    设置环境变量 ``OFFERPILOT_BRIEF_RAW_LOG`` 为日志文件路径即启用；不设置则不写，
    避免影响生产。诊断完成后应移除本函数与调用点。
    """
    log_path = os.environ.get("OFFERPILOT_BRIEF_RAW_LOG")
    if not log_path:
        return
    try:
        message = _first_choice_message(response)
        content = str(_get(message, "content") or "")
        reasoning = _get(message, "reasoning_content")
        reasoning_text = str(reasoning) if reasoning is not None else ""
        choices = _get(response, "choices") or []
        finish_reason = (
            _get(choices[0], "finish_reason") if choices else None
        )
        usage = _get(response, "usage")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": provider.model,
            "finish_reason": finish_reason,
            "content": content,
            "content_len": len(content),
            "content_json_candidates": len(_extract_all_json_objects(content)),
            "has_reasoning_content": reasoning is not None,
            "reasoning_content": reasoning_text,
            "reasoning_len": len(reasoning_text),
            "prompt_tokens": _get(usage, "prompt_tokens"),
            "completion_tokens": _get(usage, "completion_tokens"),
        }
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 诊断日志不得影响主流程
        _LOGGER.debug("dump_raw_response failed", exc_info=True)


class KnowledgeJobRunner:
    """Spec §12 持久队列调度器。

    使用方式：调用方按需驱动 ``tick_*``；不启动后台线程。KI-07 测试通过多次 tick
    验证单并发、FIFO、取消与恢复。KI-09 Brief generation 由 Brief queue 接入。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        worker: ExtractionWorker,
        brief_worker: Optional[BriefWorker] = None,
    ) -> None:
        self._repository = repository
        self._worker = worker
        self._brief_worker = brief_worker

    def tick_extraction(
        self,
        *,
        lease_owner: str = "extraction-runner",
        lease_duration_seconds: int = 30,
    ) -> list[JobExecutionResult]:
        """跑一次 Extraction queue，直到没有 pending Job。

        单并发由 ``claim_next_job`` 的 ``with_for_update(skip_locked=True)`` 与
        ``status='pending'`` 过滤共同保证：同一时刻只有一个 worker 能 claim 成功。
        """

        results: list[JobExecutionResult] = []
        while True:
            job = self._repository.claim_next_job(
                "extraction",
                lease_owner=lease_owner,
                lease_duration_seconds=lease_duration_seconds,
            )
            if job is None:
                return results
            result = self._worker.execute(
                job,
                attempt_token=job.attempt_token,
                lease_owner=lease_owner,
            )
            results.append(result)
            if not result.accepted:
                # lease 被其他 worker 抢走 / token 不匹配 -> 退出本 tick。
                return results

    def tick_brief(
        self,
        *,
        lease_owner: str = "brief-runner",
        lease_duration_seconds: int = 120,
    ) -> list[JobExecutionResult]:
        """Brief queue 调度入口。

        KI-09 实现：
        - 若配置了 ``BriefWorker``，claim 一个 brief Job 后委托给 worker.execute。
        - 否则保持 KI-07 兼容占位行为：claim 后标记 brief_not_implemented。

        Spec §12 单并发：claim_next_job 用乐观 UPDATE 守卫，调用方串行驱动。
        """
        results: list[JobExecutionResult] = []
        job = self._repository.claim_next_job(
            "brief",
            lease_owner=lease_owner,
            lease_duration_seconds=lease_duration_seconds,
        )
        if job is None:
            return results
        if self._brief_worker is None:
            ok, _ = self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_not_implemented",
                error_code="brief_not_implemented",
                error_message="Brief generation 由 KI-09 实现",
            )
            results.append(
                JobExecutionResult(
                    job_id=job.id,
                    accepted=ok,
                    status="failed",
                    error_code="brief_not_implemented",
                    error_message="Brief generation 由 KI-09 实现",
                )
            )
            return results
        result = self._brief_worker.execute(job)
        results.append(result)
        return results

    def retry_extract(
        self,
        source_id: int,
    ) -> Optional[JobRecord]:
        """Spec §12 "手动重试进入队尾"。

        创建新的 ``kind=extract, queue=extraction, status=pending`` Job，排到队尾。
        不影响已有 Job 状态（已 succeeded 的旧 Job 保留为历史）。
        """
        from offerpilot.knowledge.repository import JobCreateInput

        return self._repository.create_job(
            JobCreateInput(
                kind="extract",
                queue="extraction",
                source_id=source_id,
                stage="retry_pending",
            )
        )


class KnowledgeWorkerRuntime:
    """应用生命周期内的双队列 Worker 运行时。

    每个队列固定一个线程：Extraction 与 Brief 可以并行，但同一队列不会在本运行时
    内并发消费。运行时不拥有数据库连接，停止时只设置事件并等待当前安全点返回；模型
    调用无法主动中断时，Worker 的 lease/cancel 门禁会拒绝迟到结果。

    ``start`` / ``stop`` 由应用生命周期调用；测试和 CLI 可使用 ``run_once`` 或
    ``run_forever``，无需依赖 FastAPI。
    """

    def __init__(
        self,
        runner: KnowledgeJobRunner,
        repository: KnowledgeRepository,
        *,
        poll_interval_seconds: float = 0.5,
        extraction_lease_seconds: int = 30,
        brief_lease_seconds: int = 300,
        on_extraction_succeeded: Optional[Callable[[int], Any]] = None,
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._poll_interval_seconds = max(0.05, poll_interval_seconds)
        self._extraction_lease_seconds = max(1, extraction_lease_seconds)
        self._brief_lease_seconds = max(1, brief_lease_seconds)
        self._on_extraction_succeeded = on_extraction_succeeded
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._running = False

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    def start(self) -> None:
        """启动两个固定单并发消费者；重复调用不会创建额外线程。"""

        with self._state_lock:
            if self._running:
                return
            self._recover_stale_jobs()
            self._repair_missing_brief_jobs()
            self._stop_event.clear()
            self._threads = [
                threading.Thread(
                    target=self._queue_loop,
                    args=("extraction",),
                    name="knowledge-extraction-worker",
                    daemon=True,
                ),
                threading.Thread(
                    target=self._queue_loop,
                    args=("brief",),
                    name="knowledge-brief-worker",
                    daemon=True,
                ),
            ]
            self._running = True
            for thread in self._threads:
                thread.start()

    def stop(self, timeout: Optional[float] = 10.0) -> None:
        """请求停止并等待队列线程在安全点退出。"""

        with self._state_lock:
            if not self._running:
                return
            self._stop_event.set()
            threads = list(self._threads)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        for thread in threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        with self._state_lock:
            self._threads = [thread for thread in threads if thread.is_alive()]
            self._running = bool(self._threads)
            if not self._running:
                self._threads = []

    close = stop

    def _recover_stale_jobs(self) -> list[int]:
        """恢复过期 Job 并重新入队；兼容仅用于测试的旧式替身。"""

        recover = self._repository.recover_stale_running_jobs
        try:
            parameters = list(inspect.signature(recover).parameters.values())
        except (TypeError, ValueError):
            parameters = []
        supports_requeue = any(
            parameter.name == "requeue"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if supports_requeue:
            return recover(requeue=True)
        return recover()

    def _repair_missing_brief_jobs(self) -> None:
        """恢复 Extraction 提交后、Brief 回调前崩溃留下的 Source。"""
        if self._on_extraction_succeeded is None:
            return
        for source in self._repository.list_sources(include_archived=True):
            if source.extraction_status != "extracted" or source.brief_status not in (
                "not_started",
                "outdated",
            ):
                continue
            active_brief_job = any(
                job.kind == "brief"
                and job.status in ("pending", "running")
                and not job.canceled
                and job.snapshot_id == source.active_snapshot_id
                for job in self._repository.list_jobs_for_source(source.id)
            )
            if active_brief_job:
                continue
            try:
                self._on_extraction_succeeded(source.id)
            except Exception:
                _LOGGER.exception(
                    "Knowledge Brief recovery callback failed for source %s", source.id
                )

    def run_once(self) -> dict[str, list[JobExecutionResult]]:
        """同步驱动两条队列一次，供 CLI、smoke 和测试使用。"""

        self._recover_stale_jobs()
        self._repair_missing_brief_jobs()
        return {
            "extraction": self._runner.tick_extraction(
                lease_owner="knowledge-extraction-runtime",
                lease_duration_seconds=self._extraction_lease_seconds,
            ),
            "brief": self._runner.tick_brief(
                lease_owner="knowledge-brief-runtime",
                lease_duration_seconds=self._brief_lease_seconds,
            ),
        }

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        """在当前线程同步运行双队列，适合外部进程管理器托管。"""

        event = stop_event or self._stop_event
        self._recover_stale_jobs()
        self._repair_missing_brief_jobs()
        while not event.is_set():
            try:
                self._recover_stale_jobs()
                self._repair_missing_brief_jobs()
                extraction = self._runner.tick_extraction(
                    lease_owner="knowledge-extraction-runtime",
                    lease_duration_seconds=self._extraction_lease_seconds,
                )
                brief = self._runner.tick_brief(
                    lease_owner="knowledge-brief-runtime",
                    lease_duration_seconds=self._brief_lease_seconds,
                )
                if not extraction and not brief:
                    event.wait(self._poll_interval_seconds)
            except Exception:  # noqa: BLE001 - 运行时必须保持队列消费者存活
                _LOGGER.exception("Knowledge worker runtime tick failed")
                event.wait(self._poll_interval_seconds)

    def _queue_loop(self, queue: str) -> None:
        lease_owner = f"knowledge-{queue}-runtime"
        lease_seconds = (
            self._extraction_lease_seconds
            if queue == "extraction"
            else self._brief_lease_seconds
        )
        while not self._stop_event.is_set():
            try:
                self._recover_stale_jobs()
                if queue == "extraction":
                    results = self._runner.tick_extraction(
                        lease_owner=lease_owner,
                        lease_duration_seconds=lease_seconds,
                    )
                else:
                    results = self._runner.tick_brief(
                        lease_owner=lease_owner,
                        lease_duration_seconds=lease_seconds,
                    )
                if not results:
                    self._stop_event.wait(self._poll_interval_seconds)
            except Exception:  # noqa: BLE001 - 单个 Job 失败不能杀死消费者
                _LOGGER.exception("Knowledge %s worker tick failed", queue)
                self._stop_event.wait(self._poll_interval_seconds)
