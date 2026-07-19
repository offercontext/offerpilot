# Tickets: Knowledge V1 Source / Evidence 发布

将 [Knowledge V1 Source / Evidence 发布验证](docs/superpowers/specs/2026-07-18-knowledge-v1-source-evidence-release.md)
落地为不依赖 AI Provider 的资料工作台。V1 只包含 Imported Source、确定性 Extraction、Evidence/FTS、
搜索、回读、状态与运维可靠性；Brief 留到 V1.1 决策，内部消费链路留到 V2。

工作时只处理 **frontier**：一张 Ticket 的所有 blocker 完成后才能开始。每张 Ticket 使用一个全新上下文，
通过 `/implement` 完成测试、最小实现、验证和独立 Code Review；不得跨 Ticket 提前实现 V1.1 或 V2。

实施前必须阅读：

- [Knowledge 系统主文档](docs/architecture/knowledge-system.md)
- [Knowledge V1 Source / Evidence 发布 Spec](docs/superpowers/specs/2026-07-18-knowledge-v1-source-evidence-release.md)
- [ADR-0010](docs/architecture/decisions/0010-stage-knowledge-v1-v11-v2.md)
- [Knowledge Ingest 实施 Spec](docs/superpowers/specs/2026-07-12-knowledge-ingest-rewrite-design.md)，仅沿用 Source/Evidence 契约

通用完成要求：

- Source 原件不可变，Evidence 必须稳定定位和原样回读，SQLite 继续作为运行时唯一事实源。
- 行为变化先写失败测试，再做最小实现；不得禁用、排除或放宽现有测试、ruff、mypy 和 release gate。
- 不删除 Brief 代码或数据结构，但 V1 不自动执行、不展示为主状态、不把它作为验收门禁。
- 不新增 Knowledge Context、Pilot/练习消费、Captured Source、Knowledge Note、embedding 或 rerank。
- 普通日志不得打印 Source/Evidence 正文、查询全文、本机路径、Prompt、Provider secret 或模型响应。
- 非平凡实现完成后启动独立子代理 Code Review，修复发现的问题或明确记录剩余风险。

依赖图：

```text
KV1-01 ─┬→ KV1-02 ─┐
         └→ KV1-03 ─┼→ KV1-05
KV1-04 ─────────────┘
```

## KV1-01：导入完成后不再自动触发 Brief

**What to build:** 用户导入 Source 后，系统只执行 Preflight、Extraction、Snapshot、Evidence 和 FTS
提交。同步导入和异步 Worker 都在 Evidence 可搜索后结束，不创建 Brief Job、不检查 Provider，也不把
Brief pending/blocked/failed 写成 Source 的未完成状态。显式 Brief 重建代码可以留存，但不由 V1 导入触发。

**Blocked by:** None — can start immediately.

- [x] 先建立同步 Ingest 回归测试：Evidence 提交后 Source 为 `extracted`、Brief 保持未请求状态，且不存在 Brief Job。
- [x] 建立异步 Worker 回归测试：Extraction success callback 不创建 Brief Job，也不调用 Provider 选择逻辑。
- [x] 应用启动、Worker runtime 和重启恢复路径均不注册自动 Brief callback；不能只修改一个构造入口。
- [x] 同步 Ingest 在 Extraction 成功后不再直接调用 Brief 入队或写入 Brief enqueue failure。
- [x] 无 Provider、Provider 配置错误和 Provider context 不足均不影响 Source 达到 V1 可用状态。
- [x] 重复导入、Worker 重放和恢复 pending Extraction 不产生重复或迟到 Brief Job。
- [x] Source 列表、详情和上传响应中的 extraction 状态与 active Snapshot/Evidence 一致。
- [x] Evidence 搜索和 detail 回读证明 Source 在没有 Brief 的情况下完整可用。
- [x] 显式 Brief rebuild 代码不被破坏性删除；其行为不纳入本 Ticket 的 V1 成功定义。
- [x] 更新受影响的既有测试，使其显式触发 Brief 场景，不再依赖导入自动入队的旧前提。
- [x] 定向后端测试、ruff 和 mypy 通过，且没有新增日志敏感信息。

## KV1-02：将 Source 工作台收缩为 V1 Evidence 体验

**What to build:** 用户在 Knowledge 工作台只看到 Source 生命周期、Extraction、Evidence、原文和处理
状态。列表与详情不再用 Brief Pill、Brief tab、Attempt、暂缓原因或自动轮询暗示导入未完成；搜索命中
仍能进入 Source、定位 Evidence 并回读原文。

