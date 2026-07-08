# Bugs

> Bug 复盘注册表。每条记录现象/根因/修复/教训四段式。
> 触发与使用指南见 [`architecture/documentation-rules.md`](architecture/documentation-rules.md) §1。

## 当前记录

_(intentional empty registry — 当前无记录。首次新增时按下方模板,从 BUG-1 起编号。)_

> **不是 placeholder**:这是真实的"暂无记录"状态,与"禁止 TODO/待补充"规范不冲突。当首条 BUG 落地后,本段会被具体条目替换。

## BUG 模板

```markdown
## BUG-N: [一句话现象]

**日期**: YYYY-MM-DD
**影响**: [受影响的功能/用户/版本]

### 现象
[观察到的错误行为,可观察的事实]

### 根因
[真正的原因。不是"症状"。代码层面或设计层面的具体定位]

### 修复
[改了什么。引用 commit hash 或 PR 编号。代码是 ground truth,这里只写关键思路]

### 教训
[下次怎么避免。如果有"不该再被破坏"的规则 → 同步加 RULE-N]
```

## 单条长度

软上限 60 行。复杂多阶段 bug 可超限,需在记录头注明超限原因。
