"""KBR-07：一次性离线 Knowledge 数据域迁移（非长期产品能力）。

批准 Spec：``docs/superpowers/specs/2026-07-17-kbr07-one-time-knowledge-reset-design.md``。

能力边界
~~~~~~~~

- 唯一操作界面是本地 CLI ``oc knowledge reset --confirm``。
- 不暴露 HTTP API、前端入口、Agent tool 或启动恢复协议。
- 不使用 quarantine / generation / manifest / intent / cleanup pending。
- 失败后不恢复旧 Knowledge，只允许重新运行命令继续向空状态收敛。
- 数据库与文件均验证为空且保护项通过后，才写入一次性完成标记
  ``kbr07_one_time_knowledge_reset_complete``；标记存在时永久拒绝再次清空。

执行顺序
~~~~~~~~

1. 门禁：``runtime_mode=local`` 且 ``confirm=True``（零副作用，不打开会触发恢复的 DB）。
2. 若完成标记已存在 → ``reset_already_completed``，不触碰任何数据。
3. 预检固定清理根路径；非法则 fail closed，不开始 DB 清理。
4. 单 SQLite 事务 DELETE Knowledge 表闭集；失败整体回滚且不开始文件清理。
5. 提交后安全清理固定路径 ``knowledge/`` 与 ``.knowledge-reset/``。
6. 验证 Knowledge 表与文件均为空、非 Knowledge 与 AI 配置不变。
7. 独立事务写入完成标记；写后立即复验空状态，失败则撤销标记。
"""

from __future__ import annotations

import sqlite3
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.config import RuntimeMode, load_config

# Knowledge 表族闭集（reset 范围）。删除顺序：先子表后父表。
# 该清单是 reset 边界的唯一事实源；绝不包含非 Knowledge 表。
KNOWLEDGE_RESET_TABLES: tuple[str, ...] = (
    "knowledge_evidence_fts",
    "knowledge_retrieval_traces",
    "knowledge_logs",
    "knowledge_jobs",
    "knowledge_source_briefs",
    "knowledge_brief_attempts",
    "knowledge_evidence",
    "knowledge_source_assets",
    "knowledge_extraction_snapshots",
    "knowledge_source_origins",
    "knowledge_sources",
)

# 非 Knowledge 代表表：reset 前后统计行数，断言不变。
NON_KNOWLEDGE_GUARD_TABLES: tuple[str, ...] = (
    "applications",
    "application_events",
    "conversations",
    "chat_messages",
    "interview_notes",
    "offers",
    "resumes",
    "questions",
    "wakeups",
)

AI_CONFIG_FILENAME = "config.json"
KNOWLEDGE_DIR_NAME = "knowledge"
LEGACY_RESET_DIR_NAME = ".knowledge-reset"
COMPLETION_MIGRATION_VERSION = "kbr07_one_time_knowledge_reset_complete"
COMPLETION_MIGRATION_DESCRIPTION = (
    "KBR-07 one-time offline Knowledge reset completed; refuse further resets"
)


