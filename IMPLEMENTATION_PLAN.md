# Implementation Plan: Knowledge Evidence 元数据过滤与 Brief 修复闭环 (KBR-01 ~ KBR-08)

> **Status**: Stopped by product scope decision (2026-07-18)。KBR-02/KBR-03 的 Source/Evidence 成果继续
> 服务 Knowledge V1；Brief repair 与 KBR-08 Brief 发布验收后移到 V1.1 候选，不再继续实施。

**BASE_COMMIT**: `36802ab`（KBR-01 完成 HEAD，即 KBR-02~08 起始点）
**分支**: `feat/20260710-knowledge-wiki`（延续 KBR-01，单 worktree；未新建隔离 worktree，因 KBR-01~08 为同 feature 连续 ticket 组，新建会割裂 history）
**调度模式**: 全部实现工作由 subagent 完成；主循环只负责依赖解析、派发、验收、Review 编排、汇报。
**Spec**: `docs/superpowers/specs/2026-07-15-knowledge-evidence-metadata-and-brief-repair-design.md`

## 依赖图

```
KBR-01 → KBR-02 ┬→ KBR-03 ───────────┐
                 └→ KBR-04 → KBR-05 → KBR-06 ─┤
                                               ├→ KBR-07 → KBR-08
```

## 每张 Ticket 的 subagent 流程
理解现状 → 写失败测试 → 最小实现 → 重构 → 定向验证 → 独立子代理 Review（Standards+Spec 双轴）→ 修复发现 → commit(`KBR-XX:` 开头，不用 --no-verify) → 勾选 tickets.md → 主循环验收 → 重新计算 frontier → 下一张。

## Stage 1: KBR-01 — 异步 Ingest→Brief 最高层测试 seam
**Status**: Complete (commit 36802ab)。测试 seam: `tests/test_knowledge_kbr01_seam.py`。

## Stage 2: KBR-02 — 结构化 provenance + frontmatter 排除
**Goal**: 有效 frontmatter 不生成 Evidence/FTS/Brief；提取最小 provenance；canonical Source/hash 不变；非法单字段只忽略+警告；provenance 不进 FTS/support 但用于出处展示。
**Status**: Complete (e132722 + ed089d2 修复 Review 4 项；双轴 pass-with-notes)

## Stage 3: KBR-03 — 元数据样板过滤 + 规则统计（Blocked by KBR-02）
**Status**: Complete (e982d08 + d2f272f 修复 Review 4 项；双轴 pass-with-notes)

## Stage 4: KBR-04 — Brief Schema v2 + 派生 coverage（Blocked by KBR-02）
**Status**: Complete (5486c00；双轴 Spec pass / Standards pass-with-notes 仅既有死代码；2 nit 转交 KBR-05)

## Stage 5: KBR-05 — 汇总质量失败 + 完整 Attempt 报告（Blocked by KBR-04）
**Status**: Complete (926f21d + a7933e5 修复 Review 7 项；双轴 pass-with-notes)

## Stage 6: KBR-06 — 结构化 patch 唯一一次 repair（Blocked by KBR-05）
**Status**: Complete (f06c69b + 6ff352b 修复 Review 3 项；双轴 pass-with-notes；possibly unbound 为 Pyright false positive 已确认)

## Stage 7: KBR-07 — Knowledge-only 破坏性 reset（Blocked by KBR-03,04,06 — 全满足）
**Status**: Complete (13eeebd + 7e90d5d 修复 Review 4 项；双轴 Standards pass / Spec pass-with-notes；表清单 Knowledge 闭集独立核对)

## Stage 8: KBR-08 — @Async 真实回放 + 发布验收（Blocked by KBR-07）
**Status**: Deferred。V1 改为 Source/Evidence 发布验证，不再以 Brief 回放作为完成门禁。
