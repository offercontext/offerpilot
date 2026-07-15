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
    KNOWLEDGE_RESET_TABLES,
    KnowledgeResetError,
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


def test_reset_leaves_db_clean_when_file_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文件清理在 DB 提交后失败时，DB Knowledge 表必须已清空——不存在指向已删文件的 Source。"""
    _seed_knowledge(tmp_path)
    non_knowledge_before = _seed_non_knowledge(tmp_path)

    # DB 先提交，再清文件；注入文件删除失败模拟文件系统故障。
    import shutil as _shutil

    def failing_rmtree(target, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("simulated fs failure")

    monkeypatch.setattr(_shutil, "rmtree", failing_rmtree)

    with pytest.raises(OSError):
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )

    # 关键安全属性：DB Knowledge 表已全空（没有 Source 记录指向被删/残留文件）。
    assert set(_knowledge_counts(tmp_path).values()) == {0}
    # 非 Knowledge 数据不受文件清理失败影响。
    assert _non_knowledge_counts(tmp_path) == non_knowledge_before


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
