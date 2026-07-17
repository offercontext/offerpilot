"""KBR-07：一次性离线 Knowledge reset 边界测试。

批准 Spec：docs/superpowers/specs/2026-07-17-kbr07-one-time-knowledge-reset-design.md

最高测试 seam 是真实 CLI / 服务函数 + 临时 data directory + 真实 SQLite Schema。
不覆盖已删除的 quarantine/manifest/启动恢复协议。
绝不触碰真实 ``$OFFERPILOT_DATA``。
"""

from __future__ import annotations

import shutil
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
    COMPLETION_MIGRATION_VERSION,
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
    repository, _session_factory, source_id, snapshot_id = ingest_and_extract(
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


def _assert_completion_marked(tmp_path: Path) -> None:
    assert COMPLETION_MIGRATION_VERSION in _schema_migrations(tmp_path)


def _assert_knowledge_empty(tmp_path: Path) -> None:
    assert set(_knowledge_counts(tmp_path).values()) == {0}
    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()
    assert not knowledge_dir.is_symlink()
    assert not any(knowledge_dir.iterdir())
    assert not (tmp_path / ".knowledge-reset").exists()


# ---------------------------------------------------------------------------
# 1. 主成功路径
# ---------------------------------------------------------------------------


def test_reset_clears_all_knowledge_tables_and_fts(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    before = _knowledge_counts(tmp_path)
    assert before["knowledge_sources"] >= 1
    assert before["knowledge_evidence"] >= 1
    assert before["knowledge_evidence_fts"] >= 1
    assert before["knowledge_extraction_snapshots"] >= 1

    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    _assert_knowledge_empty(tmp_path)
    _assert_completion_marked(tmp_path)
    assert summary.deleted_source_rows >= 1
    assert summary.completion_marked is True
    assert "sources" in summary.cleared_dir_entries


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

    assert _non_knowledge_counts(tmp_path) == before


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

    assert config_path.read_text(encoding="utf-8") == before


def test_reset_preserves_schema_and_existing_migrations(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    expected_tables = _knowledge_tables_present(tmp_path)
    expected_migrations = _schema_migrations(tmp_path)
    assert expected_tables
    assert expected_migrations
    assert COMPLETION_MIGRATION_VERSION not in expected_migrations

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert _knowledge_tables_present(tmp_path) == expected_tables
    after = _schema_migrations(tmp_path)
    assert expected_migrations.issubset(after)
    assert COMPLETION_MIGRATION_VERSION in after
    assert after - expected_migrations == {COMPLETION_MIGRATION_VERSION}


def test_reset_clears_knowledge_file_directory(tmp_path: Path) -> None:
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source_dir = tmp_path / "knowledge" / "sources" / str(source_id)
    assert source_dir.is_dir()

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()
    assert not any(knowledge_dir.iterdir())
    assert not source_dir.exists()


def test_reset_does_not_touch_files_outside_knowledge_dir(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "offerpilot.log"
    log_file.write_text("keep-me", encoding="utf-8")
    outside_marker = tmp_path / "outside-marker.txt"
    outside_marker.write_text("keep", encoding="utf-8")
    similar_name = tmp_path / ".knowledge-reset-userdata"
    similar_name.mkdir()
    (similar_name / "keep.txt").write_text("用户数据", encoding="utf-8")
    similar_knowledge = tmp_path / "knowledge-backup"
    similar_knowledge.mkdir()
    (similar_knowledge / "keep.txt").write_text("backup", encoding="utf-8")

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert outside_marker.read_text(encoding="utf-8") == "keep"
    assert log_file.read_text(encoding="utf-8") == "keep-me"
    assert (tmp_path / "data.db").exists()
    assert (similar_name / "keep.txt").read_text(encoding="utf-8") == "用户数据"
    assert (similar_knowledge / "keep.txt").read_text(encoding="utf-8") == "backup"


def test_reset_clears_legacy_knowledge_reset_dir(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    legacy = tmp_path / ".knowledge-reset"
    child = legacy / "quarantine-old"
    child.mkdir(parents=True)
    (child / "leftover.md").write_text("stale", encoding="utf-8")

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert not legacy.exists()
    _assert_knowledge_empty(tmp_path)


def test_reset_missing_knowledge_and_legacy_dirs_are_empty_ok(tmp_path: Path) -> None:
    init_database(tmp_path / "data.db")
    assert not (tmp_path / "knowledge").exists()
    assert not (tmp_path / ".knowledge-reset").exists()

    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert summary.deleted_source_rows == 0
    _assert_knowledge_empty(tmp_path)
    _assert_completion_marked(tmp_path)


# ---------------------------------------------------------------------------
# 2. 门禁
# ---------------------------------------------------------------------------


def _snapshot_data_dir(tmp_path: Path) -> tuple[dict[str, int], set[str], list[str], str]:
    """门禁拒绝路径用的全量不变性快照：表计数、迁移、相对文件路径、配置原文。"""
    counts = _knowledge_counts(tmp_path)
    migrations = _schema_migrations(tmp_path)
    files = sorted(
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*")
        if p.is_file() or p.is_symlink()
    )
    config_path = tmp_path / "config.json"
    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    return counts, migrations, files, config_text


def test_reset_refuses_production_runtime(tmp_path: Path) -> None:
    config = _qualified_config()
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    before = _snapshot_data_dir(tmp_path)
    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="server",
            confirm=True,
        )
    assert exc.value.code == "reset_not_allowed_in_runtime"
    assert _snapshot_data_dir(tmp_path) == before


def test_reset_requires_explicit_confirm(tmp_path: Path) -> None:
    config = _qualified_config()
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    before = _snapshot_data_dir(tmp_path)
    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=False,
        )
    assert exc.value.code == "reset_requires_confirm"
    assert _snapshot_data_dir(tmp_path) == before


# ---------------------------------------------------------------------------
# 3. 完成标记门禁 + 重新导入保护
# ---------------------------------------------------------------------------


def test_reset_already_completed_refuses_and_protects_new_data(tmp_path: Path) -> None:
    config = _qualified_config()
    _seed_knowledge(tmp_path, config=config)
    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    _assert_completion_marked(tmp_path)

    # 完成后重新导入新 Source。
    repository, source_id, snapshot_id = _seed_knowledge(tmp_path, config=config)
    assert source_id > 0
    assert snapshot_id > 0
    evidence = repository.list_evidence(source_id, snapshot_id=snapshot_id, limit=50).items
    assert evidence
    source_file = tmp_path / "knowledge" / "sources" / str(source_id)
    assert source_file.is_dir()
    before_counts = _knowledge_counts(tmp_path)

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_already_completed"
    assert _knowledge_counts(tmp_path) == before_counts
    assert source_file.is_dir()


# ---------------------------------------------------------------------------
# 4. 事务回滚 / 文件失败重试 / READY_TO_MARK
# ---------------------------------------------------------------------------


def test_reset_db_transaction_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    assert knowledge_dir.is_dir()
    before_files = sorted(p.name for p in knowledge_dir.rglob("*") if p.is_file())

    from offerpilot.knowledge import reset as reset_module

    real_execute = reset_module._delete_from_table
    call_count = {"n": 0}

    def failing_delete(conn, table_name: str) -> None:  # type: ignore[no-untyped-def]
        call_count["n"] += 1
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

    assert _knowledge_counts(tmp_path) == before_counts
    assert knowledge_dir.is_dir()
    after_files = sorted(p.name for p in knowledge_dir.rglob("*") if p.is_file())
    assert after_files == before_files
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)


def test_reset_file_cleanup_failure_then_retry_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_knowledge(tmp_path)
    non_knowledge_before = _seed_non_knowledge(tmp_path)

    from offerpilot.knowledge import reset as reset_module

    real_clear = reset_module._clear_knowledge_files
    call_count = {"n": 0}

    def failing_then_ok(data_dir: Path) -> list[str]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 模拟 DB 已提交后、文件只清理一部分：留下 knowledge/sources 残留。
            knowledge_dir = data_dir / "knowledge"
            if knowledge_dir.exists() and knowledge_dir.is_dir():
                leftover = knowledge_dir / "sources"
                leftover.mkdir(parents=True, exist_ok=True)
                (leftover / "partial.bin").write_bytes(b"partial")
            raise KnowledgeResetError(
                "reset_file_cleanup_failed",
                "simulated partial file cleanup failure",
            )
        return real_clear(data_dir)

    monkeypatch.setattr(reset_module, "_clear_knowledge_files", failing_then_ok)

    with pytest.raises(KnowledgeResetError) as first:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert first.value.code == "reset_file_cleanup_failed"
    # DB 已空，文件仍有残留，完成标记未写。
    assert set(_knowledge_counts(tmp_path).values()) == {0}
    assert (tmp_path / "knowledge" / "sources" / "partial.bin").exists()
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)
    assert _non_knowledge_counts(tmp_path) == non_knowledge_before

    # 第二次从 DB_CLEARED_FILES_PENDING 继续收敛。
    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert summary.completion_marked is True
    _assert_knowledge_empty(tmp_path)
    _assert_completion_marked(tmp_path)
    assert _non_knowledge_counts(tmp_path) == non_knowledge_before


def test_reset_ready_to_mark_only_writes_completion(tmp_path: Path) -> None:
    """DB 空、文件空、无标记 → 只验证并写完成标记。"""
    init_database(tmp_path / "data.db")
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    assert not any(knowledge_dir.iterdir())
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)

    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )

    assert summary.deleted_source_rows == 0
    assert summary.completion_marked is True
    _assert_knowledge_empty(tmp_path)
    _assert_completion_marked(tmp_path)


