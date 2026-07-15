<!-- 超限原因: 本文冻结 Source、Extraction、Evidence、Brief、后台任务、API、前端与破坏性迁移的跨模块实施契约。 -->
# Knowledge Imported Source Ingest 破坏性重写设计

**Date**: 2026-07-12  
**Status**: Approved  
**Decider**: 用户  
**Architecture SSOT**: [OfferPilot Knowledge 系统：核心方向与架构设计](../../architecture/knowledge-system.md)  
**Storage decision**: [ADR-0007](../../architecture/decisions/0007-use-sqlite-as-knowledge-wiki-ssot.md)

## 1. 文档职责

本文定义新 Knowledge 架构第一轮实现的可执行契约，只覆盖 Imported Source Ingest。
领域术语、Knowledge/Memory/Business Record 边界、长期数据流和为什么放弃自动 Wiki，均以架构
主文档为准。本文不重新定义这些事实。

本文完成后，后续实施 Plan 应把这里的垂直切片拆成可测试任务，不得自行扩大到 Knowledge Note、
Captured Source、Pilot 写入或练习消费。

## 2. 目标

本轮必须交付一个用户可操作、可检索、可审计、可恢复的 Imported Source Ingest 闭环：

```text
Imported Source
→ Preflight
→ Extraction Snapshot
→ Evidence + FTS
→ Source Brief candidate
→ validation
→ current Source Brief
```

完成标准不是“后台任务返回成功”，而是：原始 Source 可回读，Evidence 可稳定定位，关键词查询
可以召回，Brief 的每条事实均有受支持的 citation，任一 AI 失败都不破坏 Evidence。

## 3. 非目标

- 不实现 Knowledge Note、Note Preview、Note Version 或 Note 引用 UI。
- 不实现 Captured Source、Conversation/Interview/Exercise/Web capture。
- 不向 Pilot 暴露 Knowledge 搜索或写入 Tool。
- 不接入练习生成或 Knowledge Context。
- 不实现 PDF、DOCX、网页抓取、OCR、图片语义理解或音视频解析。
- 不实现 embedding、向量数据库、rerank、GraphRAG 或 LLM 查询改写。
- 不实现标签、类型、Collection、主题树、slug、Wikilink、Index 或 Review。
- 不实现 Markdown Wiki、Obsidian 同步、批量 ZIP 或知识库导出。
- 不实现 CLI；后端领域服务必须可被后续 CLI 复用。
- 不保留旧 Knowledge API、表、AI Tool 或前端的兼容层。

## 4. 支持的输入

### 4.1 输入方式

首版只接受：

1. 单个 `.md` 文件。
2. 单个 `.txt` 文件。
3. 一个 Markdown 主文件和 PNG/JPEG/WebP 附件组成的 Source Bundle。
4. 用户粘贴的 Markdown 正文；系统将其视为虚拟 `main.md`。

粘贴正文时可以填写可选 `origin_url`。系统不访问该 URL；它只作为 provenance 保存。

### 4.2 文件限制

| 项目 | 限制 |
|---|---:|
| 主 Markdown/Text 文件 | 5 MiB |
| 规范文本 | 64,000 product tokens |
| 单张图片 | 10 MiB |
| Bundle 总大小 | 50 MiB |
| Bundle 图片数量 | 50 |
| 单张图片像素 | 40 megapixels |
| 文件名或逻辑路径 | 255 bytes |

`knowledge-tokenizer-v1` 固定使用 pinned `cl100k_base` 计数。该计数器是产品输入计量规则，
不随当前 Provider 改变。文件字节限制与 token 限制必须同时满足。

Brief Provider 必须明确配置 `context_window >= 96_000`；`0` 代表未知，不得根据模型名称猜测。
64K 上限为 Prompt、Evidence 元数据、结构化输出和校验保留余量。

超过文本上限时，Preflight 拒绝整个 Source，返回实际 token 数、上限和“请按主题拆分资料”。
系统不截断、不自动分批，也不创建只有部分内容的 Source。

### 4.3 编码

