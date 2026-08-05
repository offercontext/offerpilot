# 投递岗位资料（JD）单一事实源设计

**基线：** `origin/main@b4363b0`

**分支：** `feat/20260805-application-jd-versions`

**设计状态：** 待复审；本阶段不进入代码实现。

## 1. 目标与背景

OfferPilot 已具备投递管理、Opportunity Fit 两阶段岗位评估、材料建议、面试准备、文本模拟面试、面试复盘与知识沉淀、Offer 比较与谈薪准备，以及 UI/Pilot 双入口。

当前的基础问题是：同一条投递的 JD 仍由各个流程分别接收临时 `jd_text`。用户需要重复粘贴，同一投递的不同模块也可能使用不同 JD，系统无法判断哪个版本是当前岗位资料，来源变化提示只能依赖各模块自己的快照。

本设计建立 Application 级、用户确认的 JD 原文版本链。用户只需为一条投递保存一次岗位资料；后续 Application-bound 能力默认读取当前 JD 版本，并在 Proposal 中冻结实际使用的版本、原文和哈希。

本任务不是“投递旅程”改造。投递详情继续负责投递事实、状态、岗位资料与面试事件，不增加新的旅程面板、Dashboard 或产品能力调度器。

## 2. 产品边界与不变量

### 2.1 唯一岗位事实

岗位事实只能是用户确认保存的 JD 原文版本及其来源元数据：

- 用户粘贴的 JD 原文；
- 可选来源 URL，仅作 provenance 保存；
- 保存入口：`ui` 或 `pilot`；
- 版本号、原文哈希和创建时间。

以下内容不能写入岗位事实：

- AI 摘要、自动提取的职责、技能标签或岗位分类；
- 匹配结论、岗位评分、录用概率、推荐或拒绝意见；
- 面试预测、市场薪酬或任何未经用户确认的推断。

AI 可以在各自 Proposal 中基于冻结 JD 生成带证据的建议，但不能反向修改 JD 版本链。

### 2.2 版本不变量

1. 每次用户确认保存都会创建不可变新版本，不覆盖旧版本。
2. 当前 JD 是该 Application 可见版本中 `version_number` 最大的版本。
3. 历史版本只读，不能 PATCH 或 DELETE；“恢复旧版本”通过复制原文并确认创建新版本完成。
4. 新建 Application-bound AI Attempt 只能使用当前 JD 版本。
5. 每个新 Proposal/Attempt 必须冻结 `jd_version_id`、`version_number`、原文和原文哈希。
6. JD 更新后，旧 Proposal、Brief、Review、历史知识和模拟面试记录保持原样，并在可比较当前来源时标记 `source_changed`。
7. AI 不得把摘要、标签或推断写回 JD 事实表。
8. URL 只被保存和展示为来源；服务端、浏览器和 AI 流程不抓取、访问或回退访问该 URL。

### 2.3 明确不做

本任务不包含：

- 招聘网站抓取、登录、OCR 或平台 API；
- 自动从 URL 导入 JD；
- JD 的 AI 自动解析并写回岗位事实；
- 匹配分、录用判断、自动投递、自动状态推进；
- Knowledge Source、Dashboard、新 Application Journey 或简历结构化编辑器；
- Offer、谈薪能力改造。

## 3. 数据模型与迁移

### 3.1 新表

新增迁移 `0018_application_jd_versions`，创建表 `application_jd_versions`：

| 字段 | 语义 |
| --- | --- |
| `id` | 自增主键 |
| `application_id` | `applications.id` 外键 |
| `version_number` | 同一投递内从 1 开始递增的版本号 |
| `jd_text` | 用户确认保存的原始字符串，不 trim 后落库 |
| `content_sha256` | 原始 `jd_text` UTF-8 字节的 SHA-256 |
| `source_url` | 可空来源 URL，仅作 provenance |
| `source_kind` | `ui` 或 `pilot` |
| `idempotency_key` | 本次保存请求的 ASCII 幂等键 |
| `created_at` | 创建时间 |

约束和索引：