# ---------------------------------------------------------------------------
# 5. 路径安全 fail closed
# ---------------------------------------------------------------------------


def test_reset_rejects_knowledge_root_symlink(tmp_path: Path) -> None:
    # 必须先 seed 再替换为 symlink：证明路径拒绝发生在 DB 清表之前。
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    assert before_counts["knowledge_sources"] >= 1
    outside = tmp_path.parent / "kbr07-knowledge-root-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "secret.txt"
    sentinel.write_text("must-not-delete", encoding="utf-8")
    knowledge_dir = tmp_path / "knowledge"
    shutil.rmtree(knowledge_dir)
    knowledge_link = tmp_path / "knowledge"
    knowledge_link.symlink_to(outside)

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_path_escape"
    assert sentinel.read_text(encoding="utf-8") == "must-not-delete"
    assert knowledge_link.is_symlink()
    # 关键：路径失败不得清空 DB。
    assert _knowledge_counts(tmp_path) == before_counts
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)


def test_reset_rejects_legacy_reset_root_symlink(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    outside = tmp_path.parent / "kbr07-legacy-reset-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "secret.txt"
    sentinel.write_text("must-not-delete", encoding="utf-8")
    legacy_link = tmp_path / ".knowledge-reset"
    legacy_link.symlink_to(outside)

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_path_escape"
    assert sentinel.read_text(encoding="utf-8") == "must-not-delete"
    assert legacy_link.is_symlink()
    assert _knowledge_counts(tmp_path) == before_counts
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)


