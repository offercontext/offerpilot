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
- Finding 3 原子性（intent-first）：DB 事务前先原子写 intent manifest，再原子把 ``knowledge/``
  移到 quarantine；DB 提交失败则原子移回并清理 intent；DB 提交成功后重建空 ``knowledge/``，
  再 best-effort 清理 quarantine（失败只记 pending）。两个并列禁止的半重置状态都不出现；
  已持久化 intent 对应的崩溃状态由启动恢复处理。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.config import RuntimeMode, load_config

_LOGGER = logging.getLogger(__name__)

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

# Finding 3 + 二轮 Review P1-B/C：quarantine 放在受控父目录 ``data_dir/.knowledge-reset/`` 下，
# 避免平铺前缀 ``.knowledge-reset-*`` 与用户/他模块同名目录碰撞被启动恢复误删。每个
# quarantine 子目录配一份 manifest 证明归属与代际；无 manifest 的目录一律不触碰。
KNOWLEDGE_RESET_QUARANTINE_DIR = ".knowledge-reset"
KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX = "quarantine-"
KNOWLEDGE_RESET_MANIFEST_SUFFIX = ".manifest"
# manifest 的 stage 标识，校验 manifest 确由 Knowledge reset 写入（非任意同名文件）。
KNOWLEDGE_RESET_MANIFEST_STAGE = "knowledge_reset"


def _quarantine_root(data_dir: Path) -> Path:
    """受控 quarantine 父目录（``data_dir/.knowledge-reset/``）。"""
    return data_dir / KNOWLEDGE_RESET_QUARANTINE_DIR


def _quarantine_manifest_path(child: Path) -> Path:
    """quarantine 子目录的同级 manifest 路径（``<child>.manifest``）。"""
    return child.parent / f"{child.name}{KNOWLEDGE_RESET_MANIFEST_SUFFIX}"


def _new_quarantine_child(data_dir: Path) -> tuple[Path, str]:
    """生成唯一的 quarantine 子目录路径 + generation（时间戳 + pid 防并发碰撞）。

    子目录 ``data_dir/.knowledge-reset/quarantine-<ts>-<pid>/`` 与 ``knowledge/`` 同在
    data_dir 下 → 同文件系统 → ``os.replace`` 原子 rename 成立。
    """
    generation = f"{int(time.time())}-{os.getpid()}"
    child = (
        _quarantine_root(data_dir)
        / f"{KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX}{generation}"
    )
    return child, generation


def _is_regular_file(path: Path) -> bool:
    """普通文件（非 symlink）。``is_file()`` 会跟随链接，故必须先排除 symlink。"""
    return path.exists() and not path.is_symlink() and path.is_file()


def _is_real_dir(path: Path) -> bool:
    """真实目录（非 symlink）。``is_dir()`` 会跟随链接，故必须先排除 symlink。"""
    return path.exists() and not path.is_symlink() and path.is_dir()


def _path_contained(path: Path, root: Path) -> bool:
    """``path`` resolve 后严格位于 ``root`` resolve 内（含 root 自身）。"""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _expected_generation_from_child(child: Path) -> Optional[str]:
    """从 quarantine child 名称提取 generation；命名不匹配时返回 None。"""
    prefix = KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX
    if not child.name.startswith(prefix):
        return None
    generation = child.name[len(prefix) :]
    return generation or None


