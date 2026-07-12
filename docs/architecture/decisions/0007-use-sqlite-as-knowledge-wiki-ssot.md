# ADR-0007: 采用 SQLite 作为 Knowledge 运行时唯一事实源

**Status**: Accepted (2026-07-11)
**Decider**: 用户
**Informed by**: `docs/llm-wiki.md`、`llm-wiki-generation`、OfferPilot SQLite-first 架构、2026-07-11 Grill

## Context（背景）

Karpathy pattern 和两个参考实现以 Markdown vault 为运行时存储。OfferPilot则是通过 FastAPI、SQLite事务和 React前端工作的本地 Web应用。若同时维护 SQLite和可编辑 vault，将出现两个事实源、写入顺序和冲突解决问题。

## Decision（决策）

1. SQLite保存 Source元数据、Job、Evidence、Source Brief、Knowledge Note、Log和版本历史，是唯一运行时事实源。
2. 原始 Source和图片附件以不可变文件存入 `$OFFERPILOT_DATA/knowledge/`，SQLite保存路径和 hash；不存大 BLOB。
3. Obsidian兼容通过用户主动下载的只读 ZIP快照实现；导出内容不回写 SQLite。
4. 一次 Ingest或 Note确认的正式关系变化必须在单个 SQLite事务中可见。
5. 结构化关系使用表；仅由单个 Pipeline消费的 Analysis、checkpoint和 staging使用版本化 JSON。

长期领域模型和行为边界以 [Knowledge 系统主文档](../knowledge-system.md) 为准。

## Consequences（后果）

**正面**:

- 与 OfferPilot备份、API和部署模型一致。
- SQLite事务可消除参考文件实现的半次 Ingest。
- Evidence、Note版本和搜索可以使用结构化查询与约束。

**负面**:

- 用户不能把运行目录直接作为 Obsidian vault编辑。
- Source文件和 SQLite仍需可恢复地协调删除。

**风险/不确定性**:

- 导出快照不能表达实时双向协作；若未来需要协作，应重新做独立决策。

## Alternatives Considered（备选方案）

| 方案 | 优点 | 缺点 | 为什么没选 |
|---|---|---|---|
| 纯 Markdown vault | 贴近原始 pattern，可直接用 Obsidian/git | Web API事务、查询和状态机困难 | 不符合 OfferPilot运行架构 |
| SQLite与 vault双向同步 | 同时支持 Web与 Obsidian编辑 | 双 SSOT、冲突和恢复复杂 | 一致性成本不可接受 |
| SQLite存全部 BLOB | 单文件备份 | 大文件放大数据库、删除和流式下载成本 | 文件系统更适合不可变二进制 |

## Related（关联）

- Knowledge 系统主文档：当前领域模型与数据流