- 支持 UTF-8、UTF-8 BOM、UTF-16LE/BE BOM。
- 无 BOM 内容先按 UTF-8 严格解码。
- GBK/GB18030 等无 BOM 内容只在编码检测达到固定置信阈值且严格解码成功时接受。
- 禁止 `errors="ignore"` 和 `errors="replace"`。
- 无法确定编码时拒绝上传，并提示用户转换为 UTF-8。
- Snapshot 记录原始编码、检测方法、规范化版本和 tokenizer 版本。

### 4.4 自包含 Bundle

- Ingest 永远不主动联网。
- 普通 Markdown 链接保留文本和 URL，但不抓取目标内容。
- 图片必须使用扁平相对路径，并对应本次上传的附件。
- 远程图片、绝对路径、父目录引用和跨目录引用均拒绝。
- 缺失图片、重复逻辑名、未使用附件或不支持的媒体类型使整个 Preflight 失败。
- 图片必须通过真实解码、媒体类型、大小、像素和 hash 检查，不能只信文件扩展名。
- 内嵌 HTML 作为不可信原文处理；不执行脚本、不加载资源，预览时必须转义或净化。

## 5. Source 身份与生命周期

### 5.1 内容寻址

`source_hash` 由主文件原始字节、附件原始字节及附件逻辑路径的规范清单计算。展示标题、
本机路径、上传时间和 `origin_url` 不参与内容身份。

同一工作区内，同一内容只能有一个有效 Source：

- 命中处理中 Source：返回已有 Source 和当前 Job，不重复排队。
- 命中已提取、已就绪或 Brief 失败 Source：返回已有 Source，不自动重建。
- 重复导入追加一条 `knowledge_source_origins`，但不重复 Evidence 或检索权重。
- 重复上传响应使用 `200` 和 `deduplicated=true`；新 Source 使用 `202`。

### 5.2 不可变内容与可编辑标题

- 原始文件、附件、manifest 和 `source_hash` 创建后不可修改。
- 内容变化必须创建新 Source。
- 系统从用户标题、文件名或首个 Markdown 标题得到 `title_hint`。
- 用户可修改 `display_title`；该操作不触发 Extraction 或 Brief。
- 标题可参与搜索排序和展示，但不得进入 Evidence 身份。

### 5.3 归档

- 归档和取消归档是同步 SQLite 操作。
- 归档 Source 默认不出现在列表和普通 Evidence 检索中。
- 归档不删除 Source、Snapshot、Evidence、Brief、Job 或文件。
- 归档数据不自动过期；只有永久删除才清除。

### 5.4 永久删除

本轮尚无 Note，因此永久删除不实现引用冲突 UI，但领域服务必须保留未来可增加
`SourceReferenced` 检查的边界。

删除流程：

1. Source 进入 `deleting`，停止接受新 Extraction/Brief Job。
2. 取消该 Source 尚未完成的 Job；已发出的模型响应不得提交。
3. Source 目录原子移动到 `knowledge/quarantine/`。
4. SQLite 事务删除 FTS、Brief、Attempt、Evidence、Snapshot、Asset、Origin、Job 和 Source。
5. 提交后删除 quarantine 文件；启动恢复负责完成异常中断的删除。

删除是异步危险操作，前端必须二次确认。成功后不保留 `source_hash` 墓碑；再次上传相同内容会创建
新 Source。Knowledge Log 只保留原 Source ID、删除时间和结果，不保留标题、正文或路径。

未来 Note 引入后，任何 Note Version 引用都必须阻止默认永久删除；不得使用 `CASCADE` 或
`SET NULL` 制造无 Evidence 的 Note。

## 6. 上传与文件提交协议

上传请求同步完成全部 Preflight，但不在 HTTP 请求中生成 Evidence 或调用模型：

```text
request
→ 写入 knowledge/staging/<upload-id>
→ Preflight + hash
→ 去重检查
→ SQLite 中创建 Source/Origin/Extraction Job
→ staging 原子 rename 到 knowledge/sources/<source-id>
→ commit
→ 202
```

数据库提交前必须完成最终目录 rename。若 rename 失败，事务回滚；若进程在 rename 后、commit 前
崩溃，启动恢复删除无数据库记录的孤儿目录。staging 中过期且无 Job 的目录同样清理。

