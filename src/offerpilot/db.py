import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.models import Base

SessionFactory = sessionmaker[Session]


# KI-02 起新表 knowledge_sources/origins/snapshots/evidence/evidence_fts/jobs 由本模块创建并维护，
# 不再视为 legacy；只保留旧自动 Wiki 占位实现的表名作为破坏性重置对象。
KNOWLEDGE_LEGACY_TABLES = (
    "knowledge_bases",
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_chunks_fts",
    "knowledge_wiki_pages",
    "knowledge_wiki_pages_fts",
    "knowledge_page_versions",
    "knowledge_index_entries",
    "knowledge_page_evidence",
    "knowledge_wikilinks",
    "knowledge_reviews",
    "knowledge_review_revisions",
    "knowledge_review_jobs",
    "knowledge_config_versions",
)


def _remove_recovery_path(path: Path) -> None:
    """清理恢复目录中的文件、目录或符号链接，不跟随链接。"""

    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except OSError:
        pass


def init_database(db_path: Path) -> SessionFactory:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_size=1,
        max_overflow=0,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    _reset_incompatible_v01_tables(engine)
    _ensure_schema_migrations(engine)
    _reset_knowledge_legacy_tables(engine, db_path.parent)
    Base.metadata.create_all(engine)
    # ``attempt_id`` was added after the initial KI-10 schema.  Add it before
    # creating the integrity triggers below so existing databases can use the
    # same association checks as fresh databases.
    if _ensure_column(engine, "knowledge_jobs", "attempt_id", "INTEGER"):
        _record_migration(
            engine,
            "0008_knowledge_job_attempt_id",
            "Add Knowledge Brief Attempt association to jobs",
        )
    _ensure_knowledge_fts(engine)
    _ensure_knowledge_integrity_constraints(engine)
    _recover_knowledge_deletions(engine, db_path.parent)
    # KI-07：补齐 KnowledgeJob 持久队列所需列；旧库升级保证 attempt_token 存在，
    # 否则 lease claim 无法防迟到提交。
    knowledge_job_migrations = [
        _ensure_column(
            engine, "knowledge_jobs", "attempt_token", "TEXT DEFAULT ''"
        ),
    ]
    if any(knowledge_job_migrations):
        _record_migration(
            engine,
            "0006_knowledge_job_attempt_token",
            "Add knowledge_jobs.attempt_token for KI-07 lease correctness",
        )
    # KI-10 / Spec §11.1 / §11.4：Brief Attempt 固定 fallback 候选、记录实际成功
    # Provider，并持久化 Provider 层重试计数与 next retry，保证重启后不从零开始。
    knowledge_brief_attempt_migrations = [
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "fallback_provider_id",
            "TEXT DEFAULT ''",
        ),
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "fallback_provider_model",
            "TEXT DEFAULT ''",
        ),
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "actual_provider_id",
            "TEXT DEFAULT ''",
        ),
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "actual_provider_model",
            "TEXT DEFAULT ''",
        ),
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "provider_retry_count",
            "INTEGER NOT NULL DEFAULT 0",
        ),
        _ensure_column(
            engine,
            "knowledge_brief_attempts",
            "next_retry_at",
            "DATETIME",
        ),
    ]
    if any(knowledge_brief_attempt_migrations):
        _record_migration(
            engine,
            "0007_knowledge_brief_attempt_ki10",
            "Add fallback/actual provider and retry fields for KI-10",
        )
    # KBR-02：frontmatter 白名单 provenance 沿 Source 所有权（author/published_at），
    # metadata extraction version 沿 Snapshot 所有权。加列兼容旧库。
    knowledge_provenance_migrations = [
        _ensure_column(engine, "knowledge_sources", "author", "TEXT DEFAULT ''"),
        _ensure_column(engine, "knowledge_sources", "published_at", "DATETIME"),
        _ensure_column(
            engine,
            "knowledge_extraction_snapshots",
            "metadata_extraction_version",
            "TEXT DEFAULT ''",
        ),
    ]
    if any(knowledge_provenance_migrations):
        _record_migration(
            engine,
            "0009_knowledge_provenance_kbr02",
            "Add Source author/published_at and Snapshot metadata_extraction_version for KBR-02",
        )
    _recover_knowledge_runtime(engine, db_path.parent)
    _record_migration(engine, "0001_base_schema", "Create current application tables")

    chat_migrations = [
        _ensure_column(engine, "conversations", "mode", "TEXT DEFAULT 'general'"),
        _ensure_column(engine, "conversations", "title_source", "TEXT DEFAULT 'manual'"),
        _ensure_column(engine, "conversations", "context_type", "TEXT DEFAULT 'workspace'"),
        _ensure_column(engine, "conversations", "context_ref", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pinned_at", "DATETIME"),
        _ensure_column(engine, "conversations", "archived_at", "DATETIME"),
        _ensure_column(engine, "conversations", "pending_tool_call_id", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_tool_name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_args", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "pending_human", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_tool_call_id", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_tool_name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_args", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_human", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "clarification_question", "TEXT DEFAULT ''"),
        _ensure_column(engine, "conversations", "last_write_undo_json", "TEXT DEFAULT ''"),
        _ensure_column(engine, "chat_messages", "provider_blocks", "TEXT DEFAULT ''"),
    ]
    if any(chat_migrations):
        _record_migration(engine, "0002_chat_state_columns", "Add durable chat state columns")

    resume_migrations = [
        _ensure_column(engine, "resumes", "name", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "file_path", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parsed_data", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "parse_status", "TEXT DEFAULT 'pending'"),
        _ensure_column(engine, "resumes", "title", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "is_master", "INTEGER DEFAULT 0"),
        _ensure_column(engine, "resumes", "parent_resume_id", "INTEGER"),
        _ensure_column(engine, "resumes", "source", "TEXT DEFAULT 'manual'"),
        _ensure_column(engine, "resumes", "source_file_path", "TEXT DEFAULT ''"),
        _ensure_column(engine, "resumes", "content_json", "TEXT DEFAULT '{}'"),
        _ensure_column(engine, "resumes", "deleted_at", "DATETIME"),
    ]
    resume_backfilled = _backfill_resume_v01(engine)
    if any(resume_migrations):
        _record_migration(engine, "0003_resume_content_columns", "Add resume content columns")
        _record_migration(engine, "0004_resume_v01_columns", "Add resume v0.1 columns")
    elif resume_backfilled:
        _record_migration(engine, "0004_resume_v01_columns", "Add resume v0.1 columns")

    application_migrations = [
        _ensure_column(engine, "applications", "first_pending_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_applied_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_written_test_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_interview_at", "DATETIME"),
        _ensure_column(engine, "applications", "first_offer_at", "DATETIME"),
        _ensure_column(engine, "applications", "closed_reason", "TEXT DEFAULT ''"),
        _ensure_column(engine, "applications", "closed_at", "DATETIME"),
        _ensure_column(engine, "applications", "deleted_at", "DATETIME"),
    ]
    application_backfilled = _backfill_application_lifecycle(engine)
    if any(application_migrations) or application_backfilled:
        _record_migration(
            engine,
            "0005_application_lifecycle_columns",
            "Add application lifecycle and soft-delete columns",
        )
    _record_migration(
        engine,
        "0006_application_evidence_bundles",
        "Add immutable application evidence bundles",
    )
    _record_migration(
        engine,
        "0007_material_revision_proposals",
        "Add evidence-gated material revision proposals",
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_knowledge_fts(engine) -> None:  # type: ignore[no-untyped-def]
    """创建 Evidence FTS5 虚拟表并验证 trigram tokenizer 可用。

    FTS5 不可用属于 Spec §13 中 `fts_unavailable` 错误码，必须启动期失败而非静默吞掉。
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_evidence_fts USING fts5(
                        evidence_id UNINDEXED,
                        source_id UNINDEXED,
                        source_title,
                        heading_path,
                        content,
                        tokenize = 'trigram'
                    )
                    """
                )
            )
            probe = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_evidence_fts'"
                )
            ).fetchone()
            if probe is None:
                raise RuntimeError("fts_unavailable: knowledge_evidence_fts virtual table missing")
    except OperationalError as exc:
        message = str(exc).lower()
        if "fts5" in message or "no such module" in message:
            raise RuntimeError(
                "fts_unavailable: SQLite FTS5 / trigram tokenizer not available"
            ) from exc
        raise


