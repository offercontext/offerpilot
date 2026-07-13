# Tickets: Knowledge Imported Source Ingest

将 [Knowledge Imported Source Ingest 破坏性重写设计](docs/superpowers/specs/2026-07-12-knowledge-ingest-rewrite-design.md)
实现为可导入、可检索、可引用、可验证的 Source/Evidence/Brief 垂直闭环。

工作方式：只处理 **frontier**，即所有 blocker 都已完成的 Ticket。每张 Ticket 使用一个全新上下文，
完成代码、测试、真实验收和 commit 后再勾选。不要跨 Ticket 提前实现后续能力。

实施前必须阅读：

- [Knowledge 系统主文档](docs/architecture/knowledge-system.md)
- [Knowledge Ingest 实施 Spec](docs/superpowers/specs/2026-07-12-knowledge-ingest-rewrite-design.md)
- [ADR-0007](docs/architecture/decisions/0007-use-sqlite-as-knowledge-wiki-ssot.md)

通用完成要求：

- 保持每次提交可运行、可测试，不回滚工作区中不属于当前 Ticket 的改动。
- 每个行为变化先建立失败测试，再完成最小实现。
- 同一能力涉及数据、领域服务、API、前端和测试时，在同一 Ticket 内闭环。
- 不恢复旧 Page、Review、Index、Wikilink、Purpose/Schema 或旧 Knowledge Document 兼容层。
- 不引入 Note、Captured Source、Pilot Tool、练习、向量检索、OCR 或未在 Spec 中确认的能力。
- 完成前运行与改动面匹配的测试；最终 Ticket 运行完整 gate。
- 非平凡实现完成后进行独立子代理 Code Review，并修复发现的问题。

依赖图：

```text
KI-01 → KI-02 ─┬→ KI-03 → KI-04 ─┬→ KI-06 → KI-07 ─┐
               └→ KI-05 ─────────┘                  ├→ KI-09 → KI-10 ─┐
                          KI-03 + KI-06 → KI-08 ─────┘                 ├→ KI-11 → KI-12
                                                        KI-08 ────────┘
```

## KI-01：切换到空的新 Knowledge Source 工作台

**What to build:** 将未发布的旧自动 Wiki 占位实现破坏性切换为空的新 Source Library。用户进入
Knowledge 后只看到稳定的“资料来源”空状态；旧 Page、Review、Index、配置、导出和 AI Tool 均不再
存在，其他业务模块继续正常工作。

**Blocked by:** None — can start immediately.

**Scope boundaries:** 本 Ticket 不实现上传、Extraction、Evidence、搜索或 Brief，只建立可继续纵向
扩展的空壳和破坏性重置边界。

- [x] 启动时识别旧 Knowledge Schema，并静默删除所有旧 Knowledge 表、FTS、运行文件和生成产物。
- [x] 破坏性重置严格限定在 Knowledge 表族和 Knowledge 数据目录，不修改其他业务表或文件。
- [x] 重置可重复执行；新数据库、已重置数据库和带旧占位数据的数据库都能正常启动。
- [x] 新 Source 列表接口存在并在空库返回稳定的空集合契约。
- [x] Knowledge 导航进入新的“资料来源”空状态，不展示不可用按钮或未来 Note 占位入口。
- [x] 旧 Page、Review、Index、Lint、Config、Export 路由全部返回 404。
- [x] 旧 Knowledge Document 路由、CLI 命令和 `add_to_wiki` / `search_wiki` AI Tool 不再注册。
- [x] 前后端不再暴露 Page、slug、Wikilink、Review、Purpose/Schema 等旧产品语言。
- [x] 删除旧实现后，所有非 Knowledge 测试和基础应用 smoke 仍通过。
- [x] 新增迁移测试证明旧 Knowledge 被清除而 Application、Conversation、Interview、Resume、Question
      等数据保持不变。
- [x] 独立 Code Review 确认没有保留隐式兼容分支或误删其他模块。

## KI-02：导入 Markdown 并生成可回读 Evidence