正式 Source 目录不得被 Worker 原地修改。Worker 每次读取时核验 manifest 和 hash；不一致时
Extraction 失败并记录 `source_integrity_mismatch`。

## 7. 确定性 Extraction Snapshot

### 7.1 规范化

Extractor 必须版本化，并依次执行：

1. 严格解码。
2. 换行规范化为 `\n`。
3. 记录但不静默删除 Unicode 控制字符；不允许 NUL。
4. Markdown 使用固定版本语法树解析器，Text 使用段落解析器。
5. 生成 canonical text、结构节点、行/字符位置和 Asset 引用。
6. 计算 Snapshot digest。

相同 Source、相同 extractor/normalization/parser 版本必须生成相同 Snapshot digest 和结构清单。

### 7.2 Snapshot 版本

- `(source_id, extractor_version)` 唯一。
- 同版本重跑是幂等 upsert，不创建重复 Snapshot。
- extractor 升级创建新 Snapshot 和新 Evidence，并在成功提交后切换 `active_snapshot_id`。
- 旧 Snapshot/Evidence 不覆盖、不立即删除，为未来历史 Note citation 保留。
- 升级不自动批量重建；Source 标记 Snapshot/Brief `outdated` 后由用户显式触发。

## 8. Evidence 生成

Evidence 是引用单位，不是固定 token 检索 Chunk。模型不得参与 Evidence 的选择、切分、改写或命名。

### 8.1 Markdown 映射

| Markdown 结构 | Evidence 规则 |
|---|---|
| heading | 不单独生成；进入后续块的 `heading_path` |
| paragraph | 一个文本 Evidence；超长时按句子边界拆分 |
| list item | 每个条目一个 Evidence，保留嵌套父路径 |
| blockquote | 每个连续引用块一个 Evidence |
| table | 每个数据行一个 Evidence，渲染时携带表头 |
| fenced code | 整块一个 Evidence，记录语言和行范围 |
| thematic/navigation | 不生成 Evidence |
| image reference | 对应一个 Asset Evidence，并记录所有引用位置 |

普通文本 Evidence 目标不超过 2,000 Unicode characters，禁止重叠。无法按句子安全拆分的超长
代码块或表格单元允许到 8,000 characters，超过后按行边界拆分。检索上下文通过前后邻接扩展，
而不是把重叠文本写入多条 Evidence。

### 8.2 Evidence 字段与身份

每条 Evidence 至少保存：

- `id`、`source_id`、`snapshot_id`、`kind`、`ordinal`
- `block_kind`、`heading_path`
- `char_start/end`、`line_start/end`
- canonical excerpt、search text、content hash
- `asset_id`（仅 Asset Evidence）
- `previous_evidence_id`、`next_evidence_id`

ID 使用以下稳定输入生成 opaque `ev_...` 值：

```text
snapshot_digest + extractor_version + structural_locator + content_hash
```

ID 不暴露段落序号。相同 Snapshot 重跑必须得到相同 ID；改变 FTS tokenizer、排序或未来检索 Chunk
不得改变 ID。Snapshot 版本变化允许生成新 ID，旧 ID 继续指向旧 Snapshot。

### 8.3 图片

图片只保存原始 Asset、hash、尺寸、逻辑路径和引用位置。Markdown alt text 是作者原文，可进入文本
Evidence。首版不执行 OCR、多模态描述或图片内容检索；Brief 不能声明仅由图片支持的事实。

## 9. Evidence 提交与可见性

Extraction Worker 在单个 SQLite 事务中：

1. 插入或复用 Snapshot。
2. 写入全部 Evidence。
3. 重建当前 Snapshot 的 `knowledge_evidence_fts` 行。
4. 更新 `active_snapshot_id` 和 `extraction_status=extracted`。
5. 创建 Brief 排队条件或记录 Provider block reason。

事务提交前，新 Snapshot/Evidence/FTS 对读请求均不可见。失败时旧有效 Snapshot（若存在）继续可用；
首次 Extraction 失败的 Source 不进入检索。

## 10. Source Brief

### 10.1 输出 Schema

