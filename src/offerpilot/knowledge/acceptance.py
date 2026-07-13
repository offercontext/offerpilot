"""KI-11：真实 Source 与检索质量门禁。

本模块是维护者验收工具，一次性对 5 份真实 Source、≥20 条人工确认查询、7 类 Brief
故障场景与编码/空/超限/Markdown 结构/Bundle 边界 fixtures 做端到端评估，产出不含
原文/API Key/Prompt/Provider 响应的安全报告；任一硬门禁失败 → ``AcceptanceReport.passed``
为 ``False`` 并输出可定位 bad case 的 Evidence ID。

设计约束（tickets.md KI-11 Scope boundaries）：
- 私有/受版权原文不提交仓库；仓库只保存安全 fixtures、fixture hash、查询与预期规则。
- 检索只走 SQLite FTS5，不引入 embedding / rerank / LLM query rewrite。
- Brief 默认用 stub ``model_client`` 覆盖全部门禁逻辑；``--real-ai`` 由 CLI 注入 litellm。
- 报告数据最小化：只暴露 source_key、hash 前缀、Snapshot digest、Evidence 计数、指标与 bad case。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, cast

from offerpilot.config import AIProviderProfile, Config
from offerpilot.db import init_database, session_factory_for_data_dir
from offerpilot.knowledge.assets import AssetInput
from offerpilot.knowledge.brief import (
    BRIEF_MIN_CONTEXT_WINDOW,
    build_section_coverage_plan,
)
from offerpilot.knowledge.encoding import decode_source_bytes
from offerpilot.knowledge.extractor import (
    EXTRACTOR_VERSION,
    MarkdownExtractor,
    compute_source_hash,
)
from offerpilot.knowledge.repository import (
    EvidenceRecord,
    JobCreateInput,
    KnowledgeRepository,
)
from offerpilot.knowledge.service import IngestError, IngestRequest, KnowledgeIngestService
from offerpilot.knowledge.worker import (
    BriefWorker,
    ExtractionWorker,
    KnowledgeJobRunner,
)


# ---------------------------------------------------------------------------
# 配置数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceFixtureSpec:
    """manifest.json 中一份真实 Source 的标识规则。"""

    source_key: str
    display_name: str
    kind: str  # markdown | text | bundle
    fixture_path: str  # 相对 fixtures_dir
    expected_source_hash: str  # "sha256:" + 64hex
    bundle_assets: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuerySpec:
    """queries.json 中一条人工确认查询。"""

    query: str
    query_type: str  # lexical_chinese | lexical_english | lexical_code | natural_language
    source_key: str
    expect_hit: bool
    content_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptanceGateConfig:
    """硬门禁阈值。默认对齐 tickets.md KI-11 要求。"""

    lexical_recall_at_5: float = 1.0
    lexical_mrr_min: float = 0.9
    natural_language_recall_at_5: float = 0.8
    evidence_readback_rate: float = 1.0
    brief_pass_rate: float = 1.0


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryResult:
    query: str
    query_type: str
    expected_source_key: str
    expect_hit: bool
    hit_source_keys: tuple[str, ...]  # 前 5 命中的 source_key
    first_rank: Optional[int]  # expected source 在前 5 的排名（1-based），None=未进前 5
    recall_hit: bool
    mrr_score: float
    content_keyword_hit: bool
    retrieval_method: str = "fts"


@dataclass(frozen=True)
class SourceResult:
    source_key: str
    source_hash_prefix: str  # "sha256:" + 前 16 hex，不暴露完整路径
    snapshot_digest: str
    evidence_count: int
    readback_pass: int
    readback_fail: int
    readback_failed_evidence_ids: tuple[str, ...]
    brief_status: str
    brief_error_code: str
    rerun_snapshot_digest: str
    rerun_consistent: bool


@dataclass(frozen=True)
class BriefFailureResult:
    scenario: str
    brief_status: str  # ready | failed
    brief_error_code: str
    evidence_searchable: bool


@dataclass(frozen=True)
class EdgeFixtureResult:
    name: str
    accepted: bool
    rejected: bool
    error_code: str
    evidence_kind_count: int


@dataclass(frozen=True)
class BundleFixtureResult:
    name: str
    accepted: bool
    rejected: bool
    error_code: str


@dataclass(frozen=True)
class FailureCase:
    """门禁失败时的可定位 bad case。"""

    gate: str
    source_key: str
    query: str
    evidence_id: str
    reason: str


class AcceptanceReport:
    """KI-11 验收报告。``to_safe_json`` 保证不含原文/Key/Prompt/响应。"""

    def __init__(
        self,
        *,
        gate_config: AcceptanceGateConfig,
        metrics: dict[str, float],
        source_results: list[SourceResult],
        query_results: list[QueryResult],
        brief_failure_results: list[BriefFailureResult],
        edge_fixture_results: list[EdgeFixtureResult],
        bundle_fixture_results: list[BundleFixtureResult],
        failures: list[FailureCase],
        fixture_errors: list[str],
        provider_summary: dict[str, Any],
    ) -> None:
        self.gate_config = gate_config
        self.metrics = metrics
        self.source_results = source_results
        self.query_results = query_results
        self.brief_failure_results = brief_failure_results
        self.edge_fixture_results = edge_fixture_results
        self.bundle_fixture_results = bundle_fixture_results
        self.failures = failures
        self.fixture_errors = fixture_errors
        self.provider_summary = provider_summary
        self.passed = not failures and not fixture_errors

    def to_safe_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "gates": {
                "lexical_recall_at_5": self.gate_config.lexical_recall_at_5,
                "lexical_mrr_min": self.gate_config.lexical_mrr_min,
                "natural_language_recall_at_5": self.gate_config.natural_language_recall_at_5,
                "evidence_readback_rate": self.gate_config.evidence_readback_rate,
                "brief_pass_rate": self.gate_config.brief_pass_rate,
            },
            "metrics": dict(self.metrics),
            "sources": [
                {
                    "source_key": s.source_key,
                    "source_hash_prefix": s.source_hash_prefix,
                    "snapshot_digest": s.snapshot_digest,
                    "evidence_count": s.evidence_count,
                    "readback_pass": s.readback_pass,
                    "readback_fail": s.readback_fail,
                    "brief_status": s.brief_status,
                    "brief_error_code": s.brief_error_code,
                    "rerun_consistent": s.rerun_consistent,
                }
                for s in self.source_results
            ],
            "queries": [
                {
                    "query": q.query,
                    "query_type": q.query_type,
                    "expected_source_key": q.expected_source_key,
                    "expect_hit": q.expect_hit,
                    "recall_hit": q.recall_hit,
                    "mrr_score": q.mrr_score,
                    "content_keyword_hit": q.content_keyword_hit,
                    "retrieval_method": q.retrieval_method,
                }
                for q in self.query_results
            ],
            "brief_failures": [
                {
                    "scenario": b.scenario,
                    "brief_status": b.brief_status,
                    "brief_error_code": b.brief_error_code,
                    "evidence_searchable": b.evidence_searchable,
                }
                for b in self.brief_failure_results
            ],
            "edge_fixtures": [
                {
                    "name": e.name,
                    "accepted": e.accepted,
                    "rejected": e.rejected,
                    "error_code": e.error_code,
                    "evidence_kind_count": e.evidence_kind_count,
                }
                for e in self.edge_fixture_results
            ],
            "bundle_fixtures": [
                {
                    "name": b.name,
                    "accepted": b.accepted,
                    "rejected": b.rejected,
                    "error_code": b.error_code,
                }
                for b in self.bundle_fixture_results
            ],
            "failures": [
                {
                    "gate": f.gate,
                    "source_key": f.source_key,
                    "query": f.query,
                    "evidence_id": f.evidence_id,
                    "reason": f.reason,
                }
                for f in self.failures
            ],
            "fixture_errors": list(self.fixture_errors),
            "provider_summary": dict(self.provider_summary),
        }


# ---------------------------------------------------------------------------
# manifest / queries 加载
# ---------------------------------------------------------------------------


def load_manifest(fixtures_dir: Path) -> list[SourceFixtureSpec]:
    data = json.loads((fixtures_dir / "manifest.json").read_text("utf-8"))
    specs: list[SourceFixtureSpec] = []
    for row in data.get("sources", []):
        specs.append(
            SourceFixtureSpec(
                source_key=str(row["source_key"]),
                display_name=str(row.get("display_name", "")),
                kind=str(row.get("kind", "markdown")),
                fixture_path=str(row["fixture_path"]),
                expected_source_hash=str(row["expected_source_hash"]),
                bundle_assets=tuple(row.get("bundle_assets", ())),
            )
        )
    return specs


def load_queries(fixtures_dir: Path) -> list[QuerySpec]:
    data = json.loads((fixtures_dir / "queries.json").read_text("utf-8"))
    queries: list[QuerySpec] = []
    for row in data.get("queries", []):
        queries.append(
            QuerySpec(
                query=str(row["query"]),
                query_type=str(row["query_type"]),
                source_key=str(row.get("source_key", "")),
                expect_hit=bool(row["expect_hit"]),
                content_keywords=tuple(row.get("content_keywords", ())),
            )
        )
    return queries


# ---------------------------------------------------------------------------
# fixture hash 校验
# ---------------------------------------------------------------------------


def verify_fixture_hashes(fixtures_dir: Path, specs: list[SourceFixtureSpec]) -> list[str]:
    """Spec §20.5：真实 Source 以内容 hash 标识；缺失或被修改时明确失败。"""

    errors: list[str] = []
    for spec in specs:
        path = fixtures_dir / spec.fixture_path
        if not path.exists():
            errors.append(f"{spec.source_key}: fixture 缺失 ({spec.fixture_path})")
            continue
        actual = compute_source_hash(path.read_bytes())
        if actual != spec.expected_source_hash:
            errors.append(
                f"{spec.source_key}: source_hash 不匹配，期望 "
                f"{spec.expected_source_hash[:20]}…，实际 {actual[:20]}…"
            )
    return errors


# ---------------------------------------------------------------------------
# Brief stub：从 prompt 提取 Evidence 构造合法 payload
# ---------------------------------------------------------------------------


_EVIDENCE_ID_PATTERN = re.compile(r'"id":\s*"(ev_[A-Za-z0-9_]+)"')


def _extract_evidence_ids_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    # 直接从 user message content 字符串提取；不能用 json.dumps(messages)，否则内部
    # 引号被转义成 \"id\" 导致正则失配。
    text = ""
    for message in messages:
        if message.get("role") == "user":
            text += str(message.get("content", ""))
    found = _EVIDENCE_ID_PATTERN.findall(text)
    return list(dict.fromkeys(found))


def _resolve_evidences(
    repository: KnowledgeRepository, ev_ids: list[str]
) -> list[EvidenceRecord]:
    resolved = [repository.get_evidence(eid) for eid in ev_ids]
    return [row for row in resolved if row is not None]


def _is_validation_call(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") == "system":
            content = str(message.get("content", ""))
            if "Validator" in content or "validation" in content.lower():
                return True
    return False


def _is_fallback_model(model_name: str) -> bool:
    return "fallback" in (model_name or "").lower()


def _generation_response(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200},
    }


def _validation_response(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"content": json.dumps(decision, ensure_ascii=False)}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def _heading_path_for_guide(entry: Any) -> list[str]:
    raw = getattr(entry, "heading_path", ()) or ()
    path: list[str] = [str(item) for item in raw]
    if path:
        return path
    return [str(getattr(entry, "section_key", "__document__"))]


def _build_valid_payload(
    evidences: list[EvidenceRecord], plan: Any
) -> dict[str, Any]:
    """从真实 Evidence 与 coverage plan 构造合法 Brief payload。"""

    text_evidences = [e for e in evidences if e.kind != "asset"]
    pool = text_evidences if len(text_evidences) >= 2 else evidences
    if len(pool) < 2:
        # 证据不足时允许重复引用同一 Evidence 以满足 overview ≥ 2 条
        first = pool[0].id
        second = pool[0].id
    else:
        first = pool[0].id
        second = pool[1].id

    section_guides: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for entry in plan.sections.values():
        if getattr(entry, "must_skip", False):
            coverage.append(
                {
                    "section_key": entry.section_key,
                    "status": "skipped",
                    "skipped_reason": getattr(entry, "skipped_reason", "") or "assets_only",
                }
            )
        else:
            coverage.append(
                {"section_key": entry.section_key, "status": "covered", "skipped_reason": ""}
            )
    # 为第一个非 skip section 生成 guide（满足 Schema 至少有 section_guides 条目）
    non_skip = [e for e in plan.sections.values() if not getattr(e, "must_skip", False)]
    guide_target = non_skip[0] if non_skip else next(iter(plan.sections.values()))
    section_guides.append(
        {
            "section_key": guide_target.section_key,
            "heading_path": _heading_path_for_guide(guide_target),
            "summary": f"{guide_target.section_key} 章节导读。",
            "evidence_ids": [first],
        }
    )
    return {
        "schema_version": 1,
        "language": "zh-CN",
        "overview": [
            {"statement": "概述基于 Evidence。", "evidence_ids": [first]},
            {"statement": "第二条概述引用。", "evidence_ids": [second]},
        ],
        "key_points": [{"statement": "要点引用 Evidence。", "evidence_ids": [first]}],
        "section_guides": section_guides,
        "limitations": [{"statement": "限制条目。", "evidence_ids": [second]}],
        "coverage": coverage,
    }


def _render_payload_template(
    template: dict[str, Any], evidences: list[EvidenceRecord], plan: Any
) -> dict[str, Any]:
    """将 failure/ 静态 payload 模板的占位替换为运行时值。

    覆盖需要真实 Evidence ID / section_key 的样本（如 coverage-missing.json）：
    - ``ev_:real:N`` → 第 N 条文本 Evidence 的 ID；
    - ``__SECTION_KEY_0__`` → plan 第一个 section_key；
    - ``__HEADING_PATH_0__`` → plan 第一个 section 的首段 heading。

    伪造 ID（``ev_:forged:N``）不替换，保留以触发 citation 存在性门禁。
    """
    text_evs = [e for e in evidences if e.kind != "asset"]
    pool = text_evs if text_evs else evidences
    sections = list(plan.sections.values())
    first = sections[0] if sections else None
    sec_key = first.section_key if first else "__document__"
    sec_heading = _heading_path_for_guide(first)[0] if first else sec_key

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {key: _walk(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [_walk(item) for item in obj]
        if isinstance(obj, str):
            if obj.startswith("ev_:real:"):
                suffix = obj.rsplit(":", 1)[-1]
                idx = int(suffix) if suffix.isdigit() else 0
                return pool[idx % len(pool)].id if pool else obj
            if obj == "__SECTION_KEY_0__":
                return sec_key
            if obj == "__HEADING_PATH_0__":
                return sec_heading
            return obj
        return obj

    return cast(dict[str, Any], _walk(template))


def make_perfect_brief_stub(
    repository: KnowledgeRepository,
) -> Callable[..., dict[str, Any]]:
    """构造"完美模型"stub：generation 返回合法 payload，validation 返回 supported。

    stub 从 generation prompt 的 Evidence 列表提取真实 ev_ ID，用 repository 反查
    Evidence heading_path 重建 coverage plan，确保产出的 payload 能通过 BriefWorker
    全部门禁（Schema / citation / support / coverage）。
    """

    def _stub(**payload: Any) -> dict[str, Any]:
        messages = list(payload.get("messages") or [])
        if _is_validation_call(messages):
            return _validation_response({"decision": "supported", "reason": "stub supported"})
        ev_ids = _extract_evidence_ids_from_messages(messages)
        evidences = _resolve_evidences(repository, ev_ids)
        if not evidences:
            return _generation_response("{}")
        plan = build_section_coverage_plan(evidences)
        return _generation_response(
            json.dumps(_build_valid_payload(evidences, plan), ensure_ascii=False)
        )

    return _stub


def _make_failure_stub(
    scenario: str,
    repository: KnowledgeRepository,
    fixtures_dir: Path,
) -> Callable[..., dict[str, Any]]:
    """7 类 Brief 故障场景的 stub。

    invalid_json / forged_citation / coverage_missing / unsupported_support 从
    failure/ 静态 fixture 读取样本：invalid_json 与 forged_citation 直接使用静态内容
    （伪造 citation 先于 coverage 被拒）；coverage_missing 用 _render_payload_template
    注入运行时 Evidence ID 与 section_key，保留"只覆盖一个章节"的故障特征；
    unsupported_support 的 validator decision 直接取自静态文件。timeout / rate_limit /
    fallback_success 由 stub 代码模拟异常或 Provider 切换行为。
    """
    failure_dir = fixtures_dir / "failure"
    invalid_json_text = (failure_dir / "invalid-json.txt").read_text("utf-8")
    forged_payload = json.loads(
        (failure_dir / "forged-citation.json").read_text("utf-8")
    )["payload"]
    coverage_missing_template = json.loads(
        (failure_dir / "coverage-missing.json").read_text("utf-8")
    )["payload"]
    unsupported_decision = json.loads(
        (failure_dir / "unsupported-validation.json").read_text("utf-8")
    )

    def _stub(**payload: Any) -> dict[str, Any]:
        messages = list(payload.get("messages") or [])
        model_name = str(payload.get("model", ""))
        if scenario == "invalid_json":
            return _generation_response(invalid_json_text)
        if scenario == "timeout":
            raise RuntimeError("connection timeout")
        if scenario == "rate_limit":
            raise RuntimeError("429 Rate Limit Exceeded")
        is_validation = _is_validation_call(messages)
        ev_ids = _extract_evidence_ids_from_messages(messages)
        evidences = _resolve_evidences(repository, ev_ids)
        plan = build_section_coverage_plan(evidences) if evidences else None
        if scenario == "forged_citation":
            if is_validation:
                return _validation_response({"decision": "supported", "reason": "stub"})
            return _generation_response(json.dumps(forged_payload, ensure_ascii=False))
        if scenario == "unsupported_support":
            if is_validation:
                return _validation_response(unsupported_decision)
            assert plan is not None and evidences
            return _generation_response(
                json.dumps(_build_valid_payload(evidences, plan), ensure_ascii=False)
            )
        if scenario == "coverage_missing":
            if is_validation:
                return _validation_response({"decision": "supported", "reason": "stub"})
            assert plan is not None and evidences
            rendered = _render_payload_template(
                coverage_missing_template, evidences, plan
            )
            return _generation_response(json.dumps(rendered, ensure_ascii=False))
        if scenario == "fallback_success":
            if _is_fallback_model(model_name):
                if is_validation:
                    return _validation_response({"decision": "supported", "reason": "stub"})
                assert plan is not None and evidences
                return _generation_response(
                    json.dumps(_build_valid_payload(evidences, plan), ensure_ascii=False)
                )
            raise RuntimeError("503 Service Unavailable")
        return _generation_response("{}")

    return _stub


# ---------------------------------------------------------------------------
# 验收主流程
# ---------------------------------------------------------------------------


def _import_fixture(
    service: KnowledgeIngestService, fixtures_dir: Path, spec: SourceFixtureSpec
) -> int:
    path = fixtures_dir / spec.fixture_path
    request = IngestRequest(
        filename=path.name,
        content_bytes=path.read_bytes(),
        title_hint=spec.display_name,
    )
    result = service.ingest(request)
    return result.source.id


def _drafts_signature(extraction: Any) -> tuple[Any, ...]:
    return tuple(
        (
            getattr(d, "locator", ""),
            getattr(d, "char_start", 0),
            getattr(d, "char_end", 0),
            getattr(d, "line_start", 0),
            getattr(d, "line_end", 0),
            getattr(d, "canonical_excerpt", ""),
            getattr(d, "content_hash", ""),
        )
        for d in getattr(extraction, "evidence_drafts", [])
    )


def _evaluate_source(
    repository: KnowledgeRepository,
    fixtures_dir: Path,
    spec: SourceFixtureSpec,
    source_id: int,
    inject_readback_failure: bool,
) -> SourceResult:
    source = repository.get_source(source_id)
    assert source is not None
    assert source.active_snapshot_id is not None
    snapshot = repository.get_snapshot(source.active_snapshot_id)
    assert snapshot is not None
    page = repository.list_evidence(source_id, snapshot_id=snapshot.id, limit=500)
    evidences = page.items

    readback_pass = 0
    readback_fail = 0
    failed_ids: list[str] = []
    canonical = snapshot.canonical_text
    for index, ev in enumerate(evidences):
        excerpt = canonical[ev.char_start : ev.char_end]
        if inject_readback_failure and index == 0:
            excerpt = excerpt + "__tampered__"
        if excerpt == ev.canonical_excerpt:
            readback_pass += 1
        else:
            readback_fail += 1
            failed_ids.append(ev.id)

    # 幂等：相同 extractor 独立 extract 两次，digest / draft signature 必须一致。
    raw = (fixtures_dir / spec.fixture_path).read_bytes()
    decoded = decode_source_bytes(raw)
    extractor = MarkdownExtractor()
    ext1 = extractor.extract(
        decoded.text, encoding=decoded.encoding, detection_method=decoded.detection_method
    )
    ext2 = extractor.extract(
        decoded.text, encoding=decoded.encoding, detection_method=decoded.detection_method
    )
    rerun_consistent = (
        ext1.digest == ext2.digest == snapshot.digest
        and _drafts_signature(ext1) == _drafts_signature(ext2)
    )

    hash_prefix = source.source_hash[:23]

    return SourceResult(
        source_key=spec.source_key,
        source_hash_prefix=hash_prefix,
        snapshot_digest=snapshot.digest,
        evidence_count=len(evidences),
        readback_pass=readback_pass,
        readback_fail=readback_fail,
        readback_failed_evidence_ids=tuple(failed_ids),
        brief_status=source.brief_status,
        brief_error_code=source.brief_error_code,
        rerun_snapshot_digest=ext2.digest,
        rerun_consistent=rerun_consistent,
    )


def _evaluate_queries(
    repository: KnowledgeRepository,
    source_id_by_key: dict[str, int],
    queries: list[QuerySpec],
) -> list[QueryResult]:
    id_to_key = {sid: key for key, sid in source_id_by_key.items()}
    results: list[QueryResult] = []
    for q in queries:
        hits = repository.search_evidence(q.query, limit=5)
        hit_source_keys = tuple(id_to_key.get(h.source_id, "") for h in hits)
        if q.expect_hit:
            expected_id = source_id_by_key.get(q.source_key)
            ranks = [i + 1 for i, h in enumerate(hits) if h.source_id == expected_id]
            first_rank: Optional[int] = ranks[0] if ranks else None
            recall_hit = first_rank is not None
            mrr_score = 1.0 / first_rank if first_rank else 0.0
            content_keyword_hit = _check_content_keywords(hits, expected_id, q.content_keywords)
        else:
            first_rank = None
            recall_hit = False
            mrr_score = 0.0
            content_keyword_hit = False
        results.append(
            QueryResult(
                query=q.query,
                query_type=q.query_type,
                expected_source_key=q.source_key,
                expect_hit=q.expect_hit,
                hit_source_keys=hit_source_keys,
                first_rank=first_rank,
                recall_hit=recall_hit,
                mrr_score=mrr_score,
                content_keyword_hit=content_keyword_hit,
                retrieval_method="fts",
            )
        )
    return results


def _check_content_keywords(
    hits: list[Any], expected_id: Optional[int], keywords: tuple[str, ...]
) -> bool:
    if not keywords or expected_id is None:
        return False
    for hit in hits:
        if hit.source_id != expected_id:
            continue
        excerpt = getattr(hit, "canonical_excerpt", "") or ""
        if any(kw in excerpt for kw in keywords):
            return True
    return False


def _aggregate_metrics(
    query_results: list[QueryResult], source_results: list[SourceResult]
) -> dict[str, float]:
    lexical = [
        q for q in query_results if q.query_type.startswith("lexical_") and q.expect_hit
    ]
    natural = [
        q for q in query_results if q.query_type == "natural_language" and q.expect_hit
    ]
    lex_recall = (
        sum(1 for q in lexical if q.recall_hit) / len(lexical) if lexical else 0.0
    )
    lex_mrr = sum(q.mrr_score for q in lexical) / len(lexical) if lexical else 0.0
    nl_recall = (
        sum(1 for q in natural if q.recall_hit) / len(natural) if natural else 0.0
    )
    total_ev = sum(s.evidence_count for s in source_results)
    total_pass = sum(s.readback_pass for s in source_results)
    readback_rate = total_pass / total_ev if total_ev else 0.0
    ready = sum(1 for s in source_results if s.brief_status == "ready")
    brief_rate = ready / len(source_results) if source_results else 0.0
    return {
        "lexical_recall_at_5": lex_recall,
        "lexical_mrr": lex_mrr,
        "natural_language_recall_at_5": nl_recall,
        "evidence_readback_rate": readback_rate,
        "brief_pass_rate": brief_rate,
    }


def _collect_failures(
    metrics: dict[str, float],
    gates: AcceptanceGateConfig,
    query_results: list[QueryResult],
    source_results: list[SourceResult],
    fixture_errors: list[str],
) -> list[FailureCase]:
    failures: list[FailureCase] = []
    if metrics["lexical_recall_at_5"] < gates.lexical_recall_at_5:
        failures.append(
            FailureCase(
                gate="lexical_recall_at_5",
                source_key="",
                query="",
                evidence_id="",
                reason=(
                    f"lexical Recall@5={metrics['lexical_recall_at_5']:.3f} "
                    f"低于门禁 {gates.lexical_recall_at_5}"
                ),
            )
        )
        for q in query_results:
            if q.query_type.startswith("lexical_") and q.expect_hit and not q.recall_hit:
                failures.append(
                    FailureCase(
                        gate="lexical_recall_at_5",
                        source_key=q.expected_source_key,
                        query=q.query,
                        evidence_id="",
                        reason="lexical 查询未进前 5",
                    )
                )
    if metrics["lexical_mrr"] < gates.lexical_mrr_min:
        failures.append(
            FailureCase(
                gate="lexical_mrr",
                source_key="",
                query="",
                evidence_id="",
                reason=(
                    f"lexical MRR={metrics['lexical_mrr']:.3f} "
                    f"低于门禁 {gates.lexical_mrr_min}"
                ),
            )
        )
        for q in query_results:
            if (
                q.query_type.startswith("lexical_")
                and q.expect_hit
                and q.recall_hit
                and q.mrr_score < gates.lexical_mrr_min
            ):
                failures.append(
                    FailureCase(
                        gate="lexical_mrr",
                        source_key=q.expected_source_key,
                        query=q.query,
                        evidence_id="",
                        reason=f"MRR={q.mrr_score:.2f}",
                    )
                )
    if metrics["natural_language_recall_at_5"] < gates.natural_language_recall_at_5:
        failures.append(
            FailureCase(
                gate="natural_language_recall_at_5",
                source_key="",
                query="",
                evidence_id="",
                reason=(
                    f"NL Recall@5={metrics['natural_language_recall_at_5']:.3f} "
                    f"低于门禁 {gates.natural_language_recall_at_5}"
                ),
            )
        )
        for q in query_results:
            if q.query_type == "natural_language" and q.expect_hit and not q.recall_hit:
                failures.append(
                    FailureCase(
                        gate="natural_language_recall_at_5",
                        source_key=q.expected_source_key,
                        query=q.query,
                        evidence_id="",
                        reason="自然语言查询未进前 5",
                    )
                )
    if metrics["evidence_readback_rate"] < gates.evidence_readback_rate:
        for s in source_results:
            for eid in s.readback_failed_evidence_ids:
                failures.append(
                    FailureCase(
                        gate="evidence_readback",
                        source_key=s.source_key,
                        query="",
                        evidence_id=eid,
                        reason="canonical_text 切片与 canonical_excerpt 不一致",
                    )
                )
        if not any(f.gate == "evidence_readback" for f in failures):
            failures.append(
                FailureCase(
                    gate="evidence_readback",
                    source_key="",
                    query="",
                    evidence_id="",
                    reason=(
                        f"回读率={metrics['evidence_readback_rate']:.3f} "
                        f"低于门禁 {gates.evidence_readback_rate}"
                    ),
                )
            )
    if metrics["brief_pass_rate"] < gates.brief_pass_rate:
        for s in source_results:
            if s.brief_status != "ready":
                failures.append(
                    FailureCase(
                        gate="brief_pass",
                        source_key=s.source_key,
                        query="",
                        evidence_id="",
                        reason=f"Brief 状态={s.brief_status} ({s.brief_error_code})",
                    )
                )
        if not any(f.gate == "brief_pass" for f in failures):
            failures.append(
                FailureCase(
                    gate="brief_pass",
                    source_key="",
                    query="",
                    evidence_id="",
                    reason=(
                        f"Brief 通过率={metrics['brief_pass_rate']:.3f} "
                        f"低于门禁 {gates.brief_pass_rate}"
                    ),
                )
            )
    for err in fixture_errors:
        failures.append(
            FailureCase(
                gate="fixture_hash",
                source_key="",
                query="",
                evidence_id="",
                reason=err,
            )
        )
    return failures


def _config_with_fallback(base: Config) -> Config:
    """为故障场景构造带 fallback 的 Provider 配置。"""

    primary = base.active_provider()
    primary_id = primary.id if primary else "default"
    fallback = AIProviderProfile(
        id="fallback",
        label="Fallback",
        provider="openai",
        api_key="sk-fallback-acceptance",
        base_url="https://fallback.example.com",
        model="gpt-fallback",
        enabled=True,
        context_window=BRIEF_MIN_CONTEXT_WINDOW,
        max_output_tokens=4096,
    )
    providers = list(base.provider_profiles()) + [fallback]
    return Config(
        api_key=base.api_key,
        providers=providers,
        active_provider_id=primary_id,
        fallback_provider_id="fallback",
    )


def _drain_brief_queue(runner: KnowledgeJobRunner, max_rounds: int = 20) -> None:
    for _ in range(max_rounds):
        results = runner.tick_brief(lease_owner="acceptance")
        if not results:
            break


def _enqueue_brief_rebuild(
    repository: KnowledgeRepository, source_id: int
) -> None:
    source = repository.get_source(source_id)
    assert source is not None and source.active_snapshot_id is not None
    repository.create_job(
        JobCreateInput(
            kind="brief",
            queue="brief",
            source_id=source_id,
            snapshot_id=source.active_snapshot_id,
            stage="brief_rebuild_pending",
        )
    )


def _run_brief_failure_scenarios(
    repository: KnowledgeRepository,
    data_dir: Path,
    session_factory: Any,
    base_config: Config,
    source_id_by_key: dict[str, int],
    fixtures_dir: Path,
) -> list[BriefFailureResult]:
    fallback_config = _config_with_fallback(base_config)
    probe_source_id = source_id_by_key["kafka-isr"]
    results: list[BriefFailureResult] = []
    for scenario in (
        "invalid_json",
        "forged_citation",
        "unsupported_support",
        "coverage_missing",
        "timeout",
        "rate_limit",
        "fallback_success",
    ):
        stub = _make_failure_stub(scenario, repository, fixtures_dir)
        _enqueue_brief_rebuild(repository, probe_source_id)
        worker = BriefWorker(
            repository, fallback_config, model_client=stub, sleeper=lambda _: None
        )
        runner = KnowledgeJobRunner(
            repository,
            ExtractionWorker(repository, data_dir, session_factory),
            brief_worker=worker,
        )
        _drain_brief_queue(runner)
        attempt = repository.find_latest_brief_attempt(probe_source_id)
        status_raw = attempt.status if attempt else "unknown"
        brief_status = "ready" if status_raw == "succeeded" else status_raw
        error_code = attempt.error_code if attempt else ""
        hits = repository.search_evidence(
            "ISR", source_ids=[probe_source_id], limit=5
        )
        results.append(
            BriefFailureResult(
                scenario=scenario,
                brief_status=brief_status,
                brief_error_code=error_code,
                evidence_searchable=bool(hits),
            )
        )
    return results


def _try_ingest(
    service: KnowledgeIngestService, path: Path
) -> tuple[bool, str, int]:
    try:
        source_id = service.ingest(
            IngestRequest(filename=path.name, content_bytes=path.read_bytes())
        ).source.id
        return True, "", source_id
    except IngestError as exc:
        return False, exc.code, 0


def _evaluate_edge_fixtures(
    fixtures_dir: Path, data_dir: Path
) -> list[EdgeFixtureResult]:
    sandbox = data_dir / "edge-sandbox"
    init_database(sandbox / "data.db")
    session_factory = session_factory_for_data_dir(sandbox)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, sandbox, session_factory, config=None)
    edge = fixtures_dir / "edge"
    results: list[EdgeFixtureResult] = []

    for name in ("utf8", "utf8bom", "utf16le", "utf16be", "gbk"):
        accepted, error, _ = _try_ingest(service, edge / "encoding" / f"{name}.md")
        results.append(
            EdgeFixtureResult(
                name=name, accepted=accepted, rejected=not accepted,
                error_code=error, evidence_kind_count=0,
            )
        )

    accepted, error, _ = _try_ingest(service, edge / "empty.md")
    results.append(
        EdgeFixtureResult(
            name="empty", accepted=accepted, rejected=not accepted,
            error_code=error, evidence_kind_count=0,
        )
    )

    template = (edge / "oversized-template.md").read_bytes()
    target_size = 5 * 1024 * 1024 + 64
    oversized = template * (target_size // len(template) + 1)
    oversized = oversized[:target_size]
    try:
        service.ingest(IngestRequest(filename="oversized.md", content_bytes=oversized))
        results.append(
            EdgeFixtureResult(
                name="oversized", accepted=True, rejected=False,
                error_code="", evidence_kind_count=0,
            )
        )
    except IngestError as exc:
        results.append(
            EdgeFixtureResult(
                name="oversized", accepted=False, rejected=True,
                error_code=exc.code, evidence_kind_count=0,
            )
        )

    accepted, error, source_id = _try_ingest(service, edge / "markdown-structure.md")
    kind_count = 0
    if accepted and source_id:
        source = repository.get_source(source_id)
        assert source is not None and source.active_snapshot_id is not None
        page = repository.list_evidence(source_id, limit=500)
        kind_count = len({e.block_kind for e in page.items})
    results.append(
        EdgeFixtureResult(
            name="markdown_structure", accepted=accepted, rejected=not accepted,
            error_code=error, evidence_kind_count=kind_count,
        )
    )

    accepted, error, _ = _try_ingest(service, edge / "text-plain.txt")
    results.append(
        EdgeFixtureResult(
            name="text_plain", accepted=accepted, rejected=not accepted,
            error_code=error, evidence_kind_count=0,
        )
    )
    return results


def _evaluate_bundle_fixtures(
    fixtures_dir: Path, data_dir: Path
) -> list[BundleFixtureResult]:
    """Spec §4.4 Bundle 边界 fixtures：合法 Bundle 通过，非法变体以 bundle_invalid 拒绝。

    每个 Bundle 的附件由代码构造（复用仓库内合法 PNG 字节 + 文本伪装字节），fixture
    目录只保存 main.md，避免仓库保存冗余二进制。各非法变体的拒绝点：
    - 缺图：``_validate_image_references`` 发现引用未上传；
    - 重复逻辑名：``verify_bundle`` 的 ``seen_logical`` 集合；
    - 未使用附件：``_validate_image_references`` 发现上传未被引用；
    - 路径穿越：``safe_logical_name`` 拒绝 ``..``；
    - 媒体伪装：``verify_image_asset`` Pillow 解码失败。
    """

    sandbox = data_dir / "bundle-sandbox"
    init_database(sandbox / "data.db")
    session_factory = session_factory_for_data_dir(sandbox)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, sandbox, session_factory, config=None)
    bundle_dir = fixtures_dir / "bundles"
    valid_png = (bundle_dir / "valid" / "diagram.png").read_bytes()
    fake_png = (bundle_dir / "invalid-media-disguise" / "fake.png").read_bytes()

    cases: list[tuple[str, str, list[tuple[bytes, str]]]] = [
        ("valid", "valid", [(valid_png, "diagram.png")]),
        ("invalid_missing_image", "invalid-missing-image", [(valid_png, "diagram.png")]),
        (
            "invalid_duplicate_image",
            "invalid-duplicate-image",
            [(valid_png, "diagram.png"), (valid_png + valid_png, "diagram.png")],
        ),
        ("invalid_unused_asset", "invalid-unused-asset", [(valid_png, "unused.png")]),
        ("invalid_path_traversal", "invalid-path-traversal", [(valid_png, "../secret.png")]),
        ("invalid_media_disguise", "invalid-media-disguise", [(fake_png, "fake.png")]),
    ]

    results: list[BundleFixtureResult] = []
    for key, dirname, assets in cases:
        main_path = bundle_dir / dirname / "main.md"
        request = IngestRequest(
            filename="main.md",
            content_bytes=main_path.read_bytes(),
            asset_inputs=tuple(
                AssetInput(logical_name=name, content_bytes=data)
                for data, name in assets
            ),
        )
        try:
            service.ingest(request)
            accepted, error = True, ""
        except IngestError as exc:
            accepted, error = False, exc.code
        results.append(
            BundleFixtureResult(
                name=key, accepted=accepted, rejected=not accepted, error_code=error
            )
        )
    return results


def _provider_summary(
    config: Optional[Config],
    repository: KnowledgeRepository,
    source_id_by_key: dict[str, int],
    real_mode: bool,
) -> dict[str, Any]:
    provider = config.active_provider() if config else None
    total_latency = 0
    total_in = 0
    total_out = 0
    provider_ids: set[str] = set()
    for source_id in source_id_by_key.values():
        attempt = repository.find_latest_brief_attempt(source_id)
        if attempt is None:
            continue
        total_latency += attempt.latency_ms
        total_in += attempt.token_input_count
        total_out += attempt.token_output_count
        if attempt.actual_provider_id:
            provider_ids.add(attempt.actual_provider_id)
    return {
        "mode": "real" if real_mode else "stub",
        "active_provider_id": provider.id if provider else "",
        "active_provider_model": provider.model if provider else "",
        "context_window": provider.context_window if provider else 0,
        "extractor_version": EXTRACTOR_VERSION,
        "actual_providers": sorted(provider_ids),
        "total_latency_ms": total_latency,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "note": (
            "使用 stub model_client；真实 Provider 验收请经 CLI --real-ai 运行"
            if not real_mode
            else "使用真实 litellm Provider"
        ),
    }


def run_acceptance(
    *,
    fixtures_dir: Path,
    data_dir: Path,
    config: Optional[Config] = None,
    model_client: Optional[Callable[..., dict[str, Any]]] = None,
    gates: AcceptanceGateConfig = AcceptanceGateConfig(),
    enable_brief: bool = True,
    enable_brief_failure_scenarios: bool = True,
    inject_readback_failure: bool = False,
    real_mode: bool = False,
) -> AcceptanceReport:
    """运行 KI-11 全量验收，返回安全报告。

    - ``fixtures_dir``：含 manifest.json / queries.json / structures / edge / bundles / failure。
    - ``data_dir``：临时 OFFERPILOT_DATA（验收独立数据库，不污染用户数据）。
    - ``config`` / ``model_client``：Brief Provider 配置与模型注入；缺省用 stub。
    - ``real_mode``：True 表示 ``model_client`` 为真实 litellm，影响 provider_summary。
    """

    specs = load_manifest(fixtures_dir)
    queries = load_queries(fixtures_dir)

    fixture_errors = verify_fixture_hashes(fixtures_dir, specs)
    if fixture_errors:
        return AcceptanceReport(
            gate_config=gates,
            metrics={},
            source_results=[],
            query_results=[],
            brief_failure_results=[],
            edge_fixture_results=[],
            bundle_fixture_results=[],
            failures=[],
            fixture_errors=fixture_errors,
            provider_summary={"mode": "stub", "note": "fixture 校验失败，未运行验收"},
        )

    init_database(data_dir / "data.db")
    session_factory = session_factory_for_data_dir(data_dir)
    repository = KnowledgeRepository(session_factory)
    service = KnowledgeIngestService(repository, data_dir, session_factory, config=config)

    # 导入 5 份真实 Source。
    source_id_by_key: dict[str, int] = {}
    for spec in specs:
        source_id_by_key[spec.source_key] = _import_fixture(service, fixtures_dir, spec)

    # Brief 主验收（ingest 已 enqueue brief job，tick 即可）。
    if enable_brief and config is not None:
        stub = model_client or make_perfect_brief_stub(repository)
        worker = BriefWorker(
            repository, config, model_client=stub, sleeper=lambda _: None
        )
        runner = KnowledgeJobRunner(
            repository,
            ExtractionWorker(repository, data_dir, session_factory),
            brief_worker=worker,
        )
        _drain_brief_queue(runner)

    # 构建 source_results（回读 + 幂等 + Brief 状态）。
    source_results = [
        _evaluate_source(
            repository, fixtures_dir, spec, source_id_by_key[spec.source_key],
            inject_readback_failure,
        )
        for spec in specs
    ]

    # 检索指标。
    query_results = _evaluate_queries(repository, source_id_by_key, queries)

    # Brief 故障场景。
    brief_failure_results: list[BriefFailureResult] = []
    if enable_brief_failure_scenarios and config is not None:
        brief_failure_results = _run_brief_failure_scenarios(
            repository, data_dir, session_factory, config, source_id_by_key, fixtures_dir
        )

    # 边界 fixtures（独立 sandbox，不污染主指标）。
    edge_fixture_results = _evaluate_edge_fixtures(fixtures_dir, data_dir)
    bundle_fixture_results = _evaluate_bundle_fixtures(fixtures_dir, data_dir)

    metrics = _aggregate_metrics(query_results, source_results)
    failures = _collect_failures(
        metrics, gates, query_results, source_results, fixture_errors
    )
    provider_summary = _provider_summary(
        config, repository, source_id_by_key, real_mode
    )

    return AcceptanceReport(
        gate_config=gates,
        metrics=metrics,
        source_results=source_results,
        query_results=query_results,
        brief_failure_results=brief_failure_results,
        edge_fixture_results=edge_fixture_results,
        bundle_fixture_results=bundle_fixture_results,
        failures=failures,
        fixture_errors=fixture_errors,
        provider_summary=provider_summary,
    )