def test_reset_rejects_knowledge_root_non_directory(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    knowledge_dir = tmp_path / "knowledge"
    shutil.rmtree(knowledge_dir)
    knowledge_file = tmp_path / "knowledge"
    knowledge_file.write_text("not-a-dir", encoding="utf-8")

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_path_escape"
    assert knowledge_file.is_file()
    assert knowledge_file.read_text(encoding="utf-8") == "not-a-dir"
    assert _knowledge_counts(tmp_path) == before_counts
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)


def test_reset_rejects_legacy_reset_root_non_directory(tmp_path: Path) -> None:
    _seed_knowledge(tmp_path)
    before_counts = _knowledge_counts(tmp_path)
    legacy_file = tmp_path / ".knowledge-reset"
    legacy_file.write_text("not-a-dir", encoding="utf-8")

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_path_escape"
    assert legacy_file.is_file()
    assert legacy_file.read_text(encoding="utf-8") == "not-a-dir"
    assert _knowledge_counts(tmp_path) == before_counts
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)


def test_reset_rejects_absolute_escape_target_via_helper_boundary(
    tmp_path: Path,
) -> None:
    """固定路径清理 helper 对越界 target fail closed，外部 sentinel 完好。

    公开 reset 入口只接受 data_dir 下固定子名；此处直接调用路径守卫 helper，
    验证 resolve 越界分支本身拒绝删除外部目录。
    """
    from offerpilot.knowledge.reset import _assert_safe_fixed_root

    init_database(tmp_path / "data.db")
    outside = tmp_path.parent / "kbr07-resolve-escape-outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "secret.txt"
    sentinel.write_text("must-not-delete", encoding="utf-8")

    with pytest.raises(KnowledgeResetError) as exc:
        _assert_safe_fixed_root(tmp_path, outside, "knowledge")
    assert exc.value.code == "reset_path_escape"
    assert sentinel.read_text(encoding="utf-8") == "must-not-delete"