def _write_quarantine_manifest(child: Path, generation: str) -> None:
    """原子写 intent/quarantine manifest（JSON）：同目录临时文件 + flush/fsync + os.replace。

    必须在 rename ``knowledge/`` 之前调用，使启动恢复在崩溃后仍能识别该 generation。
    写入失败不得留下有效或半写目标 manifest。
    """
    manifest = _quarantine_manifest_path(child)
    payload = json.dumps(
        {
            "generation": generation,
            "pid": os.getpid(),
            "created_at": int(time.time()),
            "stage": KNOWLEDGE_RESET_MANIFEST_STAGE,
        },
        ensure_ascii=False,
    )
    # 临时文件放在同目录，保证 os.replace 同文件系统原子。
    tmp = manifest.with_name(f"{manifest.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, manifest)
    except Exception:
        # 清理半写临时文件；目标 manifest 若尚未 replace 则保持不存在。
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        raise


def _read_quarantine_manifest(
    manifest: Path, *, expected_generation: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """读并校验 quarantine manifest。

    结构非法 / stage 不符 / generation 与 child 名不匹配 → None（视作非 reset 创建）。
    manifest 必须是普通文件，不能是 symlink。
    """
    if not _is_regular_file(manifest):
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    generation = data.get("generation")
    stage = data.get("stage")
    if not isinstance(generation, str) or not generation:
        return None
    if stage != KNOWLEDGE_RESET_MANIFEST_STAGE:
        return None
    # generation 必须与 quarantine child 名称严格匹配，不能只校验 stage。
    if expected_generation is not None and generation != expected_generation:
        return None
    return data


def _remove_quarantine_manifest(child: Path) -> None:
    """删除 quarantine manifest（best-effort，不存在/失败静默）。

    仅 unlink 同级普通文件；symlink / 越界路径一律不碰。
    """
    manifest = _quarantine_manifest_path(child)
    try:
        if manifest.is_symlink():
            return
        if not manifest.is_file():
            return
        # 必须仍位于 child 的父目录内。
        if not _path_contained(manifest, child.parent):
            return
        manifest.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _assert_safe_quarantine_root(data_dir: Path, quarantine_root: Path) -> None:
    """quarantine root 必须是 data_dir 内的真实目录，不能是 symlink 或越界路径。"""
    if not _is_real_dir(quarantine_root):
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 根目录不是受信任的真实目录，拒绝操作",
        )
    if not _path_contained(quarantine_root, data_dir):
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 根目录越出 data_dir，拒绝操作",
        )


def _assert_safe_quarantine_child(data_dir: Path, child: Path) -> None:
    """quarantine child 必须是受控 root 下的真实直接子目录，不能是 symlink 或越界。"""
    quarantine_root = _quarantine_root(data_dir)
    _assert_safe_quarantine_root(data_dir, quarantine_root)
    if child.parent != quarantine_root:
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 子目录不是受控根的直接子项，拒绝操作",
        )
    if not _is_real_dir(child):
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 子目录不是受信任的真实目录，拒绝操作",
        )
    if not _path_contained(child, quarantine_root):
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 子目录越出受控根，拒绝操作",
        )
    expected = _expected_generation_from_child(child)
    if expected is None:
        raise KnowledgeResetError(
            "reset_path_escape",
            "quarantine 子目录命名非法，拒绝操作",
        )


def _maybe_remove_empty_quarantine_root(data_dir: Path, parent: Path) -> None:
    """best-effort 删除空的 quarantine root；失败静默。"""
    try:
        if (
            _is_real_dir(parent)
            and parent == _quarantine_root(data_dir)
            and _path_contained(parent, data_dir)
            and not any(parent.iterdir())
        ):
            parent.rmdir()
    except OSError:
        pass


def _best_effort_cleanup_quarantine(child: Path, data_dir: Path) -> None:
    """quarantine 子目录 + manifest + 空父目录的 best-effort 清理。

    helper 自身执行边界校验，且必须以调用方提供的权威 ``data_dir`` 为准：
    非真实目录、symlink、越出 ``data_dir`` 受控 root 时不 rmtree / 不 unlink。
    特殊情况：child 已被原子移回 ``knowledge/``（路径不存在）时，仍在受控布局下清理 intent
    manifest，避免恢复后留下误导性残留。
    清理失败只留待启动恢复扫除（记 warning），不让运行时进入失败半状态；不打印本机路径。
    """
    parent = child.parent
    expected_root = _quarantine_root(data_dir)
    if parent != expected_root:
        _LOGGER.warning(
            "Knowledge reset quarantine 路径校验失败，跳过清理"
        )
        return

    # child 已不存在：通常是恢复路径刚把 quarantine 原子移回 knowledge/。
    # 此时仍需清理 intent manifest，但绝不对外部路径做 unlink。
    if not child.exists():
        expected = _expected_generation_from_child(child)
        if expected is None:
            return
        try:
            _assert_safe_quarantine_root(data_dir, parent)
        except KnowledgeResetError:
            _LOGGER.warning(
                "Knowledge reset quarantine 路径校验失败，跳过清理"
            )
            return
        _remove_quarantine_manifest(child)
        _maybe_remove_empty_quarantine_root(data_dir, parent)
        return

    try:
        _assert_safe_quarantine_child(data_dir, child)
    except KnowledgeResetError:
        _LOGGER.warning(
            "Knowledge reset quarantine 路径校验失败，跳过清理"
        )
        return

    try:
        # 再次确认仍是真实目录（TOCTOU 最小防护），绝不跟随 symlink。
        if _is_real_dir(child) and _path_contained(child, parent):
            shutil.rmtree(child)
    except OSError:
        _LOGGER.warning(
            "Knowledge reset quarantine 物理清理失败，留待启动恢复扫除"
        )
        return
    _remove_quarantine_manifest(child)
    _maybe_remove_empty_quarantine_root(data_dir, parent)