**What to build:** 用户上传一份合法 Markdown 后，系统保存不可变原件，创建持久 Extraction Job，
后台生成 Snapshot、文本 Evidence 和 FTS；用户能在工作台看到分阶段状态、Evidence 和对应原文位置，
并执行一次基础关键词搜索。

**Blocked by:** KI-01：切换到空的新 Knowledge Source 工作台。

**Scope boundaries:** 只完成 Markdown happy path 和必要失败路径；完整编码矩阵、Text/Paste、复杂 AST、
Bundle、归档和 Brief 分别由后续 Ticket 扩展。

- [x] 上传接口只接受当前 Ticket 支持的 Markdown，执行安全文件名、空内容和基础大小检查。
- [x] 新 Source 原件先进入 staging，正式目录 rename 与数据库创建遵守 Spec 的提交顺序。
- [x] 上传新 Source 返回 `202`，包含 Source 摘要和持久 Extraction Job 摘要。
- [x] Source 使用独立 lifecycle、extraction、brief 状态，不引入模糊 `done`。
- [x] 基础 Source hash 能阻止完全相同内容创建第二份有效 Source。
- [x] 后台 Extraction Job 从原件生成带版本和 digest 的 Snapshot。
- [x] Markdown 标题路径和普通段落生成稳定 Evidence；重复执行得到相同 Snapshot digest 和 Evidence ID。
- [x] Evidence 保存结构位置、原文片段、content hash 和相邻 Evidence ID。
- [x] Snapshot、Evidence、FTS 和 `extracted` 状态在同一个 SQLite 事务中提交。
- [x] 事务失败时没有部分 Evidence 或 FTS 可见；首次失败 Source 不参与搜索。
- [x] Source 列表和详情展示 Extraction 与 Brief 的独立状态和最近安全错误。
- [x] Source 详情可查看 Evidence 列表，并从 Evidence 回到规范文本位置。
- [x] 原始 Markdown 可以按原始字节安全下载，不暴露本机绝对路径。
- [x] 基础 Evidence 搜索返回 Evidence、Source、位置、snippet 和 score，而不是旧 Page 结果。
- [x] API、Repository、Worker 和前端测试覆盖成功、空文件、格式错误、事务回滚和幂等重跑。
- [x] 独立 Code Review 重点检查文件系统与 SQLite 的半提交风险。

## KI-03：完成 Text、粘贴正文与结构感知解析

**What to build:** 用户可以上传 Text 或粘贴 Markdown；系统严格处理编码和 64K token 上限，并按
Markdown/Text 自然结构生成稳定 Evidence。列表、表格、引用和代码都能在 UI 中准确定位和回读。

**Blocked by:** KI-02：导入 Markdown 并生成可回读 Evidence。

**Scope boundaries:** 不处理图片附件或 Brief；本 Ticket 完成所有文本 Source 的正式 Extraction
契约，并取代 KI-02 的基础段落解析。

- [x] 支持 `.md`、`.txt` 和粘贴正文；粘贴正文作为虚拟 `main.md` 进入同一 Pipeline。
- [x] 固定产品 tokenizer 和 64,000 token 上限，不随 Provider 切换而变化。
- [x] 主文件 5 MiB 限制与 token 限制同时执行，错误返回实际值和允许值。
- [x] 支持已确认的 UTF 编码和高置信 GBK/GB18030；未知或冲突编码明确拒绝。
- [x] 任何解码路径都不使用字符忽略或替换；Snapshot 记录编码和规范化版本。
- [x] Markdown 使用固定版本 AST 解析器，不再依赖按空行正则切段。
- [x] heading 进入 `heading_path`，不生成孤立标题 Evidence。
- [x] paragraph、list item、blockquote、table row 和 fenced code 按 Spec 生成 Evidence。
- [x] 表格 Evidence 带表头，代码 Evidence 带语言和行范围，嵌套列表保留父路径。
- [x] 超长普通文本按句子边界拆分，超长代码/表格按行拆分，Evidence 之间没有重叠。
- [x] 每条 Evidence 保存字符与行范围，并能从 canonical text 精确回读。
- [x] Evidence ID 由 Snapshot、结构 locator 和内容 hash 确定，不暴露段落序号。
- [x] extractor 升级创建新 Snapshot/Evidence；相同版本重跑幂等，不覆盖旧 Snapshot。
- [x] 原文预览安全处理内嵌 HTML，不执行脚本、不加载远程资源。
- [x] 单元测试覆盖标题、列表、嵌套列表、引用、表格、代码、长段落、控制字符和各种编码。
- [x] 属性或参数化测试证明 Evidence 不越界、不重叠、顺序稳定且可完整回读。
- [x] 独立 Code Review 检查解析器是否把检索 Chunk 策略混入 Evidence 身份。