class KnowledgeResetError(Exception):
    """一次性 Knowledge 迁移边界错误。``code`` 供 CLI 稳定映射。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class KnowledgeResetSummary:
    """reset 执行报告（破坏性操作的审计摘要）。"""

    deleted_source_rows: int
    cleared_tables: list[str]
    cleared_dir_entries: list[str]
    preserved_non_knowledge: dict[str, int]
    preserved_ai_config: bool
    preserved_migrations: int
    completion_marked: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "deleted_source_rows": self.deleted_source_rows,
            "cleared_tables": list(self.cleared_tables),
            "cleared_dir_entries": list(self.cleared_dir_entries),
            "preserved_non_knowledge": dict(self.preserved_non_knowledge),
            "preserved_ai_config": self.preserved_ai_config,
            "preserved_migrations": self.preserved_migrations,
            "completion_marked": self.completion_marked,
        }


@dataclass
class _PreSnapshot:
    """reset 前的非 Knowledge 数据快照，用于事后断言不变。"""

    non_knowledge: dict[str, int] = field(default_factory=dict)
    ai_config_payload: str = ""
    ai_config_exists: bool = False
    # 完成标记写入前已有的 migration 版本集合（不含即将写入的完成标记）。
    migration_versions: set[str] = field(default_factory=set)


def _existing_tables(conn: Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type IN ('table')")
        ).fetchall()
    }


def _delete_from_table(conn: Connection, table_name: str) -> None:
    """删除单张 Knowledge 表的全部行。表不存在时视为已清空（可重复执行）。"""
    conn.execute(text(f"DELETE FROM {table_name}"))


def _count_rows(conn: Connection, table_name: str) -> int:
    row = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
    return int(row[0]) if row is not None else 0


def _path_contained(path: Path, root: Path) -> bool:
    """``path`` resolve 后严格位于 ``root`` resolve 内（含 root 自身）。"""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _assert_safe_fixed_root(data_dir: Path, target: Path, label: str) -> None:
    """固定清理根必须是 data_dir 下的真实直接子目录，不能是 symlink / 非目录 / 越界。

    helper 在执行删除前自行检查，不依赖调用方预检。
    """
    if target.is_symlink():
        raise KnowledgeResetError(
            "reset_path_escape",
            f"{label} 是符号链接，拒绝跟随外部目标",
        )
    if not target.exists():
        return
    if not target.is_dir():
        raise KnowledgeResetError(
            "reset_path_escape",
            f"{label} 不是目录，拒绝清理",
        )
    if target.parent.resolve() != data_dir.resolve():
        raise KnowledgeResetError(
            "reset_path_escape",
            f"{label} 不是 data_dir 的直接子路径，拒绝清理",
        )
    if not _path_contained(target, data_dir):
        raise KnowledgeResetError(
            "reset_path_escape",
            f"{label} 越出 data_dir，拒绝清理",
        )


def _precheck_cleanup_roots(data_dir: Path) -> None:
    """在任何破坏性 DB 操作前预检固定清理根。

    不存在视为空；symlink / 非目录 / 越界 → ``reset_path_escape``，且不得开始清表。
    """
    _assert_safe_fixed_root(data_dir, data_dir / KNOWLEDGE_DIR_NAME, KNOWLEDGE_DIR_NAME)
    _assert_safe_fixed_root(
        data_dir, data_dir / LEGACY_RESET_DIR_NAME, LEGACY_RESET_DIR_NAME
    )


def _capture_pre_snapshot(session_factory: sessionmaker[Session]) -> _PreSnapshot:
    snapshot = _PreSnapshot()
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        for table in NON_KNOWLEDGE_GUARD_TABLES:
            if table in existing:
                snapshot.non_knowledge[table] = _count_rows(conn, table)
        if "schema_migrations" in existing:
            snapshot.migration_versions = {
                str(row[0])
                for row in conn.execute(
                    text("SELECT version FROM schema_migrations")
                ).fetchall()
            }
    return snapshot


def _capture_ai_config(data_dir: Path) -> str:
    config_path = data_dir / AI_CONFIG_FILENAME
    if not config_path.exists():
        return ""
    return config_path.read_text(encoding="utf-8")


def completion_mark_exists_at(data_dir: Path) -> bool:
    """只读查询完成标记，不触发 init_database / 启动恢复。

    供 CLI 在打开会执行恢复副作用的 session factory 之前做门禁。
    """
    db_path = data_dir / "data.db"
    if not db_path.exists():
        return False
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='schema_migrations' LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            found = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ? LIMIT 1",
                (COMPLETION_MIGRATION_VERSION,),
            ).fetchone()
            return found is not None
    except sqlite3.Error:
        # 数据库不可读时不视为已完成，交给后续正式路径处理。
        return False


def assert_reset_preconditions(
    data_dir: Path,
    *,
    runtime_mode: RuntimeMode,
    confirm: bool,
) -> None:
    """零副作用门禁：不打开会触发恢复的 DB 连接，不触碰文件。

    CLI 必须在 ``session_factory_for_data_dir`` 之前调用本函数。
    """
    if runtime_mode != "local":
        raise KnowledgeResetError(
            "reset_not_allowed_in_runtime",
            f"runtime_mode={runtime_mode!r} 非本地模式，拒绝执行破坏性 Knowledge reset",
        )
    if not confirm:
        raise KnowledgeResetError(
            "reset_requires_confirm",
            "破坏性 reset 需要显式确认（confirm=True）",
        )
    if completion_mark_exists_at(data_dir):
        raise KnowledgeResetError(
            "reset_already_completed",
            "KBR-07 一次性 Knowledge reset 已完成，拒绝再次清空",
        )


def _completion_mark_exists(session_factory: sessionmaker[Session]) -> bool:
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        if "schema_migrations" not in existing:
            return False
        row = conn.execute(
            text(
                "SELECT 1 FROM schema_migrations WHERE version = :version LIMIT 1"
            ),
            {"version": COMPLETION_MIGRATION_VERSION},
        ).fetchone()
        return row is not None


def _write_completion_mark(session_factory: sessionmaker[Session]) -> None:
    """独立事务写入一次性完成标记。"""
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        if "schema_migrations" not in existing:
            raise KnowledgeResetError(
                "reset_migration_missing",
                "schema_migrations 不存在，无法写入一次性完成标记",
            )
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO schema_migrations (version, description)
                VALUES (:version, :description)
                """
            ),
            {
                "version": COMPLETION_MIGRATION_VERSION,
                "description": COMPLETION_MIGRATION_DESCRIPTION,
            },
        )
        session.commit()


