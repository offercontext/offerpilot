# 结构化面试故事库：发布验证记录

## 结论

**状态：阻塞，不能发布、推送或合并。**

本记录覆盖的实现 HEAD 为 `14dd130108b556e549e45059587a3976020a1f03`，实施基线为
`bc706a68e1ae05d355df93a1985e439e0b117fbd`。本文件仅记录最终门禁的真实结果；其后仅提交本报告，未修改产品代码。

阻塞原因是 Story 专项 real-AI 在 UI Proposal 阶段返回
`502 story_unverifiable`。一次隔离、脱敏诊断显示该请求经历一次允许的格式修复后，仍为
`semantic_contract`；不是超时、Provider HTTP 错误或网络结果未知。因此没有放宽证据校验、JSON 契约或重试策略。

完整 real-AI verify、CDP 浏览器双入口闭环和截图验收尚未运行，不能由 API/local smoke 替代。

## 范围与变更性质

- 本功能新增结构化面试 Story、不可变 Version、Evidence Link、用户原始陈述和 Proposal Attempt 的领域能力；迁移为 `0019`，不改写既有历史数据。
- 本次发布收口新增两处测试稳定性修正：在完整串行门禁下为两项刻意慢处理器测试提供足够的测试超时窗口；不改变生产行为、AI 调用、证据门控或 API。
- 无新的破坏性 API 变更；部署仍需执行本分支已有的 `0019` 迁移。

## 已完成的本地门禁

### 后端完整分组门禁

结果目录：`%TEMP%\\offerpilot-story-release-pytest-14dd130`。

使用当前实现 HEAD 收集到 1,819 个 node id，收集阶段未发现重复 node id。五组均退出码为 0：

| 分组 | 通过 | 允许 skip |
| --- | ---: | ---: |
| agent | 423 | 0 |
| domain | 70 | 0 |
| knowledge | 655 | 4 |
| proposals | 355 | 0 |
| misc | 312 | 0 |
| 合计 | 1,815 | 4 |

允许的 4 个 skip 均已核验为当前 Windows 环境没有创建符号链接权限，且仅为以下 node id：

1. `tests.test_knowledge_ingest_integrity::test_failed_commit_cleanup_does_not_follow_symlink`
2. `tests.test_knowledge_reset::test_cli_rejects_knowledge_root_symlink_with_external_sentinels`
3. `tests.test_knowledge_reset::test_cli_rejects_legacy_reset_root_symlink_with_external_sentinels`
4. `tests.test_knowledge_reset::test_cli_does_not_follow_nested_escape_symlink`

聚合输出确认覆盖完整的 1,819 个测试；后端脚本的 aggregate 为控制台聚合结果，不生成虚构的 aggregate JSON。

### 前端完整分组门禁

结果目录：`%TEMP%\\offerpilot-story-release-vitest-66b042d`。

十个命名 Vitest 分组全部退出码为 0，实际执行 114 个测试文件、855 项测试；聚合 source hash 为
`6fbdb172bb6383ebcf275c496649c9c49e1238d11e9719c050d6e46633b932de`，测试 ID 哈希为
`ef09ff497bffb8dcd90902d69ebb12f3817ce77ebb79ecf407d959cd8a4614f2`。

`14dd130` 仅修改 Python 测试，前端源码、测试、配置、锁文件及门禁脚本与上述前端 manifest 一致。前端套件仍会产生既有 React `hasSider` 警告，但不影响退出码。

### 静态、构建与 local 验收

| 命令 | 结果 |
| --- | --- |
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过（66 个 source files） |
| `npx.cmd tsc -b` | 通过 |
| `npm.cmd run build` | 通过 |
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过 |
| `uv run oc verify-interview-stories --profile local --static-dir web/dist` | 通过 |

Story local 验收覆盖手工生命周期、UI/Pilot Proposal 确认、Chat 零写入隔离、Provider 未知结果同 key 恢复、不可验证终态不创建 Version，以及来源变化的只读历史标记。

## Real-AI 与浏览器验收

### Story 专项 real-AI（失败）

命令：

```powershell
uv run oc verify-interview-stories --profile real-ai --static-dir web/dist
```

结果：退出码 1。UI Proposal 未进入 ready，返回 `502 story_unverifiable`。

在独立临时数据目录中，以相同类型的隔离 Story 流程补充了一次脱敏诊断。仅保留以下诊断字段：

| 字段 | 值 |
| --- | --- |
| failure category | `semantic_contract` |
| repair attempted | `true` |
| repair count | `1` |
| elapsed | `35,824 ms` |
| HTTP status | `null` |
| timeout | `false` |

诊断未输出配置、密钥、简历/JD/复盘原文、模型原文或 Provider request id。隔离数据在 `finally` 中释放并删除。

### 完整 real-AI、CDP 与截图（未运行）

因 Story real-AI 的前置条件失败，以下验收**未启动**：

- `oc verify --profile real-ai` 完整验证；
- UI 与 Pilot 的真实浏览器/CDP 闭环；
- 中文、亮色、宽屏截图录制与逐张检查。

本轮没有启动 Story CDP harness、临时浏览器或 Provider 代理，因此不存在可作为发布证据的浏览器截图，也没有需要额外关闭的本轮浏览器/代理进程。不得将 local/API 验收表述为浏览器闭环通过。

## 清理与工作区

- local 与 real-AI 验收均使用隔离临时数据；运行完成后服务和数据目录已按验收流程清理。
- 保留仅含门禁输出的临时结果目录，便于复核；其中不包含配置或业务原文。
- 实施基线文件 `%TEMP%\\offerpilot-interview-story-library-baseline.txt` 按已批准计划保留：因为最终 real-AI/CDP 门禁未全绿，禁止重新计算或删除该基线。
- 本报告提交后将重新执行工作区 clean 与 `git diff --check` 检查。

## 剩余风险与后续动作

1. 必须先在不放宽契约的前提下，定位并修复/稳定复现 `semantic_contract` 的真实 Provider 输出；必要时应以新的设计/测试审查处理，不能通过增加业务重试掩盖。
2. Story 专项 real-AI 通过后，重新运行完整 real-AI verify。
3. 仅在两个 real-AI 门禁通过后，执行 UI/Pilot 中文亮色宽屏 CDP 闭环、截图和跨领域零写入审计。
4. 任何产品或测试代码修复都会使本记录中的最终门禁证据过期，必须重新运行完整门禁并更新本报告。