def test_reset_does_not_follow_nested_escape_symlink(tmp_path: Path) -> None:
    """rmtree 对嵌套 symlink 只 unlink 链接本身，不跟随外部目标。"""
    _repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    nested_dir = tmp_path / "knowledge" / "sources" / str(source_id)
    assert nested_dir.is_dir()
    outside_file = tmp_path.parent / "kbr07-nested-outside-target.txt"
    outside_file.write_text("nested-must-not-delete", encoding="utf-8")
    (nested_dir / "escape-link").symlink_to(outside_file)

    reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert outside_file.exists()
    assert outside_file.read_text(encoding="utf-8") == "nested-must-not-delete"
    _assert_knowledge_empty(tmp_path)


# ---------------------------------------------------------------------------
# 6. reset 后重新导入并完成 Brief v2
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

    # 完成标记存在后，正常 ingest 仍可运行；但再次 reset 会被拒绝。
    repository2, session_factory, second_source_id, second_snapshot_id = (
        ingest_and_extract(tmp_path, CONTENT.encode("utf-8"), config=config)
    )
    assert second_source_id != first_source_id
    assert second_snapshot_id > 0
    evidence = repository2.list_evidence(
        second_source_id, snapshot_id=second_snapshot_id, limit=50
    ).items
    assert evidence

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

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_already_completed"
    assert repository2.get_source(second_source_id) is not None


def test_reset_post_state_is_empty(tmp_path: Path) -> None:
    repository, _source_id, _snapshot_id = _seed_knowledge(tmp_path)
    assert repository.list_sources()

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
# 7. 启动恢复：staging / 孤儿 Source / Job lease 仍保留；不再恢复 reset quarantine
# ---------------------------------------------------------------------------


def test_startup_recovery_still_cleans_orphan_sources_and_staging(tmp_path: Path) -> None:
    repository, source_id, _snapshot_id = _seed_knowledge(tmp_path)
    source_dir = tmp_path / "knowledge" / "sources" / str(source_id)
    assert source_dir.is_dir()

    # 不经过 reset：直接制造孤儿 Source 目录与 staging 残留，验证正常 Knowledge 恢复。
    orphan = tmp_path / "knowledge" / "sources" / "999999"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "leftover.md").write_text("x", encoding="utf-8")
    staging = tmp_path / "knowledge" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "half.bin").write_bytes(b"x")

    init_database(tmp_path / "data.db")

    assert not orphan.exists()
    assert source_dir.exists()  # 有 DB 记录的 Source 目录保留
    if staging.exists():
        assert not any(staging.iterdir())
    assert repository.get_source(source_id) is not None


# ---------------------------------------------------------------------------
# 8. API 404 + CLI
# ---------------------------------------------------------------------------


def test_api_reset_endpoint_removed(tmp_path: Path) -> None:
    """原 reset HTTP 路由已删除；未知 /api/* 必须稳定返回 404。"""
    with TestClient(create_app(data_dir=tmp_path)) as client:
        resp = client.post("/api/knowledge/reset", json={"confirm": True})
        assert resp.status_code == 404
        assert "deleted_source_rows" not in resp.text
        assert "cleared_tables" not in resp.text
        get_resp = client.get("/api/knowledge/reset")
        assert get_resp.status_code == 404
        assert "deleted_source_rows" not in get_resp.text