def _remove_completion_mark(session_factory: sessionmaker[Session]) -> None:
    """撤销误写的完成标记（写标记后复验失败时使用）。"""
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        if "schema_migrations" not in existing:
            return
        conn.execute(
            text("DELETE FROM schema_migrations WHERE version = :version"),
            {"version": COMPLETION_MIGRATION_VERSION},
        )
        session.commit()


def _knowledge_tables_empty(session_factory: sessionmaker[Session]) -> bool:
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        for table_name in KNOWLEDGE_RESET_TABLES:
            if table_name in existing and _count_rows(conn, table_name) > 0:
                return False
    return True


def _knowledge_files_empty(data_dir: Path) -> bool:
    """Knowledge 文件是否已收敛到空安全状态。

    - ``knowledge/`` 不存在或为空真实目录 → 空。
    - ``.knowledge-reset/`` 不存在 → 空；若存在则非空（需清理）。
    - 根路径是 symlink / 非目录 → 视为未空，由清理路径 fail closed。
    """
    knowledge_dir = data_dir / KNOWLEDGE_DIR_NAME
    legacy_reset_dir = data_dir / LEGACY_RESET_DIR_NAME

    try:
        if knowledge_dir.exists():
            if knowledge_dir.is_symlink() or not knowledge_dir.is_dir():
                return False
            if any(knowledge_dir.iterdir()):
                return False

        if legacy_reset_dir.exists():
            # 残留本身就需要清理；symlink/非目录也视为未空，交清理路径 fail closed。
            return False
    except OSError:
        return False

    return True


def _list_knowledge_dir_entries(knowledge_dir: Path) -> list[str]:
    if not knowledge_dir.exists() or knowledge_dir.is_symlink() or not knowledge_dir.is_dir():
        return []
    try:
        return sorted(child.name for child in knowledge_dir.iterdir())
    except OSError as exc:
        raise KnowledgeResetError(
            "reset_file_cleanup_failed",
            f"列举 knowledge/ 失败：{exc.__class__.__name__}",
        ) from exc


def _clear_fixed_directory(data_dir: Path, name: str, *, recreate_empty: bool) -> list[str]:
    """安全清理 data_dir 下的固定直接子路径。

    - 不存在：视为空，不构成错误。
    - symlink / 非目录 / 越界：``reset_path_escape``。
    - 删除时 helper 自行校验边界；``rmtree`` 对嵌套 symlink 只 unlink 链接本身。
    - 所有文件 I/O 异常映射为稳定 ``reset_file_cleanup_failed`` / ``reset_path_escape``。
    """
    target = data_dir / name
    _assert_safe_fixed_root(data_dir, target, name)
    if not target.exists():
        if recreate_empty:
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise KnowledgeResetError(
                    "reset_file_cleanup_failed",
                    f"创建 {name}/ 失败：{exc.__class__.__name__}",
                ) from exc
            _assert_safe_fixed_root(data_dir, target, name)
        return []

    try:
        cleared = (
            _list_knowledge_dir_entries(target)
            if name == KNOWLEDGE_DIR_NAME
            else sorted(child.name for child in target.iterdir())
        )
    except OSError as exc:
        raise KnowledgeResetError(
            "reset_file_cleanup_failed",
            f"列举 {name}/ 失败：{exc.__class__.__name__}",
        ) from exc

    # 再次校验后再删除（helper 自带边界检查，不依赖调用方预检）。
    _assert_safe_fixed_root(data_dir, target, name)
    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise KnowledgeResetError(
            "reset_file_cleanup_failed",
            f"清理 {name}/ 失败：{exc.__class__.__name__}",
        ) from exc

    if recreate_empty:
        try:
            target.mkdir(parents=True, exist_ok=True)
            _assert_safe_fixed_root(data_dir, target, name)
            if any(target.iterdir()):
                raise KnowledgeResetError(
                    "reset_file_cleanup_failed",
                    f"{name}/ 重建后仍非空",
                )
        except KnowledgeResetError:
            raise
        except OSError as exc:
            raise KnowledgeResetError(
                "reset_file_cleanup_failed",
                f"重建 {name}/ 失败：{exc.__class__.__name__}",
            ) from exc
    return cleared