def _best_effort_cleanup_orphan_intent(data_dir: Path) -> None:
    """清理「intent 已写、rename 前崩溃」留下的孤儿 manifest（无对应 child 目录）。

    只删除受控 root 下、generation 合法且匹配、普通文件形式的 intent；绝不跟随 symlink。
    """
    quarantine_root = _quarantine_root(data_dir)
    if not quarantine_root.exists():
        return
    try:
        _assert_safe_quarantine_root(data_dir, quarantine_root)
    except KnowledgeResetError:
        _LOGGER.warning(
            "Knowledge reset quarantine 根路径校验失败，跳过孤儿 intent 清理"
        )
        return
    for entry in quarantine_root.iterdir():
        if not entry.name.endswith(KNOWLEDGE_RESET_MANIFEST_SUFFIX):
            continue
        if entry.is_symlink() or not entry.is_file():
            continue
        # ``quarantine-<gen>.manifest`` → child 名 ``quarantine-<gen>``。
        child_name = entry.name[: -len(KNOWLEDGE_RESET_MANIFEST_SUFFIX)]
        if not child_name.startswith(KNOWLEDGE_RESET_QUARANTINE_CHILD_PREFIX):
            continue
        expected = _expected_generation_from_child(Path(child_name))
        if expected is None:
            continue
        child = quarantine_root / child_name
        if child.exists() or child.is_symlink():
            # 对应 child 仍在，由正常 recovery/cleanup 路径处理。
            continue
        if _read_quarantine_manifest(entry, expected_generation=expected) is None:
            continue
        _remove_quarantine_manifest(child)
    _maybe_remove_empty_quarantine_root(data_dir, quarantine_root)


