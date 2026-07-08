#!/usr/bin/env bash
# PreToolUse hook: git commit 前提醒文档自检
# 触发条件: Bash 工具 + 命令含 "git commit" + staged 改动含 .md 文件
# 行为: 输出清单到 stderr, exit 0 (不阻塞)
# 启用方式: 由 .claude/settings.json 注册(本 PR 暂未带 settings.json,是否启用由团队决定)

set -euo pipefail

input=$(cat)

tool_name=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
if [[ "$tool_name" != "Bash" ]]; then
  exit 0
fi

command=$(echo "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
if ! echo "$command" | grep -qE 'git commit'; then
  exit 0
fi

# 仅当 staged 改动含 .md 文件时才提醒
if ! git diff --cached --name-only 2>/dev/null | grep -qE '\.md$'; then
  exit 0
fi

cat <<'EOF' >&2

📋 文档自检清单(完成适用的项再 commit,不适用可忽略):

[1] 架构决策改动(新增/修改接口、模块、协议、跨包约定、领域红线)?
    → 写/更新 ADR: docs/architecture/decisions/00NN-xxx.md
    → 模板: docs/architecture/documentation-rules.md §4
    → 必填 Alternatives Considered 段(≥2 个备选 + 为什么没选)

[2] Bug 修复?
    → 追加 docs/BUGS.md:现象/根因/修复/教训四段式
    → 如暴露新规则 → 同步加 docs/architecture/rules.md RULE-NN

[3] 完成迭代功能(原 spec/plan 在 docs/superpowers/)?
    → v0.1 收尾前:作历史快照保留,不强求收敛
    → v0.1 收尾后:浓缩为 ADR + 同 commit 删原 spec/plan 文件

[4] 修改了 AGENTS.md 涉及的事实?
    → 检查 SSOT:同一事实是否在多处定义?若是,只留一处,其他改指针
    → 检查长度:根 AGENTS.md ≤ 300 行(软上限)

[5] 新建文档?
    → 默认不写,先看能否加进 ADR/RULE/BUGS
    → 必须新建时:docs/ 下 ≤ 300 行(ADR ≤ 800 行),契约文档超限需注明原因

[6] 本次改动有"为什么选 A 不选 B"的判断?
    → 必须写进 ADR 的 Alternatives 段,不要只写在 commit message

如全部不适用,直接 commit。如适用但未做,先补文档。
规范详见 docs/architecture/documentation-rules.md

EOF

exit 0
