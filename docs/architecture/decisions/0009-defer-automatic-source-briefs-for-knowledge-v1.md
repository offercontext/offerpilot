# ADR-0009: Knowledge V1 暂缓自动 Source Brief

**Status**: Accepted (2026-07-18)
**Decider**: 用户
**Supersedes for V1**: ADR-0008 的实施优先级

## Context（背景）

Source Brief 当前只供人浏览。代码核查确认 Pilot、练习和 Knowledge Context 均不读取 Brief；
“Brief 辅助 Source 粗排”只是长期架构中的候选方向，尚未实现。为稳定 Brief 设计 supported-only
状态机、逐块校验、repair、裁剪和审计，会引入大量模型调用和实现复杂度，却不能改善当前内部
知识消费链路。

Knowledge V1 的首要目标是验证 Source 能否确定性生成 Evidence，以及工作台中的搜索、回读、
状态和运维是否可靠。Pilot、练习和其他内部消费者统一后移到 V2；Brief 在 V1.1 再评估。

## Decision（决策）

1. Imported Source 的 V1 Ingest 在 Evidence 提交并可搜索后完成，不自动排队生成 Brief。
2. 保留现有 Brief 代码和历史数据结构，但 V1 不承诺 Brief 产品能力；V1.1 再决定是否提供手动入口。
3. Brief 未生成、生成中或失败均不影响 Source/Evidence 可用性，也不进入 Knowledge V1 发布门禁。
4. Pilot、练习和 Knowledge Context 不读取 Brief payload，所有可引用知识必须回到 Evidence；
   Knowledge Note 若进入消费链路，也必须保留 Evidence 引用。
5. ADR-0008 和 supported-only 状态机 Spec 暂缓，不继续修复其 review blocker。
6. “Brief 辅助 Source 粗排”保留为后续候选能力。只有真实检索 trace 与对照评估证明稳定收益时，
   才重新设计机器消费契约。

## Consequences（后果）

- 自动 Brief 模型调用降为零，Provider 不可用不再影响 Imported Source 达到可用状态。
- Knowledge V1 的工程投入回到 Source、Extraction、Evidence、FTS、工作台和运维可靠性。
- V1.1 开始前不以 Brief 体验、成功率或状态机作为发布指标。
- 现有 Brief 状态字段和 Worker 可以暂时保留；实现阶段只需切断自动触发并修正状态/UI 语义。
- 若未来恢复自动 Brief，必须基于真实使用数据新建设计，不默认恢复 ADR-0008 的全部复杂度。
