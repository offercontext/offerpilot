# 文档规范

> 本文件是 agent 写文档时的强制规范,跨 Codex / Claude / Cursor 适用。
> 触发时机:写/改任何 .md 文档前;`git commit` 时(若启用 `.claude/hooks/pre-commit-doc-check.sh`,详见 hook 注册讨论)。
> 工程文档优先为 agent 与维护者服务;`README.md` 等对外文档仍以人类读者为主。

## 1. 文档类型决策树

改动完成后,按以下顺序判断该写什么文档:

```
这次改动是?
│
├─ 架构决策(新增/修改接口、模块、协议、跨包约定、依赖方向、领域红线)
│  └─ 写 ADR: docs/architecture/decisions/00NN-xxx.md
│
├─ Bug 修复
│  └─ 追加 BUGS: docs/BUGS.md(现象/根因/修复/教训四段式)
│     └─ 如果该 bug 暴露了"不该再被破坏"的规则 → 同时加 RULE
│
├─ 完成迭代功能(原 spec/plan 在 docs/superpowers/)
│  └─ 浓缩为 ADR + 同 commit 删除原 spec/plan 文件
│  └─ ⚠️ 激活时机:v0.1 收尾后启用。当前阶段(2026-07)仍处于快速成型,
│     原 spec/plan 暂作历史快照保留,不强制收敛。
│
├─ 发现新的显式约束(被破坏过 ≥1 次,或绕过代价极大)
│  └─ 加 RULE: docs/architecture/rules.md
│
├─ 环境变量/命令/配置变更
│  └─ 更新 AGENTS.md 对应段 + .env.example / README 安装段
│
└─ 都不适用
   └─ 不写新文档。如需说明,写在 commit message 或 ADR 的 Related 段
```

## 2. 长度上限(软约束)

| 文档类型 | 软上限 | 超过怎么办 |
|---|---|---|
| 根 `AGENTS.md` | 300 行 | 拆出独立 doc 并改为指针;确需保留时在文档头注明超限原因 |
| ADR | 800 行(含 Alternatives) | 拆为多个 ADR(如 0009a/0009b) |
| `docs/` 下其他文档 | 300 行 | 拆分或浓缩 |
| RULE 单条 | Why 段 ≤ 5 行 | 删冗余示例,只留根因 |
| BUGS 单条 | ≤ 60 行 | 删实施细节,代码是 ground truth |

**超限例外**:契约文档(如 `python-rewrite-contract.md`)与跨多模块数据流文档可超限,需在文档头一行注明 `<!-- 超限原因: ... -->`。

## 3. SSOT 原则(Single Source of Truth)

每个事实**只能在一处定义**。其他位置只能放指针。

| 事实 | SSOT 位置 | 其他位置只能写 |
|---|---|---|
| 领域红线(application_events、context_type/ref、v0.1/0.2/0.3 范围) | `AGENTS.md` §6 | 指针 |
| Python rewrite 契约 | `docs/python-rewrite-contract.md` | 指针 |
| P0 发布清单 | `docs/p0-release-checklist.md` | 指针 |
| 飞书 PRD / ADR / Check 表 | 飞书 wiki(见 AGENTS.md §4) | 指针 + token |
| 架构决策 | `docs/architecture/decisions/00NN-*.md` | `AGENTS.md` 只列 ADR 编号 + 一句话 |
| 显式规则 | `docs/architecture/rules.md` | ADR 引用 RULE 编号 |

**禁止**:在多个文档重复同一事实。例如"v0.1 面试范围"不能同时出现在 `AGENTS.md`、`README.md` 和某个 plan 里——只在 `AGENTS.md` §6 定义,其他位置写 `→ 详见 AGENTS.md §6`。

## 4. ADR 模板

```markdown
# ADR-00NN: 标题(动词性,如"采用单 Agent 架构")

**Status**: Accepted(YYYY-MM-DD)
**Decider**:
**Informed by**: (参考的飞书 PRD / 文档 / 讨论)

## Context(背景)
为什么现在做这个决策?触发因素是什么?
- 业务需求 / 技术约束 / 之前的 bug

## Decision(决策)
我们决定做什么。具体到可执行的层面:
1. ...

## Consequences(后果)
**正面**:
- ...

**负面**:
- ...

**风险/不确定性**:
- ...

## Alternatives Considered(备选方案 — 必填,详细)

| 方案 | 优点 | 缺点 | 为什么没选 |
|---|---|---|---|
| 方案 A | ... | ... | ... |
| 方案 B | ... | ... | ... |

(如有 v1→v2→v3 演进,在此段说明每次修订的原因)

## Related(关联)
- ADR-00XX:(关联决策)
- docs/xxx.md:(相关文档)
- BUGS.md BUG-XX:(相关 bug)
- RULE-NN:(由此 ADR 衍生的规则)
```