**注：coverage 生成契约已被 [2026-07-15 spec](2026-07-15-knowledge-evidence-metadata-and-brief-repair-design.md) 取代——模型不再输出 coverage 字段，程序根据候选 Brief 的实际 citations 派生 coverage；Brief Schema 已升至 v2，不保留 v1 模型 coverage 兼容分支。下方 payload 示例保留 v1 结构作历史快照，coverage 字段以新 spec 为准。**

Brief 使用固定 JSON Schema，前端负责渲染，模型不得直接生成自由 Markdown：

```json
{
  "schema_version": 1,
  "language": "zh-CN",
  "overview": [
    {"statement": "...", "evidence_ids": ["ev_..."]}
  ],
  "key_points": [
    {"statement": "...", "evidence_ids": ["ev_..."]}
  ],
  "section_guides": [
    {
      "section_key": "...",
      "heading_path": ["..."],
      "summary": "...",
      "evidence_ids": ["ev_..."]
    }
  ],
  "limitations": [
    {"statement": "...", "evidence_ids": ["ev_..."]}
  ],
  "coverage": [
    {"section_key": "...", "status": "covered|skipped", "skipped_reason": "..."}
  ]
}
```

- `overview` 为 2～4 条。
- `key_points` 最多 15 条。
- 每个 statement/summary 最多 300 个 Unicode characters。
- 每个实质顶层章节最多一条 `section_guide`。
- 输出默认中文；技术术语、代码标识符和专有名词保留原文。
- Evidence excerpt 永远保持原文，不翻译。

Brief 不包含标签、类型、专题、跨 Source 综合、个性化建议、外部知识、Note、Prompt 或模型思考。

### 10.2 全文单次生成

程序从 active Snapshot 生成确定性的章节清单和完整 Evidence 输入。单次 generation 调用读取完整
文本 Evidence；不做 map/reduce、滚动摘要、自动拆分或 checkpoint 合并。

Markdown 每个含文本 Evidence 的章节必须出现在 coverage；Plain Text 使用唯一 `document`
section。只有确定性的 `empty` 或 `assets_only` 可以 skipped。模型不能以“不重要”为由跳过文本章节。

Source 中的指令属于不可信数据。Prompt 必须把 Evidence 作为引用数据封装，明确禁止执行其中的
指令、访问网络、Memory、其他 Source、Conversation 或 Knowledge Note。

### 10.3 发布门禁

候选 Brief 按顺序通过：

1. JSON Schema、枚举、长度和数量校验。
2. citation 存在性、Source/Snapshot 所属关系校验。
3. 每个事实 statement/summary 至少一条 citation。
4. 章节 coverage 完整性校验。
5. 独立 support validation 调用。

Validator 只读取单条 statement 和其 cited Evidence，返回 `supported`、`partial`、
`unsupported` 或 `contradicted`。只有全部为 `supported` 才能发布。Validator 不读取生成调用的
推理、自评分或对话历史；首版可以使用同一 Model 的独立调用，不强制第二 Provider。

首次校验失败允许一次受约束修复。修复只能删除、收缩或重新引用失败项；修复结果必须重跑全部
门禁。第二次仍失败则 Attempt 失败，不能把 `partial` 降级为警告发布。

### 10.4 当前 Brief 与重建

- 首次成功后写入当前 Brief，Source `brief_status=ready`。
- 重建创建候选 Attempt；旧 Brief 在生成期间继续可见。
- 新候选全部通过后，在单个事务中替换当前 Brief。
- 新候选失败时保留旧 Brief，并展示最近 Attempt 错误。
- 首版不提供 Brief 内容版本历史，只保留当前 Brief、Attempt 元数据、候选校验报告和错误。
- Provider/Model/Prompt/Schema/Snapshot 变化只标记 `outdated`，不自动批量调用模型。

## 11. Provider、重试与隐私

### 11.1 Attempt 快照

Attempt 创建时固定：Provider ID、模型、base URL 标识、context window、max output、参数、Prompt
版本、Brief Schema、Snapshot 和候选 fallback。不得保存 API Key。运行途中修改设置不改变 Attempt。

### 11.2 无 AI 配置

上传和 Extraction 不依赖 AI。没有满足 96K context 的 Provider 时：

