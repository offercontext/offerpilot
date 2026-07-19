# ADR-0008: Source Brief 采用 supported-only 发布语义

**Status**: Deferred (2026-07-18；由 ADR-0009 暂缓实施)
**Decider**: 用户
**Informed by**: Source Brief Attempt 18、2026-07-18 Grill

> 本 ADR 的 supported-only 语义本身未被判定为错误，但自动 Source Brief 已退出 Knowledge V1
> 核心链路。V1 不继续实现或修复本 ADR 的状态机；仅当真实人工使用证明 Brief 值得继续投入时，
> 才重新评估本决策。

## Context（背景）

Attempt 18 在一次局部 repair 后重新校验全部 block，两个未修改且首次为 `supported` 的 block 翻转为 `partial`，相同事实在同轮其他位置又被判为 `supported`。把概率性 verdict 的全量重算作为全有或全无门禁，会使 Brief 成功依赖随机翻转，而不是候选内容是否发生变化。

## Decision（决策）

Source Brief MVP 采用 supported-only 发布语义：首次通过的未修改 block 冻结 verdict；repair 后只复验新增或修改的 block；复验仍不受支持的可选 block 可以确定性删除。可删除性不按字段名静态划分，而由删除后的结果决定：Brief Schema v2 仍合法，并且所有实质章节仍由至少一个保留 block 的有效 citation 覆盖。MVP 保持 Schema v2 的现有最低数量，不引入 Schema v3。最终发布的每个事实 block 必须为 `supported`。一次 generation、一次 repair 后状态机必须终止，不引入 `ready_with_warnings`。

Verdict 只在同一次 Attempt 内复用，不做跨 Attempt 持久缓存。未修改由 Validator 实际输入指纹定义：规范化 statement、保持顺序的 evidence_ids 与 snapshot_id 完全相同；block_path 重排不使 verdict 失效，输入任一部分变化都必须复验。Provider failover 不推翻同一次 Attempt 内已冻结的 verdict。

确定性裁剪只适用于 Validator 成功返回的 `partial`、`unsupported` 或 `contradicted`。Validator 协议解析失败、调用失败或程序门禁失败表示结果未知或契约不成立，不能通过删除 block 伪装成内容质量结论；重试与 failover 耗尽后 Attempt 失败。

MVP 继续以 overview、key point、section guide summary 和 limitation 等现有 UI block 为校验单位，不引入内嵌或持久化 `BriefClaim`。只有 5-10 个真实 Source 的回归数据证明复合 block 是主要失败来源时，才重新设计 claim 粒度；`BriefClaim` 即使未来引入，也不是 Knowledge Note、事实图谱节点或可检索知识对象。

Changed-only 复验之后不运行第二次全局模型审计。发布前仍完整运行确定性门禁，并确认每个保留 block 都有本 Attempt 内可复用的 supported verdict。重复全量 Validator 只用于离线稳定性评估，不参与线上 Attempt 状态机。

本轮以正常无重试的 Attempt 18 回放不超过 37 次模型调用作为性能硬门禁，暂不实现 Validator 并发、批量校验或新 Provider。真实 Source 的墙钟时间只记录；若仍超过 10 分钟，再单独评估有界并发，避免把共享 retry、failover 和 Attempt ledger 的并发改造带入正确性 MVP。

MVP 沿用 Provider 默认采样参数，不强制设置 temperature 或 top_p。采样参数为零也不是确定性保证，且不同 Provider 的参数能力不同；完成后先用 5-10 个真实 Source 重复重建测量稳定性，再决定是否引入按阶段配置。裁剪导致实质章节失去 coverage 时直接失败，不增加 extractive fallback。

裁剪后成功仍发布为普通 `ready`，不引入 `ready_with_warnings`，current Brief 也不保留删除占位符。每次自动删除都在 append-only Attempt ledger 中留下 `prune` 步骤，记录定位、稳定原因码和输入指纹但不复制 statement 或 Evidence 正文；裁剪数量作为后续离线质量指标。

## Consequences（后果）

Brief 可能比生成候选更短，但不会发布未受支持的事实。若不可删除的最小骨架或章节 coverage 无法由 supported 内容满足，Attempt 仍然失败。跨 Attempt 缓存若未来引入，必须另行定义 Validator Prompt、模型、采样参数与 Evidence 内容变化的失效协议。

MVP 完成以 Attempt 18 离线回放、37 次正常路径调用上限、关键状态机分支回归、完整本地 gate 和一次真实 Source 1 重建为门禁。真实墙钟耗时只记录；5-10 个 Source 的重复稳定性实验在 MVP 后执行。
