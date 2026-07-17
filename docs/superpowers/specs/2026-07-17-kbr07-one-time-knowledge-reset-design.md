<!-- 本文冻结 KBR-07 的最终收缩边界：一次性、离线、可重试的数据清理，不是长期 reset 协议。 -->
# KBR-07 一次性 Knowledge Reset 收缩版设计

**Date**: 2026-07-17
**Status**: Approved
**Decider**: 用户
**Revision**: 2，基于当前代码与两轮 Code Review 重新收缩
**Architecture SSOT**: OfferPilot Knowledge 系统：核心方向与架构设计
**Related ADR**: ADR-0007：采用 SQLite 作为 Knowledge 运行时唯一事实源
**Supersedes**: 旧 KBR-07 长期 reset 设计，以及本文 Revision 1 中的在线并发复验、绝对零副作用、精确 HTTP 状态码和多阶段完成标记补偿要求

## Problem Statement

KBR-02 至 KBR-06 已经改变 Knowledge provenance、Evidence policy、Brief Schema v2、citation
coverage 和 repair 契约。旧 Snapshot、Evidence、Brief 和 Job 都是可丢弃的测试期数据，不需要迁移；
切换只需要清空一次旧 Knowledge，再按新契约重新导入 Source。

旧实现把这个一次性动作扩张成了长期产品能力，加入 API、前端入口、quarantine、generation
manifest 和启动恢复。第一次收缩虽然删除了这些产品入口，却仍沿用正常应用数据库初始化，并继续要求
在线并发检测、写后复验、撤销完成标记、拒绝路径绝对零副作用和旧 URL 精确返回 `404`。这些要求互相
影响，导致一个简单离线清理命令不断增加门禁、时间窗口和补偿分支。

根本问题不是 SQLite 与文件系统必须实现共同事务，而是一次性迁移错误复用了带启动恢复副作用的正常
应用初始化入口，并承担了不属于离线工具的在线正确性承诺。用户需要的是一条小而明确的离线路径：
应用和 Worker 停止后，直接清空指定表和固定目录；中断时重新执行；成功后禁止再次清空新数据。

## Solution

保留唯一入口 `oc knowledge reset --confirm`，将其实现为专用离线迁移命令。命令不得调用正常应用的
数据库初始化、Schema repair、staging 恢复、Source 删除恢复或 Job lease 恢复，而是直接连接已经存在的
SQLite 数据库。

命令先验证 local runtime、显式确认和两个固定文件根，再通过专用数据库连接检查一次性完成标记。
未完成时，在一个 SQLite 事务内清空 Knowledge 表闭集；提交后删除 `knowledge/` 与旧
`.knowledge-reset/`，重建空 `knowledge/`，验证目标为空和保护项未变化，最后写入完成标记。

数据库提交后发生任何文件错误都不恢复旧 Knowledge，也不写完成标记。操作者修复环境后重新运行，
命令从当前状态继续向空状态收敛。应用和 Worker 同时运行属于违反前置条件的未支持场景，不再为其设计
锁、写后复验、标记撤销或竞态补偿。

后端不提供 reset API，前端不提供清空入口。只要求 reset 业务路由不存在；不为了某个具体 `404/405`
结果修改全局 API fallback 行为。

## User Stories