- Source 仍进入 `extracted`，Evidence 正常搜索。
- `brief_status=pending`，`brief_block_reason=provider_unavailable`。
- 配置变化不自动批量生成；用户点击“生成 Brief”后创建 Attempt。

### 11.3 fallback

只有网络错误、超时、限流和 Provider 5xx 等基础设施失败可以切换已配置 fallback。鉴权失败、
模型不存在、上下文超限、非法 JSON、citation 或支持性失败均不切换 Provider。

fallback 必须满足相同上下文要求。系统记录实际成功 Provider，不能将 fallback 结果记为 active。

### 11.4 自动重试

- 每个 Provider 最多调用 3 次，即首次加 2 次自动重试。
- 只重试超时、连接错误、限流和 5xx。
- 优先使用 `Retry-After`；否则使用带少量抖动的 2 秒、10 秒退避。
- 400、401、403、404、上下文超限等确定性错误不重试。
- 重试计数和 `next_retry_at` 持久化；重启后不得清零。
- 用户手动重建创建新 Attempt 和新预算。

## 12. Worker、队列与恢复

后台服务提供两个固定单并发执行通道：

1. Extraction queue：执行 Extraction，并承载永久删除等本地 Source 维护 Job。
2. Brief queue：执行 generation、validation 和最多一次 repair。

两条队列可以并行，但各自并发固定为 1，不提供用户配置。每条队列按 `created_at, id` FIFO；手动
重试排到队尾。Source 完成 Evidence 提交后立即可搜索，不等待 Brief。

Job 使用持久 lease：`lease_owner`、`lease_expires_at`、`heartbeat_at`。进程退出后，过期 running Job
重新进入 pending。每个阶段只在事务提交后标记成功；重复 claim 必须幂等。

模型请求在崩溃时可能已产生费用但没有返回。恢复时允许重发，但旧 worker 的迟到结果必须因
Attempt/lease 不匹配而拒绝提交。

取消规则：

- pending Job 直接标记 canceled。
- running 本地任务在安全点检查取消标记。
- 已发出的模型请求无法可靠中断时，响应也不得提交。
- 取消一个 Source 不影响其他 Source。

## 13. 状态模型

状态必须分离，禁止恢复一个模糊的 `done`：

| 维度 | 状态 |
|---|---|
| Source lifecycle | `active`, `archived`, `deleting`；删除后 Source 行不存在 |
| Extraction | `pending`, `processing`, `extracted`, `failed` |
| Brief | `not_started`, `pending`, `processing`, `ready`, `failed`, `outdated` |
| Job | `pending`, `running`, `succeeded`, `failed`, `canceled` |

`deleted` 只出现在删除 Job/Log 的终态，不保留为 Source 墓碑。UI 的总状态由上述字段计算，不另存
“导入成功”布尔值。

每个阶段错误使用稳定 `error_code` 和用户安全 message。至少覆盖：

```text
unsupported_type
encoding_unknown
source_too_large
bundle_invalid
source_integrity_mismatch
extraction_failed
fts_unavailable
provider_unavailable
provider_context_too_small
provider_transient_error
brief_schema_invalid
brief_quality_failed
job_canceled
```

KBR-05 起，citation/coverage/support 三类质量失败合并为单一 `brief_quality_failed`（schema 不可解析仍用 `brief_schema_invalid`）；细分类型见各 Attempt 的 `validation_report.issue_type`。

## 14. SQLite 数据模型

字段类型、索引和约束以下表为实施基线；具体 SQLAlchemy 声明可以按项目现有风格实现。

### 14.1 `knowledge_sources`

核心字段：`id`、`source_hash UNIQUE`、`source_kind`、`display_title`、`title_hint`、主文件名/
媒体类型/相对路径、manifest JSON、总字节数、token 数、lifecycle、extraction/brief 状态、
active Snapshot/Brief ID、block/error code、归档和时间字段。

### 14.2 `knowledge_source_origins`

记录每次导入来源：`source_id`、`import_method=file|paste|bundle`、原文件名、可选 `origin_url`、
导入时间。URL 只允许 `http/https`，不参与 Source hash，也不触发网络请求。