def _ensure_knowledge_integrity_constraints(engine) -> None:  # type: ignore[no-untyped-def]
    """补齐模型暂未声明的活动引用与队列一致性约束。

    KnowledgeSource 的 active_* 字段和若干历史引用需要与 Source/Snapshot 保持
    同源；这些约束用 SQLite trigger 实现，不重建现有表，兼容已经存在的数据库。
    活动 Job/Attempt 使用部分唯一索引，防止并发 rebuild 产生两个正式候选。
    """
    with engine.begin() as conn:
        # 早期开发版本曾创建过过严的 active_snapshot trigger；启动时重建为下面的
        # 正确同源约束，既允许合法代际切换，也拒绝指向其他 Source/不存在 Snapshot。
        conn.execute(text("DROP TRIGGER IF EXISTS trg_knowledge_source_snapshot_ref"))
        # 这些触发器在旧数据库中可能已经存在；定义发生变化时必须先删除，
        # 否则 ``CREATE IF NOT EXISTS`` 会静默保留旧版的宽松约束。
        for trigger_name in (
            "trg_knowledge_evidence_neighbor_ref",
            "trg_knowledge_evidence_neighbor_ref_insert",
            "trg_knowledge_job_snapshot_ref",
            "trg_knowledge_job_snapshot_ref_update",
        ):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
        # Brief Job 的唯一性包含 Snapshot。SQLite UNIQUE 对 NULL 不互相约束，不能把
        # Extraction/Delete 与 Brief 共用一个 (source_id, kind, snapshot_id) 索引，
        # 否则同一 Source 会出现多个 snapshot_id=NULL 的 Extract Job。
        conn.execute(text("DROP INDEX IF EXISTS uq_knowledge_active_job_source_kind"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_active_job_source_kind
                ON knowledge_jobs (source_id, kind)
                WHERE source_id IS NOT NULL
                  AND kind IN ('extract', 'delete')
                  AND status IN ('pending', 'running')
                  AND canceled = 0
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_active_brief_source_snapshot
                ON knowledge_jobs (source_id, snapshot_id)
                WHERE source_id IS NOT NULL
                  AND kind = 'brief'
                  AND snapshot_id IS NOT NULL
                  AND status IN ('pending', 'running')
                  AND canceled = 0
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_active_attempt_source
                ON knowledge_brief_attempts (source_id)
                WHERE status IN ('pending', 'processing')
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_attempt "
                "ON knowledge_jobs (attempt_id)"
            )
        )

        trigger_sql = (
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_source_snapshot_ref
            BEFORE UPDATE OF active_snapshot_id ON knowledge_sources
            WHEN NEW.active_snapshot_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.active_snapshot_id AND source_id = NEW.id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_source_active_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_source_brief_ref
            BEFORE UPDATE OF active_brief_id ON knowledge_sources
            WHEN NEW.active_brief_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_source_briefs
                WHERE id = NEW.active_brief_id AND source_id = NEW.id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_source_active_brief_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_evidence_snapshot_ref
            BEFORE INSERT ON knowledge_evidence
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_evidence_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_evidence_asset_ref
            BEFORE INSERT ON knowledge_evidence
            WHEN NEW.asset_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_source_assets
                WHERE id = NEW.asset_id AND source_id = NEW.source_id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_evidence_asset_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_evidence_asset_ref_update
            BEFORE UPDATE OF asset_id, source_id ON knowledge_evidence
            WHEN NEW.asset_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_source_assets
                WHERE id = NEW.asset_id AND source_id = NEW.source_id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_evidence_asset_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_evidence_neighbor_ref
            BEFORE UPDATE OF previous_evidence_id, next_evidence_id ON knowledge_evidence
            WHEN (
                NEW.previous_evidence_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM knowledge_evidence
                    WHERE id = NEW.previous_evidence_id
                      AND source_id = NEW.source_id
                      AND snapshot_id = NEW.snapshot_id
                )
            ) OR (
                NEW.next_evidence_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM knowledge_evidence
                    WHERE id = NEW.next_evidence_id
                      AND source_id = NEW.source_id
                      AND snapshot_id = NEW.snapshot_id
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_evidence_neighbor_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_evidence_neighbor_ref_insert
            BEFORE INSERT ON knowledge_evidence
            WHEN (
                NEW.previous_evidence_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM knowledge_evidence
                    WHERE id = NEW.previous_evidence_id
                      AND source_id = NEW.source_id
                      AND snapshot_id = NEW.snapshot_id
                )
            ) OR (
                NEW.next_evidence_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM knowledge_evidence
                    WHERE id = NEW.next_evidence_id
                      AND source_id = NEW.source_id
                      AND snapshot_id = NEW.snapshot_id
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_evidence_neighbor_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_job_snapshot_ref
            BEFORE INSERT ON knowledge_jobs
            WHEN NEW.snapshot_id IS NOT NULL
             AND (
                NEW.source_id IS NULL
                OR NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
                )
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_job_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_job_snapshot_ref_update
            BEFORE UPDATE OF snapshot_id, source_id ON knowledge_jobs
            WHEN NEW.snapshot_id IS NOT NULL
             AND (
                NEW.source_id IS NULL
                OR NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
                )
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_job_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_job_attempt_ref
            BEFORE INSERT ON knowledge_jobs
            WHEN NEW.attempt_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_brief_attempts
                WHERE id = NEW.attempt_id
                  AND source_id = NEW.source_id
                  AND snapshot_id = NEW.snapshot_id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_job_attempt_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_job_attempt_ref_update
            BEFORE UPDATE OF attempt_id, source_id, snapshot_id ON knowledge_jobs
            WHEN NEW.attempt_id IS NOT NULL
             AND NOT EXISTS (
                SELECT 1 FROM knowledge_brief_attempts
                WHERE id = NEW.attempt_id
                  AND source_id = NEW.source_id
                  AND snapshot_id = NEW.snapshot_id
             )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_job_attempt_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_snapshot_ref
            BEFORE INSERT ON knowledge_source_briefs
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_snapshot_ref_update
            BEFORE UPDATE OF snapshot_id, source_id ON knowledge_source_briefs
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_attempt_snapshot_ref
            BEFORE INSERT ON knowledge_brief_attempts
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_attempt_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_attempt_snapshot_ref_update
            BEFORE UPDATE OF snapshot_id, source_id ON knowledge_brief_attempts
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_extraction_snapshots
                WHERE id = NEW.snapshot_id AND source_id = NEW.source_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_attempt_snapshot_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_attempt_ref
            BEFORE INSERT ON knowledge_source_briefs
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_brief_attempts
                WHERE id = NEW.winning_attempt_id
                  AND source_id = NEW.source_id
                  AND snapshot_id = NEW.snapshot_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_attempt_mismatch');
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS trg_knowledge_brief_attempt_ref_update
            BEFORE UPDATE OF winning_attempt_id, source_id, snapshot_id
                ON knowledge_source_briefs
            WHEN NOT EXISTS (
                SELECT 1 FROM knowledge_brief_attempts
                WHERE id = NEW.winning_attempt_id
                  AND source_id = NEW.source_id
                  AND snapshot_id = NEW.snapshot_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'knowledge_brief_attempt_mismatch');
            END
            """,
        )
        for sql in trigger_sql:
            conn.execute(text(sql))


def _reset_incompatible_v01_tables(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        application_event_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(application_events)")).fetchall()}
            if "application_events" in tables
            else set()
        )
        question_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(questions)")).fetchall()}
            if "questions" in tables
            else set()
        )
        conversation_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)")).fetchall()}
            if "conversations" in tables
            else set()
        )
        mock_columns = (
            {row[1] for row in conn.execute(text("PRAGMA table_info(mock_sessions)")).fetchall()}
            if "mock_sessions" in tables
            else set()
        )
        reset_application_events = "application_events" in tables and (
            "subtype" not in application_event_columns
            or "tags" not in application_event_columns
            or "duration_minutes" not in application_event_columns
            or "remind_at" not in application_event_columns
        )
        reset_questions = "questions" in tables and (
            "knowledge_base_id" in question_columns or "topic" not in question_columns
        )
        reset_conversations = "conversations" in tables and "offer_id" in conversation_columns
        reset_mock_sessions = "mock_sessions" in tables and "knowledge_base_id" in mock_columns
        drop_tables: list[str] = []
        if "events" in tables:
            drop_tables.append("events")
        if reset_application_events:
            drop_tables.append("application_events")
        if reset_questions:
            drop_tables.extend(["question_reviews", "questions"])
        if reset_conversations:
            drop_tables.extend(["chat_messages", "mock_sessions", "conversations"])
        elif reset_mock_sessions:
            drop_tables.append("mock_sessions")
        if not drop_tables:
            return
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in drop_tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _reset_knowledge_legacy_tables(engine, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            ).fetchall()
        }
        legacy_present = any(table in existing for table in KNOWLEDGE_LEGACY_TABLES)
        already_migrated = conn.execute(
            text("SELECT version FROM schema_migrations WHERE version = 'knowledge_rewrite_reset'")
        ).fetchone() is not None

    knowledge_runtime_dir = data_dir / "knowledge"
    # KI-02 之后 knowledge/ 目录可能含有合法 Source 原件；只在尚未迁移（首次启动）且目录非空时
    # 才视为 legacy，避免清空用户已上传的 Source。
    runtime_legacy_present = (
        (not already_migrated)
        and knowledge_runtime_dir.exists()
        and any(knowledge_runtime_dir.iterdir())
    )

    if not legacy_present and not runtime_legacy_present:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO schema_migrations (version, description) "
                    "VALUES ('knowledge_rewrite_reset', 'Knowledge rewrite base schema applied')"
                )
            )
        return

    if already_migrated and not legacy_present:
        return

    if legacy_present:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for table in KNOWLEDGE_LEGACY_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

    if runtime_legacy_present:
        shutil.rmtree(knowledge_runtime_dir, ignore_errors=True)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations (version, description) "
                "VALUES ('knowledge_rewrite_reset', 'Knowledge rewrite legacy tables dropped')"
            )
        )


def session_factory_for_data_dir(data_dir: Path) -> SessionFactory:
    return init_database(data_dir / "data.db")


def _recover_knowledge_runtime(engine, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    """KI-07：Spec §6 / §12 启动恢复。

    职责：
    1. 清理 ``knowledge/staging/`` 残留目录（任何进程崩溃都可能留下半写入的 staging）。
    2. 清理 ``knowledge/sources/<source_id>/`` 中无 ``knowledge_sources`` 记录的孤儿
       目录（rename 后、commit 前崩溃）。
    3. 保留过期 running Job 的持久重试信息，并将其放回 ``pending``；应用创建
       ``KnowledgeWorkerRuntime`` 后会继续按 lease 规则消费。不能在运行时启动前标记
       ``failed``，否则真正的 Worker 恢复会看不到该 Job。

    必须在 ``_recover_knowledge_deletions`` 之后执行——delete Job 的恢复由后者负责
    （连 Source 行 + 所有 Job 一并清理）。本函数只处理 extract/brief Job。
    KBR-07 一次性 reset 不再参与启动恢复；旧 quarantine/manifest 协议已删除。
    """

    knowledge_dir = data_dir / "knowledge"
    staging_root = knowledge_dir / "staging"
    if staging_root.exists() and staging_root.is_dir() and not staging_root.is_symlink():
        for child in staging_root.iterdir():
            _remove_recovery_path(child)

    sources_root = knowledge_dir / "sources"
    if sources_root.exists() and sources_root.is_dir() and not sources_root.is_symlink():
        with engine.begin() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
            if "knowledge_sources" not in tables:
                return
            existing_ids = {
                int(row[0])
                for row in conn.execute(
                    text("SELECT id FROM knowledge_sources")
                ).fetchall()
            }
        for child in sources_root.iterdir():
            try:
                child_id = int(child.name)
            except ValueError:
                continue
            if child_id not in existing_ids:
                _remove_recovery_path(child)

    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "knowledge_jobs" not in tables:
            return
        # 用 Python 端 now.isoformat() 与写入侧 datetime.now(timezone.utc) 保持时区与
        # 格式一致；CURRENT_TIMESTAMP 在 SQLite 返回无 tz 的 "YYYY-MM-DD HH:MM:SS"，
        # 与带 +00:00 的 ISO 字符串按字节比较时结果不稳定。
        now_iso = datetime.now(timezone.utc).isoformat()
        stale_jobs = conn.execute(
            text(
                """
                SELECT id, kind, source_id, attempt_id, snapshot_id
                FROM knowledge_jobs
                WHERE status = 'running'
                  AND kind != 'delete'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < :now
                """
            ),
            {"now": now_iso},
        ).fetchall()
        if not stale_jobs:
            return
        for job_id, kind, source_id, attempt_id, snapshot_id in stale_jobs:
            conn.execute(
                text(
                    """
                    UPDATE knowledge_jobs
                    SET status = 'pending',
                        stage = 'recovered_pending',
                        error_code = '',
                        error_message = '',
                        lease_expires_at = NULL,
                        lease_owner = '',
                        heartbeat_at = NULL,
                        updated_at = :now
                    WHERE id = :jid
                    """
                ),
                {"jid": job_id, "now": now_iso},
            )
            if kind == "brief":
                # 只终结该 Job 绑定的 Attempt，不能按 Source 批量更新，否则同一
                # Source 的新 Snapshot 候选会被旧 lease 恢复误标失败。
                if attempt_id is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE knowledge_brief_attempts
                            SET status = 'failed',
                                error_code = 'job_lease_expired',
                                error_message = 'Brief Job lease expired during restart recovery',
                                updated_at = :now
                            WHERE id = :attempt_id
                              AND status = 'processing'
                            """
                        ),
                        {"attempt_id": attempt_id, "now": now_iso},
                    )
                elif source_id is not None and snapshot_id is not None:
                    # 旧库没有 attempt_id 时，至少用 Snapshot 约束回退匹配，避免
                    # 误伤同 Source 的其他代际 Attempt。
                    conn.execute(
                        text(
                            """
                            UPDATE knowledge_brief_attempts
                            SET status = 'failed',
                                error_code = 'job_lease_expired',
                                error_message = 'Brief Job lease expired during restart recovery',
                                updated_at = :now
                            WHERE source_id = :sid
                              AND snapshot_id = :snapshot_id
                              AND status = 'processing'
                            """
                        ),
                        {
                            "sid": source_id,
                            "snapshot_id": snapshot_id,
                            "now": now_iso,
                        },
                    )