**必填段**:Context / Decision / Consequences / Alternatives Considered。
**Alternatives 不得少于 2 个备选方案**,且每个都要写"为什么没选"。

## 5. AGENTS.md 内容约束

根 `AGENTS.md` 只留:
- 项目一句话定位(§1)
- 开工前置检查(§2)
- 分支命名(§3)
- 事实源指针(§4)
- 代码改动规则(§5)
- 领域红线(§6)
- 验证 / CR / Superpowers / 飞书 / 汇报格式(§7–§11)
- 文档规范指针(§11,指向本文件)

**禁止内容**:架构详解(放 ADR)、版本变更摘要(放 ADR 的 Alternatives 段)、环境变量完整列表(放 `.env.example`)。

## 6. 迭代产物处理

完成迭代功能后:
1. 把 `docs/superpowers/specs/*.md` + `docs/superpowers/plans/*.md` 浓缩为 ADR
2. **同 commit 删除原 spec/plan 文件**(避免半浓缩中间态)
3. 如有 bug 修复,同步追加 `BUGS.md`
4. 如有新规则,同步追加 `rules.md`

**⚠️ 激活时机**:v0.1 收尾后启用。当前阶段(2026-07)所有 `docs/superpowers/` 文档作为历史快照保留,不强求收敛。

**禁止**:在 v0.1 收尾后,仍然在 `docs/superpowers/` 留已完成功能的文档。

## 7. 禁止条款

1. 不在 `docs/` 下写超过 300 行的文档(ADR 除外),契约文档超限时在文档头注明原因
2. 不在多个文档重复同一事实(SSOT)
3. 不新建 `docs/<random>/` 目录,统一放 `docs/architecture/` 或 `docs/superpowers/`
4. 不写"教学性"叙事文档(工程文档直接结构化要点)
5. 不留 placeholder(`TODO`、`待补充`),要么写完整,要么不写
6. 不在没有 ADR 的情况下,把"为什么选 A 不选 B"只写进 commit message

## 8. RULE 使用指南

### 何时读 RULEs

任何涉及以下模块的改动,启动时必须先读 [`rules.md`](./rules.md):

- `application_events` 表与 `event_type/subtype/tags` 语义
- `context_type/context_ref` 上下文模型
- v0.1 / v0.2 / v0.3 功能范围边界
- Auth gate / auth middleware / auth session
- SQLite migrations 与 schema 演进
- Agent runtime(langgraph / AgentEngine)
- Skill registry / trust model / provenance
- LiteLLM provider routing
- HITL 写操作确认流
- AI tool schemas 与产品语言对齐

绕过任何 RULE 前,**停下,先到 PR 描述里写出理由**。大多数情况下绕过是错的。

### 何时新增 RULE

**应该新增**:

1. **bug 修复后**:某个 bug 揭示了"不该再被破坏"的规则(尤其已出现 2 次以上)
2. **架构决策落地**:ADR 决策有"绕过代价极大"特性(如领域红线、依赖方向、单一入口)
3. **code review 反复纠正**:reviewer 在 3 个 PR 里都纠正了同一件事

**不应新增**:

- TypeScript / React / Python 通用规范(交给 linter)
- ADR 已完整说明的决策(只在 ADR 不够"显眼"时加 RULE 指针)
- 一次性 bug 无通用教训(写进 BUGS.md 就够)
- 实现细节(放代码注释,不是 RULE)

### RULE 格式模板

```markdown
### RULE-N: [一句话规则]

**规则**:[具体的、可验证的规则描述,不要模糊]

**Why**:[为什么这条规则存在。来自 bug 引用 BUG-XX,来自 ADR 引用 ADR-XXXX。≤ 5 行]

**How to apply**:[具体执行方式。改动 X 时检查什么、测试如何覆盖、grep 什么关键字验证]

**关联**:[BUG-XX / ADR-XXXX / 相关 RULE-XX]
```

### 对人类 reviewer

PR 描述模板应含勾选项:"我已阅读 [RULEs](docs/architecture/rules.md),本 PR 未违反任何规则"。触碰 RULE 涉及模块但未勾选,**request changes**。