def _clear_knowledge_files(data_dir: Path) -> list[str]:
    """清理 ``knowledge/`` 与旧 ``.knowledge-reset/``，返回 knowledge 根下曾存在的条目名。"""
    cleared_entries = _clear_fixed_directory(
        data_dir, KNOWLEDGE_DIR_NAME, recreate_empty=True
    )
    # 旧长期 reset 残留：只按固定直接子路径识别，不扫描相似前缀。
    _clear_fixed_directory(data_dir, LEGACY_RESET_DIR_NAME, recreate_empty=False)
    return cleared_entries


def _verify_preservation(
    session_factory: sessionmaker[Session],
    data_dir: Path,
    pre: _PreSnapshot,
    *,
    expect_completion_mark: bool,
) -> tuple[dict[str, int], bool, int]:
    """重取非 Knowledge 计数与 AI 配置，断言与 reset 前一致。"""
    preserved: dict[str, int] = {}
    migrations = 0
    migration_versions: set[str] = set()
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        for table in NON_KNOWLEDGE_GUARD_TABLES:
            if table in existing:
                preserved[table] = _count_rows(conn, table)
        if "schema_migrations" in existing:
            migration_versions = {
                str(row[0])
                for row in conn.execute(
                    text("SELECT version FROM schema_migrations")
                ).fetchall()
            }
            migrations = len(migration_versions)

    for table, before_count in pre.non_knowledge.items():
        if preserved.get(table) != before_count:
            raise KnowledgeResetError(
                "non_knowledge_violation",
                f"非 Knowledge 表 {table} 行数变化：{before_count} -> {preserved.get(table)}",
            )

    expected_versions = set(pre.migration_versions)
    if expect_completion_mark:
        expected_versions.add(COMPLETION_MIGRATION_VERSION)
    if migration_versions != expected_versions:
        raise KnowledgeResetError(
            "migration_violation",
            "schema_migrations 记录与预期不一致",
        )

    ai_config_now = _capture_ai_config(data_dir)
    ai_config_unchanged = (
        pre.ai_config_exists == (ai_config_now != "")
        and pre.ai_config_payload == ai_config_now
    )
    if not ai_config_unchanged:
        raise KnowledgeResetError(
            "ai_config_violation",
            "AI 配置在 reset 过程中发生变化",
        )
    return preserved, ai_config_unchanged, migrations


def _clear_knowledge_tables(
    session_factory: sessionmaker[Session],
) -> tuple[int, list[str]]:
    """在单个 SQLite 事务中清空 Knowledge 表闭集。

    任何删除或 commit 失败都整体回滚；表不存在视为已空。
    """
    deleted_source_rows = 0
    cleared_tables: list[str] = []
    with session_factory() as session:
        conn = session.connection()
        existing_tables = _existing_tables(conn)
        if "knowledge_sources" in existing_tables:
            deleted_source_rows = _count_rows(conn, "knowledge_sources")
        for table_name in KNOWLEDGE_RESET_TABLES:
            if table_name in existing_tables:
                _delete_from_table(conn, table_name)
                cleared_tables.append(table_name)
        session.commit()
    return deleted_source_rows, cleared_tables


def _assert_knowledge_domain_empty(
    session_factory: sessionmaker[Session],
    data_dir: Path,
) -> None:
    if not _knowledge_tables_empty(session_factory):
        raise KnowledgeResetError(
            "reset_verification_failed",
            "Knowledge 表清空后验证仍非空，拒绝写入完成标记",
        )
    if not _knowledge_files_empty(data_dir):
        raise KnowledgeResetError(
            "reset_verification_failed",
            "Knowledge 文件清空后验证仍非空，拒绝写入完成标记",
        )