def _delete_retrieval_traces_for_source(conn, source_id: int) -> None:  # type: ignore[no-untyped-def]
    """按 Trace 的结构化 filters/hits 清理指定 Source 的评估记录。"""
    rows = conn.execute(
        text(
            "SELECT id, filters_json, hits_json "
            "FROM knowledge_retrieval_traces"
        )
    ).fetchall()
    trace_ids: list[int] = []
    for trace_id, filters_json, hits_json in rows:
        try:
            filters = json.loads(filters_json or "{}")
        except (TypeError, json.JSONDecodeError):
            filters = {}
        try:
            hits = json.loads(hits_json or "[]")
        except (TypeError, json.JSONDecodeError):
            hits = []
        source_ids = filters.get("source_ids") if isinstance(filters, dict) else None
        if isinstance(source_ids, list) and any(
            str(value) == str(source_id) for value in source_ids
        ):
            trace_ids.append(int(trace_id))
            continue
        if isinstance(hits, list) and any(
            isinstance(hit, dict)
            and str(hit.get("source_id")) == str(source_id)
            for hit in hits
        ):
            trace_ids.append(int(trace_id))
    for trace_id in trace_ids:
        conn.execute(
            text("DELETE FROM knowledge_retrieval_traces WHERE id = :trace_id"),
            {"trace_id": trace_id},
        )


