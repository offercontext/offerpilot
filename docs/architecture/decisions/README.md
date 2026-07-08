# Architecture Decision Records

> 本目录存放所有架构决策记录(ADR)。每条 ADR 编号 `00NN-<slug>.md`,slug 为动词性短描述。
> 模板与字段要求见 [`.claude/rules/documentation.md`](../../.claude/rules/documentation.md) §4。

## 现有 ADR

_(暂无。首次添加时从 ADR-0001 起编号。)_

## 命名约定

- 文件名:`00NN-<kebab-case-slug>.md`,如 `0001-adopt-langgraph-agent.md`
- 标题:`# ADR-00NN: 标题(动词性)`,如 `# ADR-0001: 采用 LangGraph 作为 Agent runtime`

## 何时写 ADR

- 新增/修改接口、模块、协议、跨包约定、依赖方向
- 领域红线落地(application_events、context_type/ref、auth gate 等)
- 完成迭代功能后,把 `docs/superpowers/specs|plans/` 浓缩为 ADR(v0.1 收尾后激活)

## 必填段

Context / Decision / Consequences / Alternatives Considered。
**Alternatives 不得少于 2 个备选方案**,且每个都要写"为什么没选"。