**Blocked by:** KV1-01：导入完成后不再自动触发 Brief。

- [x] Source 列表只展示生命周期和 Extraction 状态，不展示 Brief 状态 Pill。
- [x] Source 详情头不展示 Brief 状态，也不把 `not_started` 表现为警告、失败或待完成。
- [x] V1 主界面移除或隐藏 Brief 浏览、重建入口、Brief Attempt timeline 和 Brief block/error 文案。
- [x] 后台轮询只由 Extraction、删除或其他 V1 任务的在途状态触发，不因 Brief 状态持续刷新。
- [x] 无 Brief 的 extracted Source 默认进入 Evidence 或原文视图，而不是空 Brief 状态。
- [x] Evidence 搜索结果点击后仍能选择正确 Source、滚动并高亮对应 Evidence。
- [x] Evidence citation 仍能跳转到原文位置，Source provenance 和过滤摘要保持可见。
- [x] 归档、取消归档、删除、标题编辑、原件下载和资产查看行为不回归。
- [x] 前端 types/services 可以保留 Brief 字段以兼容后端，但 V1 组件不得依赖它决定完成度。
- [x] 前端测试覆盖无 Brief Source、Extraction pending/failed/extracted、搜索定位和处理记录。
- [x] production build 通过；桌面和窄屏下状态、按钮、标签和长文本不重叠。

## KV1-03：提供无 Provider 的 Source / Evidence V1 验收 Profile

**What to build:** 维护者可以运行一个明确的 V1 acceptance profile，在独立数据目录导入 5 份 Source，
执行至少 20 条查询，并验证 Evidence 回读、检索指标、幂等和边界 fixtures。该 profile 不需要 Provider，
不创建 Brief Job，也不计算 Brief 成功率或运行 Brief 故障场景。

**Blocked by:** KV1-01：导入完成后不再自动触发 Brief。

- [x] V1 profile 是维护者 CLI 和领域验收入口的明确选项，并成为 Knowledge V1 推荐默认路径。
- [x] V1 profile 不要求 AI 配置、model client、API Key 或真实 Provider。
- [x] 验收导入只消费 Extraction queue；运行前后都断言没有 Brief Job 和模型调用。
- [x] 报告保留 Source 数量、Evidence 数量、回读率、重跑一致性、lexical Recall@5、MRR 和自然语言 Recall@5。
- [x] V1 报告与 failure collection 不包含 Brief pass rate、Brief 状态或 Brief failure scenario 门禁。
- [x] 5 份 Source、每份至少 4 条查询、总计至少 20 条的 manifest/query 契约继续强制校验。
- [x] Evidence 回读成功率必须为 100%，lexical Recall@5 必须为 100%，MRR 不低于 0.9。
- [x] 自然语言 Recall@5 低于 80% 时报告 bad cases，不自动引入 embedding、rerank 或 query model。
- [x] 编码、空内容、超限、Markdown 结构、Bundle 路径/资产等 edge fixtures 继续作为硬门禁。
- [x] fixture 缺失、hash 漂移、FTS 错误和回读不一致均返回非零结果与安全、可定位的报告。
- [x] 现有 Brief 验收能力如需保留，必须成为独立的 V1.1 候选 profile，不能污染 V1 默认语义。
- [x] 验收工具和 CLI 测试覆盖成功、指标失败、fixture 失败及无 Provider 场景。

## KV1-04：恢复遗留 Brief 代码的仓库健康门禁

**What to build:** 在不继续开发 Brief 产品能力的前提下，最小修复当前遗留 Brief Worker 的单测和类型
错误，使完整 Knowledge 测试和 mypy 恢复全绿。修复只恢复仓库健康，不实现 supported-only、prune、
changed-only validation 或其他 V1.1 设计。

**Blocked by:** None — can start immediately.

- [x] 修复直接构造 Brief Worker 的 timeout 测试，使测试对象拥有生产调用所需的完整 trace 初始状态。
- [x] 修复 trace 接口的 `set[str]` / `list[str]` 类型不一致，保持 Evidence ID 顺序和既有运行语义明确。
- [x] 不通过 `getattr` 静默兜底、类型忽略、禁用测试或缩小 mypy 检查范围掩盖初始化契约问题。
- [x] 不实现 ADR-0008 的 changed-only validation、自动 prune、prune ledger 或 37 次调用门禁。
- [x] 不改变 Source/Evidence、Provider retry/failover 或 current Brief 事务替换语义。
- [x] 当前失败的 Brief timeout 测试通过，且相关 Worker/lease/trace 回归测试通过。
- [x] 全部 `test_knowledge*.py` 通过，`uv run mypy src` 和 ruff 通过。
- [x] 变更保持最小，独立 Code Review 确认没有把 V1.1 范围重新带回 V1。