def test_cli_knowledge_reset_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _qualified_config()
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))
    before = _snapshot_data_dir(tmp_path)

    from typer.testing import CliRunner

    from offerpilot.cli import app as cli_app

    runner = CliRunner()
    missing = runner.invoke(cli_app, ["knowledge", "reset"])
    assert missing.exit_code != 0
    assert "reset_requires_confirm" in missing.output
    assert _snapshot_data_dir(tmp_path) == before

    ok = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert ok.exit_code == 0, ok.output
    assert "一次性迁移完成" in ok.output or "完成标记" in ok.output
    _assert_knowledge_empty(tmp_path)
    _assert_completion_marked(tmp_path)

    after_complete = _snapshot_data_dir(tmp_path)
    again = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert again.exit_code != 0
    assert "reset_already_completed" in again.output
    assert _snapshot_data_dir(tmp_path) == after_complete


def test_cli_gate_refusal_does_not_run_startup_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完成后再次 CLI 拒绝时，不得触发 init_database 启动恢复清理 staging。"""
    config = _qualified_config()
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))

    from typer.testing import CliRunner

    from offerpilot.cli import app as cli_app

    runner = CliRunner()
    ok = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert ok.exit_code == 0, ok.output
    _assert_completion_marked(tmp_path)

    staging = tmp_path / "knowledge" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    sentinel = staging / "sentinel.bin"
    sentinel.write_bytes(b"keep-me")
    before = _snapshot_data_dir(tmp_path)

    again = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert again.exit_code != 0
    assert "reset_already_completed" in again.output
    assert sentinel.exists()
    assert sentinel.read_bytes() == b"keep-me"
    assert _snapshot_data_dir(tmp_path) == before

    # 缺少 --confirm 同样不得有副作用。
    missing = runner.invoke(cli_app, ["knowledge", "reset"])
    assert missing.exit_code != 0
    assert "reset_requires_confirm" in missing.output
    assert sentinel.exists()
    assert _snapshot_data_dir(tmp_path) == before


def test_completion_mark_revoked_if_post_write_empty_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """写标记后复验失败必须撤销标记，避免误标 COMPLETE。"""
    _seed_knowledge(tmp_path)
    from offerpilot.knowledge import reset as reset_module

    real_assert = reset_module._assert_knowledge_domain_empty
    real_write = reset_module._write_completion_mark
    state = {"written": False}

    def write_then_flag(session_factory) -> None:  # type: ignore[no-untyped-def]
        real_write(session_factory)
        state["written"] = True

    def flaky_empty(session_factory, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
        # 写标记前的检查放行；写标记后第一次复验失败。
        if not state["written"]:
            return real_assert(session_factory, data_dir)
        raise KnowledgeResetError(
            "reset_verification_failed",
            "Knowledge 文件清空后验证仍非空，拒绝写入完成标记",
        )

    monkeypatch.setattr(reset_module, "_write_completion_mark", write_then_flag)
    monkeypatch.setattr(reset_module, "_assert_knowledge_domain_empty", flaky_empty)

    with pytest.raises(KnowledgeResetError) as exc:
        reset_knowledge_domain(
            session_factory_for_data_dir(tmp_path),
            tmp_path,
            runtime_mode="local",
            confirm=True,
        )
    assert exc.value.code == "reset_verification_failed"
    assert state["written"] is True
    # 标记必须被撤销。
    assert COMPLETION_MIGRATION_VERSION not in _schema_migrations(tmp_path)
    # DB 已清空（写标记前已完成），可重跑收敛。
    assert set(_knowledge_counts(tmp_path).values()) == {0}

    # 去掉 monkeypatch 后应能写标记完成。
    monkeypatch.undo()
    summary = reset_knowledge_domain(
        session_factory_for_data_dir(tmp_path),
        tmp_path,
        runtime_mode="local",
        confirm=True,
    )
    assert summary.completion_marked is True
    _assert_completion_marked(tmp_path)


def test_cli_knowledge_reset_refuses_non_local_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _qualified_config()
    config.runtime_mode = "server"
    save_config(tmp_path, config)
    _seed_knowledge(tmp_path, config=config)
    monkeypatch.setenv("OFFERPILOT_DATA", str(tmp_path))
    before = _snapshot_data_dir(tmp_path)

    from typer.testing import CliRunner

    from offerpilot.cli import app as cli_app

    runner = CliRunner()
    result = runner.invoke(cli_app, ["knowledge", "reset", "--confirm"])
    assert result.exit_code != 0
    assert "reset_not_allowed_in_runtime" in result.output
    assert _snapshot_data_dir(tmp_path) == before
