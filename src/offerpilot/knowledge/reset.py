"""KBR-07：Knowledge 数据域破坏性 reset 边界服务。

Spec Implementation Decisions：

- "Knowledge 重置覆盖 Source、Origin、Asset、Snapshot、Evidence、FTS、Brief、Attempt、
   Knowledge Job、处理日志及 Knowledge 文件目录。保留 Schema、迁移记录、AI Provider/应用
   配置和所有非 Knowledge 业务数据。"
- "Evidence 规则变化视为 Extraction 版本变化……本次因尚未上线，采用限定在 Knowledge 数据域内的
   破坏性清空，不实现旧 Snapshot 迁移。"
- "执行删除前仍应使用 Knowledge 专用 reset 边界，禁止手工扩大到整个应用数据库或数据目录。"

红线
~~~~

- 只 DELETE 数据，绝不 DROP 表（保留 Schema）。
- 表清单 ``KNOWLEDGE_RESET_TABLES`` 是 Knowledge* 闭集的唯一事实源，绝不包含非 Knowledge 表。
- 文件清理只允许触碰 ``$OFFERPILOT_DATA/knowledge/`` 内的目标；符号链接逃逸、绝对路径与目录
  穿越一律拒绝（``reset_path_escape``）。
- 删除顺序遵循 FK 依赖（子表先于父表），不依赖临时禁用外键（SQLite 在事务内无法切换
  ``PRAGMA foreign_keys``）。
- DB 事务原子提交后才清文件，保证不会出现"数据库仍有 Source 记录但原件已被删除"的危险半状态；
  文件清理失败留下的孤儿目录由启动恢复（``_recover_knowledge_runtime``）自愈。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.config import RuntimeMode, load_config

# Knowledge 表族闭集（reset 范围）。删除顺序：先子表（被引用者）后父表。
# 该清单是 reset 边界的唯一事实源；绝不包含非 Knowledge 表。FK 均为 ondelete=CASCADE，
# 但本顺序保证即便未启用 PRAGMA foreign_keys 也能安全删除。
KNOWLEDGE_RESET_TABLES: tuple[str, ...] = (
    # 虚拟表 / 无 FK 的独立表先删。
    "knowledge_evidence_fts",
    "knowledge_retrieval_traces",
    "knowledge_logs",
    # jobs 引用 sources + attempts，先于 attempts 删。
    "knowledge_jobs",
    # briefs 引用 sources + snapshots。
    "knowledge_source_briefs",
    # attempts 引用 sources + snapshots；jobs 已删，无引用者。
    "knowledge_brief_attempts",
    # evidence 引用 sources + snapshots（asset_id 是普通 Integer，非 FK）。
    "knowledge_evidence",
    "knowledge_source_assets",
    # snapshots 是 briefs/attempts/evidence 的父表，三者均已删。
    "knowledge_extraction_snapshots",
    "knowledge_source_origins",
    # 根父表，最后删。
    "knowledge_sources",
)

# 非 Knowledge 代表表：reset 前后统计行数，断言不变（边界安全证据）。
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


class KnowledgeResetError(Exception):
    """破坏性 reset 边界错误。``code`` 供 CLI/API 稳定映射到错误码。"""

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "deleted_source_rows": self.deleted_source_rows,
            "cleared_tables": list(self.cleared_tables),
            "cleared_dir_entries": list(self.cleared_dir_entries),
            "preserved_non_knowledge": dict(self.preserved_non_knowledge),
            "preserved_ai_config": self.preserved_ai_config,
            "preserved_migrations": self.preserved_migrations,
        }


@dataclass
class _PreSnapshot:
    """reset 前的非 Knowledge 数据快照，用于事后断言不变。"""

    non_knowledge: dict[str, int] = field(default_factory=dict)
    ai_config_payload: str = ""
    ai_config_exists: bool = False
    migrations: int = 0


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


def _capture_pre_snapshot(session_factory: sessionmaker[Session]) -> _PreSnapshot:
    snapshot = _PreSnapshot()
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        for table in NON_KNOWLEDGE_GUARD_TABLES:
            if table in existing:
                snapshot.non_knowledge[table] = _count_rows(conn, table)
        if "schema_migrations" in existing:
            snapshot.migrations = _count_rows(conn, "schema_migrations")
    return snapshot


def _capture_ai_config(data_dir: Path) -> str:
    config_path = data_dir / AI_CONFIG_FILENAME
    if not config_path.exists():
        return ""
    return config_path.read_text(encoding="utf-8")


def _verify_preservation(
    session_factory: sessionmaker[Session],
    data_dir: Path,
    pre: _PreSnapshot,
) -> tuple[dict[str, int], bool, int]:
    """重取非 Knowledge 计数与 AI 配置摘要，断言与 reset 前一致。"""
    preserved: dict[str, int] = {}
    migrations = 0
    with session_factory() as session:
        conn = session.connection()
        existing = _existing_tables(conn)
        for table in NON_KNOWLEDGE_GUARD_TABLES:
            if table in existing:
                preserved[table] = _count_rows(conn, table)
        if "schema_migrations" in existing:
            migrations = _count_rows(conn, "schema_migrations")
    # 严格断言：reset 前存在的代表表，reset 后行数必须不变。
    for table, before_count in pre.non_knowledge.items():
        assert preserved.get(table) == before_count, (
            f"非 Knowledge 表 {table} 行数变化：{before_count} -> {preserved.get(table)}"
        )
    ai_config_now = _capture_ai_config(data_dir)
    ai_config_unchanged = (
        pre.ai_config_exists == (ai_config_now != "")
        and pre.ai_config_payload == ai_config_now
    )
    return preserved, ai_config_unchanged, migrations


def _clear_knowledge_file_directory(data_dir: Path) -> list[str]:
    """清空 ``$OFFERPILOT_DATA/knowledge/`` 的全部内容（保留 knowledge 根目录本身）。

    路径安全红线：
    - 解析 knowledge 根目录，拒绝其本身越出 data_dir（例如被替换为符号链接）。
    - 逐个检查子项；符号链接的目标必须解析后仍在 knowledge 根内，否则 ``reset_path_escape``。
      链接本身被 unlink（不跟随），普通目录 rmtree，普通文件 unlink。
    - 不处理绝对路径或 ``..``：``iterdir`` 只返回 knowledge 根下真实条目，恶意穿越只能经由
      符号链接，已由上面的 resolve + relative_to 拦截。
    """
    knowledge_dir = data_dir / "knowledge"
    if not knowledge_dir.exists():
        return []
    data_root = data_dir.resolve()
    # knowledge 根本身必须是受信任的真实目录；若被替换为符号链接指向外部，拒绝清理。
    if knowledge_dir.is_symlink() or not knowledge_dir.is_dir():
        raise KnowledgeResetError(
            "reset_path_escape",
            "knowledge 根目录不是受信任的真实目录，拒绝清理",
        )
    knowledge_root = knowledge_dir.resolve()
    try:
        knowledge_root.relative_to(data_root)
    except ValueError as exc:
        raise KnowledgeResetError(
            "reset_path_escape",
            "knowledge 根目录越出 data_dir，拒绝清理",
        ) from exc

    cleared: list[str] = []
    for child in knowledge_dir.iterdir():
        name = child.name
        # 符号链接：删链接本身，但目标必须落在 knowledge 根内，否则拒绝（防越界删除）。
        if child.is_symlink():
            try:
                target = child.resolve()
                target.relative_to(knowledge_root)
            except (OSError, ValueError) as exc:
                raise KnowledgeResetError(
                    "reset_path_escape",
                    f"knowledge 子项 {name} 是越界符号链接，拒绝清理",
                ) from exc
            child.unlink()
        elif child.is_dir():
            # 不跟随目录内潜在的符号链接——rmtree 对真实子目录是安全的；目录自身的归属已校验。
            shutil.rmtree(child)
        else:
            child.unlink()
        cleared.append(name)
    return cleared


def reset_knowledge_domain(
    session_factory: sessionmaker[Session],
    data_dir: Path,
    *,
    runtime_mode: RuntimeMode,
    confirm: bool,
) -> KnowledgeResetSummary:
    """执行 Knowledge 数据域破坏性 reset。

    覆盖范围：``KNOWLEDGE_RESET_TABLES``（含 FTS 虚拟表）+ ``$OFFERPILOT_DATA/knowledge/``
    文件目录。保留：数据库 Schema（只 DELETE 不 DROP）、``schema_migrations``、AI 配置
    （``config.json``）与所有非 Knowledge 表/文件。

    安全门禁（违反即 ``KnowledgeResetError``）：

    - ``runtime_mode != "local"`` → ``reset_not_allowed_in_runtime``（生产环境保护）。
    - ``confirm`` 非真 → ``reset_requires_confirm``。
    - 文件清理遇越界符号链接 → ``reset_path_escape``。

    原子性：DB 删除在单个事务内提交，中途失败整体回滚；文件清理在 DB 提交后执行，失败留下
    的孤儿目录由启动恢复自愈，不会产生"数据库仍有 Source 指向已删文件"的危险状态。
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

    # AI 配置摘要必须在跨 session 比较前捕获——load_config 仅用于结构校验，不改写文件。
    pre = _capture_pre_snapshot(session_factory)
    pre.ai_config_exists = (data_dir / AI_CONFIG_FILENAME).exists()
    pre.ai_config_payload = _capture_ai_config(data_dir)
    # 顺带校验 config 可解析（保护 AI 配置完整性，不修改）。
    if pre.ai_config_exists:
        load_config(data_dir)

    existing_tables: set[str] = set()
    deleted_source_rows = 0
    cleared_tables: list[str] = []
    with session_factory() as session:
        conn = session.connection()
        existing_tables = _existing_tables(conn)
        if "knowledge_sources" in existing_tables:
            deleted_source_rows = _count_rows(conn, "knowledge_sources")
        # 单事务、按 FK 依赖顺序删除全部 Knowledge 表。事务失败整体回滚，无半重置。
        for table_name in KNOWLEDGE_RESET_TABLES:
            if table_name in existing_tables:
                _delete_from_table(conn, table_name)
                cleared_tables.append(table_name)
        session.commit()

    # DB 提交成功后才清文件；此处的失败只会留下孤儿文件，由启动恢复自愈。
    cleared_dir_entries = _clear_knowledge_file_directory(data_dir)

    preserved, ai_config_unchanged, migrations = _verify_preservation(
        session_factory, data_dir, pre
    )

    return KnowledgeResetSummary(
        deleted_source_rows=deleted_source_rows,
        cleared_tables=cleared_tables,
        cleared_dir_entries=cleared_dir_entries,
        preserved_non_knowledge=preserved,
        preserved_ai_config=ai_config_unchanged,
        preserved_migrations=migrations,
    )