## KV1-05：完成 Knowledge V1 发布验收

**What to build:** 在前四张 Ticket 完成后，以全新本地数据目录执行 Source/Evidence V1 acceptance、完整
工程 gate 和真实工作台浏览器走查，形成可复核的 Go/No-Go 结论。只允许修复验收暴露的 V1 缺陷，
不得借发布验收加入 Brief、内部消费或新检索方案。

**Blocked by:** KV1-01：导入完成后不再自动触发 Brief；KV1-02：将 Source 工作台收缩为 V1 Evidence
体验；KV1-03：提供无 Provider 的 Source / Evidence V1 验收 Profile；KV1-04：恢复遗留 Brief 代码的
仓库健康门禁。

- [ ] 使用全新数据目录运行 V1 profile，确认 5 份 Source、至少 20 条查询和全部 edge/bundle 门禁通过。
- [ ] 报告证明 Evidence 回读成功率 100%、lexical Recall@5 100%、MRR 不低于 0.9，并列出自然语言指标。
- [ ] 验收全程不配置 Provider、不创建 Brief Job、不产生模型调用。
- [ ] 完整后端 pytest、ruff、mypy、前端测试和 production build 通过。
- [ ] 本地应用 smoke 验证上传、异步 Extraction、列表/详情、Evidence search/detail、原文和 SPA fallback。
- [ ] 浏览器走查 file、bundle、paste、重复导入、搜索定位、原文回读、归档、取消归档和永久删除。
- [ ] 浏览器验证 Extraction pending/failed/extracted 状态清晰，界面不出现 Brief 待完成或错误暗示。
- [ ] 桌面与窄屏视口无重叠、截断、不可达操作或动态内容导致的布局跳动。
- [ ] 删除后文件、Evidence、FTS、Job 和 UI 缓存均无残留；重启后不会恢复已删除 Source。
- [ ] 最终报告明确列出执行命令、指标、浏览器结果、未执行项和剩余风险。
- [ ] 任一硬门禁未通过时结论必须为 No-Go；不得用跳过测试、启用 Brief 或加入向量检索绕过。

---

# Historical Tickets: Knowledge Evidence 元数据过滤与 Brief 修复闭环

将 [Knowledge Evidence 元数据过滤与 Brief 修复闭环设计](docs/superpowers/specs/2026-07-15-knowledge-evidence-metadata-and-brief-repair-design.md)
实现为确定性 Evidence 资格、真实 citation coverage、汇总式单次 repair 和完整失败诊断闭环。

这是 KI-01～KI-12 完成后的 follow-up ticket 组。工作时只处理 **frontier**：一张 Ticket 的所有
blocker 完成后才能开始。每张 Ticket 使用一个全新上下文，通过 `/implement` 完成代码、测试、验证和
Code Review；不要跨 Ticket 提前实现后续能力。

实施前必须阅读：

- [Knowledge 系统主文档](docs/architecture/knowledge-system.md)
- [Knowledge Evidence 元数据与 Brief 修复 Spec](docs/superpowers/specs/2026-07-15-knowledge-evidence-metadata-and-brief-repair-design.md)
- [Knowledge Ingest 实施 Spec](docs/superpowers/specs/2026-07-12-knowledge-ingest-rewrite-design.md)
- [ADR-0007](docs/architecture/decisions/0007-use-sqlite-as-knowledge-wiki-ssot.md)

通用完成要求：

- 保持 Source 不可变、Evidence 可回读和 SQLite 单一事实源，不以清洗为由改写原件。
- 每个行为变化先建立失败测试，再完成最小实现；禁止禁用、放宽或绕过现有门禁。
- 每张 Ticket 在数据、领域服务、API、前端和测试之间形成可独立验证的纵向闭环。
- 不保留旧 Brief Schema、模型自报 coverage 或完整 Brief repair 的运行时兼容分支。
- 不引入任意 metadata JSON、自动 tags、LLM 元数据分类、通用网页正文抽取或整批 Validator。
- 普通日志不得打印 Source/Evidence/Brief 正文、完整 Prompt、API Key 或本机路径。
- 完成前运行与改动面匹配的测试；KBR-08 运行完整 release gate 和真实浏览器验收。
- 非平凡实现完成后启动独立子代理 Code Review，修复发现的问题或记录明确剩余风险。

依赖图：