## KI-04：支持自包含图文 Bundle

**What to build:** 用户上传 Markdown 主文件和本地图片附件后，系统验证 Bundle 完整性并保存不可变
Asset；Evidence 能定位图片引用，用户可安全查看和下载图片，但系统不会 OCR 或猜测图片内容。

**Blocked by:** KI-03：完成 Text、粘贴正文与结构感知解析。

**Scope boundaries:** 图片只作为 Asset Evidence；不调用多模态 Provider，不让图片内容进入 FTS 或
Brief 事实。

- [x] Bundle 上传接受一个 Markdown 主文件和 PNG/JPEG/WebP 附件。
- [x] 强制执行 5 MiB 主文件、10 MiB 单图、50 MiB Bundle、50 图和 40MP 限制。
- [x] 根据实际图片解码和媒体类型验证内容，不能只信扩展名或请求头。
- [x] 图片引用只允许扁平相对路径；远程、绝对、父目录和跨目录路径明确拒绝。
- [x] 缺图、重复逻辑名、未使用附件和不支持媒体类型使整个 Bundle 失败，无部分 Source。
- [x] Source hash 包含主文件字节、附件字节和附件逻辑路径的规范 manifest。
- [x] Asset 保存 bytes、sha256、媒体类型、尺寸和相对路径，不存 SQLite BLOB。
- [x] 每个图片 Asset 生成稳定 Asset Evidence，并记录其全部 Markdown 引用位置。
- [x] Markdown alt text 作为作者原文参与文本 Evidence；模型生成 caption 不存在。
- [x] Source 详情能在 Evidence 上下文中安全预览图片，并按原始字节下载单个附件。
- [x] 浏览器不会执行图片附近的 HTML，也不会请求 Source 中的远程资源。
- [x] 删除或事务失败不会遗留半个 Bundle、孤儿 Asset 行或未引用文件。
- [x] 测试覆盖正常 Bundle、媒体伪装、坏图、像素炸弹、缺图、重复图、未使用图和路径穿越。
- [x] 独立 Code Review 检查路径白名单、图片解码资源限制和数据目录逃逸风险。

## KI-05：实现内容去重、来源记录与标题整理

**What to build:** 重复上传或粘贴同一内容时，用户会进入已有 Source，而不是得到重复 Evidence；
系统保留每次 file/paste/URL 来源记录，用户可以整理展示标题而不改变 Source 身份。

**Blocked by:** KI-02：导入 Markdown 并生成可回读 Evidence。

**Scope boundaries:** 不实现 Collection、标签或多个 Knowledge Base；一个工作区内同一内容只有一个
有效 Source。

- [x] 新建 Source 在数据库层以 `source_hash` 保证唯一，并正确处理并发重复请求。
- [x] 命中正在处理的 Source 时返回已有 Source/Job，不创建第二个 Job。
- [x] 命中 extracted、ready 或 brief failed Source 时返回已有 Source，不自动重跑。
- [x] 重复响应使用 `200` 和 `deduplicated=true`，新建仍使用 `202`。
- [x] 每次导入都追加 Origin，记录 file、paste 或 bundle、原文件名和导入时间。
- [x] 粘贴正文支持可选 HTTP/HTTPS `origin_url`，只保存 provenance，绝不访问网络。
- [x] 同内容来自不同 URL 时复用 Source，但保留多条 Origin。
- [x] 标题推导顺序稳定，并区分 `title_hint` 与用户可编辑 `display_title`。
- [x] 用户修改 `display_title` 不触发 Extraction、Brief 或 Evidence ID 变化。
- [x] 标题修改后列表、详情和搜索展示一致，相关 FTS 展示字段及时更新。
- [x] 重复提示清楚说明“资料已导入”，并提供进入已有 Source 的操作。
- [x] 测试覆盖相同字节不同文件名/标题、不同 URL、并发上传和标题修改。
- [x] 独立 Code Review 确认去重不会重复计权，也不会丢失 provenance。