1. As a Knowledge 维护者, I want 用一条本地 CLI 清空测试期旧 Knowledge, so that 新旧数据契约不会混用。
2. As a Knowledge 维护者, I want 命令只在 local runtime 且显式确认后执行, so that 破坏性迁移不会被普通操作触发。
3. As a Knowledge 维护者, I want 命令明确要求应用和 Worker 已停止, so that 一次性迁移不承担在线并发协调。
4. As a Knowledge 维护者, I want CLI 使用专用 SQLite 连接而不是应用初始化入口, so that reset 不会先触发 staging、Source 或 Job 恢复。
5. As a Knowledge 维护者, I want Knowledge 表在一个事务内清空, so that 数据库错误不会留下部分表已删除的状态。
6. As a Knowledge 维护者, I want 文件清理失败后可以重新执行, so that 不需要恢复本来就要丢弃的旧 Knowledge。
7. As a Knowledge 维护者, I want 迁移成功后永久拒绝再次清空, so that 新契约下重新导入的数据受到保护。
8. As a Knowledge 维护者, I want 文件操作只触碰两个固定目录, so that data directory 中其他文件和相似名称目录保持不变。
9. As a 其他业务模块用户, I want 非 Knowledge 表、Schema、迁移记录和 AI 配置保持不变, so that Knowledge 切换不扩大边界。
10. As a Knowledge 用户, I want 前端不存在清空入口, so that 一次性运维命令不会成为日常产品功能。
11. As an API 使用者, I want 后端不存在 reset 业务路由, so that 运行中的服务不能触发这次迁移。
12. As a Knowledge 维护者, I want reset 后能重新导入相同 Source 并完成 Brief v2, so that 新契约可以从空状态验收。

## Implementation Decisions

### 最终能力边界

- KBR-07 是一次性离线迁移，不是长期“清空 Knowledge”产品能力。
- 唯一入口是本地 CLI `oc knowledge reset --confirm`。
- 删除 reset HTTP handler、后端 reset API 依赖、前端按钮、确认交互、mutation、service 方法和前端响应类型。
- 删除长期 reset 的 quarantine、generation、manifest、intent、cleanup pending 和 reset 启动恢复。
- 保留正常 Knowledge 的 staging 清理、Source 删除恢复和 Job lease 恢复；它们只服务正常应用启动，CLI 不调用它们。
- 不新增 Agent tool、设置项、环境变量、隐藏 HTTP 入口或兼容 wrapper。

### 离线前置条件

- 操作者必须先停止 OfferPilot 应用和全部 Knowledge Worker，再执行命令。
- CLI 帮助和执行提示必须明确该前置条件。
- CLI 不检测进程、不获取全系统锁，也不修改 ingest、Worker 或 API 来参与锁协议。
- 如果操作者违反离线前置条件，行为不受本 Spec 保证。实现和测试不得继续为并发写入增加复验循环或补偿状态。

### 专用数据库路径

- CLI 不得调用正常应用数据库初始化入口，因为该入口会执行 Schema repair 和 Knowledge 启动恢复。
- CLI 使用专用、最小的 SQLite 连接打开已经存在的 `data.db`。连接只执行本 Spec 声明的查询、DELETE 和完成标记写入。
- 数据库不存在、不是可用 SQLite 数据库、缺少 `schema_migrations` 或无法读取时，命令以非零状态失败，不创建新数据库、不运行迁移、不修复 Schema。
- 数据库路径沿用整个应用已支持的数据目录契约。reset 不单独扩张特殊路径字符或跨平台 URI 能力；实现应使用普通文件路径连接，不自行拼接 SQLite URI。
- 专用连接启用外键，并使用明确事务。不得通过禁用外键绕过删除顺序。

### 简化执行顺序

命令只遵循下面一条线性路径：

1. 解析 data directory 和配置。
2. 检查 `runtime_mode=local` 与 `--confirm`。
3. 检查 `knowledge/` 和 `.knowledge-reset/` 是 data directory 下的固定直接路径；存在时必须是真实目录而非 symlink。
4. 用专用只读数据库连接检查完成标记；标记存在则返回 `reset_already_completed`。
5. 记录非 Knowledge 代表表、既有 migration version 集合和 AI 配置内容。
6. 在一个 SQLite 写事务中按闭集顺序 DELETE Knowledge 表并提交。
7. 删除固定的 `knowledge/` 与 `.knowledge-reset/`，然后创建空 `knowledge/`。
8. 验证 Knowledge 表为空、`knowledge/` 为空、`.knowledge-reset/` 不存在，且保护项与步骤 5 相同。
9. 在独立短事务中插入完成标记并返回成功。