```text
KBR-01 → KBR-02 ┬→ KBR-03 ───────────┐
                 └→ KBR-04 → KBR-05 → KBR-06 ─┤
                                               ├→ KBR-07 → KBR-08
```

## KBR-01：恢复异步 Ingest 到 Brief 的最高层测试 seam

**What to build:** 建立一个稳定的集成测试入口，从用户导入 Source 原始字节开始，真实驱动
Extraction queue 完成 Snapshot/Evidence/FTS 提交，再驱动 Brief queue。后续 Ticket 可以在同一
seam 注入确定性模型响应并观察最终 Source、Attempt、Brief 和调用顺序，不再依赖同步 Extraction
假设或手工插入 Evidence。

**Blocked by:** None — can start immediately.

**Scope boundaries:** 这是 make-the-change-easy 的测试 prefactor。不得改变生产 Pipeline、队列顺序、
Provider 行为或产品 Schema；不得在本 Ticket 实现元数据过滤、coverage 或 repair 新语义。

- [x] 测试入口使用正式 Ingest/Job/Worker 边界创建并处理 Source，不直接向 Snapshot、Evidence、FTS
      或 Brief 表插入伪造数据。
- [x] 测试显式运行 Extraction queue，等待 Source 达到 extracted 且 active Snapshot/Evidence 可见后，
      才运行 Brief queue。
- [x] 测试入口支持注入按角色和阶段返回的确定性模型响应，并能区分 generation、Validator 和 repair。
- [x] 测试入口可以记录调用角色、调用顺序、模型输入摘要和调用次数，但不把完整 Source 或 Prompt 写入
      普通测试日志。
- [x] 测试入口返回可断言的 Source、Job、Attempt、current Brief、Evidence 和 validation report。
- [x] 成功路径证明 Extraction 提交后 Brief 才开始，并最终得到 ready Brief。
- [x] 失败路径证明 Brief 失败不影响 Evidence 搜索，且没有半提交 current Brief。
- [x] 重建路径证明旧 current Brief 在候选失败时继续可见。
- [x] 当前因 Evidence 为空而提前失败的 Brief repair 测试改用新 seam，并真正执行到目标门禁。
- [x] 原有队列 lease、取消、Provider retry/fallback 和 Brief 测试继续通过。
- [x] 本 Ticket 不改变任何用户可见行为，diff 仅为测试 seam 和必要的无行为 prefactor。

## KBR-02：结构化 provenance 并从 Evidence 排除 frontmatter

**What to build:** 用户导入带有效 frontmatter 的 Markdown 后，系统完整保留 canonical Source，提取
最小 provenance，并且 frontmatter 不生成 Evidence、不进入 FTS 或 Brief。用户在 Source 详情中仍
能看到标题、来源 URL、作者和发布时间；点击正文 Evidence 时位置继续对应完整原件。

**Blocked by:** KBR-01：恢复异步 Ingest 到 Brief 的最高层测试 seam。

**Scope boundaries:** 本 Ticket 只处理明确边界的文档头部 frontmatter 和最小 provenance。作者卡、
阅读数、导航、Evernote/Obsidian 样板由 KBR-03 处理；不得引入任意 metadata 字典或 tags 产品能力。

- [x] provenance 契约只包含 Source 标题、Source URL、作者、发布时间、系统捕获时间和元数据提取版本。
- [x] provenance 沿用 Source 与 Source Origin 的现有所有权边界，不建立无约束 metadata JSON。
- [x] 文档开头存在成对 frontmatter 边界时，整个 frontmatter 块不生成 Evidence。
- [x] title、author、source URL 和 published time 采用明确白名单解析；tags 和未知字段不进入领域模型。
- [x] 单个白名单字段格式非法时只忽略该字段并记录安全警告，Source Extraction 仍成功。
- [x] 只有起始边界而没有闭合边界时，内容按普通 Markdown 保守处理，不静默吞掉后续正文。
- [x] 正文中的 `key: value`、YAML 示例和代码块保持为可检索 Evidence。
- [x] canonical Source、原始文件和 Source hash 不因 provenance 提取而改变。
- [x] 保留 Evidence 的 line/char offsets 能从完整 canonical Source 精确回读。
- [x] frontmatter 内容不进入 Evidence FTS，普通 Evidence 搜索不能召回 tags 或作者字段。
- [x] Source 标题仍可通过现有资料定位能力找到，但 provenance 不参与正文事实支持。
- [x] Source 详情 API 和前端显示已有的非空 provenance 字段，空字段不制造占位噪声。
- [x] Evidence 搜索/详情响应可以附带所属 Source 的 provenance，用于出处展示而不是召回计权。
- [x] Snapshot 记录 metadata extraction version；相同输入和版本重跑结果稳定。
- [x] 单元、Repository/API、前端和最高层集成测试覆盖成功、非法字段、未闭合边界和正文反例。