## KI-06：实现 Source 归档与永久删除

**What to build:** 用户可以把 Source 从日常列表和检索中归档，也可以在危险区永久清除原文及全部
派生数据。归档可恢复，永久删除不可恢复；删除后相同内容能作为新 Source 再次导入。

**Blocked by:** KI-04：支持自包含图文 Bundle；KI-05：实现内容去重、来源记录与标题整理。

**Scope boundaries:** 本轮没有 Note，因此不实现受 Note 引用的冲突 UI；领域服务保留未来
`SourceReferenced` 检查边界，不创建空 Note 表。

- [x] 归档和取消归档只修改 lifecycle，不删除文件、Evidence、Brief 或 Job 历史。
- [x] 默认 Source 列表和普通搜索排除 archived；显式筛选可以查看归档资料。
- [x] 归档 Source 仍可查看详情、Evidence、原文和附件。
- [x] 归档不会自动过期或后台清理。
- [x] 永久删除前端入口位于危险操作区，并要求明确的不可恢复确认。
- [x] 删除请求返回 Delete Job，Source 立即进入 `deleting` 并拒绝新 Job。
- [x] 删除会取消未完成任务，迟到结果无法重新写回 Source。
- [x] Source 目录先移动到 quarantine，再在事务中清理全部数据库关系和 FTS。
- [x] 正常删除完成后，Source、Origin、Asset、Snapshot、Evidence、FTS、Brief/Attempt、Job 和文件均无残留。
- [x] 删除日志只保留 Source ID、时间和结果，不保留标题、正文、URL 或路径。
- [x] 删除不保留 source hash 墓碑；重新上传相同内容创建新 ID 和新 Job。
- [x] 未来 Note 引用保护使用限制删除语义；当前代码不得预设 CASCADE 或 SET NULL。
- [x] 测试覆盖归档过滤、取消归档、处理中删除、Bundle 删除、重复删除和删除后重导入。
- [x] 独立 Code Review 检查隐私清除语义和文件/数据库协调顺序。

## KI-07：加固持久队列、取消与崩溃恢复

**What to build:** 连续上传、删除、应用重启和用户取消都不会制造重复 Job、半提交 Evidence 或孤儿
文件。Extraction 与 Brief 使用独立单并发通道，Source 能尽快达到可搜索状态。

**Blocked by:** KI-06：实现 Source 归档与永久删除。

**Scope boundaries:** Brief 业务逻辑仍由后续 Ticket 实现；本 Ticket 提供 Brief queue 的稳定执行
契约和可测试调度能力。

- [x] Extraction queue 和 Brief queue 各自并发固定为 1，两条队列可以并行。
- [x] Extraction queue 同时承载 Source 永久删除等本地维护 Job，不增加第三个可配置队列。
- [x] 队列按创建时间和 ID FIFO；手动重试进入队尾。
- [x] Job 持久化 kind、queue、stage、status、retry、next retry、cancel 和错误字段。
- [x] Job claim 使用 lease owner、expiry 和 heartbeat，防止两个 worker 同时提交。
- [x] 应用重启后，过期 running Job 能恢复；已提交阶段不会重复执行。
- [x] 迟到的旧 lease 结果因 owner/Attempt 不匹配而拒绝提交。
- [x] pending Job 可立即取消；running 本地任务在安全点停止。
- [x] 已发出的模型调用即使无法中止，其返回也不能在取消后提交。
- [x] Job detail 和 cancel API 返回稳定、用户安全的状态和错误。
- [x] 前端处理记录展示队列、阶段、进度、重试、取消和最近错误。
- [x] 启动恢复清理无数据库记录的 staging/final orphan，并完成或恢复 quarantine 删除。
- [x] Worker 每次读取正式 Source 时核验 manifest/hash，不一致时以稳定错误失败。
- [x] 自动重试计数和 `next_retry_at` 在重启后保持，不从零开始。
- [x] 并发与故障注入测试覆盖重复 claim、进程中断、事务前后崩溃、取消和迟到结果。
- [x] 独立 Code Review 检查幂等性、lease 竞争和无法真正原子化的文件系统边界。

