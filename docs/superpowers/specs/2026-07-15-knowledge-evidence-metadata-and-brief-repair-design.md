<!-- 本文冻结 Evidence 元数据边界、Brief coverage 与 repair 的跨 Extraction、持久化、AI 校验和 UI 契约。 -->
# Knowledge Evidence 元数据过滤与 Brief 修复闭环设计

**Date**: 2026-07-15  
**Status**: Approved  
**Decider**: 用户  
**Architecture SSOT**: OfferPilot Knowledge 系统：核心方向与架构设计  
**Supersedes**: Knowledge Imported Source Ingest 破坏性重写设计中由模型输出 coverage、按首个失败立即 repair、repair 重写完整 Brief 的相关契约

## Problem Statement

用户导入的 Source 经常包含 YAML frontmatter、标签、作者卡片、阅读数、导航、推荐链接、图片链接壳和导出工具残片。这些内容目前会与正文一起生成 Evidence，进入 FTS、Brief Prompt 和章节 coverage。它们通常不能支撑知识陈述，却会增加检索噪声、扩大模型上下文，并让无价值章节成为 Brief 的强制覆盖对象。

最近一次真实 `@Async` Source Brief 生成暴露了这一问题：Generator 将文档顶层标签和来源作者区域标记为 skipped；程序因为这些区域包含文本 Evidence 而拒绝候选，唯一一次 repair 只把两个 coverage 状态形式上改成 covered，没有改善任何 statement。随后 28 条 statement 的逐条 support validation 发现 10 条 partial，但 repair 额度已被 coverage 消耗，最终 Brief 失败。全部 Provider 请求均正常完成，因此这不是异步队列或 Provider 可用性问题，而是 Evidence 资格、coverage 语义和 repair 时机共同造成的正确性缺陷。

从用户视角看，Source 原文应完整可回读，有价值的来源信息应保留，但标签残片和页面样板不应冒充知识 Evidence。Brief 应以真实 citation 证明章节覆盖，并在唯一一次 repair 中获得完整质量反馈；它不能因为先遇到一个形式问题而失去修复真实内容问题的机会。

## Solution

系统把不可变 Source、结构化 provenance 和 Evidence 明确分层。canonical Source 始终完整保留；确定性元数据解析器从明确边界中提取最小 provenance；Evidence eligibility policy 只允许能支撑知识陈述的正文块生成 Evidence。过滤只影响 Evidence 发射，不改写 Source，不改变原文位置语义。

Brief 不再由模型声明 coverage。程序根据 post-filter Evidence 的章节集合和候选 Brief 的实际 citations 确定 coverage：只有某章节的 Evidence 被事实 block 实际引用，该章节才是 covered。模型生成原子、可独立验证的 statement；Validator 继续只读取单条 statement 及其声明的 Evidence。

Schema 合法的候选先完成所有可执行的 citation、support 和 coverage 检查，再汇总问题发起唯一一次 repair。Repair Agent 只返回针对失败 block 的结构化 patch，可以从当前 Source/Snapshot 的完整 Evidence 集合中重新选择 citation，但不能修改已通过 block、引用其他 Source 或增加新主题。程序应用 patch 后重跑全部门禁；任何 partial、unsupported 或 contradicted 都使候选无法发布。

项目仍处于测试阶段，本次切换直接清空 Knowledge 数据域并重新导入测试 Source，不迁移旧 Evidence、Brief 或 Job，也不触碰其他业务模块和 AI 配置。

## User Stories