def _recover_knowledge_deletions(engine, data_dir: Path) -> None:  # type: ignore[no-untyped-def]
    """KI-06：启动恢复完成 Spec §5.4 异常中断的删除流程。

    场景:
    1. ``complete_purge`` 事务已提交 → Source 行不存在,但 quarantine 目录残留(物理
       删除失败或进程崩溃)。本函数物理删除 quarantine 子目录。
    2. ``begin_delete`` 已标记 lifecycle=deleting,但 ``complete_purge`` 未执行(进程
       崩溃)。本函数:
       a. 尝试完成事务清理:删除 FTS / Evidence / Snapshot / Asset / Origin / Job /
          Source 行。
       b. 物理删除 quarantine 目录。
       c. 写入 ``knowledge_logs``(source_deleted, succeeded)。

    Spec §6 / §12：启动恢复负责完成异常中断的删除。任何 quarantine 子目录对应的
    Source 行若不存在 → 物理删除 quarantine。
    """
    knowledge_dir = data_dir / "knowledge"
    quarantine_root = knowledge_dir / "quarantine"
    sources_root = knowledge_dir / "sources"

    # 根目录本身若是符号链接，任何 move/rmtree 都可能越出 data_dir；保留 deleting
    # 状态等待人工修复路径，不触碰外部目标。
    if sources_root.is_symlink() or quarantine_root.is_symlink():
        return
    if (sources_root.exists() and not sources_root.is_dir()) or (
        quarantine_root.exists() and not quarantine_root.is_dir()
    ):
        return

    # 关键点：不能因为 quarantine 根目录不存在就跳过 deleting Source。进程可能
    # 在 begin_delete 提交后、创建根目录前崩溃；此时仍应恢复数据库状态。
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "knowledge_sources" not in tables:
            return
        deleting_sources = [
            int(row[0])
            for row in conn.execute(
                text(
                    "SELECT id FROM knowledge_sources WHERE lifecycle = 'deleting'"
                )
            ).fetchall()
        ]

    for source_id in deleting_sources:
        source_dir = sources_root / str(source_id)
        quarantine_dir = quarantine_root / str(source_id)

        # 删除链接本身而不是跟随链接，避免恢复流程接触 data_dir 外的文件。
        for link in (source_dir, quarantine_dir):
            if link.is_symlink():
                try:
                    link.unlink()
                except OSError:
                    pass

        # 若尚未完成 rename，先尝试把正式目录移入 quarantine。移动失败时保留
        # deleting 行与原件，等待下一次启动重试，绝不先删数据库行。
        if source_dir.exists() and not quarantine_dir.exists():
            try:
                quarantine_root.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_dir), str(quarantine_dir))
            except OSError:
                continue

        try:
            with engine.begin() as conn:
                # active_* 是非 FK 引用，先清空再删除目标行，保持引用完整性。
                conn.execute(
                    text(
                        "UPDATE knowledge_sources SET active_snapshot_id = NULL, "
                        "active_brief_id = NULL WHERE id = :sid"
                    ),
                    {"sid": source_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM knowledge_evidence_fts WHERE source_id = :sid"
                    ),
                    {"sid": source_id},
                )
                conn.execute(
                    text("DELETE FROM knowledge_evidence WHERE source_id = :sid"),
                    {"sid": source_id},
                )
                conn.execute(
                    text(
                        "DELETE FROM knowledge_extraction_snapshots WHERE source_id = :sid"
                    ),
                    {"sid": source_id},
                )
                conn.execute(
                    text("DELETE FROM knowledge_source_assets WHERE source_id = :sid"),
                    {"sid": source_id},
                )
                conn.execute(
                    text("DELETE FROM knowledge_source_origins WHERE source_id = :sid"),
                    {"sid": source_id},
                )
                # KI-09：Spec §5.4 删除时清理 Brief / Attempt；存在性检查避免旧库未建表。
                if "knowledge_source_briefs" in tables:
                    conn.execute(
                        text(
                            "DELETE FROM knowledge_source_briefs WHERE source_id = :sid"
                        ),
                        {"sid": source_id},
                    )
                if "knowledge_brief_attempts" in tables:
                    conn.execute(
                        text(
                            "DELETE FROM knowledge_brief_attempts WHERE source_id = :sid"
                        ),
                        {"sid": source_id},
                    )
                if "knowledge_retrieval_traces" in tables:
                    _delete_retrieval_traces_for_source(conn, source_id)
                conn.execute(
                    text("DELETE FROM knowledge_jobs WHERE source_id = :sid"),
                    {"sid": source_id},
                )
                conn.execute(
                    text("DELETE FROM knowledge_sources WHERE id = :sid"),
                    {"sid": source_id},
                )
                if "knowledge_logs" in tables:
                    conn.execute(
                        text(
                            "INSERT INTO knowledge_logs (source_id, action, result) "
                            "VALUES (:sid, 'source_deleted', 'succeeded')"
                        ),
                        {"sid": source_id},
                    )
        except OperationalError:
            # 事务失败 → 留给下次启动重试，物理目录保持不动。
            continue

        # 数据库提交后再删除物理目录；失败会留下 quarantine/orphan，由下一次
        # 启动继续清理，且不会重新暴露已删除 Source。
        for path in (quarantine_dir, source_dir):
            _remove_recovery_path(path)

    # 处理孤儿 quarantine 目录（Source 行已被事务删除）并保留根目录本身。
    if quarantine_root.exists():
        for child in quarantine_root.iterdir():
            if child.is_dir():
                _remove_recovery_path(child)
            elif child.is_symlink() or child.is_file():
                _remove_recovery_path(child)