### 14.3 `knowledge_source_assets`

保存 `source_id`、逻辑名、媒体类型、相对路径、bytes、sha256、width、height。`(source_id,
logical_name)` 唯一。

### 14.4 `knowledge_extraction_snapshots`

保存 Source、extractor/parser/normalization/tokenizer 版本、encoding、canonical text、结构 manifest、
digest 和时间。`(source_id, extractor_version)` 唯一。

### 14.5 `knowledge_evidence`

保存第 8.2 节字段。`id` 为 TEXT 主键；`(snapshot_id, ordinal)` 唯一；Source、Snapshot 和 Asset
使用外键约束。相邻 ID 只允许同一 Snapshot。

### 14.6 `knowledge_evidence_fts`

SQLite FTS5 virtual table，至少包含 `evidence_id UNINDEXED`、`source_id UNINDEXED`、
`source_title`、`heading_path`、`content`，使用 `tokenize='trigram'`。

### 14.7 `knowledge_source_briefs`

每个 Source 只保存当前 Brief：Source、Snapshot、winning Attempt、Schema、语言、payload JSON、
outdated 标记和时间。Source 唯一。

### 14.8 `knowledge_brief_attempts`

保存 Source/Snapshot、状态、Provider 快照、Prompt/Schema 版本、token/时延/重试数据、候选 JSON、
validation report、error code/message 和时间。不保存 API Key、完整 Prompt 或不可解析原始响应。

### 14.9 `knowledge_jobs`

保存 `kind=extract|brief|delete`、队列、Source/Attempt、状态、重试、next retry、取消、lease、错误和
时间字段。唯一活动 Job 约束防止同一 Source/阶段重复排队。

### 14.10 `knowledge_logs` 与 `knowledge_retrieval_traces`

Log 只保存结构化事件元数据。Retrieval Trace 保存本地查询、过滤条件、命中 Evidence ID、分数、
位置、延时和评估标签，不属于 Knowledge，不参与召回。

## 15. Evidence 检索

P0 只实现 SQLite FTS5 基线：

- 主语料为当前 active Snapshot 的文本 Evidence。
- Source title、heading path 和 content 分列索引并加权。
- 中文、中英文混合和代码标识符使用 trigram。
- 少于 3 个字符的查询使用有上限的精确/子串回退。
- Query parser 不沿用“中文整句加引号”行为；必须把自然问句、ASCII identifier 和短术语转换为
  可解释的候选表达式。
- 默认只检索 `active` Source；调用方显式指定时可搜索 archived。
- 返回 Evidence 原文、Source、Snapshot、heading/line/char 位置、snippet、score 和邻接 ID。
- Brief 只用于 Source 列表搜索或后续粗排实验，不能替代 Evidence hit 或 citation。
- FTS 创建、MATCH 或 bm25 失败必须显式报错；禁止 `except: return []`。

启动时验证 SQLite FTS5 和 trigram tokenizer。缺失时 Knowledge 模块启动失败并显示
`fts_unavailable`，不能表现为“没有搜索结果”。

## 16. HTTP API

### 16.1 Source

```text
POST   /api/knowledge/sources
GET    /api/knowledge/sources
GET    /api/knowledge/sources/{source_id}
PATCH  /api/knowledge/sources/{source_id}
GET    /api/knowledge/sources/{source_id}/content
GET    /api/knowledge/sources/{source_id}/assets/{asset_id}/content
POST   /api/knowledge/sources/{source_id}/brief/rebuild
POST   /api/knowledge/sources/{source_id}/archive
POST   /api/knowledge/sources/{source_id}/unarchive
DELETE /api/knowledge/sources/{source_id}
```

`POST` 使用 multipart 支持 file、bundle 和 pasted content；新建返回 `202` 与 Source/Extraction Job，
重复返回 `200` 与 `deduplicated=true`。`PATCH` 首版只允许 `display_title`。

原件下载返回原始字节、安全文件名和正确媒体类型，不暴露本机绝对路径。永久删除返回 `202` 和
Delete Job。

### 16.2 Evidence