## KBR-03：过滤已知元数据样板并记录规则统计

**What to build:** 用户导入已知平台或导出工具产生的 Markdown 时，作者卡、阅读数、推荐导航、空链接
壳、纯装饰图片壳和资源路径残片不会进入 Evidence；无法确认的内容仍被保留。维护者能从 Snapshot
处理信息看到每条稳定规则的命中数量，而不会保存第二份被过滤正文。

**Blocked by:** KBR-02：结构化 provenance 并从 Evidence 排除 frontmatter。

**Scope boundaries:** 只实现低歧义全局结构规则和当前真实样本所需的明确适配器。不得使用覆盖所有
Source 的宽泛关键词/正则，不实现通用网页正文抽取或 LLM 分类。

- [x] Evidence eligibility policy 与 Markdown block 解析职责分离；规则决定是否发射 Evidence，不修改
      canonical text 或 AST 的原始位置。
- [x] 全局规则只处理低歧义结构，包括空链接壳、明确导出控件文本和纯装饰图片壳。
- [x] 来源/导出格式适配器按确定性结构信号选择：Obsidian 由文档级 `![[...]]`/`%%...%%` 触发、Evernote 由 `<en-*>`/`.enex` 触发、web 文章由 ingest `origin_url` 触发；一个信号只启用自身适配器，品牌名称、正文关键词与文件标题不作信号。信号只从允许的结构块（heading/paragraph/list/blockquote）行内文本提取，显式排除 fenced code、缩进 code block、table 单元格与行内 code（教程示例语法不激活 adapter）。无任何信号时平台规则不执行、相关正文默认保留。
- [x] 首版适配器覆盖真实 `@Async` 样本中的 Obsidian/Evernote 资源残片、作者区域、阅读信息和导航噪声。
- [x] 每条过滤规则具有稳定 rule ID、明确输入边界、正例和至少一个容易误判的反例。
- [x] 不确定块默认生成 Evidence；新增过滤规则必须通过版本提升和测试进入。
- [x] 被过滤块不进入 Evidence、FTS、Brief Prompt 或预期 coverage 章节集合。
- [x] 被过滤块仍能在 Source 原文中查看，且相邻保留 Evidence 的 line/char offsets 不发生偏移。
- [x] Snapshot 结构摘要记录 filtered block 总数、按 rule ID 聚合的数量、命中的 provenance 字段名、
      metadata extraction version 和 evidence policy version。
- [x] 结构摘要不重复保存被过滤正文、URL、作者名或本机路径。
- [x] Source 处理记录展示过滤数量和规则摘要；普通用户界面不展示内部正则或实现细节。
- [x] 相同 Source 与 policy version 重跑得到相同 Snapshot digest、Evidence ID、顺序和过滤统计。
- [x] policy version 变化使旧 Brief 正确进入 outdated 语义，不把新旧 Snapshot Evidence 混用。
- [x] 搜索回归证明被过滤噪声不可召回，正文术语、URL、数字和配置示例仍可召回。
- [x] 最高层测试从真实样本字节完成 Extraction，并断言 tags、作者卡和图片壳没有成为 Evidence。

## KBR-04：切换 Brief Schema v2 与确定性 citation coverage

**What to build:** 模型生成 Brief 时不再自报 coverage。系统从当前 post-filter Evidence 生成预期章节，
并根据候选 Brief 的实际 citations 计算 coverage；只有真正引用了该章节 Evidence 才算 covered。
API/UI 继续展示稳定 coverage，但模型无法通过填写状态绕过门禁。

**Blocked by:** KBR-02：结构化 provenance 并从 Evidence 排除 frontmatter。

**Scope boundaries:** 本 Ticket 完成 Schema、Prompt、程序门禁和派生 coverage 的成功/失败闭环；完整
失败汇总和 repair patch 分别由 KBR-05、KBR-06 完成。

