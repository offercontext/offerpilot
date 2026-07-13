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
- Extraction queue 同时承载 Source 永久删除等本地维护 Job（KI-06 已实现 delete Job
  直接在 purge_source 同步完成，KI-07 不改该路径）。
- Brief queue 并发固定为 1；与 Extraction queue 可以并行。
- 迟到的旧 lease 结果因 owner/Attempt 不匹配而拒绝提交（``complete_job`` 验证
  ``attempt_token``）。
- pending Job 立即 cancel；running 本地任务在安全点检查 ``is_job_canceled`` 并停止。
- 已发出的模型调用即使无法中止，其返回也不能在取消后提交（``complete_job`` 在
  ``status != running`` 时返回 ``False``）。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

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
)
from offerpilot.knowledge.encoding import DecodedContent, decode_source_bytes
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    NORMALIZATION_VERSION,
    PARSER_VERSION,
    MarkdownExtractor,
)
from offerpilot.knowledge.repository import (
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


# ---------------------------------------------------------------------------
# KI-09 Brief generation / validation
# ---------------------------------------------------------------------------


BriefModelClient = Callable[..., Any]


@dataclass(frozen=True)
class BriefGenerationResult:
    """``BriefWorker.execute`` 单次 generation 返回。"""

    payload: BriefPayload
    validation_report_json: str
    support_results: list[dict[str, Any]]
    token_input_count: int
    token_output_count: int
    latency_ms: int


class BriefWorker:
    """Spec §10 / §11.1 / §10.3：单 Source Brief 生成与校验。

    KI-09 范围（不含 KI-10 fallback / 网络重试）：
    - 启动时校验 Provider ``context_window >= 96_000``；不满足拒绝创建 Attempt。
    - generation 单次完整 Evidence 输入；repair 单次重写。
    - 程序校验 Schema、citation、coverage；独立 Validator 逐条返回 supported/partial/
      unsupported/contradicted；只有全部 supported 才发布。
    - 成功 Brief + winning Attempt + Source ``brief_status=ready`` 单事务提交。
    - 第二次仍失败标记 Attempt failed，Source ``brief_status=failed``，旧 Brief 保留。
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        config: Config,
        *,
        model_client: Optional[BriefModelClient] = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._model_client = model_client or litellm_completion

    # ------------------------------------------------------------------
    # Provider 适配
    # ------------------------------------------------------------------

    def resolve_provider(self) -> Optional[AIProviderProfile]:
        """Spec §4.2 / §11.2：返回满足 96K context 的 active Provider。

        - ``context_window == 0`` 视为未知，按 Spec §4.2 不得根据模型名称猜测。
        - ``context_window < BRIEF_MIN_CONTEXT_WINDOW`` 视为不足窗口，拒绝发出请求。
        """
        provider = self._config.active_provider()
        if not provider.enabled or not provider.api_key:
            return None
        if provider.context_window < BRIEF_MIN_CONTEXT_WINDOW:
            return None
        return provider

    def provider_block_reason(self) -> str:
        """Spec §11.2：返回稳定 block reason 文案，用于 Source.brief_block_reason。"""
        provider = self._config.active_provider()
        if not provider.api_key:
            return "provider_unavailable"
        if provider.context_window < BRIEF_MIN_CONTEXT_WINDOW:
            return "provider_context_too_small"
        return ""

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

        provider = self.resolve_provider()
        if provider is None:
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

        snapshot_id = source.active_snapshot_id
        assert snapshot_id is not None
        try:
            attempt_record, brief_job_id, attempt_token = (
                self._repository.create_brief_attempt(
                    BriefAttemptCreateInput(
                        source_id=source_id,
                        snapshot_id=snapshot_id,
                        provider_id=provider.id,
                        provider_model=provider.model,
                        provider_base_url=provider.base_url,
                        context_window=provider.context_window,
                        max_output_tokens=provider.max_output_tokens,
                        prompt_version=BRIEF_PROMPT_VERSION,
                        schema_version=BRIEF_SCHEMA_VERSION,
                        language=BRIEF_LANGUAGE,
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
        # brief Job（``create_brief_attempt`` 内部创建）。
        # 为了让 lease / complete_job 集中在原始 queue Job 上，本 worker 直接使用
        # ``brief_job_id`` 完成任务，原 queue Job 由 ``complete_job`` 在子事务外标记
        # succeeded/failed。
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
            self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="brief_support_invalid",
                error_message="Source 缺少可引用的文本 Evidence",
            )
            self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_no_evidence",
                error_code="brief_support_invalid",
                error_message="Source 缺少可引用的文本 Evidence",
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="failed",
                error_code="brief_support_invalid",
                error_message="Source 缺少可引用的文本 Evidence",
            )

        coverage_plan = build_section_coverage_plan(evidence_rows)
        title_for_prompt = (
            source.display_title or source.title_hint or source.main_filename
        )

        generation_result, failure = self._run_generation_with_repair(
            attempt_id=attempt_id,
            brief_job_id=brief_job_id,
            attempt_token=attempt_token,
            provider=provider,
            source_title=title_for_prompt,
            evidence_rows=evidence_rows,
            coverage_plan=coverage_plan,
        )
        if generation_result is None or failure is not None:
            # 已经在 helper 内部 fail_brief_attempt，直接退出。
            error_code = failure[0] if failure else "brief_generation_failed"
            error_message = failure[1] if failure else "Brief generation 未通过门禁"
            self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage=error_code,
                error_code=error_code,
                error_message=error_message,
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="failed",
                error_code=error_code,
                error_message=error_message,
            )

        support_results = generation_result.support_results
        non_supported = [
            item for item in support_results if item["decision"] != "supported"
        ]
        if non_supported:
            self._repository.fail_brief_attempt(
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
            )
            self._repository.complete_job(
                job.id,
                attempt_token=job.attempt_token,
                status="failed",
                stage="brief_support_invalid",
                error_code="brief_support_invalid",
                error_message=self._format_support_failure(non_supported),
            )
            return JobExecutionResult(
                job_id=job.id,
                accepted=True,
                status="failed",
                error_code="brief_support_invalid",
                error_message=self._format_support_failure(non_supported),
            )

        if self._repository.is_job_canceled(job.id):
            self._repository.fail_brief_attempt(
                attempt_id,
                job_id=brief_job_id,
                attempt_token=attempt_token,
                error_code="job_canceled",
                error_message="用户在 Brief 校验通过后、提交前取消",
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
        provider: AIProviderProfile,
        source_title: str,
        evidence_rows: list[EvidenceRecord],
        coverage_plan: SectionCoveragePlan,
    ) -> tuple[Optional[BriefGenerationResult], Optional[tuple[str, str]]]:
        """Spec §10.3：generation + 程序校验；失败允许一次 repair。

        返回 ``(generation_result, failure)``：
        - 成功：``(BriefGenerationResult, None)``。
        - 失败：``(None, (error_code, error_message))``，已调用 ``fail_brief_attempt``。
        """
        evidence_ids = {row.id for row in evidence_rows}
        repair_count = 0
        candidate_payload_dict: Optional[dict[str, Any]] = None
        last_issues: list[str] = []
        last_brief: Optional[BriefPayload] = None
        last_token_in = 0
        last_token_out = 0
        last_latency_ms = 0

        while True:
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
                raw_text, token_in, token_out, latency_ms = self._call_model(
                    provider, messages
                )
            except BriefModelCallError as exc:
                self._repository.fail_brief_attempt(
                    attempt_id,
                    job_id=brief_job_id,
                    attempt_token=attempt_token,
                    error_code=exc.code,
                    error_message=exc.message,
                    repair_count=repair_count,
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
                    )
                    return None, (error_code, "; ".join(report.issues)[:500])
                repair_count += 1
                candidate_payload_dict = brief.model_dump(mode="json")
                last_issues = list(report.issues)
                last_brief = brief
                last_token_in = token_in
                last_token_out = token_out
                last_latency_ms = latency_ms
                continue

            last_brief = brief
            last_token_in = token_in
            last_token_out = token_out
            last_latency_ms = latency_ms
            break

        assert last_brief is not None
        support_results = self._run_support_validation(
            brief=last_brief,
            evidence_index={row.id: row for row in evidence_rows},
            provider=provider,
        )
        validation_report_payload = {
            "stage": "support_validation",
            "support_results": support_results,
            "repair_count": repair_count,
            "programmatic_issues": last_issues,
        }
        return (
            BriefGenerationResult(
                payload=last_brief,
                validation_report_json=json.dumps(
                    validation_report_payload, ensure_ascii=False
                ),
                support_results=support_results,
                token_input_count=last_token_in,
                token_output_count=last_token_out,
                latency_ms=last_latency_ms,
            ),
            None,
        )

    def _run_support_validation(
        self,
        *,
        brief: BriefPayload,
        evidence_index: dict[str, EvidenceRecord],
        provider: AIProviderProfile,
    ) -> list[dict[str, Any]]:
        """Spec §10.3 独立 Validator：逐条 statement 判定 supported/partial/..."""
        results: list[dict[str, Any]] = []
        for block_name, statement, evidence_ids in collect_brief_statement_blocks(
            brief
        ):
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
                raw_text, _, _, _ = self._call_model(
                    provider,
                    build_validation_prompt(
                        statement=statement, cited_evidence=cited
                    ),
                )
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

    def _format_support_failure(self, items: list[dict[str, Any]]) -> str:
        summary = "; ".join(
            f"{item.get('block')}: {item.get('decision')} ({item.get('reason')})"
            for item in items[:5]
        )
        return f"Brief 存在 {len(items)} 条 statement 未通过 support 校验：{summary}"

    def _call_model(
        self, provider: AIProviderProfile, messages: list[dict[str, str]]
    ) -> tuple[str, int, int, int]:
        """Spec §11 / §18：调用 litellm.completion，返回 (text, in_tokens, out_tokens, ms)。

        不持久化原始响应；只保留稳定错误类别与 token/延时元数据。KI-09 不实现重试，
        KI-10 在此入口加包装。

        错误归类（KI-09 基线，KI-10 进一步细化）：
        - ``provider_auth_invalid``：401/403 鉴权失败（不重试）。
        - ``provider_model_unavailable``：404 模型不存在 / 上下文超限（不重试）。
        - ``provider_transient_error``：超时 / 连接 / 限流 / 5xx（KI-10 重试）。
        """
        started = time.monotonic()
        payload: dict[str, Any] = {
            "model": _litellm_model_name(provider),
            "messages": messages,
            "api_key": provider.api_key,
        }
        api_base = _litellm_api_base(provider)
        if api_base:
            payload["api_base"] = api_base
        try:
            response = self._model_client(**payload)
        except Exception as exc:  # noqa: BLE001 - litellm 错误族未导出统一基类
            latency_ms = int((time.monotonic() - started) * 1000)
            code = _classify_model_error(exc)
            raise BriefModelCallError(
                code,
                f"Provider 调用失败：{type(exc).__name__}",
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        message = _first_choice_message(response)
        content = str(_get(message, "content") or "")
        token_in = int(_get(response, "usage.prompt_tokens") or 0)
        token_out = int(_get(response, "usage.completion_tokens") or 0)
        return content, token_in, token_out, latency_ms


class BriefModelCallError(Exception):
    """Spec §13 Brief Provider 调用失败的稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _classify_model_error(exc: BaseException) -> str:
    """Spec §11.4 错误分类：区分永久性 vs 暂时性失败。

    KI-10 会在此函数基础上实现自动重试；KI-09 仅给出稳定 code 便于记录。
    """
    name = type(exc).__name__.lower()
    message = str(exc).lower() if str(exc) else ""
    if "authentication" in name or "auth" in name or "401" in message or "403" in message:
        return "provider_auth_invalid"
    if (
        "notfound" in name
        or "not_found" in name
        or "404" in message
        or "context" in message
        and "length" in message
    ):
        return "provider_model_unavailable"
    if "rate" in name or "rate_limit" in message or "429" in message:
        return "provider_transient_error"
    if "timeout" in name or "timeout" in message or "5" in message[:1]:
        return "provider_transient_error"
    return "provider_transient_error"


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