```text
GET  /api/knowledge/sources/{source_id}/evidence
GET  /api/knowledge/evidence/{evidence_id}
POST /api/knowledge/evidence/search
```

列表按 Snapshot/ordinal 稳定分页。搜索请求至少支持 `query`、`limit`、可选 `source_ids` 和
`include_archived`；`limit` 默认 10、最大 50。所有结果必须可通过 Evidence detail 回读。

### 16.3 Job

```text
GET  /api/knowledge/jobs/{job_id}
POST /api/knowledge/jobs/{job_id}/cancel
```

Job 响应公开 kind、stage、status、progress、retry、error 和时间，不返回 Prompt、Provider secret 或
Source 正文。

### 16.4 移除接口

必须删除旧 `/api/knowledge-documents*`、`/api/knowledge/wiki/*`、Page、Index、Review、Lint、Config
和 Export 接口；不保留 redirect、alias 或 deprecated handler。

## 17. 前端 Source 工作台

Knowledge 导航本轮直接进入“资料来源”，不显示尚未实现的 Note 空入口。

```text
顶部：上传文件 / 上传 Bundle / 粘贴正文 / Evidence 搜索 / 归档筛选
左侧：紧凑 Source 列表
右侧：Brief / Evidence / 原文 / 处理记录
```

要求：

- Extraction 和 Brief 状态分别显示。
- 默认打开 Brief；无有效 Brief 时打开 Evidence。
- 搜索命中后进入 Source，定位并高亮 Evidence 与原文位置。
- 图片可以安全查看和下载，但不显示 AI 图片描述。
- Markdown 预览净化 HTML，不执行脚本或加载远程资源。
- 归档默认隐藏，可筛选和取消归档。
- 永久删除放在危险菜单并二次确认。
- 错误区分编码/格式、Extraction、Provider、Schema、citation、coverage 和 support。
- 移除旧 Page、Review、Index、Purpose/Schema、Lint、Wiki Export 等全部界面和文案。

页面沿用项目现有设计系统，桌面使用列表-详情布局；窄屏切换为列表和独立详情，不允许状态文本或
操作按钮重叠。

## 18. 诊断与数据最小化

持久化 Provider/Model/版本、ID、token、时延、重试、错误和结构化 validation report。合法但未
通过验证的候选 Brief 可以保存在 Attempt 中。

禁止持久化完整模型 Prompt、重复 Source 原文、chain-of-thought、reasoning content、API Key、认证
头或不可解析的完整模型响应。非法响应只记录长度、hash 和错误类别。

普通应用日志不得打印 Evidence、查询、Brief 正文或本机文件路径。Retrieval Trace 只保存在本地
SQLite。Langfuse 等外部 Trace 默认关闭；未来启用必须单独获得用户授权并说明数据范围。

## 19. 破坏性切换

当前 Knowledge 是未发布占位实现，没有真实用户。升级时可以静默重置 Knowledge 数据，不显示迁移
确认，也不编写旧模型兼容迁移。

必须删除：

- 旧表：`knowledge_config_versions`、旧 `knowledge_sources`、旧 snapshots/jobs/logs、
  `knowledge_wiki_pages`、`knowledge_page_versions`、`knowledge_index_entries`、
  `knowledge_page_evidence`、`knowledge_wikilinks`、`knowledge_reviews`、
  `knowledge_review_revisions`。
- 旧 FTS：`knowledge_wiki_pages_fts`，以及遗留 `knowledge_documents/chunks/chunks_fts`。
- 旧 Source 文件、staging、quarantine 和 export 目录。
- 旧 Page/Review/Index/Config/Lint/Export repository、runner、API、schemas 和测试。
- `add_to_wiki`、`search_wiki` 及旧 Knowledge Document AI tools。
- 旧 `KnowledgeWikiView` 及 Page/Review/Index 相关前端 types、services、components 和 tests。

重置只作用于 Knowledge 表族和 `$OFFERPILOT_DATA/knowledge/`，不得修改 Application、Conversation、
Interview、Resume、Question、Memory 或其他业务数据。

迁移完成后直接创建第 14 节新表。代码库中不得留下运行时分支判断旧 Knowledge Schema。

## 20. 测试策略