- [x] Brief Schema 提升到 v2，模型输入/输出契约移除 coverage，不保留 v1 模型响应兼容分支。
- [x] generation Prompt 要求 key point、limitation 和 section guide summary 使用单一可验证核心断言。
- [x] overview 可以有限综合，但 Prompt 明确禁止加入 citations 未直接支持的事实、因果和建议。
- [x] 预期 coverage 章节只来自当前 Snapshot 的合格正文 Evidence，不包含 provenance 或被过滤块。
- [x] 某章节至少有一条 Evidence 被 overview、key point、section guide 或 limitation 实际引用时才为 covered。
- [x] assets-only 等确定性非正文章节由程序标记 skipped，不要求模型为图片生成事实。
- [x] 引用其他章节 Evidence 不能让当前章节通过 coverage；只声明 section guide key 也不能通过。
- [x] 含合格正文 Evidence 的章节缺少实际 citation 时返回稳定 coverage failure。
- [x] 没有可引用文本 Evidence 的 Source 保持 extracted/Evidence 可用，Brief 使用稳定 block/failure 语义，
      不发送无意义的 generation 请求。
- [x] 派生 coverage 写入候选 validation report，并在 Brief 成功提交时作为 API/UI 消费字段持久化或计算。
- [x] 前端继续展示 covered/skipped 结果，但不暴露“模型声明 coverage”的旧语言。
- [x] Provider/Prompt/Brief Schema/Snapshot 版本变化正确标记已有 Brief outdated。
- [x] v1 测试和 mock data 全部切换到 v2；代码库不存在运行时判断旧 coverage 响应的分支。
- [x] 测试覆盖全覆盖、遗漏章节、错章节 citation、纯 Asset 章节、无正文 Evidence 和伪造 coverage 字段。
- [x] 最高层测试证明模型即使返回额外 coverage 字段也不能改变程序派生结果或绕过门禁。

## KBR-05：汇总全部质量失败并展示完整 Attempt 报告

**What to build:** Schema 合法的候选 Brief 不再因为第一个 citation 或 coverage 问题立即消耗 repair。
系统完成所有仍可执行的 citation、逐条 support 和 coverage 检查，形成一份完整结构化报告；用户在
Source 状态区看到简短摘要，在 Attempt/处理记录中看到所有失败 block 和对应 Evidence。

**Blocked by:** KBR-04：切换 Brief Schema v2 与确定性 citation coverage。

**Scope boundaries:** 本 Ticket 先建立完整质量报告和用户可解释失败路径；repair patch 的生成、权限
和应用由 KBR-06 完成。不得为了收集更多问题而让非法 citation 进入 Validator。

- [x] JSON/Schema 完全无法解析时保留立即 repair 的现有能力，因为后续门禁无法安全运行。
- [x] Schema 合法时，程序先计算全部 citation ownership/existence 问题，不按首个错误返回。
- [x] citation 无效的 block 不发起 support Validator 调用，其问题仍进入统一报告。
- [x] citation 有效的其他 block 继续逐条 support validation，以收集尽可能完整的质量反馈。
- [x] Validator 仍只读取单条 statement 和它声明的 Evidence，不读取 Source 其他 Evidence 兜底。
- [x] coverage 使用 KBR-04 的实际 citation 结果计算，并与 citation/support 问题合并。
- [x] 每条报告项至少包含 block path、issue type、decision、reason 和 evidence IDs；reason 由程序按 issue type/decision 派生为稳定原因码加限长安全摘要，不来自模型文本。
- [x] issue type 能区分 Schema、citation missing/ownership、support partial/unsupported/contradicted 和
      coverage missing，供 repair 与 UI 使用。
- [x] support 结果只有 supported 才通过；任何 partial、unsupported 或 contradicted 仍是硬失败。
- [x] validation report 保存全部失败项，不使用 error message 的字符上限作为数据存储边界。
- [x] Source 状态区只显示稳定 error code、失败总数和不会在半句中截断的短摘要。
- [x] Attempt/处理记录展示全部失败项，并能定位到候选 Brief block 和已引用 Evidence。
- [x] 失败详情不把完整 Evidence 正文复制进 report 或普通日志；详情按 Evidence ID 从本地数据读取。逐条 Validator 原始 reason 仅内存内受限使用（限长并做回显检测），不落库、不进前端。
- [x] 重建失败时旧 current Brief 继续可见，失败候选和完整报告归属于新 Attempt。
- [x] 测试构造同一候选同时含 citation、support 和 coverage 问题，证明报告完整、调用顺序正确且只统计
      实际失败 block。

## KBR-06：使用结构化 patch 完成唯一一次 repair

**What to build:** 用户的合法候选在质量门禁失败后，Repair Agent 一次收到全部问题，只返回针对失败
block 的结构化 patch。程序原子应用 replace/delete/split，拒绝越权修改和跨 Source citation，随后
重跑全部门禁；只有全部 supported 的候选才能替换 current Brief。

**Blocked by:** KBR-05：汇总全部质量失败并展示完整 Attempt 报告。