```text
UNIQUE(application_id, version_number)
UNIQUE(application_id, idempotency_key)
INDEX(application_id, version_number DESC)
```

`application_id` 使用外键并支持 Application 物理删除级联。Application 软删除后，版本对普通 API 不可见；历史 Proposal 中已经冻结的 JD 仍按各自历史保留规则只读展示，不能借此恢复已删除投递。

### 3.2 原文与输入校验

- 使用 `jd_text.strip()` 判断空白，但保存和哈希必须保留用户输入的原始字符；禁止 trim 后落库。
- 使用现有 60KB UTF-8 上限；超限返回 `422`。
- 保留 Unicode、CJK、emoji、换行和原始空格；不得做 Unicode 规范化。
- `source_url` 可为空，非空时最多 2048 个字符；只保存字符串，不发起网络请求。
- `source_kind` 只允许 `ui | pilot`。
- 版本号由服务端在 SQLite `BEGIN IMMEDIATE` 事务中分配，不能由客户端传入。
- 保存请求的完整幂等输入指纹由原始 `jd_text`、`source_url`、`source_kind` 规范化组成；同一 Application、同一幂等键与相同输入返回原版本，不重复创建；同一幂等键与不同输入返回 `409 application_jd_idempotency_conflict`。
- 不同幂等键即使原文相同，也允许创建新版本；前端在内容没有变化时禁用保存，以避免用户无意生成无意义版本。

### 3.3 不回填历史临时 JD

不从 JD Analysis、Resume Match、Material Kit、Opportunity Fit、Interview Preparation、Mock Interview 或其他 Proposal 快照回填当前 JD 版本。这些输入可能只是某次流程的临时内容，不能冒充用户确认的岗位事实。

旧 Proposal 保留已有冻结文本和哈希，不伪造 `jd_version_id`，并显示“历史独立快照”。新 Proposal 才要求关联真实 JD 版本。

## 4. API 契约

### 4.1 读取当前版本

```http
GET /api/applications/{application_id}/job-description
```

有当前版本时返回：

```json
{
  "current": {
    "id": 123,
    "application_id": 42,
    "version_number": 3,
    "jd_text": "用户确认的 JD 原文",
    "content_sha256": "...",
    "source_url": "https://example.invalid/job",
    "source_kind": "ui",
    "created_at": "2026-08-05T10:00:00Z"
  }
}
```

没有版本时返回 `200` 和 `{ "current": null }`。不可见或不存在的 Application 返回稳定 `404`。

### 4.2 读取历史

```http
GET /api/applications/{application_id}/job-description/versions?offset=0&limit=50
GET /api/applications/{application_id}/job-description/versions/{version_id}
```

列表按 `version_number DESC` 排序，默认 `limit=50`，最大 `200`；详情只能读取属于路径 Application 的版本。历史响应保留完整原文、版本号、哈希、来源和创建时间，并明确只读。

### 4.3 创建新版本

```http
POST /api/applications/{application_id}/job-description/versions
```

请求体：

```json
{
  "jd_text": "用户确认的 JD 原文",
  "source_url": "https://example.invalid/job",
  "source_kind": "ui",
  "idempotency_key": "ascii-key-at-least-16"
}
```

语义：

- 新建版本：`201`；
- 同 key 同输入重放：`200`，返回原版本；
- Application 不存在、不可见或已软删除：`404`；
- 空白、超限、非法 source 字段或非法幂等键：`422`，不创建版本；
- 同 key 不同输入：`409 application_jd_idempotency_conflict`，不修改原版本；
- 版本号分配和行插入在同一 `BEGIN IMMEDIATE` 事务中完成，并发请求不得产生重复版本号。

本任务不新增版本 PATCH、DELETE 或 URL 抓取接口。

## 5. Application-bound 流程交接

### 5.1 输入交接

以下新建流程不再接受自由的临时 `jd_text` 作为 Application-bound 来源：

- Opportunity Fit v2 Triage / Deep Review；
- Material Kit 与 Material Proposal；
- Interview Preparation；
- Mock Interview；
- 其他使用 Application-bound JD 的正式入口。

请求改为携带 `jd_version_id`。服务端必须在同一业务边界内：