## KI-08：交付可评估的 Evidence FTS 检索

**What to build:** 用户用中文术语、英文技术词、代码标识符或自然问句搜索时，系统返回可直接回读
的 Evidence，而不是 Page 摘要；搜索失败有明确错误，并产生本地可评估 Trace。

**Blocked by:** KI-03：完成 Text、粘贴正文与结构感知解析；KI-06：实现 Source 归档与永久删除。

**Scope boundaries:** 只实现 SQLite FTS5；不添加 embedding、rerank、图扩展或 LLM 查询改写。

- [x] 启动时验证 SQLite FTS5 和 trigram tokenizer；缺失时 Knowledge 明确失败。
- [x] FTS 只索引 active Snapshot 的文本 Evidence，不索引旧 Snapshot 或图片二进制。
- [x] source title、heading path 和 content 使用分列权重，结果仍以 Evidence 为单位。
- [x] Query parser 正确处理中文长问句、ASCII identifier、英文词组和混合输入。
- [x] 不再把无空格中文整句作为一个强制精确短语。
- [x] 少于 3 字符查询使用有上限的精确/子串回退，避免全库无界扫描。
- [x] 默认只搜索 active Source；`include_archived` 和 source filter 行为可测试。
- [x] 结果返回 Evidence 原文、Source、Snapshot、heading、line/char 位置、snippet、score 和相邻 ID。
- [x] 点击搜索结果进入 Source 详情并定位、高亮 Evidence 和原文位置。
- [x] FTS MATCH、bm25 或查询语法错误显式返回稳定错误，不静默变成空结果。
- [x] 每次搜索本地记录 query、filters、命中 ID/score、耗时和可选评估标签。
- [x] Retrieval Trace 不参与 Knowledge 召回，也不写普通应用日志或外部 Trace。
- [x] 测试覆盖中文、英文、代码、短词、无结果、归档、Source filter 和 FTS 故障。
- [x] 建立一组小型确定性查询样本，为 KI-11 的正式指标工具提供接口契约。
- [x] 独立 Code Review 检查查询注入、无界 LIKE 和异常吞噬。

## KI-09：生成并验证首个 Source Brief

**What to build:** 对已提取 Source，配置合格 Provider 后，系统读取完整文本 Evidence，生成中文结构化
导读；程序和独立支持性校验共同阻止伪造 citation、遗漏章节或不受支持内容发布。

**Blocked by:** KI-04：支持自包含图文 Bundle；KI-07：加固持久队列、取消与崩溃恢复。

**Scope boundaries:** 只实现配置正常时的完整成功/质量失败闭环；fallback、网络重试、重建和 Provider
切换由 KI-10 完成。