### 20.1 单元测试

- 编码识别、严格失败、换行和 Unicode 规范化。
- Markdown AST 的段落、标题路径、列表、引用、表格、代码和图片映射。
- 超长块句子/行边界拆分，不重叠。
- Snapshot digest 与 Evidence ID 幂等。
- Bundle 路径、缺图、重复图、未使用附件、远程图片、媒体伪装和像素限制。
- source_hash、重复导入和 Origin 追加。
- FTS query parser、短查询回退、归档过滤和异常显式失败。
- Brief Schema、citation、coverage、support 与一次 repair。
- Provider retry/fallback 分类和上下文窗口检查。

### 20.2 Repository/Worker 集成测试

- 上传文件提交协议与 orphan staging 恢复。
- Snapshot/Evidence/FTS 单事务可见性。
- 两条单并发队列可以彼此并行且各自不并发。
- lease 过期、重启恢复、迟到模型结果拒绝和取消。
- Brief candidate 成功替换、失败保留旧 Brief。
- 无 AI 时 Evidence 仍完成。
- 归档、取消归档和永久删除后无文件、行或 FTS 残留。

### 20.3 API 契约测试

- file、bundle、paste、重复上传及所有错误码。
- Source 列表/详情/改名/原件/Asset/归档/删除。
- Evidence 分页、detail、search 和位置回读。
- Brief rebuild 和 Job cancel。
- 所有旧 Knowledge 路由返回 404。
- 响应不泄露绝对路径、Prompt、Provider secret 或原文日志。

### 20.4 前端测试与浏览器验收

- 三种导入入口、重复提示、独立状态、错误恢复。
- Brief/Evidence/原文/处理记录切换。
- 搜索定位、高亮、归档筛选、安全下载和删除确认。
- 旧 Wiki 文案和入口不存在。
- 桌面和移动宽度下无内容、状态或按钮重叠。

### 20.5 真实 Source 与检索门禁

重新导入本次调研使用的 5 份真实 Source。私有或受版权保护原文不得提交仓库；验收工具以外部
fixture 目录和内容 hash 标识样本。另提交可公开的最小边界 fixtures。

硬门禁：

- 5 份 Source 全部完成 Preflight、Extraction 和 Evidence 提交。
- 相同 extractor 重跑的 Snapshot/Evidence 完全一致。
- Evidence 回读成功率 100%。
- Brief Schema、citation、support 和章节 coverage 通过率 100%。
- 每份 Source 至少 4 条人工确认查询，总数至少 20 条。
- Lexical 查询 `Recall@5 = 100%`、`MRR >= 0.9`。
- 自然语言查询 `Recall@5 >= 80%`。
- Brief/Provider 失败时 Evidence 仍可搜索。

若自然语言指标未达标，本实现不得偷偷加入 embedding 或查询模型。应保留测量结果，并针对检索方案
重新开启设计决策。

## 21. 完成门禁

本轮只有同时满足以下条件才可声明完成：

1. 新 Source/Evidence/Brief/Job 垂直切片按本文工作。
2. 旧自动 Wiki 代码、Schema、API、AI Tool、前端和测试全部删除。
3. 定向与完整后端测试、ruff、mypy、前端测试和 build 通过。
4. 新数据目录 smoke 通过；旧 Knowledge 数据静默重置且其他数据不变。
5. 5 份真实 Source、20 条查询和 Brief validation 硬门禁通过。
6. 浏览器完成桌面和窄屏真实交互验收。
7. 非平凡实现经过独立子代理 Code Review，发现的问题已修复或明确接受。

Docker 不可用、真实 Provider 不可用或任何 gate 未执行时，最终报告必须明确说明，不能按通过处理。

## 22. 后续边界

下一轮 Note/Pilot Spec 可以消费本轮稳定的 Source、Evidence 和搜索接口，并增加 Captured Source、
Note Version 与引用保护。它不得回头把 Pilot 总结写成 Source，也不得改变已有 Evidence 身份来迁就
新的检索策略。

图片理解、PDF/DOCX、Web capture、向量召回和导出均需要真实使用或评估触发后单独设计，不属于
本实施 Spec 的隐藏扩展点。