def _assert_safe_knowledge_dir(data_dir: Path, knowledge_dir: Path) -> None:
    """移动前校验 ``knowledge/`` 是受信任的真实目录、未越出 data_dir，且根级子项无越界符号链接。

    根级越界符号链接（target 越出 knowledge 根）按 Spec KBR-07 拒绝（``reset_path_escape``）。
    嵌套在真实子目录内的符号链接不由本检查处理：atomic move 后 ``shutil.rmtree(quarantine)``
    对符号链接条目仅 unlink 链接本身、不跟随，外部目标不会被删除（实现细节 → 契约，见测试）。
    """
    if knowledge_dir.is_symlink() or not knowledge_dir.is_dir():
        raise KnowledgeResetError(
            "reset_path_escape",
            "knowledge 根目录不是受信任的真实目录，拒绝清理",
        )
    data_root = data_dir.resolve()
    knowledge_root = knowledge_dir.resolve()
    try:
        knowledge_root.relative_to(data_root)
    except ValueError as exc:
        raise KnowledgeResetError(
            "reset_path_escape",
            "knowledge 根目录越出 data_dir，拒绝清理",
        ) from exc
    for child in knowledge_dir.iterdir():
        if child.is_symlink():
            try:
                child.resolve().relative_to(knowledge_root)
            except (OSError, ValueError) as exc:
                raise KnowledgeResetError(
                    "reset_path_escape",
                    f"knowledge 子项 {child.name} 是越界符号链接，拒绝清理",
                ) from exc


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
    # 严格守卫：reset 前存在的代表表，reset 后行数必须不变。破坏性操作不用 assert
    # （``python -O`` 会剥离致守卫静默失效），任一不一致即显式抛错，稳定映射到错误码。
    for table, before_count in pre.non_knowledge.items():
        if preserved.get(table) != before_count:
            raise KnowledgeResetError(
                "non_knowledge_violation",
                f"非 Knowledge 表 {table} 行数变化：{before_count} -> {preserved.get(table)}",
            )
    ai_config_now = _capture_ai_config(data_dir)
    ai_config_unchanged = (
        pre.ai_config_exists == (ai_config_now != "")
        and pre.ai_config_payload == ai_config_now
    )
    return preserved, ai_config_unchanged, migrations


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

    崩溃恢复协议（intent-first）：

    1. DB 事务前：原子写 intent manifest（同目录 tmp + fsync + replace），再原子移动
       ``knowledge/`` 到 quarantine child。
    2. DB 提交失败：原子移回 ``knowledge/``，并清理对应 intent manifest。
    3. DB 提交成功：重建空 ``knowledge/``，best-effort 清理 quarantine（失败只记 pending）。
    4. 启动恢复负责处理已持久化 intent 对应的崩溃状态（rename 后、commit 前崩溃等）。

    运行时尽力消除「DB 有记录 + 文件缺失」与「DB 空 + knowledge/ 内残留」两种半重置状态；
    若 DB 回滚移回失败等极端路径仍残留，由启动恢复按 intent 继续处理。
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

    knowledge_dir = data_dir / "knowledge"
    # intent-first：先原子写 intent manifest，再原子 rename knowledge/。
    # 任一步失败都必须保持 knowledge/ 与 DB 原样，并清理误导恢复的 intent。
    cleared_dir_entries: list[str] = []
    quarantine_child: Optional[Path] = None
    intent_written = False
    if knowledge_dir.exists():
        _assert_safe_knowledge_dir(data_dir, knowledge_dir)
        cleared_dir_entries = sorted(child.name for child in knowledge_dir.iterdir())
        quarantine_root = _quarantine_root(data_dir)
        quarantine_root.mkdir(parents=True, exist_ok=True)
        # 新建的 quarantine root 必须是真实目录且 contained。
        _assert_safe_quarantine_root(data_dir, quarantine_root)
        quarantine_child, generation = _new_quarantine_child(data_dir)
        try:
            # 1) 先写 intent：崩溃后启动恢复可识别 generation。
            _write_quarantine_manifest(quarantine_child, generation)
            intent_written = True
            # 2) 再原子 rename knowledge/ → quarantine child。
            os.replace(knowledge_dir, quarantine_child)
        except Exception:
            # rename 失败或 write 后任何异常：knowledge/ 保持原位，清理 intent。
            if intent_written:
                _remove_quarantine_manifest(quarantine_child)
            raise

    deleted_source_rows = 0
    cleared_tables: list[str] = []
    try:
        with session_factory() as session:
            conn = session.connection()
            existing_tables = _existing_tables(conn)
            if "knowledge_sources" in existing_tables:
                deleted_source_rows = _count_rows(conn, "knowledge_sources")
            # 单事务、按 FK 依赖顺序删除全部 Knowledge 表。
            for table_name in KNOWLEDGE_RESET_TABLES:
                if table_name in existing_tables:
                    _delete_from_table(conn, table_name)
                    cleared_tables.append(table_name)
            session.commit()
    except Exception:
        # DB 提交失败：把 quarantine 原子移回 knowledge/，并清 intent，消除半状态。
        # 路径不安全或移回失败时不吞原异常；残留由启动恢复按 intent 处理。
        if quarantine_child is not None and not knowledge_dir.exists():
            try:
                _assert_safe_quarantine_child(data_dir, quarantine_child)
                os.replace(quarantine_child, knowledge_dir)
                _remove_quarantine_manifest(quarantine_child)
            except (KnowledgeResetError, OSError):
                _LOGGER.warning(
                    "Knowledge reset DB 失败后回滚文件失败，留待启动恢复"
                )
        raise

    # 逻辑完成：DB 已提交。重建空 knowledge/（子目录由 service 按需创建）。
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # quarantine best-effort 清理（子目录 + manifest + 空父目录）；失败留待启动恢复扫除。
    if quarantine_child is not None:
        _best_effort_cleanup_quarantine(quarantine_child, data_dir)

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
