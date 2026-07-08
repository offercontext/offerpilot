# Claude Code Entry

请先阅读并遵守 [AGENTS.md](AGENTS.md)。

本仓库统一维护 Agent 施工协议在 `AGENTS.md`；`CLAUDE.md` 只是 Claude Code / cc 的入口适配层，不单独维护第二套规则。

关键规则以 `AGENTS.md` 为准，包括：

- 分支命名：`<type>/<yyyymmdd>-<name>`
- 开发前确认并使用 Superpowers workflow
- 写完功能必须测试，非平凡代码改动必须开子代理 CR
- 产品事实源是 Feishu PRD / ADR / Check 表
- 不回退 `application_events`、`context_type/context_ref` 等领域口径
- 浏览器验证优先使用内置 Codex browser，除非用户明确要求 Chrome

