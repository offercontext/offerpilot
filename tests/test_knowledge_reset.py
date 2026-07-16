"""KBR-07：Knowledge-only 破坏性 reset 边界测试。

验证 Spec Implementation Decisions：
- "Knowledge 重置覆盖 Source、Origin、Asset、Snapshot、Evidence、FTS、Brief、Attempt、
   Knowledge Job、处理日志及 Knowledge 文件目录。保留 Schema、迁移记录、AI Provider/应用
   配置和所有非 Knowledge 业务数据。"
- "本次破坏性 reset 必须在最终交付中明确报告。执行删除前仍应使用 Knowledge 专用 reset 边界，
   禁止手工扩大到整个应用数据库或数据目录。"

所有测试使用 ``tmp_path`` 临时数据目录 + 临时 SQLite，绝不触碰真实 ``$OFFERPILOT_DATA``。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from offerpilot.api import create_app
from offerpilot.config import AIProviderProfile, Config, save_config
from offerpilot.db import init_database, session_factory_for_data_dir
from offerpilot.knowledge.brief import BRIEF_MIN_CONTEXT_WINDOW, BRIEF_SCHEMA_VERSION
from offerpilot.knowledge.repository import KnowledgeRepository
from offerpilot.knowledge.reset import (
    KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX,
    KNOWLEDGE_RESET_QUARANTINE_DIR,
    KNOWLEDGE_RESET_MANIFEST_STAGE,
    KNOWLEDGE_RESET_TABLES,
    KnowledgeResetError,
    _quarantine_manifest_path,
    reset_knowledge_domain,
)
from offerpilot.models import Application, Conversation

from _knowledge_seam import (
    RoleAwareModelClient,
    build_supported_brief_json,
    drive_brief_queue,
    ingest_and_extract,
)

CONTENT = (
    "# 概述\n\n"
    "OfferPilot 使用 SQLite 作为 Knowledge 单一事实源。\n\n"
    "## 第二段\n\n"
    "Evidence 是引用单位，Evidence 不重叠。\n"
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _qualified_config() -> Config:
    provider = AIProviderProfile(
        id="default",
        label="Default",
        provider="openai",
        api_key="sk-test-kbr07",
        base_url="https://example.com",
        model="gpt-test",
        enabled=True,
        context_window=BRIEF_MIN_CONTEXT_WINDOW,
        max_output_tokens=4096,
    )
    return Config(
        api_key="sk-test-kbr07",
        providers=[provider],
        active_provider_id="default",
        runtime_mode="local",
    )


def _seed_knowledge(
    tmp_path: Path, *, config: Config | None = None
) -> tuple[KnowledgeRepository, int, int]:
    """通过正式 Ingest + Extraction 产出一条完整 Knowledge 数据（含文件目录）。"""
    cfg = config or _qualified_config()
    repository, session_factory, source_id, snapshot_id = ingest_and_extract(
        tmp_path, CONTENT.encode("utf-8"), config=cfg
    )
    return repository, source_id, snapshot_id


def _seed_non_knowledge(tmp_path: Path) -> dict[str, int]:
    """插入非 Knowledge 代表数据，返回用于前后比对的计数摘要。"""
    session_factory = session_factory_for_data_dir(tmp_path)
    with session_factory() as session:
        session.add(
            Application(
                company_name="ByteDance",
                position_name="Backend",
                status="interview",
            )
        )
        session.add(
            Conversation(title="Pilot 对话", context_type="workspace", context_ref="")
        )
        session.commit()
    return _non_knowledge_counts(tmp_path)


def _non_knowledge_counts(tmp_path: Path) -> dict[str, int]:
    """统计非 Knowledge 代表表的行数，用于断言 reset 前后不变。"""
    with sqlite3.connect(tmp_path / "data.db") as conn:
        return {
            "applications": conn.execute(
                "SELECT COUNT(*) FROM applications"
            ).fetchone()[0],
            "conversations": conn.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()[0],
        }


def _knowledge_counts(tmp_path: Path) -> dict[str, int]:
    """统计所有 Knowledge 表行数（含 FTS），用于断言 reset 后全空。"""
    counts: dict[str, int] = {}
    with sqlite3.connect(tmp_path / "data.db") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table')"
            ).fetchall()
        }
        for table in KNOWLEDGE_RESET_TABLES:
            if table in tables:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
    return counts


def _knowledge_tables_present(tmp_path: Path) -> set[str]:
    """返回当前 DB 中存在的 Knowledge 表名（验证 Schema 保留，不 DROP）。"""
    with sqlite3.connect(tmp_path / "data.db") as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table')"
            ).fetchall()
        }
    return {t for t in KNOWLEDGE_RESET_TABLES if t in existing}


def _schema_migrations(tmp_path: Path) -> set[str]:
    with sqlite3.connect(tmp_path / "data.db") as conn:
        return {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }


# ---------------------------------------------------------------------------
# 1. reset 清空 Knowledge 表族 + FTS
# ---------------------------------------------------------------------------


def test_reset_clears_all_knowledge_tables_and_fts(tmp_path: Path) -> None:
    repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    before = _knowledge_counts(tmp_path)
    assert before["knowledge_sources"] >= 1
    assert before["knowledge_evidence"] >= 1
    assert before["knowledge_evidence_fts"] >= 1
    assert before["knowledge_extraction_snapshots"] >= 1

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    after = _knowledge_counts(tmp_path)
    assert set(after.values()) == {0}, f"Knowledge 表未全空：{after}"


# ---------------------------------------------------------------------------
# 2. reset 保留非 Knowledge 数据 + AI 配置
# ---------------------------------------------------------------------------


def test_reset_preserves_non_knowledge_data(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    before = _seed_non_knowledge(tmp_path)
    assert before["applications"] == 1
    assert before["conversations"] == 1

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    after = _non_knowledge_counts(tmp_path)
    assert after == before, "reset 改动了非 Knowledge 业务数据"


def test_reset_preserves_ai_provider_config(tmp_path: Path) -> None:
    config = _qualified_config()
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    config_path = tmp_path / "config.json"
    before = config_path.read_text(encoding="utf-8")

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert config_path.read_text(encoding="utf-8") == before, "reset 改动了 AI 配置文件"


# ---------------------------------------------------------------------------
# 3. reset 保留 Schema（不 DROP 表）+ 迁移记录
# ---------------------------------------------------------------------------


def test_reset_preserves_schema_and_migrations(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    expected_tables = _knowledge_tables_present(tmp_path)
    expected_migrations = _schema_migrations(tmp_path)
    assert expected_tables  # 至少包含 knowledge_sources 等
    assert expected_migrations  # 至少有 0001_base_schema 等

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert _knowledge_tables_present(tmp_path) == expected_tables, (
        "reset 不应 DROP Knowledge 表（保留 Schema）"
    )
    assert _schema_migrations(tmp_path) == expected_migrations, (
        "reset 不应改动 schema_migrations"
    )


# ---------------------------------------------------------------------------
# 4. reset 清空 Knowledge 文件目录
# ---------------------------------------------------------------------------


def test_reset_clears_knowledge_file_directory(tmp_path: Path) -> None:
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source_dir = tmp_path / "knowledge" / "sources" / str(source_id)
    assert source_dir.is_dir(), "Extraction 应已创建 Source 文件目录"

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    sources_root = tmp_path / "knowledge" / "sources"
    if sources_root.exists():
        assert not any(sources_root.iterdir()), "sources/ 应被清空"
    assert not source_dir.exists(), "原 Source 目录应被删除"


def test_reset_does_not_touch_files_outside_knowledge_dir(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    # 在 data_dir 下、knowledge 之外放置代表文件：数据库、配置、日志。
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "offerpilot.log"
    log_file.write_text("keep-me", encoding="utf-8")
    outside_marker = tmp_path / "outside-marker.txt"
    outside_marker.write_text("keep", encoding="utf-8")

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert outside_marker.read_text(encoding="utf-8") == "keep"
    assert log_file.read_text(encoding="utf-8") == "keep-me"
    assert (tmp_path / "data.db").exists(), "应用数据库不应被删除"


# ---------------------------------------------------------------------------
# 5. reset 可重复执行（空库 / 空目录 / 含数据 / 二次 reset）
# ---------------------------------------------------------------------------


def test_reset_idempotent_across_states(tmp_path: Path) -> None:
    # 空库（已 init_database 但无 Knowledge 数据、无 knowledge 目录）。
    init_database(tmp_path / "data.db")
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert set(_knowledge_counts(tmp_path).values()) == {0}

    # 填入数据后 reset。
    _seed_knowledge(tmp_path)
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert set(_knowledge_counts(tmp_path).values()) == {0}

    # 二次 reset（已空）。
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert set(_knowledge_counts(tmp_path).values()) == {0}


# ---------------------------------------------------------------------------
# 6. reset 拒绝生产 runtime
# ---------------------------------------------------------------------------


def test_reset_refuses_production_runtime(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="server",
            confirm=True,
        )
    assert exc.value.code == "reset_not_allowed_in_runtime"
    # 生产环境拒绝不应改动任何数据。
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1


# ---------------------------------------------------------------------------
# 7. reset 必须显式确认
# ---------------------------------------------------------------------------


def test_reset_requires_explicit_confirm(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=False,
        )
    assert exc.value.code == "reset_requires_confirm"
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1


# ---------------------------------------------------------------------------
# 8. reset 后列表 / 搜索 / FTS / pending Job 全空
# ---------------------------------------------------------------------------


def test_reset_post_state_is_empty(tmp_path: Path) -> None:
    repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    assert repository.list_sources()  # 有数据

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert repository.list_sources() == []
    assert repository.search_evidence("Evidence", limit=5) == []
    with sqlite3.connect(tmp_path / "data.db") as conn:
        pending_running = conn.execute(
            "SELECT COUNT(*) FROM knowledge_jobs WHERE status IN ('pending', 'running')"
        ).fetchone()[0]
    assert pending_running == 0


# ---------------------------------------------------------------------------
# 9. reset 后可重新导入并完成 Brief v2
# ---------------------------------------------------------------------------


def test_reset_enables_reimport_and_brief_v2(tmp_path: Path) -> None:
    config = _qualified_config()
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path, config=config)
    first_source_id = source_id

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    # 重新导入相同内容 → 新 Source（AUTOINCREMENT 保证不复用）；确定性 Extraction 在空库上
    # 重建独立 Snapshot/Evidence。旧 Source/Snapshot 已不存在。
    repository2, session_factory, second_source_id, second_snapshot_id = (
        ingest_and_extract(tmp_path, CONTENT.encode("utf-8"), config=config)
    )
    assert second_source_id != first_source_id
    assert second_snapshot_id > 0
    evidence = repository2.list_evidence(
        second_source_id, snapshot_id=second_snapshot_id, limit=50
    ).items
    assert evidence

    # 完成 Brief v2（schema_version == 2）。
    brief_json = build_supported_brief_json(evidence)
    client = RoleAwareModelClient(generation=[brief_json])
    outcome = drive_brief_queue(
        repository2,
        session_factory,
        tmp_path,
        config=config,
        model_client=client,
        source_id=second_source_id,
    )
    assert outcome.source is not None
    assert outcome.source.brief_status == "ready"
    assert outcome.brief is not None
    assert outcome.brief.schema_version == BRIEF_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 10. 文件清理拒绝符号链接逃逸（路径安全红线）
# ---------------------------------------------------------------------------


def test_reset_rejects_symlink_escape_in_knowledge_dir(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    # 在 knowledge 根的直接子项放置指向 data_dir 之外的符号链接目录。
    outside_dir = tmp_path.parent / "kbr07-outside-target"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("must-not-delete", encoding="utf-8")
    escape_link = tmp_path / "knowledge" / "escape-link"
    escape_link.parent.mkdir(parents=True, exist_ok=True)
    escape_link.symlink_to(outside_dir)

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_path_escape"
    # 越界目标文件必须完好。
    assert outside_file.read_text(encoding="utf-8") == "must-not-delete"


def test_reset_does_not_follow_nested_escape_symlink(tmp_path: Path) -> None:
    """rmtree 不跟随嵌套在真实子目录内的逃逸 symlink（CPython 实现细节→显式契约）。

    根级逃逸 symlink 由 resolve + relative_to 拦截（见上一测试）；真实子目录（如
    ``sources/<id>/``）内的嵌套 symlink 走 ``shutil.rmtree`` 路径。rmtree 删除目录树时
    对符号链接条目仅 unlink 链接本身、不跟随，因此不会删掉外部目标。本测试把该实现
    细节固化为契约：嵌套逃逸 symlink 的外部目标文件必须完好，reset 必须成功完成。
    """
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    nested_dir = tmp_path / "knowledge" / "sources" / str(source_id)
    assert nested_dir.is_dir(), "Source 目录应已存在，作为嵌套 symlink 的宿主"
    # 外部目标文件位于 data_dir 之外（rmtree 作用域之外），含可识别内容。
    outside_file = tmp_path.parent / "kbr07-nested-outside-target.txt"
    outside_file.write_text("nested-must-not-delete", encoding="utf-8")
    # 嵌套逃逸 symlink：sources/<id>/escape-link -> 外部文件。
    (nested_dir / "escape-link").symlink_to(outside_file)

    # reset 成功完成：根级 sources 是真实目录，rmtree 整树，不因嵌套 symlink 而 raise。
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    # 外部目标完好 = rmtree 未跟随嵌套逃逸 symlink。
    assert outside_file.exists(), "嵌套逃逸 symlink 的外部目标不应被删除"
    assert outside_file.read_text(encoding="utf-8") == "nested-must-not-delete"


# ---------------------------------------------------------------------------
# 11. 原子性：DB 事务失败时全部回滚，不留半重置
# ---------------------------------------------------------------------------


def test_reset_db_transaction_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    assert before_counts["knowledge_sources"] >= 1

    # 注入：在 DELETE knowledge_evidence 后、删后续表前抛错，模拟中途失败。
    from offerpilot.knowledge import reset as reset_module

    real_execute = reset_module._delete_from_table

    call_count = {"n": 0}

    def failing_delete(conn, table_name: str) -> None:  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        # 前两张表正常删除，第三张注入失败 → 整个事务必须回滚。
        if call_count["n"] == 3:
            raise RuntimeError("simulated mid-reset failure")
        real_execute(conn, table_name)

    monkeypatch.setattr(reset_module, "_delete_from_table", failing_delete)

    with pytest.raises(Exception):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    # 事务回滚：所有 Knowledge 表行数与 reset 前一致（没有半重置）。
    after_counts = _knowledge_counts(tmp_path)
    assert after_counts == before_counts, (
        "DB 事务中途失败必须整体回滚，不允许部分表被清空"
    )


def _simulate_quarantine(tmp_path: Path, knowledge_dir: Path, gen: str) -> Path:
    """模拟 intent-first 协议：先写 intent manifest，再把 knowledge/ 原子移到 quarantine child。

    对应「rename 成功后、DB 提交前崩溃」的可恢复半状态。
    """
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    child = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}{gen}"
    # intent 必须先于 rename 落盘，启动恢复才能在崩溃后识别该代际。
    _quarantine_manifest_path(child).write_text(
        json.dumps(
            {
                "generation": gen,
                "pid": 999,
                "created_at": 999,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    os.replace(knowledge_dir, child)
    return child


def test_reset_quarantine_cleanup_failure_does_not_create_half_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3：quarantine 物理清理失败时 reset 仍逻辑成功——DB 已清空、knowledge/ 重建为空、
    不产生任何半重置状态；quarantine 残留由启动恢复扫除。"""
    _seed_knowledge(tmp_path)
    non_knowledge_before = _seed_non_knowledge(tmp_path)

    # quarantine 物理清理（shutil.rmtree）失败，模拟文件系统故障。
    import shutil as _shutil

    def failing_rmtree(target, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("simulated fs failure")

    monkeypatch.setattr(_shutil, "rmtree", failing_rmtree)

    # reset 不再因 quarantine 清理失败而抛错（best-effort，记 pending）。
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    # 关键安全属性：DB Knowledge 表已全空，无半重置。
    assert set(_knowledge_counts(tmp_path).values()) == {0}
    # 非 Knowledge 数据不受影响。
    assert _non_knowledge_counts(tmp_path) == non_knowledge_before
    # knowledge/ 重建为空目录。
    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()
    assert not any(knowledge_dir.iterdir())
    # quarantine 残留（清理失败）在受控父目录下，待启动恢复清理。
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    assert qr.is_dir()
    assert [
        p
        for p in qr.iterdir()
        if p.name.startswith(KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX)
    ]


def test_finding3_db_failure_restores_knowledge_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3：DB 事务失败时 quarantine 原子移回 knowledge/——不留「DB 有记录 + 文件缺失」
    半状态，原件完整可回读。"""
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = _repository.get_source(source_id)
    before_counts = _knowledge_counts(tmp_path)
    source_file = tmp_path / "knowledge" / "sources" / str(source_id) / source.main_filename
    assert source_file.exists()

    # 注入：DB 删除第 3 张表时失败 → 触发 except 把 quarantine 移回 knowledge/。
    from offerpilot.knowledge import reset as reset_module

    real_delete = reset_module._delete_from_table
    call_count = {"n": 0}

    def failing_delete(conn, table_name: str) -> None:  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated mid-reset db failure")
        real_delete(conn, table_name)

    monkeypatch.setattr(reset_module, "_delete_from_table", failing_delete)

    with pytest.raises(Exception):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    # DB 整体回滚：行数与 reset 前一致。
    assert _knowledge_counts(tmp_path) == before_counts
    # 关键：原件被移回，source 文件仍存在（无「DB 有记录 + 文件缺失」半状态）。
    assert source_file.exists()
    # 无 quarantine 子目录残留（已移回）；受控父目录若存在则为空。
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    assert not qr.exists() or not [
        p
        for p in qr.iterdir()
        if p.name.startswith(KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX)
    ]


def test_finding3_startup_recovery_restores_quarantine_when_db_has_rows(
    tmp_path: Path,
) -> None:
    """Finding 3 崩溃恢复：reset 移出后未提交（DB 仍有 Knowledge 行）→ init 把 quarantine
    移回 knowledge/ 恢复，原件可回读。"""
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = _repository.get_source(source_id)
    knowledge_dir = tmp_path / "knowledge"
    # 模拟 reset「移出后崩溃」：knowledge/ → 受控父目录下 quarantine child + manifest，DB 仍有行。
    child = _simulate_quarantine(tmp_path, knowledge_dir, "999999-999")
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")  # 触发启动恢复

    # knowledge/ 被移回恢复，原件可回读；quarantine child 已移走。
    assert knowledge_dir.is_dir()
    assert (knowledge_dir / "sources" / str(source_id) / source.main_filename).exists()
    assert not child.exists()


def test_finding3_startup_recovery_cleans_quarantine_when_db_empty(
    tmp_path: Path,
) -> None:
    """Finding 3 崩溃恢复：reset 已提交（DB 空）但 quarantine 清理未完成 → init 清理 quarantine。"""
    _seed_knowledge(tmp_path)
    # 先正常 reset（DB 空，knowledge/ 重建为空）。
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] == 0
    # 模拟「DB 已空但 quarantine 清理未完成」：空 knowledge/ → quarantine child + manifest。
    child = _simulate_quarantine(tmp_path, knowledge_dir, "999998-998")
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")

    # DB 空 + knowledge/ 不存在 → quarantine 被清理。
    assert not child.exists()


def test_finding3_multiple_quarantines_conservative_refusal(tmp_path: Path) -> None:
    """二轮 Review P1-B：多个 quarantine 残留无法判定代际 → init 保守拒绝，不自动恢复/删除。"""
    _repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    # knowledge/ 移到第一个 quarantine（模拟崩溃）；再伪造第二个 quarantine 残留。
    child1 = _simulate_quarantine(tmp_path, knowledge_dir, "999999-100")
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    child2 = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}999998-099"
    child2.mkdir(parents=True, exist_ok=True)
    (child2 / "leftover.md").write_text("stale", encoding="utf-8")
    _quarantine_manifest_path(child2).write_text(
        json.dumps(
            {
                "generation": "999998-099",
                "pid": 99,
                "created_at": 99,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")

    # 两个 quarantine 都保留（保守拒绝）；knowledge/ 未自动恢复，留用户介入。
    assert child1.exists()
    assert child2.exists()
    assert not knowledge_dir.exists()


def test_finding3_quarantine_without_manifest_not_touched(tmp_path: Path) -> None:
    """二轮 Review P1-C：无 manifest 的 quarantine 子目录不被视为 reset 产物，init 不触碰。"""
    _repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    # knowledge/ 移到无 manifest 的子目录（伪造，非 reset 创建）。
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    rogue = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}rogue"
    os.replace(knowledge_dir, rogue)
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")

    # 无 manifest → 不触碰（rogue 保留，knowledge/ 未恢复）。
    assert rogue.exists()
    assert not knowledge_dir.exists()


def test_finding3_user_flat_reset_prefix_dir_not_touched(tmp_path: Path) -> None:
    """二轮 Review P1-C：data_dir 下平铺的 .knowledge-reset-* 用户目录不被 init 误删。"""
    _seed_knowledge(tmp_path)
    # 用户/他模块在 data_dir 平铺创建旧前缀目录（reset 不再使用平铺前缀）。
    user_dir = tmp_path / ".knowledge-reset-userdata"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "keep.txt").write_text("用户数据", encoding="utf-8")

    init_database(tmp_path / "data.db")

    # 平铺目录不受 reset 启动恢复影响（恢复只扫受控父目录 .knowledge-reset/）。
    assert user_dir.exists()
    assert (user_dir / "keep.txt").read_text(encoding="utf-8") == "用户数据"


# ---------------------------------------------------------------------------
# 11b. 三轮 Review P1-1：intent-first manifest 原子协议
# ---------------------------------------------------------------------------


def test_p1_manifest_write_failure_leaves_knowledge_and_db_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-1：intent manifest 写入失败时 knowledge/ 未移动、DB 未变化。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = repository.get_source(source_id)
    before_counts = _knowledge_counts(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    source_file = knowledge_dir / "sources" / str(source_id) / source.main_filename
    assert source_file.exists()

    from offerpilot.knowledge import reset as reset_module

    def failing_write(_child: Path, _generation: str) -> None:
        raise OSError("simulated manifest write failure")

    monkeypatch.setattr(reset_module, "_write_quarantine_manifest", failing_write)

    with pytest.raises(OSError, match="simulated manifest write failure"):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    # knowledge/ 仍在原位，原件可回读；DB 完全未动。
    assert knowledge_dir.is_dir()
    assert source_file.exists()
    assert _knowledge_counts(tmp_path) == before_counts
    # 不得留下会误导恢复的半写/有效 intent manifest。
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    if qr.exists():
        manifests = list(qr.glob(f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}*.manifest"))
        assert manifests == []


def test_p1_manifest_temp_write_failure_leaves_no_valid_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-1：manifest 临时文件写入失败时不留下有效/半写 manifest。"""
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    knowledge_dir = tmp_path / "knowledge"

    from offerpilot.knowledge import reset as reset_module

    real_open = open
    call_state = {"fail_next_tmp": False}

    def open_interceptor(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        path = Path(file)
        # 仅拦截 intent 临时文件的写路径，触发半写失败。
        if (
            call_state["fail_next_tmp"]
            and "w" in mode
            and path.name.endswith(".tmp")
            and KNOWLEDGE_RESET_QUARANTINE_DIR in path.parts
        ):
            raise OSError("simulated temp manifest write failure")
        return real_open(file, mode, *args, **kwargs)

    # 确保后续 reset 使用我们的 open 拦截器：通过替换 builtins.open 影响 Path.write。
    import builtins

    real_write = reset_module._write_quarantine_manifest

    def write_with_failing_temp(child: Path, generation: str) -> None:
        call_state["fail_next_tmp"] = True
        monkeypatch.setattr(builtins, "open", open_interceptor)
        try:
            real_write(child, generation)
        finally:
            call_state["fail_next_tmp"] = False
            monkeypatch.setattr(builtins, "open", real_open)

    monkeypatch.setattr(reset_module, "_write_quarantine_manifest", write_with_failing_temp)

    with pytest.raises(OSError, match="simulated temp manifest write failure"):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    assert knowledge_dir.is_dir()
    assert _knowledge_counts(tmp_path) == before_counts
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    if qr.exists():
        # 既不能有有效 .manifest，也不能留下半写临时文件。
        leftovers = [
            p
            for p in qr.iterdir()
            if p.name.endswith(".manifest")
            or p.name.endswith(".tmp")
            or p.name.startswith(KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX)
        ]
        assert leftovers == [], f"不应留下半写 intent 残留：{leftovers}"


def test_p1_manifest_ready_but_rename_failure_cleans_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-1：manifest 已落盘、knowledge/ rename 失败时清理 intent，保持原位。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = repository.get_source(source_id)
    before_counts = _knowledge_counts(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    source_file = knowledge_dir / "sources" / str(source_id) / source.main_filename

    from offerpilot.knowledge import reset as reset_module

    real_replace = os.replace
    written_manifests: list[Path] = []
    real_write = reset_module._write_quarantine_manifest

    def tracking_write(child: Path, generation: str) -> None:
        real_write(child, generation)
        written_manifests.append(_quarantine_manifest_path(child))

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        src_path = Path(src)
        # 只拦截 knowledge/ → quarantine child 的 rename，不拦截其它 replace。
        if src_path.name == "knowledge" and KNOWLEDGE_RESET_QUARANTINE_DIR in Path(dst).parts:
            raise OSError("simulated knowledge rename failure")
        real_replace(src, dst)

    monkeypatch.setattr(reset_module, "_write_quarantine_manifest", tracking_write)
    monkeypatch.setattr(reset_module.os, "replace", failing_replace)
    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated knowledge rename failure"):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    assert knowledge_dir.is_dir()
    assert source_file.exists()
    assert _knowledge_counts(tmp_path) == before_counts
    assert written_manifests, "intent manifest 应已尝试落盘"
    for manifest in written_manifests:
        assert not manifest.exists(), "rename 失败后必须清理 intent manifest"


def test_p1_manifest_before_rename_crash_recovers_on_init(tmp_path: Path) -> None:
    """P1-1：intent 已落盘、rename 成功后立即崩溃 → 下次 init 按 generation 恢复。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = repository.get_source(source_id)
    knowledge_dir = tmp_path / "knowledge"
    # 模拟 intent-first + rename 成功后崩溃（DB 仍有 Source）。
    child = _simulate_quarantine(tmp_path, knowledge_dir, "777777-777")
    assert not knowledge_dir.exists()
    assert child.is_dir()
    assert _quarantine_manifest_path(child).is_file()

    init_database(tmp_path / "data.db")

    assert knowledge_dir.is_dir()
    assert (knowledge_dir / "sources" / str(source_id) / source.main_filename).exists()
    assert not child.exists()
    assert not _quarantine_manifest_path(child).exists()


def test_p1_manifest_generation_mismatch_rejects_recovery(tmp_path: Path) -> None:
    """P1-1：manifest generation 与 child 名不匹配时拒绝处理，不 move/rmtree。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = repository.get_source(source_id)
    knowledge_dir = tmp_path / "knowledge"
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    child = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}111111-111"
    os.replace(knowledge_dir, child)
    # stage 合法，但 generation 故意与 child 名不一致。
    _quarantine_manifest_path(child).write_text(
        json.dumps(
            {
                "generation": "222222-222",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )

    init_database(tmp_path / "data.db")

    # 代际不匹配 → 不恢复、不清理；DB Source 仍在，但 knowledge/ 未自动恢复。
    assert child.exists()
    assert (child / "sources" / str(source_id) / source.main_filename).exists()
    assert not knowledge_dir.exists()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1


# ---------------------------------------------------------------------------
# 11c. 三轮 Review P1-2：quarantine root/child symlink 与路径逃逸
# ---------------------------------------------------------------------------


def test_p1_quarantine_root_symlink_escape_not_followed(tmp_path: Path) -> None:
    """P1-2：quarantine root 是指向外部目录的 symlink 时不跟随、不 rmtree 外部。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    outside = tmp_path.parent / "kbr-p1-root-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel-root.txt"
    sentinel.write_text("root-must-survive", encoding="utf-8")
    # 外部真实 quarantine 结构，供 symlink root 指向。
    outside_child = outside / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}888888-888"
    outside_child.mkdir(parents=True, exist_ok=True)
    (outside_child / "payload.md").write_text("payload", encoding="utf-8")
    (outside / f"{outside_child.name}.manifest").write_text(
        json.dumps(
            {
                "generation": "888888-888",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    # data_dir 内的 .knowledge-reset 是指向外部的 symlink。
    qr_link = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr_link.symlink_to(outside)
    # knowledge/ 仍在，DB 有 Source。
    assert knowledge_dir.is_dir()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1

    init_database(tmp_path / "data.db")

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "root-must-survive"
    assert outside_child.exists()
    assert (outside_child / "payload.md").exists()
    # 不得把外部 child 移成 knowledge/，也不得删除外部。
    assert knowledge_dir.is_dir()
    assert not (knowledge_dir / "payload.md").exists()


def test_p1_quarantine_child_symlink_escape_not_followed(tmp_path: Path) -> None:
    """P1-2：quarantine child 是指向外部目录的 symlink 时不 move/rmtree 外部。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    outside = tmp_path.parent / "kbr-p1-child-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel-child.txt"
    sentinel.write_text("child-must-survive", encoding="utf-8")
    (outside / "payload.md").write_text("external-payload", encoding="utf-8")

    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    child_link = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}777001-001"
    child_link.symlink_to(outside)
    _quarantine_manifest_path(child_link).write_text(
        json.dumps(
            {
                "generation": "777001-001",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    # 模拟 knowledge/ 已不在（reset 中途），DB 仍有 Source。
    os.replace(knowledge_dir, tmp_path / "knowledge-backup-keep")
    assert not knowledge_dir.exists()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1

    init_database(tmp_path / "data.db")

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "child-must-survive"
    assert (outside / "payload.md").read_text(encoding="utf-8") == "external-payload"
    # 不得把外部 symlink 目标移成 knowledge/。
    assert not knowledge_dir.exists() or not (knowledge_dir / "payload.md").exists()
    assert child_link.is_symlink()


def test_p1_manifest_symlink_escape_not_followed(tmp_path: Path) -> None:
    """P1-2：manifest 是 symlink 时拒绝处理，不跟随、不 unlink 外部目标。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    outside = tmp_path.parent / "kbr-p1-manifest-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel-manifest.txt"
    sentinel.write_text("manifest-must-survive", encoding="utf-8")
    external_manifest = outside / "external.manifest"
    external_manifest.write_text(
        json.dumps(
            {
                "generation": "666001-001",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )

    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    child = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}666001-001"
    os.replace(knowledge_dir, child)
    manifest_link = _quarantine_manifest_path(child)
    manifest_link.symlink_to(external_manifest)
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "manifest-must-survive"
    assert external_manifest.exists()
    # symlink manifest 无效 → child 不触碰。
    assert child.exists()
    assert not knowledge_dir.exists()


def test_p1_child_resolve_escape_not_followed(tmp_path: Path) -> None:
    """P1-2：child 越出权威 data_dir 受控 root 时 cleanup 不 rmtree。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    outside = tmp_path.parent / "kbr-p1-resolve-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel-resolve.txt"
    sentinel.write_text("resolve-must-survive", encoding="utf-8")

    # 外部伪造完整 `.knowledge-reset/quarantine-*` 布局：若 cleanup 仅按目录名推断
    # data_dir，会误删外部；必须绑定权威 data_dir 拒绝。
    from offerpilot.knowledge.reset import _best_effort_cleanup_quarantine

    external_root = outside / KNOWLEDGE_RESET_QUARANTINE_DIR
    external_root.mkdir(parents=True, exist_ok=True)
    external_child = external_root / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}555001-001"
    external_child.mkdir(parents=True, exist_ok=True)
    (external_child / "payload.md").write_text("external", encoding="utf-8")
    _best_effort_cleanup_quarantine(external_child, tmp_path)

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "resolve-must-survive"
    assert external_child.exists()
    assert (external_child / "payload.md").exists()
    # 正常 knowledge/ 不受影响。
    assert knowledge_dir.is_dir()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1


def test_p1_orphan_intent_manifest_cleaned_on_init(tmp_path: Path) -> None:
    """P1-1：intent 已写、rename 前崩溃留下的孤儿 manifest 在 init 时被清理。"""
    _seed_knowledge(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    orphan_child_name = f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}121212-121"
    orphan_manifest = qr / f"{orphan_child_name}.manifest"
    orphan_manifest.write_text(
        json.dumps(
            {
                "generation": "121212-121",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    # 无对应 child 目录，knowledge/ 仍在。
    assert knowledge_dir.is_dir()
    assert not (qr / orphan_child_name).exists()

    init_database(tmp_path / "data.db")

    assert knowledge_dir.is_dir()
    assert not orphan_manifest.exists()
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1


def test_p1_symlink_escape_db_empty_also_safe(tmp_path: Path) -> None:
    """P1-2：DB 空路径下 symlink quarantine 也不得越界删除。"""
    _seed_knowledge(tmp_path)
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert _knowledge_counts(tmp_path)["knowledge_sources"] == 0

    outside = tmp_path.parent / "kbr-p1-empty-db-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel-empty-db.txt"
    sentinel.write_text("empty-db-must-survive", encoding="utf-8")
    (outside / "payload.md").write_text("payload", encoding="utf-8")

    qr = tmp_path / KNOWLEDGE_RESET_QUARANTINE_DIR
    qr.mkdir(parents=True, exist_ok=True)
    child_link = qr / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}444001-001"
    child_link.symlink_to(outside)
    _quarantine_manifest_path(child_link).write_text(
        json.dumps(
            {
                "generation": "444001-001",
                "pid": 1,
                "created_at": 1,
                "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
            }
        ),
        encoding="utf-8",
    )
    # knowledge/ 存在但为空（reset 后），DB 空 → 本应 cleanup，但 symlink 必须拒绝。
    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()

    init_database(tmp_path / "data.db")

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "empty-db-must-survive"
    assert (outside / "payload.md").exists()
    assert child_link.is_symlink()


def test_p1_legitimate_quarantine_still_recovers(tmp_path: Path) -> None:
    """P1-2：合法真实 quarantine 在路径守卫下仍能正常恢复。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source = repository.get_source(source_id)
    knowledge_dir = tmp_path / "knowledge"
    child = _simulate_quarantine(tmp_path, knowledge_dir, "333001-001")
    assert not knowledge_dir.exists()

    init_database(tmp_path / "data.db")

    assert knowledge_dir.is_dir()
    assert (knowledge_dir / "sources" / str(source_id) / source.main_filename).exists()
    assert not child.exists()


def test_reset_startup_recovery_cleans_orphan_files_after_partial_reset(
    tmp_path: Path,
) -> None:
    """Spec §6/§12：reset 后若残留孤儿 Source 目录，下一次 init_database 启动恢复应清除。"""
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source_dir = tmp_path / "knowledge" / "sources" / str(source_id)

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    # 模拟 reset 后外部又写入的孤儿目录（DB 无记录）。
    orphan = tmp_path / "knowledge" / "sources" / "999999"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "leftover.md").write_text("x", encoding="utf-8")
    (tmp_path / "knowledge" / "staging").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge" / "staging" / "half.bin").write_bytes(b"x")

    # 启动恢复清掉孤儿 Source 目录与 staging 残留。
    init_database(tmp_path / "data.db")

    assert not orphan.exists()
    assert not source_dir.exists()
    staging = tmp_path / "knowledge" / "staging"
    if staging.exists():
        assert not any(staging.iterdir())


# ---------------------------------------------------------------------------
# 12. reset 返回摘要：报告删除行数、清理目录、保留数据
# ---------------------------------------------------------------------------


def test_reset_returns_summary_with_preservation_report(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    non_knowledge_before = _seed_non_knowledge(tmp_path)

    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert summary.deleted_source_rows >= 1
    # reset 前后非 Knowledge 代表表行数逐项不变。
    for table, before_count in non_knowledge_before.items():
        assert summary.preserved_non_knowledge.get(table) == before_count, (
            f"非 Knowledge 表 {table} 行数变化"
        )
    assert summary.preserved_ai_config is True
    assert "sources" in summary.cleared_dir_entries


# ---------------------------------------------------------------------------
# 13. API endpoint：带确认参数；未确认拒绝
# ---------------------------------------------------------------------------


def test_api_reset_endpoint_requires_confirm(tmp_path: Path) -> None:
    with TestClient(create_app(data_dir=tmp_path)) as client:
        # 上传一份 Source，确保有数据。
        resp = client.post(
            "/api/knowledge/sources",
            files={"file": ("doc.md", b"# title\n\nneedle\n", "text/markdown")},
        )
        assert resp.status_code == 202

        # 未带 confirm → 拒绝。
        no_confirm = client.post("/api/knowledge/reset", json={})
        assert no_confirm.status_code == 400
        assert no_confirm.json()["error_code"] == "reset_requires_confirm"


def test_api_reset_endpoint_clears_knowledge(tmp_path: Path) -> None:
    with TestClient(create_app(data_dir=tmp_path)) as client:
        upload = client.post(
            "/api/knowledge/sources",
            files={"file": ("doc.md", b"# title\n\nneedle\n", "text/markdown")},
        )
        assert upload.status_code == 202
        source_id = upload.json()["source"]["id"]

        reset = client.post("/api/knowledge/reset", json={"confirm": True})
        assert reset.status_code == 200
        body = reset.json()
        assert body["deleted_source_rows"] >= 1

        # 列表为空；旧 Source 详情 404（无缓存残留）。
        listing = client.get("/api/knowledge/sources")
        assert listing.json() == []
        assert client.get(f"/api/knowledge/sources/{source_id}").status_code == 404


# ---------------------------------------------------------------------------
# 14. CLI：oc knowledge reset --confirm
# ---------------------------------------------------------------------------


def test_cli_knowledge_reset_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_knowledge(tmp_path)
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))

    from typer.testing import CliRunner

    from offerpilot.cli import app as cli_app

    runner = CliRunner()
    # 缺 --confirm → 非零退出、不改数据。
    missing = runner.invoke(cli_app, ["knowledge", "reset"])
    assert missing.exit_code != 0
    assert _knowledge_counts(tmp_path)["knowledge_sources"] >= 1

    # 带 --confirm → 成功、清空。
    ok = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert ok.exit_code == 0, ok.output
    assert set(_knowledge_counts(tmp_path).values()) == {0}
