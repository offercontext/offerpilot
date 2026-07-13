"""Knowledge Job Worker / Runner。

KI-07 范围：
- ``ExtractionWorker.execute`` 从持久队列消费一个 Extract Job，重新构建
  Snapshot/Evidence/FTS，并保留 Spec §6 / §9 的单事务提交语义。
- ``KnowledgeJobRunner`` 提供 ``tick_extraction`` / ``tick_brief`` / ``retry_extract``
  方法，按 Spec §12 单并发 FIFO 调度。不启动后台线程，由测试或未来 CLI 驱动。

Spec §12 关键约束：
- Extraction queue 同时承载 Source 永久删除等本地维护 Job（KI-06 已实现 delete Job
  直接在 purge_source 同步完成，KI-07 不改该路径）。
- Brief queue 框架就绪，但 Brief generation 由 KI-09 实现。
- 迟到的旧 lease 结果因 owner/Attempt 不匹配而拒绝提交（``complete_job`` 验证
  ``attempt_token``）。
- pending Job 立即 cancel；running 本地任务在安全点检查 ``is_job_canceled`` 并停止。
- 已发出的模型调用即使无法中止，其返回也不能在取消后提交（``complete_job`` 在
  ``status != running`` 时返回 ``False``）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from offerpilot.knowledge.encoding import DecodedContent, decode_source_bytes
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    MarkdownExtractor,
)
from offerpilot.knowledge.repository import (
    EvidenceDraftInput,
    JobRecord,
    KnowledgeRepository,
    SnapshotCreateInput,
    SourceRecord,
    commit_extraction,
)
from offerpilot.knowledge.tokenizer import max_token_limit


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


class ExtractionWorker:
    """Spec §6 / §12：从队列消费 Extract Job，重新构建 Snapshot/Evidence/FTS。

    KI-02 主路径在 service 层完成 Extraction，本类用于：
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
    ) -> None:
        self._repository = repository
        self._data_dir = data_dir
        self._session_factory = session_factory
        self._extractor = extractor or MarkdownExtractor()

    def can_decode(self, source: "object") -> bool:
        path = self._data_dir / getattr(source, "main_relative_path", "")
        if not path.is_file():
            return False
        return decode_markdown_bytes(path.read_bytes()) is not None

    def verify_source_integrity(self, source: SourceRecord) -> Optional[str]:
        """Spec §6：Worker 每次读取正式 Source 时核验 manifest/hash。

        返回 ``None`` 表示通过；返回字符串为 ``source_integrity_mismatch`` 错误细节。
        校验项：
        - 主文件存在且大小匹配 ``total_bytes``。
        - manifest 中 ``source_hash`` 与重新计算的 hash 一致。
        """
        main_path = self._data_dir / source.main_relative_path
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
        actual_hash = _hash_main_bytes(raw_bytes)
        if actual_hash != expected_hash:
            return (
                f"source_hash mismatch: expected {expected_hash}, got {actual_hash}"
            )
        return None

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
            main_path = self._data_dir / source.main_relative_path
            raw_bytes = main_path.read_bytes()
            decoded = decode_source_bytes(raw_bytes)
            extraction = self._extractor.extract(
                decoded.text,
                encoding=decoded.encoding,
                detection_method=decoded.detection_method,
            )
        except Exception as exc:
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
        )
        title_for_search = source.display_title or source.title_hint or source.main_filename
        try:
            with self._session_factory() as session:
                with session.begin():
                    commit_extraction(
                        session,
                        snapshot_input=snapshot_input,
                        evidence_drafts=drafts,
                        source_id=source.id,
                        source_title=title_for_search,
                        extractor_version=EXTRACTOR_VERSION,
                        asset_inputs=(),
                    )
        except Exception as exc:
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

        ok, _ = self._repository.complete_job(
            job.id,
            attempt_token=attempt_token,
            status="succeeded",
            stage="extracted",
            progress=100,
        )
        return JobExecutionResult(
            job_id=job.id,
            accepted=ok,
            status="succeeded",
            error_code="",
            error_message="",
        )


def _hash_main_bytes(raw_bytes: bytes) -> str:
    """Spec §5.1：``source_hash`` 由主文件原始字节、附件原始字节及附件逻辑路径的规范清单
    计算。

    与 ``compute_source_hash`` 一致使用 ``sha256:`` 前缀。Bundle 场景的 hash 由
    ``compute_bundle_source_hash`` 生成，本函数仅用于完整性校验时回退到主文件 hash
    （Bundle 重建需要 manifest 中的附件清单，KI-07 不在 worker 重建 Bundle hash——若
    Bundle 内容漂移，service 层 Manifest 验证会先失败）。本函数只用于暴露明显的
    "主文件被替换"场景。
    """
    return f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"


class KnowledgeJobRunner:
    """Spec §12 持久队列调度器。

    使用方式：调用方按需驱动 ``tick_*``；不启动后台线程。KI-07 测试通过多次 tick
    验证单并发、FIFO、取消与恢复。KI-09 Brief generation 由 Brief queue 接入。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        worker: ExtractionWorker,
    ) -> None:
        self._repository = repository
        self._worker = worker

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
        lease_duration_seconds: int = 60,
    ) -> list[JobExecutionResult]:
        """Brief queue 调度框架。

        KI-07 范围：只验证 lease/heartbeat/cancel 框架；不实际调用模型。Brief
        generation 由 KI-09 实现。当前实现：claim 后立即标记 failed，error_code
        为 ``brief_not_implemented``，便于测试与 KI-09 切换。
        """
        results: list[JobExecutionResult] = []
        job = self._repository.claim_next_job(
            "brief",
            lease_owner=lease_owner,
            lease_duration_seconds=lease_duration_seconds,
        )
        if job is None:
            return results
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
