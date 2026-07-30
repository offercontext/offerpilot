# 发布验证报告：证据门控面试与下一步建议

日期：2026-07-30  
分支：`feat/20260724-evidence-gated-interview-preparation`  
验证 HEAD：`399462c`  
状态：未发布；未推送；未合并

## 代码与差异卫生

- `git diff --check origin/main..HEAD`：退出码 0。
- 工作区：干净。
- 本轮产品代码未修改；新增提交 `399462c` 仅补充 DashboardView 挂载测试。

## 后端分组门禁

使用 `scripts/windows-pytest-groups.ps1`，结果目录位于系统临时目录，随后由 `-Aggregate` 校验完成标记、JUnit 摘要、重复 node id 和完整覆盖集合。

| 分组 | 收集 | 执行 | 允许跳过 |
| --- | ---: | ---: | ---: |
| agent | 423 | 423 | 0 |
| domain | 70 | 70 | 0 |
| knowledge | 658 | 658 | 4 |
| proposals | 283 | 283 | 0 |
| misc | 196 | 196 | 0 |
| 合计 | 1630 | 1630 | 4 |

聚合结果：通过。分组 node id 无重复，和完整 `--collect-only` manifest 完全一致。4 个跳过均为 Windows 无符号链接权限能力限制，且仅限既定 Knowledge 安全测试；没有额外跳过。

## 静态、前端与运行时门禁

- `uv run ruff check .`：退出码 0。
- `uv run mypy src`：退出码 0，61 个源文件无问题。
- `npm.cmd test -- --run`：退出码 0，203 个测试文件，657 passed，0 failed，0 skipped。
- `npm.cmd exec -- tsc -b --pretty false`：退出码 0。
- `npm.cmd run build`：退出码 0，Vite 生产构建完成。
- `uv run oc smoke --static-dir web/dist`：退出码 0。
- `uv run oc verify --profile local --static-dir web/dist`：退出码 0。
- local verify 源目录快照：验证前后未变化。
- `uv run oc verify-mock-interview --static-dir web/dist`：退出码 0，隔离 Mock API 验收 `attempt_1:success`。该命令明确不替代浏览器/CDP 证据。

### real-AI 状态

- `uv run oc verify --profile real-ai --static-dir web/dist`：退出码 1，未通过。
- 失败为 Mock Interview 真实 Provider 输出稳定性：三次新 Attempt 均在反馈阶段返回脱敏契约失败 `mock_interview_unverifiable:missing_turn_evidence`。
- 未放宽证据门控、JSON 契约、502 语义或人工确认；失败 Attempt 按既有清理语义处理。
- 本次结果不能声称完整 real-AI verify 通过。

## 浏览器验收

### 已完成：本地只读路径

在隔离本地服务和内置浏览器中完成：

1. 工作台显示中性“查看投递详情以确认下一步”。
2. 点击“前往”进入对应投递详情。
3. “稍后处理”折叠后可恢复；“忽略”仅当前会话隐藏，刷新后恢复。
4. 详情事实不足时不生成具体结论或无效导航。
5. 控制台错误数为 0；本次操作未触发 AI、材料生成、Proposal、面试、草稿确认或投递保存操作。

当前本地数据没有可供展示的来源风险或已安排面试事件，因此只读来源风险按钮及面试事件入口未在该数据集上展开；相应边界由挂载测试覆盖。

### 未完成：隔离真实 AI 浏览器闭环

本轮没有把 API smoke 结果替代浏览器闭环。由于完整 real-AI verify 在 Mock Interview 反馈阶段出现上述契约失败，不能报告 Opportunity Fit、面试准备、复盘/知识沉淀及 Mock Interview 的隔离真实浏览器全链路均通过。

## 清理与剩余风险

- 临时 pytest 结果、服务进程和浏览器标签已清理；本地服务端口 `18766` 已停止监听。
- 未输出密钥、简历/JD 原文或模型原文。
- 代码审核层面无新增 P0/P1；本轮 P2 测试增强已提交。
- 发布阻塞：真实 Provider 的 Mock Interview 反馈输出仍有可复现的 `missing_turn_evidence` 波动；需在不放宽契约的前提下重新完成真实浏览器闭环后，才能进入推送/合并评估。