- [ ] Brief Provider 必须显式声明至少 96K context；未知或不足窗口不会发出请求。
- [ ] Brief Job 在 Evidence 提交后进入独立 Brief queue，不阻塞 Source `extracted`。
- [ ] generation 单次读取完整 Source 文本 Evidence，不分批、不截断、不 map/reduce。
- [ ] 图片只以 assets-only coverage 信息出现，不发送二进制、不生成图片事实。
- [ ] Prompt 把 Source 视为不可信引用数据，不执行其中指令或访问外部上下文。
- [ ] 模型输出固定 JSON Schema，不接受自由 Markdown。
- [ ] Brief 默认中文，技术术语和标识符保留原文；Evidence excerpt 不翻译。
- [ ] overview、key points、section guides、limitations 和 coverage 满足数量与 300 字上限。
- [ ] 程序校验 Schema、枚举、长度、citation 存在/归属和章节 coverage。
- [ ] 每个事实 statement/summary 至少引用当前 Source/Snapshot 的 Evidence。
- [ ] 独立 Validator 逐条返回 supported/partial/unsupported/contradicted。
- [ ] 只有全部 supported 才发布；partial 不能降级为警告。
- [ ] 首次失败允许一次受约束修复，修复后完整重跑全部门禁。
- [ ] 第二次仍失败时 Brief 为 failed，Evidence 继续可搜索，候选不成为当前 Brief。
- [ ] 成功 Brief 与 winning Attempt 在一个事务中提交为当前 Brief。
- [ ] Source 详情默认展示有效 Brief；无 Brief 时自动落到 Evidence。
- [ ] UI 逐条展示 citation，并能跳转到 Evidence 和原文位置。
- [ ] 测试覆盖合法输出、非法 JSON、伪造/跨 Source citation、遗漏章节、四种支持性结果和修复。
- [ ] 独立 Code Review 检查 prompt injection、模型自评冒充校验和未引用事实漏网。

## KI-10：完善 Brief 重建与 Provider 故障语义

**What to build:** 没有 AI 或 Provider 故障时，Source/Evidence 仍正常工作；用户可以安全重建 Brief，
新候选验证失败不会覆盖旧 Brief，重试与 fallback 行为透明且有界。

**Blocked by:** KI-09：生成并验证首个 Source Brief。

**Scope boundaries:** 不引入第二个强制 Validator Provider，不自动批量重建所有 Source。

- [ ] 没有满足条件的 Provider 时 Source 保持 extracted，Brief pending 并显示 provider block reason。
- [ ] 配置 Provider 后不自动批量生成；用户显式操作才创建新 Attempt。
- [ ] Attempt 固定 Provider/Model/参数、context、Prompt/Schema/Snapshot 和 fallback 候选。
- [ ] Attempt 不保存 API Key、完整 Prompt、chain-of-thought 或不可解析原始响应。
- [ ] 网络、超时、限流和 5xx 每个 Provider 最多调用 3 次，并遵守 Retry-After 或 2/10 秒退避。
- [ ] 鉴权、模型不存在、上下文超限、非法 JSON和 validation 失败不走网络重试。
- [ ] 只有基础设施失败切换已配置 fallback；内容质量失败不换 Provider。
- [ ] fallback 必须满足上下文要求，并记录实际成功 Provider。
- [ ] 重建期间旧 Brief 继续可见，并标记“正在重建”。
- [ ] 新候选全部通过后原子替换；失败或取消保留旧 Brief 和最近错误。
- [ ] Provider、Prompt、Schema 或 Snapshot 变化标记 Brief outdated，不自动调用模型。
- [ ] 用户使用当前配置重建会创建新 Attempt 和独立重试预算。
- [ ] 应用重启保留 Attempt 的重试次数、next retry 和候选状态。
- [ ] 处理记录展示实际 Provider、模型、token、耗时、重试和结构化 validation 结果。
- [ ] 日志只记录 ID、版本、时延和错误类别，不打印 Source、Evidence、Brief 或查询正文。
- [ ] 测试覆盖无 AI、小窗口、429/5xx、鉴权失败、fallback、重建失败、取消和旧 Brief 保留。
- [ ] 独立 Code Review 检查数据是否被未经授权发送给 fallback，以及重试是否可能无限循环。

## KI-11：建立真实 Source 与检索质量门禁

**What to build:** 维护者可以用 5 份真实 Source 和至少 20 条人工确认查询，一次性得到 Extraction、
Evidence、Brief 和检索指标报告；任何硬门禁失败都会让验收失败，而不是只打印警告。

**Blocked by:** KI-08：交付可评估的 Evidence FTS 检索；KI-10：完善 Brief 重建与 Provider 故障语义。

**Scope boundaries:** 私有或受版权保护的真实原文不提交仓库；仓库只保存安全 fixtures、fixture hash、
查询和预期 Evidence 标识规则。