def reset_knowledge_domain(
    session_factory: sessionmaker[Session],
    data_dir: Path,
    *,
    runtime_mode: RuntimeMode,
    confirm: bool,
) -> KnowledgeResetSummary:
    """执行一次性离线 Knowledge 数据域清空。

    覆盖范围：``KNOWLEDGE_RESET_TABLES`` + 固定路径 ``knowledge/`` 与 ``.knowledge-reset/``。
    保留：数据库 Schema、既有 ``schema_migrations``、AI 配置与全部非 Knowledge 表。

    安全门禁：

    - ``runtime_mode != "local"`` → ``reset_not_allowed_in_runtime``
    - ``confirm`` 非真 → ``reset_requires_confirm``
    - 完成标记已存在 → ``reset_already_completed``（禁止 DELETE / 文件操作 / force）
    - 固定路径为 symlink / 非目录 / 越界 → ``reset_path_escape``

    调用方（CLI）应先调用 ``assert_reset_preconditions``，避免在门禁失败路径触发
    ``session_factory_for_data_dir`` 的启动恢复副作用。本函数仍做防御性二次检查。
    """
    # 防御性门禁（CLI 已在打开 session factory 前检查；测试可直接调用本函数）。
    if runtime_mode != "local":
        raise KnowledgeResetError(
            "reset_not_allowed_in_runtime",
            f"runtime_mode={runtime_mode!r} 非本地模式，拒绝执行破坏性 Knowledge reset",
        )
    if not confirm:
        raise KnowledgeResetError(
            "reset_requires_confirm",
            "破坏性 reset 需要显式确认（confirm=True）",
        )

    if _completion_mark_exists(session_factory):
        raise KnowledgeResetError(
            "reset_already_completed",
            "KBR-07 一次性 Knowledge reset 已完成，拒绝再次清空",
        )

    pre = _capture_pre_snapshot(session_factory)
    pre.ai_config_exists = (data_dir / AI_CONFIG_FILENAME).exists()
    pre.ai_config_payload = _capture_ai_config(data_dir)
    if pre.ai_config_exists:
        # 仅校验可解析，不改写配置文件。
        load_config(data_dir)

    # 路径预检必须在 DB 清表之前：非法根路径 fail closed，且不得留下 DB 已空的半状态。
    _precheck_cleanup_roots(data_dir)

    # DB 先于文件。事务失败整体回滚且不开始文件清理。
    deleted_source_rows, cleared_tables = _clear_knowledge_tables(session_factory)

    # 文件清理失败：不恢复旧 Knowledge、不写完成标记；重新执行继续收敛。
    cleared_dir_entries = _clear_knowledge_files(data_dir)

    _assert_knowledge_domain_empty(session_factory, data_dir)

    # 完成标记写入前先验证保护项（此时尚无完成标记）。
    preserved, ai_config_unchanged, migrations = _verify_preservation(
        session_factory,
        data_dir,
        pre,
        expect_completion_mark=False,
    )

    # 写标记前最后一次空状态检查，压缩验证→标记窗口。
    _assert_knowledge_domain_empty(session_factory, data_dir)
    _write_completion_mark(session_factory)

    # 写标记后立即复验：若并发写入导致非空，撤销标记并失败。
    try:
        _assert_knowledge_domain_empty(session_factory, data_dir)
        preserved, ai_config_unchanged, migrations = _verify_preservation(
            session_factory,
            data_dir,
            pre,
            expect_completion_mark=True,
        )
        if not _completion_mark_exists(session_factory):
            raise KnowledgeResetError(
                "reset_verification_failed",
                "完成标记写入后验证失败",
            )
    except KnowledgeResetError:
        _remove_completion_mark(session_factory)
        raise

    return KnowledgeResetSummary(
        deleted_source_rows=deleted_source_rows,
        cleared_tables=cleared_tables,
        cleared_dir_entries=cleared_dir_entries,
        preserved_non_knowledge=preserved,
        preserved_ai_config=ai_config_unchanged,
        preserved_migrations=migrations,
        completion_marked=True,
    )