1. As a Knowledge 用户, I want Source 原件完整保留, so that 我可以随时核对导入前的真实内容。
2. As a Knowledge 用户, I want YAML frontmatter 不生成普通 Evidence, so that 标签和配置字段不会污染知识检索。
3. As a Knowledge 用户, I want 作者、来源 URL 和发布时间仍可查看, so that 清理噪声不会丢失出处信息。
4. As a Knowledge 用户, I want Source 标题可用于定位资料, so that 我无需依赖正文 Evidence 才能找到某份 Source。
5. As a Knowledge 用户, I want 阅读数、导航、推荐链接和复制按钮等样板被过滤, so that 搜索结果优先返回真实正文。
6. As a Knowledge 用户, I want 普通正文中的 `key: value` 保持可检索, so that 元数据规则不会误删配置示例或技术说明。
7. As a Knowledge 用户, I want 格式损坏的元数据不阻断 Extraction, so that 一个非法日期或作者字段不会让整份 Source 失败。
8. As a Knowledge 用户, I want 无法确定是否为元数据的内容被保守保留, so that 系统宁可留下少量噪声也不静默删除知识正文。
9. As a Knowledge 用户, I want Evidence 的行号和字符位置仍对应原始 Source, so that 点击 citation 时可以准确回读上下文。
10. As a Knowledge 用户, I want provenance 只用于来源归属, so that 标签或作者信息不能支撑技术事实。
11. As a Knowledge 用户, I want 被召回的 Evidence 附带 Source provenance, so that 我能看见结论来自哪里、由谁发布以及何时发布。
12. As a Knowledge 用户, I want Brief coverage 反映真实 citation, so that 模型不能只写一个 covered 状态绕过章节完整性门禁。
13. As a Knowledge 用户, I want 无正文 Evidence 的 Source 仍保留原件和 Extraction 结果, so that AI Brief 失败不会破坏 Source 可见性。
14. As a Knowledge 用户, I want Brief 使用原子陈述, so that 每条结论都能独立核验而不是把事实、推论和建议混在一起。
15. As a Knowledge 用户, I want 每个 statement 的 citation 真正支撑它, so that 点击出处时可以直接看到依据。
16. As a Knowledge 用户, I want Validator 只依据声明的 citation, so that Source 其他位置的正确内容不能替错误引用兜底。
17. As a Knowledge 用户, I want 任何 partial 都阻止 Brief 发布, so that 未被证明的推论不会进入 Pilot 或练习下游。
18. As a Knowledge 用户, I want 首次合法候选的全部质量问题一次汇总, so that 唯一 repair 能同时处理 citation、support 和 coverage。
19. As a Knowledge 用户, I want Repair Agent 可以为失败项重新选择同一 Source 的 Evidence, so that 引错 citation 时能够真正修复。
20. As a Knowledge 用户, I want Repair Agent 只能修改失败 block, so that 已通过的 Brief 内容不会在修复时意外漂移。
21. As a Knowledge 用户, I want Repair Agent 可以删除、收缩、替换或拆分失败陈述, so that 复合 partial statement 能变成可核验的原子陈述。
22. As a Knowledge 用户, I want repair 后重新执行全部门禁, so that patch 本身不能绕过 Schema、citation、coverage 或 support 检查。
23. As a Knowledge 用户, I want 旧的 current Brief 在重建候选失败时不被半成品覆盖, so that 已发布内容保持事务一致性。
24. As a Knowledge 用户, I want Brief 失败摘要保持简短, so that Source 状态区仍易于扫描。
25. As a Knowledge 用户, I want Attempt 详情列出全部失败 block 和原因, so that 我不需要从截断错误消息猜测剩余问题。
26. As a Knowledge 用户, I want validation failure 可以跳转到候选 block 和 Evidence, so that 我能快速人工判断是陈述越界还是 citation 选错。
27. As a Knowledge 维护者, I want 元数据过滤规则带有稳定版本, so that 同一规则可以确定性重建 Snapshot。
28. As a Knowledge 维护者, I want 看到每类过滤规则命中的数量, so that Evidence 异常减少时可以定位原因而不记录第二份原文。
29. As a Knowledge 维护者, I want 平台样板规则由明确适配器承载, so that 全局模糊正则不会误删其他来源的正文。
30. As a Knowledge 维护者, I want 真实 `@Async` 失败案例成为固定回归样本, so that coverage 与 support repair 的跨阶段缺陷不会复发。
31. As a Knowledge 维护者, I want 测试期切换直接清空旧 Knowledge 数据, so that 新旧 Evidence ID、Brief 和 Job 不会混用。
32. As a 其他业务模块用户, I want Knowledge 重置不触碰 Application、Conversation、Interview、Resume 或 Memory, so that 这次破坏性切换严格限制在 Knowledge 边界内。

## Implementation Decisions