- [ ] 建立可从外部 fixture 目录读取真实 Source 的验收入口。
- [ ] 5 份真实 Source 通过内容 hash 标识，缺失或被修改时明确失败。
- [ ] 每份 Source 至少 4 条人工确认查询，总数至少 20 条。
- [ ] 查询集覆盖中文术语、英文技术词、代码标识符和自然语言问题。
- [ ] 另提供可提交仓库的编码、空文件、超限、Markdown 结构和 Bundle 边界 fixtures。
- [ ] 故障 fixtures 覆盖非法 JSON、伪造 citation、引用不支持、章节遗漏、超时、限流和 fallback。
- [ ] 验收报告列出每份 Source 的 Snapshot digest、Evidence 数量、回读结果和 Brief 状态。
- [ ] 相同 extractor 重跑的 Snapshot digest、Evidence ID、位置和内容完全一致。
- [ ] Evidence 回读成功率必须为 100%。
- [ ] Brief Schema、citation、support 和 coverage 通过率必须为 100%。
- [ ] Lexical 查询 `Recall@5 = 100%`、`MRR >= 0.9`。
- [ ] 自然语言查询 `Recall@5 >= 80%`。
- [ ] Provider/Brief 失败场景明确证明 Evidence 仍可搜索。
- [ ] 指标低于门禁时进程非零退出，并输出可定位 bad case 的 Evidence ID。
- [ ] 验收工具不得把真实 Source 正文、API Key、完整 Prompt 或 Provider 原始响应写入报告。
- [ ] 指标未达标时不得在本 Ticket 偷加向量、rerank 或 LLM query rewrite。
- [ ] 使用至少一个真实 Provider 完成 Brief 验收，并记录模型、版本、耗时和费用摘要。
- [ ] 独立 Code Review 检查指标实现、数据泄漏和“通过率被空样本抬高”等评估漏洞。

## KI-12：完成全量回归与旧架构清场

**What to build:** 新 Knowledge Ingest 作为唯一实现通过完整工程与真实浏览器验收；旧自动 Wiki 不再以
代码、Schema、API、UI、测试或文案形式影响运行时，并形成严格的 Go/No-Go 结论。

**Blocked by:** KI-11：建立真实 Source 与检索质量门禁。

**Scope boundaries:** 本 Ticket 只做整合修复、清场和验收，不新增未在 Spec 或前序 Ticket 中定义的
产品能力。

- [ ] 全仓搜索确认旧 Page、Review、Index、Wikilink、Purpose/Schema、Lint 和 Wiki Export 运行代码已删除。
- [ ] 所有旧 Knowledge 路由、AI Tool、CLI、前端入口和测试 fixture 已删除或改为新领域语言。
- [ ] 数据库初始化只创建新 Knowledge 表族和 Evidence FTS，不创建旧表或兼容视图。
- [ ] 旧占位 Knowledge 数据静默重置，新数据目录从零初始化，两种路径均通过 smoke。
- [ ] 完整后端测试通过。
- [ ] Python lint 和类型检查通过。
- [ ] 完整前端测试和生产构建通过。
- [ ] 静态目录 smoke 通过；Docker 可用时运行 Docker smoke，不可用时明确记录未执行。
- [ ] 5 份真实 Source、20 条查询和所有硬指标通过。
- [ ] 使用真实 Provider 完成 Brief generation、validation、repair/failure isolation 验收。
- [ ] 浏览器走查上传、搜索、Brief、Evidence、原文、归档、删除、错误恢复和重启恢复。
- [ ] 桌面与窄屏页面不存在状态、正文、按钮或下载控件重叠。
- [ ] 下载和 Markdown 预览验证无远程资源加载、脚本执行或路径泄漏。
- [ ] 应用日志、Attempt、Trace 和验收报告抽查确认不泄露 secret 或不允许保存的内容。
- [ ] 独立子代理对最终 diff 做 Standards 和 Spec 双轴 Review。
- [ ] Review 发现的问题已修复，或以明确理由记录为剩余风险。
- [ ] 最终报告包含改了什么、破坏性变化、剩余风险、所有验证结果和严格 Go/No-Go。
- [ ] 所有 Ticket 验收完成后，不保留临时实施计划或未决占位文档。
