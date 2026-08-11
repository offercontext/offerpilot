# 结构化面试故事库：发布验证记录

## 结论

**状态：阻塞；不得发布、推送或合并。**

本记录覆盖产品代码提交 `cc01aae`；实施基线为
`bc706a68e1ae05d355df93a1985e439e0b117fbd`。本轮已完成本地门禁、Story
专项 real-AI 和独立代码复审，但完整 real-AI 仍在既有的面试准备 Provider
调用处发生 `ReadTimeout`。它不是 Story 证据契约失败，也不能以盲目重试或放宽
证据门控处理。因此 UI/Pilot CDP 闭环和截图验收没有启动，不能用 local/API
结果替代。

## 本轮收口

- Provider 未知结果的 Story 客户端会保存服务端安全返回的 Attempt ID，并复用原
  幂等键；源选择或用户原始陈述变化会主动废弃旧冻结请求并生成新 key。
- Evidence Link 上限收紧为每个目标最多 5 条，和批准的 Story 契约一致；AI Schema、
  归一化和仓储校验同步执行该上限。
- Pilot 入口不再呈现 UI 专用的手动保存动作。UI 与 Pilot 的关键操作会由 CDP
  仅记录 allowlist 动作名，不记录页面正文、请求体、模型原文或凭据。
- Browser harness 现在在启动失败时审计 auditor、浏览器、服务和 Provider 代理均已
  退出，并清理隔离临时目录。测试同时验证 observer 注入、合法动作序列和伪造
  动作 fail-closed。

没有新增迁移、HTTP API 或数据库破坏性变化。Evidence Link 上限由 8 收紧到 5，
属于与已批准契约一致的行为收紧。

## 独立代码复审

独立只读复审已完成：无 P0/P1/P2。复审确认启动失败的临时目录与四类本地进程均被
清理，且 CDP observer 的安装、正向动作采集和非法标记拒绝都有回归测试。

## 当前 HEAD 的本地门禁

### 后端五组门禁

结果目录：`%TEMP%\offerpilot-story-release-pytest-20260811-r4`。

先执行完整收集并在排序前拒绝重复 node ID：共 **1,848** 个 node ID，无重复。
随后五组均退出码 0，aggregate 确认覆盖与完整 manifest 完全一致。

| 分组 | 收集/执行 | 允许 skip |
| --- | ---: | ---: |
| agent | 423 | 0 |
| domain | 70 | 0 |
| knowledge | 659 | 4 |
| proposals | 381 | 0 |
| misc | 315 | 0 |
| 合计 | 1,848 | 4 |

仅允许的 4 个 Windows 符号链接权限 skip（均已核验 node ID 与原因）为：

1. `tests/test_knowledge_ingest_integrity.py::test_failed_commit_cleanup_does_not_follow_symlink`
2. `tests/test_knowledge_reset.py::test_cli_rejects_knowledge_root_symlink_with_external_sentinels`
3. `tests/test_knowledge_reset.py::test_cli_rejects_legacy_reset_root_symlink_with_external_sentinels`
4. `tests/test_knowledge_reset.py::test_cli_does_not_follow_nested_escape_symlink`

### 前端十组门禁

结果目录：`%TEMP%\offerpilot-story-release-vitest-20260811-r3`。

完整收集为 **114** 个测试文件；十个命名分组均退出码 0，aggregate 通过：
**862** 项测试、无重复覆盖。当前 Web 指纹为
`b62a1c5e1c40c3fe30ad38d928ebd6e955fb1e973c97e1915be5cd0ad4bcc5f4`，
测试 ID 哈希为
`6756ecdd7c47dfe950a24ed8d95a366e53c5be062ae540f4c36cc70e7e1ab0c6`。

### 定向、静态、构建与 local 验收

| 命令 | 结果 |
| --- | --- |
| `uv run pytest tests/test_browser_network_audit.py tests/test_interview_story_browser_harness.py -q` | 30 passed（1 个既有 Starlette warning） |
| `npm.cmd exec vitest run src/components/InterviewStoryDrawer.interaction.test.tsx src/services/interviewStories.test.ts` | 19 passed |
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过，66 个源文件 |
| `npx.cmd tsc -b` | 通过 |
| `npm.cmd run build` | 通过 |
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过 |
| `uv run oc verify-interview-stories --profile local --static-dir web/dist` | 通过 |

Story local 验收覆盖手动生命周期、UI/Pilot 两个 Proposal 确认、零 Chat 写入、
Provider 未知同 key 恢复、不可验证终态不创建 Version，以及来源变化只读历史。

## Real-AI 与浏览器验收

| 命令/阶段 | 结果 |
| --- | --- |
| `uv run oc verify-interview-stories --profile real-ai --static-dir web/dist` | 通过，约 64 秒 |
| `uv run oc verify --profile real-ai --static-dir web/dist` | **失败**：面试准备请求 `ReadTimeout`，约 134 秒 |
| UI/Pilot CDP 双入口、中文亮色宽屏截图 | **未启动**：必须等待完整 real-AI 通过 |

完整 real-AI 的失败路径位于面试准备 Provider 调用；本轮 Story 产品逻辑未出现在该失败链。
为避免把受控成功误当作相同请求，也避免无界产生 Provider 费用，未进行盲目重试。
后续必须先比较 full 与受控请求的脱敏配置/路由/输入指纹/提示与 Schema 版本、
`max_tokens`、超时和响应模式；确认等价且稳定后，才可重跑完整 real-AI。

此前生成但未满足当前 CDP/截图验收前置条件的本地截图工件已丢弃，未作为发布证据。
本报告不宣称浏览器闭环或截图通过。

## 清理与剩余风险

- 本轮 local、Story real-AI 和测试使用隔离临时数据；没有输出或修改配置密钥。
- harness 回归直接验证启动失败时 Provider 代理、服务、专用浏览器与 auditor 已退出，
  临时目录已删除。
- 因完整 real-AI/CDP 未完成，实施基线文件
  `%TEMP%\offerpilot-interview-story-library-baseline.txt` 按计划保留，禁止重新计算。

剩余唯一发布阻塞是 full real-AI 的面试准备 `ReadTimeout`。在其根因完成脱敏诊断、
完整 real-AI 通过，以及 UI/Pilot CDP、跨领域零写入与逐张截图审计完成之前，
该分支不得发布、推送或合并。