- Evidence 的领域定义是“Source 中可稳定定位、可原样回读、可用于支撑知识陈述的内容”，不是 Source 的无损分块副本。
- canonical Source 和原始文件完整保留。元数据过滤只影响 EvidenceDraft 发射；不得先删除元数据再解析，也不得重写 canonical text。
- 元数据解析和 Evidence eligibility 使用确定性规则，不调用 LLM。无法确认的块默认保留为 Evidence。
- 最小 provenance 集合固定为 Source 标题、Source URL、作者、发布时间、系统捕获时间和元数据提取版本。沿用 Source 与 Source Origin 的现有所有权边界，不引入任意 metadata 字典。
- 不自动导入 Source tags，不保存任意 metadata JSON。未进入结构化字段的信息仍可从不可变 Source 原文回读。
- provenance 不进入 Evidence FTS，不参与普通知识召回排序，不支撑正文事实。Source 标题可以作为独立的资料定位字段；Evidence 被召回时附带 provenance 用于出处展示。
- 全局过滤规则只覆盖低歧义结构，包括有效的文档头部 frontmatter、纯装饰图片壳、空链接壳和明确的导出控件文本。
- 平台或导出格式特有噪声由明确适配器处理，包括作者卡、阅读数、推荐导航、Evernote/Obsidian 资源残片等。禁止使用面向所有 Source 的宽泛关键词或文本正则清洗。适配器按确定性结构信号选择：Obsidian 由文档级 `![[...]]` 嵌入或 `%%...%%` 注释触发、Evernote 由 `<en-*>` 标签或 `.enex` 触发、web 文章由 ingest `origin_url` 触发；每个适配器只启用自身规则，一个信号不得顺带启用别的适配器，品牌名称、正文关键词与文件标题不得作为信号。无任何适配器信号时平台规则不执行，正文 `作者：...`、`by: ...`、独立"目录"等一律保留为 Evidence。
- 文档开头存在成对 frontmatter 边界时，整块不生成 Evidence。单个字段解析失败只丢弃该字段并记录警告，不阻断 Extraction；边界不完整时按普通 Markdown 保守处理。
- Snapshot 结构摘要记录过滤块总数、按稳定 rule ID 聚合的数量、成功提取的 provenance 字段名、metadata extraction version 和 evidence policy version。不得重复持久化被过滤块正文。
- Evidence 规则变化视为 Extraction 版本变化。正式产品语义应创建新 Snapshot；本次因尚未上线，采用限定在 Knowledge 数据域内的破坏性清空，不实现旧 Snapshot 迁移。
- Knowledge 重置覆盖 Source、Origin、Asset、Snapshot、Evidence、FTS、Brief、Attempt、Knowledge Job、处理日志及 Knowledge 文件目录。保留 Schema、迁移记录、AI Provider/应用配置和所有非 Knowledge 业务数据。
- Knowledge reset 采用原子 quarantine：先把 `$OFFERPILOT_DATA/knowledge/` 原子移出到同文件系统的 quarantine 目录，再在单事务内 DELETE 全部 Knowledge 表并提交。DB 提交即逻辑完成点：提交失败则把 quarantine 原子移回 `knowledge/`（不留"DB 有记录 + 文件缺失"）；提交成功后 best-effort 清理 quarantine，清理失败只记 pending 待启动恢复扫除而不回退（不留"DB 空 + knowledge/ 残留"）。两个并列禁止的半重置状态都不出现。
- Brief Schema 提升版本并移除模型输出的 coverage。API 若继续返回 coverage，则该字段由程序在校验后派生，不接受模型声明。
- 预期 coverage 章节只来自 post-filter 的当前 Snapshot Evidence。某章节至少有一条 Evidence 被 overview、key point、section guide 或 limitation 实际引用，才算 covered；assets-only 等确定性非正文状态由程序标记 skipped。
- coverage 必须检查真实引用关系，而不是只检查 section key 是否出现。模型不能以“不重要”为由跳过含合格正文 Evidence 的章节。
- key point、limitation 和 section guide summary 每条只表达一个可独立验证的核心断言。overview 允许有限综合，但每个事实和因果关系都必须被 citations 直接支持。
- Validator 继续逐条独立调用，只读取单条 statement 及其声明的当前 Source/Snapshot Evidence。它不得查看 Source 其他 Evidence 为错误 citation 兜底。
- 支持性判定集合保持 supported、partial、unsupported、contradicted。只有所有事实 block 均为 supported 才能发布；不设置 partial 容忍比例。
- Schema 无法解析时可以立即消耗唯一 repair，因为后续门禁无法运行。Schema 合法时不得按首个失败抢占 repair；系统先运行所有可执行的 citation、support 和 coverage 检查，再统一生成 repair 输入。
- citation 无效的 block 不调用 support Validator，但其 citation 问题进入统一 repair report；其他引用有效的 block 继续完成 support validation，以尽可能收集完整反馈。
- Repair Agent 接收原候选、失败 block 集合、结构化失败原因、当前 Source/Snapshot 的完整 Evidence 列表和数量约束，只返回结构化 patch，不返回完整 Brief。
- Repair patch 仅允许针对失败 block 执行 replace、delete、split，以及 coverage_missing 专用的 upsert_section_guide。replace 和 split 可以从当前 Source/Snapshot 的任意 Evidence 中增加、替换或删除 citations；不得引用其他 Source、修改已通过 block 或新增主题。upsert_section_guide 只针对 coverage_missing 派生的 repair target（`coverage[section_key]`），其 section_key 与 heading_path 必须与 coverage plan 一致，citations 只能来自该 section 当前的合格 Evidence；该 section 已有 guide 则原位替换，否则追加，一个 patch 内同一 section_key 不得重复 upsert。非 guide 块（overview/key_points/limitations）的 replace 与 split 受章节边界约束：程序按原块有效 citation 所属章节集合校验新引用，越出该集合即拒绝；原块无任何有效 citation 可定章节时只允许 delete。
- Patch 应用由程序完成。所有操作基于原候选 block path 一次性解析，避免 delete 导致后续索引漂移；split 只允许用于列表型事实 block，section guide 只能替换或删除。
- Patch 应用后必须重新执行完整 Schema、数量、citation ownership、coverage 和逐条 support 门禁。第二次仍存在非 supported 结果时 Attempt 失败。
- current Brief 的事务替换语义保持不变：新候选全部通过后才替换；重建失败时保留旧 current Brief。
- validation report 结构化保存全部 block、decision、reason 和 evidence IDs。reason 由程序按 issue_type/decision 派生为稳定原因码加限长安全摘要（不来自模型文本），不得回显 statement 或所引 Evidence 正文。Source 状态只显示错误码、总数和简短摘要；现有 Attempt/处理记录界面展示完整详情并提供到候选 block 与 Evidence 的定位。
- 普通日志不得打印 Evidence 正文、完整 Prompt 或 Source 本机路径。过滤统计和 validation report 遵守现有本地 SQLite 与隐私边界。逐条 Validator 返回的原始 reason 仅在本次校验/repair 内存内受限使用（限长并做回显检测），不落库、不进前端；持久化与展示只用程序生成的原因码和安全摘要。
- 逐条 Validator 的性能优化不改变语义。本 Spec 不引入整批校验；未来缓存键可由 statement、Evidence content hashes 和 validator version 构成。
- 本次改动是破坏性产品契约切换，不保留旧 Brief Schema、旧模型 coverage 或完整 Brief repair 响应的运行时兼容分支。