def _ensure_schema_migrations(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _record_migration(engine, version: str, description: str) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO schema_migrations (version, description)
                VALUES (:version, :description)
                """
            ),
            {"version": version, "description": description},
        )


def _ensure_column(engine, table: str, column: str, definition: str) -> bool:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if any(row[1] == column for row in rows):
            return False
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        return True


def _backfill_resume_v01(engine) -> bool:  # type: ignore[no-untyped-def]
    changed = False
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "resumes" not in tables:
            return False
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(resumes)")).fetchall()}
        required = {
            "id",
            "name",
            "file_path",
            "parsed_data",
            "title",
            "is_master",
            "source_file_path",
            "content_json",
            "deleted_at",
        }
        if not required.issubset(columns):
            return False

        result = conn.execute(
            text(
                """
                UPDATE resumes
                SET title = name
                WHERE deleted_at IS NULL
                  AND (title IS NULL OR trim(title) = '')
                  AND name IS NOT NULL
                  AND trim(name) != ''
                """
            )
        )
        changed = changed or bool(result.rowcount)

        result = conn.execute(
            text(
                """
                UPDATE resumes
                SET source_file_path = file_path
                WHERE deleted_at IS NULL
                  AND (source_file_path IS NULL OR trim(source_file_path) = '')
                  AND file_path IS NOT NULL
                  AND trim(file_path) != ''
                """
            )
        )
        changed = changed or bool(result.rowcount)

        rows = conn.execute(
            text(
                """
                SELECT id, parsed_data, content_json
                FROM resumes
                WHERE deleted_at IS NULL
                  AND parsed_data IS NOT NULL
                  AND trim(parsed_data) != ''
                """
            )
        ).fetchall()
        for resume_id, parsed_data, content_json in rows:
            if str(content_json or "").strip() not in {"", "{}"}:
                continue
            conn.execute(
                text("UPDATE resumes SET content_json = :content_json WHERE id = :id"),
                {
                    "id": resume_id,
                    "content_json": json.dumps(
                        {"raw_text": parsed_data},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            )
            changed = True

        master_rows = conn.execute(
            text(
                """
                SELECT id
                FROM resumes
                WHERE deleted_at IS NULL
                  AND is_master = 1
                ORDER BY id ASC
                """
            )
        ).fetchall()
        if not master_rows:
            first_active = conn.execute(
                text(
                    """
                    SELECT id
                    FROM resumes
                    WHERE deleted_at IS NULL
                    ORDER BY id ASC
                    LIMIT 1
                    """
                )
            ).fetchone()
            if first_active is not None:
                conn.execute(
                    text("UPDATE resumes SET is_master = 1 WHERE id = :id"),
                    {"id": first_active[0]},
                )
                changed = True
        elif len(master_rows) > 1:
            keep_id = master_rows[0][0]
            result = conn.execute(
                text(
                    """
                    UPDATE resumes
                    SET is_master = 0
                    WHERE deleted_at IS NULL
                      AND is_master = 1
                      AND id != :keep_id
                    """
                ),
                {"keep_id": keep_id},
            )
            changed = changed or bool(result.rowcount)
    return changed


def _backfill_application_lifecycle(engine) -> bool:  # type: ignore[no-untyped-def]
    changed = False
    field_by_status = {
        "pending": "first_pending_at",
        "applied": "first_applied_at",
        "written_test": "first_written_test_at",
        "interview": "first_interview_at",
        "offer": "first_offer_at",
        "closed": "closed_at",
    }
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "applications" not in tables:
            return False
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(applications)")).fetchall()}
        required = {
            "status",
            "applied_at",
            "created_at",
            "updated_at",
            "deleted_at",
            *field_by_status.values(),
        }
        if not required.issubset(columns):
            return False

        for status, field in field_by_status.items():
            result = conn.execute(
                text(
                    f"""
                    UPDATE applications
                    SET {field} = COALESCE(updated_at, applied_at, created_at, CURRENT_TIMESTAMP)
                    WHERE deleted_at IS NULL
                      AND status = :status
                      AND {field} IS NULL
                    """
                ),
                {"status": status},
            )
            changed = changed or bool(result.rowcount)
    return changed