**Scope boundaries:** 只允许一次受约束内容 repair。Provider transient retry/fallback 继续沿用现有
基础设施语义；不得通过增加 repair 次数或放宽 partial 门禁解决失败。

- [x] 定义固定版本 repair patch Schema，操作只包含失败 block 的 replace、delete、split，以及 coverage_missing 专用的 upsert_section_guide。
- [x] replace 返回一个原子事实项；split 只适用于列表型事实 block，并返回满足数量约束的原子项列表。
- [x] section guide 只允许 replace 或 delete，不允许制造同 section 多条 guide。
- [x] Repair 输入包含原候选、完整结构化失败报告、失败 block 集合、数量约束和当前 Source/Snapshot
      的完整 Evidence 列表。
- [x] Repair 可以为失败 block 增加、替换或删除当前 Source/Snapshot citations，即使新 Evidence ID
      不在原候选中。
- [x] Repair 不得修改已通过 block、引用其他 Source/Snapshot、增加新主题或输出完整 Brief。非 guide 块的 replace/split 受章节边界约束：新引用必须落在原块有效 citation 所属章节集合内，越出即拒绝；原块无有效 citation 可定章节时只允许 delete。该章节集合含 Asset citation（Asset 按 heading_path 定章节，受同样约束），repair 不得用跨章节 Asset 绕过；upsert_section_guide 的 citations 只取 section 文本 Evidence。
- [x] 程序拒绝未知 block、重复操作、对已通过 block 的操作、跨 Source Evidence 和非法 action。
- [x] 所有操作以原候选 block path 为基准一次性解析并原子应用，多个 delete/split 不会因索引变化
      修改错误条目。
- [x] Patch 应用后重新执行 Schema/数量、citation ownership、实际 coverage 和全部逐条 support 门禁。
- [x] repair 后任何 partial、unsupported、contradicted、coverage missing 或 citation failure 都使 Attempt
      最终失败，候选不能成为 current Brief。
- [x] repair 成功时 winning Attempt 与 current Brief 在一个事务中提交，并保存 repair_count=1。
- [x] Schema 不可解析路径和合法候选质量路径共享“最多一次 repair”预算，不出现隐藏第二次内容 repair。
- [x] Repair 输出非法 JSON/Schema、越权 patch 或模型调用失败时使用稳定错误码并保留完整安全报告。
- [x] Prompt injection 测试证明 Source、Evidence 和 previous candidate 中的指令不能扩大 patch 权限。
- [x] 测试覆盖 replace、delete、split、多操作原子性、数量下限、跨 Source、已通过 block 漂移、repair
      后仍失败、repair 成功和旧 Brief 保留。

## KBR-07：执行 Knowledge-only 破坏性切换

**What to build:** 测试期安装切换到新的 provenance、Evidence policy 和 Brief v2 契约时，系统使用
受控边界清空全部旧 Knowledge 数据和文件，然后能从零重新导入 Source；AI 配置和其他业务模块数据
保持原样。此 Ticket 执行用户已确认的破坏性 reset，不迁移旧 Evidence 或 Brief。

**Blocked by:** KBR-03：过滤已知元数据样板并记录规则统计；KBR-04：切换 Brief Schema v2 与确定性
citation coverage；KBR-06：使用结构化 patch 完成唯一一次 repair。

**Scope boundaries:** 只清空 Knowledge 数据域。不得删除整个应用数据库、整个应用数据目录、AI 配置
或任何非 Knowledge 业务数据；不得建立旧 Schema/Evidence ID/Brief 的兼容迁移。

- [x] reset 范围覆盖 Source、Origin、Asset、Extraction Snapshot、Evidence、FTS、Brief、Attempt、
      Knowledge Job、Knowledge 处理日志和 Knowledge 文件目录。