1. 验证版本属于路径中的 Application 且 Application 可见；
2. 验证该版本仍是当前最大版本；
3. 读取原始 `jd_text`、`version_number` 和 `content_sha256`；
4. 冻结 Proposal/Attempt 所需的最小 JD 快照；
5. Provider 只接收领域契约要求的 JD 原文，不接收 `application_id`、`jd_version_id`、数据库 ID 或版本号。

版本在 Provider 调用前后发生变化时，回写阶段重新验证当前版本。发生漂移返回该领域既有的 `409` 来源冲突语义，不自动重试、不覆盖旧历史、不偷偷改用新版本。

### 5.2 历史兼容

已有历史 Proposal 不重新计算 hash，不伪造版本 ID，不改写冻结原文。读取时：

- 有真实 `jd_version_id` 且当前版本相同：显示“岗位资料 vN，当前使用”；
- 有真实 `jd_version_id` 但当前版本不同：显示“岗位资料 vN，来源已变化”；
- 没有版本 ID 的旧历史：显示“历史独立快照”，只读，不允许由该快照直接发起新生成。

旧接口若仍需要保留读取兼容，应将旧历史和新版本响应使用明确的 schema discriminator 分流，不能把旧快照伪装成当前 JD 版本。

## 6. 投递详情 UI

在现有 ApplicationDetail 中新增“岗位资料”模块，不改变页面总体布局或投递状态职责。

无当前版本时：

- 显示“尚未保存岗位资料”；
- 提供“添加 JD”按钮；
- 说明只保存用户粘贴的原文，不会访问来源链接；
- 不允许 Opportunity Fit、材料、面试准备或模拟面试用临时文本继续生成。

有当前版本时显示：

- `岗位资料 vN`；
- 保存时间和来源入口 `UI / Pilot`；
- 可选来源 URL；
- 原文只读预览；
- “更新 JD”和“查看版本历史”入口。

编辑器包含原文文本框、可选 URL、字符/UTF-8 大小提示和“确认保存为新版本”按钮。保存前不自动调用 AI；内容无变化时禁用保存。保存后刷新当前版本和历史列表，不覆盖旧内容。

任何确定性 `404/409/422` 都显示中文安全文案；`202`、网络异常、响应丢失等结果未知时保留原幂等键和原编辑内容，只允许使用原尝试重试。不得透传 Axios、Provider、快照或用户输入原文到错误提示。

## 7. Pilot 入口

Pilot 只在用户主动表达岗位资料意图时进入该流程，例如：

- “给这个投递补充 JD”；
- “更新岗位描述”；
- “查看当前岗位资料”；
- “查看 JD 历史”。

如果当前没有唯一 Application 上下文，先要求用户选择投递；不猜测投递，也不自动列出并写入。

写入流程：

1. Pilot 询问并接收用户提供的 JD 原文；
2. 可选询问来源 URL；
3. 展示待确认写入卡，包含公司、职位、拟创建版本号、原文预览、字符数、来源入口、URL 和“不访问该链接”的说明；
4. 用户明确确认后，调用与 UI 相同的版本 Repository/API；
5. 成功后显示新版本和后续只读入口，不自动触发岗位评估、材料、面试或其他 AI 流程。

Pilot 复用既有 pending confirmation 与审计机制，不新建第二套审批系统。关联投递的对话继续使用 `context_type=application` 与 `context_ref=<application_id>`；未关联投递使用 workspace 上下文。不得新增或持久化 `jd_version_id`、`application_id` 之外的旧式聊天上下文字段，不得把 JD 原文写入 Chat 之外的领域表，除非用户确认的是 JD 版本写入卡。

## 8. 来源变化、并发与安全

必须覆盖以下竞态：

- 打开生成抽屉后，另一窗口创建新 JD 版本；
- Provider 调用期间创建新版本；
- 两个保存请求同时竞争下一个版本号；
- 同一幂等键的相同输入并发重放；
- 同一幂等键的不同输入冲突；
- 保存响应丢失后使用原 key 重试；
- 旧版本 ID 发起新生成；
- Application 软删除或物理删除与版本读取/保存同时发生。

