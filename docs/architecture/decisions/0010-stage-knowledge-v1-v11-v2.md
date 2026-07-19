# ADR-0010: Knowledge 按 V1、V1.1、V2 分阶段发布

**Status**: Accepted (2026-07-18)
**Decider**: 用户

## Context（背景）

Imported Source、Extraction、Evidence 和 FTS 已经形成独立可用的知识资料工作台。Brief 只面向人类，
尚未证明实际价值；Pilot、练习和 Knowledge Context 当前也没有接入 Knowledge。把 Brief 或消费链路
纳入首发，会扩大领域契约和验收面，延迟对 Source/Evidence 基础可靠性的验证。

## Decision（决策）

1. Knowledge V1 只发布 Source/Evidence 工作台：Imported Source、确定性 Extraction、Evidence/FTS、
   搜索、回读、引用定位、状态、归档、删除、恢复和诊断。
2. V1 不包含 Brief、Captured Source、Knowledge Note、Knowledge Context、Pilot 或练习消费。
3. V1.1 是 Brief 的决策检查点，不是已承诺版本。先观察 V1 的人工浏览行为，再决定是否需要 Brief、
   是否只保留手动生成，以及需要什么质量门禁。
4. V2 再设计内部消费链路，包括 Knowledge Context、Pilot、练习，以及是否同时引入 Captured Source
   和 Knowledge Note。
5. 各阶段不能用后续能力阻塞前一阶段发布，也不能为尚未确认的后续需求预建抽象。

## Consequences（后果）

- V1 发布门禁可以完全在无 AI Provider 条件下执行。
- 当前自动 Brief 触发必须关闭；遗留 Brief 代码可以保留，但不计入 V1 功能完成度。
- V1 验收重点转为确定性、数据完整性、搜索质量、原文回读、失败恢复和工作台交互。
- V1.1 和 V2 都需要基于 V1 的真实使用数据重新进入设计，不能直接继承旧 Spec 的全部范围。