- [x] reset 保留数据库 Schema、迁移记录、AI Provider/应用配置和所有非 Knowledge 表/文件。
- [x] reset 使用正式 Knowledge 专用边界和依赖顺序，不依赖手工逐表/逐文件临时命令。
- [x] reset 在新空库、已有新 Schema 空库和包含旧测试数据的库上均可重复执行。
- [x] 中途失败不会留下指向已删除文件的 Source，或文件已存在但数据库无记录的半重置状态。
- [x] reset 采用原子 quarantine：`knowledge/` 先原子移出到同文件系统 quarantine，再提交 DB 单事务；DB 提交为逻辑完成点，提交失败原子移回，quarantine 清理失败只记 pending 待启动恢复扫除而不回退。quarantine 放在受控父目录 `.knowledge-reset/` 下并配 generation manifest；启动恢复只扫该父目录、验证 manifest（无 manifest 的目录一律不触碰，不误删用户同名目录），多 quarantine 无法判定代际时保守拒绝自动恢复/删除。
- [x] reset 后 Knowledge 列表、Evidence 搜索、FTS 和 pending/running Knowledge Job 均为空。
- [x] reset 后相同 Source 内容可以创建新的 Source/Snapshot/Evidence ID 并完成 Brief v2。
- [x] 删除前后记录非 Knowledge 代表数据和 AI 配置摘要，测试证明值和数量保持不变。
- [x] 文件清理拒绝绝对路径、目录穿越和 Knowledge 根目录之外的目标。
- [x] 旧 Brief Schema、模型 coverage、旧 Evidence policy version 和完整 Brief repair 数据不被迁移。
- [x] 前端在 reset 后稳定展示 Knowledge 空状态，不出现指向已删除 Source 的缓存详情。
- [x] Repository、启动修复、API/前端空状态和文件系统故障测试覆盖 reset 完整语义。
- [x] 最终交付明确报告本 Ticket 已执行破坏性 Knowledge 数据清空，不使用“兼容升级”措辞。

## KBR-08：固化 `@Async` 真实回放并完成发布验收

**What to build:** 将本次真实 `@Async` Brief 失败固化为最高层回归案例：元数据不生成 Evidence，
Generator 不能自报 coverage，所有 citation/support/coverage 问题一次汇总，结构化 patch 只修失败项，
repair 后只有全部 supported 才发布。完成代码、真实数据、浏览器和完整工程 gate 的 Go/No-Go 验收。

**Blocked by:** KBR-07：执行 Knowledge-only 破坏性切换。

**Scope boundaries:** 本 Ticket 只做跨 Ticket 整合修复、真实回放、浏览器验收和 release gate；不得借
验收新增 Validator 并发、缓存、向量检索、通用网页抽取或复杂诊断 UI。

- [x] 安全 fixture 保留本次案例的关键结构：frontmatter/tags、来源作者与图片壳、技术正文、多个章节、
      citation 选错和复合 partial statement；不提交私有 secret 或无授权完整原文。
- [x] 回放从 Source 原始字节经过正式 Ingest、Extraction queue、Snapshot/Evidence/FTS、Brief queue、
      generation、逐条 validation、repair patch 和最终持久化，不绕过任何层。
- [x] 断言 tags、作者卡、阅读信息、导航和图片壳不生成 Evidence，正文 Evidence 位置可完整回读。
- [x] 断言 provenance 可在 Source 详情查看，但不进入 Evidence FTS 或正文 support。
- [x] 断言模型响应不包含有效 coverage 权限，程序只依据实际 citations 派生 coverage。
- [x] 首轮合法候选的 citation、support 和 coverage 问题全部进入同一 validation report。
- [x] 整个内容质量流程最多发起一次 repair；不存在 coverage 先抢占 repair 的旧调用顺序。
- [x] Repair patch 只修改失败 block，并能为 `@EnableAsync` 等陈述选择当前 Source 中更直接的 Evidence。
- [x] 复合 statement 被收缩或 split 为原子陈述；所有 repair 后 block 均重新逐条验证。
- [x] 最终 Brief 只有在所有事实 block 为 supported 且 coverage 完整时进入 ready/current。
- [x] 构造 repair 后仍 partial 的反例，证明 Attempt failed、完整详情可见且 Evidence 继续可搜索。
- [x] 使用真实 Provider 重跑该 Source，记录 Provider/Model、调用角色数量、耗时、token 和最终门禁结果，
      不保存完整 Prompt、reasoning 或原始响应（环境仅本地测试 endpoint，详见 KBR-08 最终报告）。
- [ ]（用户验收）内置浏览器走查 Source provenance、Evidence、原文定位、Brief citations、coverage 和完整失败详情。
- [ ]（用户验收）桌面和窄屏下状态、失败列表、Evidence 链接和操作按钮不存在重叠或截断关键信息。
- [x] 运行完整后端测试、Python lint、类型检查、前端测试、生产构建和静态 smoke。
- [x] Docker 可用时运行 Docker smoke；不可用时明确记录未执行原因和剩余风险（本机 Docker 不可用）。
- [x] 独立子代理按 Standards 与 Spec 双轴 Review 最终 diff，发现的问题已修复或记录接受理由。
- [x] 最终报告包含改了什么、破坏性变化、剩余风险、全部验证结果和严格 Go/No-Go。