- 不增加写标记后的并发复验、撤销标记、active journal 或状态机。
- 写完成标记前的步骤失败时不写标记。写标记事务自身失败时返回失败；离线重跑会重新验证空状态并再次尝试写标记。
- 该流程不承诺在命令返回成功后的未来时刻继续维持空状态；后续正常 ingest 可以写入新 Knowledge。

### 一次性完成标记

- 完成标记保存在 `schema_migrations`，version 固定为 `kbr07_one_time_knowledge_reset_complete`。
- 标记只表示这次一次性迁移已经完成，不是 reset journal，也不记录中间状态。
- 标记存在时 CLI 拒绝再次执行 Knowledge DELETE 和固定目录清理，不提供 `--force`、override 或删除标记入口。
- 检查标记失败必须以非零状态 fail closed，不能把数据库读取错误解释成“尚未完成”。
- 完成标记不影响正常应用启动、ingest、Extraction、Brief 或检索。

### 数据库清理边界

- Knowledge 表闭集固定为：`knowledge_evidence_fts`、`knowledge_retrieval_traces`、
  `knowledge_logs`、`knowledge_jobs`、`knowledge_source_briefs`、`knowledge_brief_attempts`、
  `knowledge_evidence`、`knowledge_source_assets`、`knowledge_extraction_snapshots`、
  `knowledge_source_origins`、`knowledge_sources`。
- 只 DELETE 数据，不 DROP 表；子表先于父表。
- 表不存在时视为已空，以支持测试期数据库状态和中断重试。
- 数据库 DELETE 或 commit 失败时事务整体回滚，并且不开始文件清理。
- 保留数据库 Schema、既有 `schema_migrations`、全部非 Knowledge 表和 AI 配置。
- 非 Knowledge 代表数据至少覆盖 Application、Application Event、Conversation、Chat Message、
  Interview Note、Offer、Resume、Question 和 Wakeup。验证只证明本次命令没有修改这些代表数据，
  不构建新的通用数据库审计框架。

### 文件清理边界

- 只允许操作 data directory 的两个固定直接子路径：`knowledge/` 和 `.knowledge-reset/`。
- 不扫描 `.knowledge-reset-*`、相似前缀、时间戳目录或 manifest。
- 固定路径不存在时视为空；存在但为 symlink 或非目录时，在打开会触发任何应用恢复的入口之前失败。
- 清理 helper 在实际删除前再次校验固定路径，不依赖单次预检。
- 嵌套 symlink 只删除链接本身，不跟随外部目标。
- 文件 I/O 失败返回稳定 `reset_file_cleanup_failed`；已经提交的 Knowledge DB 清空不回滚，完成标记不写入。
- 文件成功清理后创建空的真实 `knowledge/` 目录。

### API 与前端移除

- 后端路由表中不得存在 Knowledge reset handler。
- 前端不得显示清空按钮、确认对话框或调用 reset service。
- 不要求旧 reset URL 精确返回 `404`。`404`、`405` 或 SPA fallback 由现有全局路由策略决定；只要请求不能执行 reset 即满足本 Spec。
- 不得为了 reset URL 的状态码新增或修改全局 `/api/*` catch-all，这属于无关范围扩张。

### 错误语义

- 非 local：`reset_not_allowed_in_runtime`。
- 缺少确认：`reset_requires_confirm`。
- 已完成：`reset_already_completed`。
- 固定根路径不安全：`reset_path_escape`。
- 数据库不存在、不可读、Schema 不符合预期或事务失败：返回非零和清晰数据库错误；不要求为每个 SQLite 异常发明独立错误码。
- 文件清理失败：`reset_file_cleanup_failed`。
- 保护项或最终空状态验证失败：`reset_verification_failed` 或现有更具体的保护错误。

## Testing Decisions