预期结果：

- 同一版本号最多有一条记录；
- 同 key 只有一条版本记录；
- 只有一个请求取得下一个版本号；
- 旧版本不能启动新 Application-bound AI 流程；
- Provider 期间发生版本变化时不写入 ready；
- 已写入历史不被覆盖，不产生隐式第二次 Provider 调用；
- 浏览器只能访问本地页面与 `/api`，服务端不访问 `source_url` 或招聘平台。

## 9. 测试与真实验收

### 9.1 后端与迁移

- 新库创建 `application_jd_versions`；
- 从上一版本真实 DDL 升级，验证旧表、既有数据、哈希和迁移记录；
- Application 软删除后版本不可见；物理删除级联清理版本；
- 版本号和联合唯一约束；双 SQLite 连接并发创建只得到一个下一个版本号；
- 同 key 同输入返回原版本，同 key 不同输入稳定返回 `409`；
- 空白、60KB 边界、超限、Unicode/CJK/emoji、原始空格和换行保留；
- `source_url` 只保存，不发出任何 HTTP 请求；空 URL、超长 URL、非法类型回归；
- 读取越权、不存在版本、非当前版本生成均稳定失败；
- 版本变化、Provider barrier、响应丢失、结果未知、来源冲突和历史只读；
- Provider payload 只含冻结 JD 原文和领域允许字段，不含内部 ID、版本号或 URL 抓取结果。

### 9.2 前端与 Pilot

- ApplicationDetail 空状态、当前版本、更新新版本和历史只读；
- 内容无变化禁用保存；保存确认后才发出一次写请求；
- 版本创建 `201`、幂等 `200`、`404/409/422` 和结果未知中文文案；
- 当前版本更新后旧 Proposal 显示来源变化，旧原文仍可读；
- UI 和 Pilot 使用同一保存 API/Repository，不产生第二套版本逻辑；
- Pilot 未主动表达意图时不显示 JD 写入卡、不发 Chat 写入、不调用 Provider；
- Pilot 确认前只展示卡片，确认后才创建 JD 版本；
- UI/Pilot 不触发岗位评估、材料、面试、Knowledge、Offer、提醒或投递状态写入；
- 没有 `jd_version_id` 的旧 Proposal 以历史独立快照只读显示。

### 9.3 隔离浏览器验收

使用临时隔离数据目录和现有配置的静默副本，中文合成案例完成：

1. 创建一条投递并在 UI 保存 JD v1；
2. 验证 Opportunity Fit、材料或面试准备入口默认引用 v1；
3. UI 更新为 v2，确认 v1 历史仍可读且旧 Proposal 标记来源变化；
4. 通过 Pilot 询问并展示 JD 写入确认卡，确认后创建 v3；
5. 验证后续新流程只使用 v3，不需要重复粘贴 JD；
6. 审计浏览器仅访问本地页面与 `/api`，服务端仅访问已配置 Provider，不访问招聘平台或保存的 URL；
7. 清理合成 Application、JD 版本、Proposal、Chat 记录和临时目录，并确认源数据目录不变。

## 10. 实施顺序与提交边界

实施前先由用户复审本设计，再编写测试先行实施计划；计划通过后才进入代码。

实现顺序：

1. 迁移、模型、版本 Repository、当前/历史读取与保存 API；
2. 幂等、并发、原文哈希、可见性、删除和迁移回归；
3. Opportunity Fit、Material Kit、Interview Preparation、Mock Interview 的当前 JD 版本交接；
4. ApplicationDetail 岗位资料 UI、历史和来源变化展示；
5. Pilot 询问、确认卡和同一保存 API；
6. 真实隔离 API、浏览器验收、零外联与零跨领域写入审计；
7. 完整后端分组门禁、前端全量、构建、local/real-AI verify、独立代码复审和发布报告。

各领域按逻辑独立提交。提交格式使用 `<type>: AI <subject>`。在设计和实施验收完成前，不推送、不合并，也不修改根工作区已有未提交的 `tests/test_smoke.py`。