## Testing Decisions

- 最高测试 seam 是从 Imported Source 原始字节开始，经过 Extraction、Evidence/FTS 提交、Brief generation、逐条 validation、单次 repair patch 到最终 Brief/Attempt 持久化状态的 Worker/Repository 集成路径。真实 `@Async` 失败案例必须在这个 seam 回放，而不是只测试 prompt helper。
- `@Async` 回归样本必须包含文档顶层 tags、来源作者/图片区域、正文技术章节、初始候选的 coverage 噪声以及 citation/support partial。测试应证明元数据不生成 Evidence、coverage 不消耗 repair、repair 收到完整问题、最终结果只在全部 supported 后发布。
- 元数据解析使用窄单元 seam 覆盖确定性边界：有效 frontmatter、非法单字段、未闭合边界、正文 `key: value`、空链接壳、纯图片壳和已知适配器规则。
- 每个全局规则和来源适配器都必须有正例与反例。好测试观察生成的 Evidence、provenance、原文位置和规则统计，不断言私有 helper 的调用顺序。
- 测试 canonical Source 在过滤前后字节语义不变，并验证保留 Evidence 的 char/line offsets 可以回读到原文。
- 测试 provenance 不进入普通 Evidence FTS，但 Source 标题仍可定位资料，召回 Evidence 时可以取得其来源归属字段。
- 测试 coverage 由实际 citations 派生：仅在输出中声明 covered、引用其他章节 Evidence或遗漏正文章节都必须失败；assets-only 的 skipped 由程序确定。
- 测试 atomic statement 约束通过行为体现：复合 statement 被 Validator 判 partial 后，repair split/replace 可产生独立 supported 条目。
- 测试 Validator 隔离：Source 其他位置存在支持 Evidence，但候选 citation 错误时仍必须失败。
- 测试统一 repair 时机：同一候选同时含 citation、coverage 和 support 问题时只发起一次 repair，并且 repair 输入包含全部已发现问题。
- 测试 Schema 完全不可解析时可以立即 repair；repair 后仍非法则失败，且不执行无意义的 support 调用。
- 测试 patch 权限：修改已通过 block、未知 block、跨 Source Evidence、新增主题、重复操作或违反数量上限都必须被程序拒绝。
- 测试多个 delete/split 操作相对原候选原子应用，不因索引变化修改错误 block。
- 测试 repair 后完整复验，任何 partial、unsupported、contradicted、citation ownership 或 coverage 失败都不能写入 current Brief。
- 测试失败 Attempt 的摘要包含正确总数，结构化报告保留全部失败项，不再只依赖前五条拼接文本。
- 测试 Knowledge 破坏性 reset 清除 Knowledge 表族、FTS 和文件目录，同时证明 AI 配置及非 Knowledge 业务数据保持不变。
- 沿用现有 Brief Worker、Knowledge repository、Extraction、API 和前端 Source 详情测试作为 prior art；修复现有异步 Extraction 测试夹具，使其先完成 Evidence 提交再进入 Brief seam，禁止用空 Evidence 绕过目标行为。
- 完成前重新导入真实测试 Source，人工检查 Evidence 噪声、Source 原文回读、provenance 展示、Brief 失败详情和检索结果；完整 release gate 仍按仓库施工协议执行。