- 最高且主要的测试 seam 是真实 CLI 集成测试：临时 data directory、真实现有 SQLite Schema、真实文件目录和 CLI runner。测试观察退出状态、数据库、文件系统和输出，不观察私有 helper 调用顺序。
- 主成功测试准备 Knowledge 与非 Knowledge 数据、AI 配置、`knowledge/` 和旧 `.knowledge-reset/`，执行 CLI 后断言 Knowledge 为空、保护项不变且完成标记存在。
- 门禁测试覆盖缺少 `--confirm`、非 local、完成标记已存在；断言命令未执行 Knowledge DELETE 或固定目录清理。
- 路径测试必须通过真实 CLI：把 `knowledge/` 或 `.knowledge-reset/` 根替换为 symlink，并在外部目标的 `staging/`、数字 Source 子目录等恢复可识别位置放置 sentinel，断言 sentinel 完好。不得只直接调用 reset service 绕过 CLI 数据库打开路径。
- 数据库事务失败测试断言全部 Knowledge 表回滚、文件未清理、完成标记不存在。
- 文件失败重试测试允许第一次留下 DB 空、文件部分残留、无完成标记；第二次 CLI 执行应完成清理并写标记。
- 完成标记保护测试在成功后重新导入新 Source，再次运行 CLI 必须拒绝并保留新 Source、Evidence、Brief 和文件。
- reset 后重新导入相同 Source 并生成 Snapshot、Evidence 和 Brief v2，作为正常流程端到端验收。
- API 测试检查应用路由中不存在 reset handler，或请求无法产生 reset 结果；不得锁定全局 fallback 的具体 `404/405/200` 状态。
- 前端测试通过真实渲染确认没有清空入口。源码字符串断言只能作为辅助，不能替代用户可见行为。
- 不测试在线并发、验证与标记之间的纳秒级窗口、主机断电持久化、SQLite URI 特殊字符扩展或写标记后的撤销协议。
- 删除仅覆盖私有 helper 抛错、写后复验、撤销标记和旧 quarantine 状态矩阵的测试。测试数量应随能力收缩，不为保留当前实现结构而保留白盒用例。
- 完成前运行 reset 聚焦测试、后端全量测试、Ruff、mypy、前端全量测试和生产构建。

## Out of Scope

- 长期“清空 Knowledge”产品功能。
- reset HTTP API、前端入口、Agent tool 或设置项。
- 在线 reset、并发写入检测、进程发现、跨进程锁和 Worker 协调。
- SQLite 与文件系统的共同事务、两阶段提交或恢复旧 Knowledge。
- quarantine、generation manifest、active journal、cleanup pending 和 reset 启动恢复。
- 写完成标记后的持续复验、标记撤销和竞态补偿。
- 断电后恢复到 reset 前状态、目录 `fsync` 和平台 durability 矩阵。
- 为 reset 单独扩张整个应用的数据目录路径兼容范围。
- 旧 reset URL 的精确 HTTP 状态码和全局 API fallback 改造。
- 自动备份、旧 Knowledge 迁移、兼容读取或导出。
- 通用数据库审计框架或非 Knowledge 领域改动。
- 创建 ticket、发布 issue 或更新项目 issue tracker。

## Further Notes

- 当前代码中最应删除的复杂性不是某个 helper，而是 CLI 对正常 `session_factory_for_data_dir` 的依赖。
  只要该依赖存在，reset 路径校验之前就可能触发正常 Knowledge 启动恢复。
- 当前写标记前后多次 `_assert_knowledge_domain_empty`、`_remove_completion_mark` 及对应 monkeypatch 测试
  来自已经撤销的在线并发承诺，应删除而不是继续调整检查顺序。
- 当前为旧 reset URL 新增的全局 `/api/*` 404 catch-all 超出本任务范围，应回退；reset handler 缺失即满足要求。
- 本设计接受一个明确事实：DB 提交后文件删除失败时，命令已经部分完成。因为旧 Knowledge 本来就要
  删除，正确恢复动作是离线重跑，不是回滚、quarantine 或人工选择代际。
- Claude Code 后续实现应以本文 Revision 2 为唯一 KBR-07 reset 契约。Revision 1 和旧 Spec 中与本文
  冲突的零副作用、并发、写后复验、撤销标记和精确 HTTP 状态码要求均已废止。