## Out of Scope

- LLM 驱动的通用元数据分类、网页正文抽取或自动清洗。
- PDF、DOCX、OCR、浏览器抓取和远程 URL 内容获取。
- 任意 metadata JSON、自动 tags、分类体系、Collection 或主题树。
- provenance 参与普通知识召回、正文事实支持或向量排序。
- Validator 整批判断、并发调度、support 缓存和性能专项优化。
- 新建独立诊断工作台或复杂 provenance 搜索界面。
- 为旧 Knowledge Evidence ID、旧 Brief Schema、旧模型 coverage 或旧 repair 响应保留兼容层。
- 迁移或保留当前测试期 Knowledge 数据。
- 修改 Knowledge Note、Memory、Application、Conversation、Interview、Resume、Exercise 或 Pilot 的领域契约。

## Further Notes

- 本 Spec 细化并替代此前 Ingest Spec 的 Source Brief Schema、coverage 和 repair 部分；Knowledge 的长期职责、Source/Evidence/Brief 定义及 SQLite SSOT 决策继续有效。
- 关键反例是“元数据 coverage 先消耗 repair，真实 support 问题随后无额度可修”。实现和评审必须保留这个跨阶段视角，不能把修复降级为新增一条 prompt 文案。
- 元数据过滤不是删除 Source 内容。用户仍可查看完整原件；Evidence 只是经过资格判断的可引用索引层。
- 本次破坏性 reset 必须在最终交付中明确报告。执行删除前仍应使用 Knowledge 专用 reset 边界，禁止手工扩大到整个应用数据库或数据目录。
- 测试 seam 已在设计讨论中确认：以真实 `@Async` 案例覆盖 Source extraction 到 Brief 最终门禁的最高层路径，辅以少量确定性 parser/policy 和 patch 权限单元测试。
