# Offer 比较与谈薪发布验证报告

日期：2026-08-04
分支：`feat/20260801-offer-negotiation`
范围：仅发布收口；未新增 Offer、谈薪、Pilot、HITL 或证据门控语义；未推送、未合并。

本文件是当前分支唯一有效的发布验证报告。`artifacts/2026-08-03-offer-negotiation/release-verification.md` 为历史路径，已明确标记废弃。

## 本轮收口变更

- 日历测试改用测试内创建的投递时间推导月份，消除固定月份导致的日期敏感失败。
- smoke 隔离数据库销毁前停止 Knowledge runtime 并释放数据库 engine，避免后台 worker 在临时目录删除后继续访问 SQLite。
- 新增前端稳定分组门禁脚本，逐组持久化 Vitest JSON 报告、文本日志和完成标记，再执行覆盖集合聚合。
- 前端门禁每次重新发现当前测试集合，并将 `web/src`、前端配置/锁文件和分组脚本内容绑定到 manifest；负向测试使用 `tmp_path` 最小仓库副本，不改写真实源码。
- `RepositoryRoot` 会规范化尾部分隔符，并在计算相对路径前校验根目录边界；补充尾部 `\`、省略参数默认根目录和 `web`/`web-evil` 相邻前缀目录拒绝回归。
- 补充 worker 停止后 dispose 顺序及 worker 未退出时禁止 dispose 的回归测试。

## 静态与测试门禁

| 检查 | 结果 |
|---|---|
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过，64 个源文件 |
| `npm.cmd run build`（`web`） | 通过 |
| `uv run pytest tests/test_calendar_api.py -q` | 3 passed |
| `git diff --check origin/main..HEAD` | 通过 |

### 后端五组门禁

完整收集 manifest：**1748 个 node id**。五组均退出码 0；聚合校验确认无重复、并集与完整 manifest 一致，五组完成标记、JUnit 和收集摘要均匹配。

| 分组 | 收集/执行 | 允许 skip |
|---|---:|---:|
| agent | 423 / 423 passed | 0 |
| domain | 70 / 70 passed | 0 |
| knowledge | 659 / 655 passed | 4 |
| proposals | 287 / 287 passed | 0 |
| misc | 309 / 309 passed | 0 |
| 合计 | 1748 / 1744 passed | 4 |

Knowledge 的 4 个 skip 仅为既定 Windows 符号链接权限条件，node id 为：

- `tests/test_knowledge_ingest_integrity.py::test_failed_commit_cleanup_does_not_follow_symlink`
- `tests/test_knowledge_reset.py::test_cli_rejects_knowledge_root_symlink_with_external_sentinels`
- `tests/test_knowledge_reset.py::test_cli_rejects_legacy_reset_root_symlink_with_external_sentinels`
- `tests/test_knowledge_reset.py::test_cli_does_not_follow_nested_escape_symlink`

分组命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-pytest-groups.ps1 -Group <group> -ResultDir <temp>
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-pytest-groups.ps1 -Aggregate -ResultDir <temp>
```

前端稳定分组门禁：**103 个文件、727 个测试全部通过**；10 个分组均退出码 0，实际 Vitest JSON 结果文件集合与 manifest 完全一致，收集文件无重复且并集完整：components-core、components-chat、components-interview、components-offer、components-support、features、layout、lib、services、theme。

前端门禁与 smoke 收口专项：`uv run pytest tests/test_frontend_vitest_groups.py tests/test_smoke.py -q` 为 **64 passed**；包含省略 `RepositoryRoot` 的默认根目录、尾部分隔根目录、相邻前缀目录拒绝和最小 fixture 四类路径回归。

| 前端分组 | 文件 / 测试 | 退出码 |
|---|---:|---:|
| components-core | 22 / 108 | 0 |
| components-chat | 11 / 182 | 0 |
| components-interview | 11 / 45 | 0 |
| components-offer | 8 / 45 | 0 |
| components-support | 8 / 32 | 0 |
| features | 12 / 129 | 0 |
| layout | 10 / 65 | 0 |
| lib | 9 / 73 | 0 |
| services | 11 / 47 | 0 |
| theme | 1 / 1 | 0 |

## 隔离运行时验收

| 命令 | 结果 |
|---|---|
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过；临时隔离目录清理完成 |
| `uv run oc verify --profile real-ai --static-dir web/dist` | **未通过** |
| `uv run oc verify-offer-negotiation --static-dir web/dist` | **未通过**；Provider 返回 `502 offer_negotiation_unverifiable:topic_evidence_mismatch` |

real-AI 复跑未再出现 `unable to open database file`。当前全量失败发生在面试准备真实 Provider 请求，错误为 `httpx.ReadTimeout`，命令退出码 1；独立 Offer 验收返回 `502 offer_negotiation_unverifiable:topic_evidence_mismatch`。数据库隔离问题已修复，但 Provider 网络与证据输出稳定性仍是发布阻塞，不能把本次验收记为通过。

真实配置只在隔离临时目录静默复制，未输出、修改或保留密钥；正式数据目录未作为验收写入目标。

## 本地浏览器键盘验收

使用临时隔离服务和中文 Offer“星云数据｜后端工程师”，通过内置浏览器完成 Pilot 主动选择 Offer 后打开覆盖式谈薪工作区：

- 对话框存在 `role="dialog"`、`aria-modal="true"`，动态可访问名称为“为 星云数据 准备谈薪”。
- 打开后焦点进入“关闭”按钮，且焦点位于对话框内部。
- `Shift+Tab` 从首个焦点循环到最后一个可用输入控件；`Tab` 从最后一个可用控件循环回首个控件；焦点未离开对话框。
- `Escape` 关闭对话框，并将焦点恢复到“准备谈薪”触发按钮。
- 本次键盘验收仅执行本地 UI 操作，未调用 Provider，未创建谈薪 Proposal 或 Brief。

## 清理与剩余风险

- 已停止临时服务、浏览器标签及测试后台进程，并删除本轮创建的临时数据、Vitest JSON 报告、manifest 和分组结果目录。
- 产品代码与测试门禁没有新增 skip；4 个既定符号链接权限 skip 已逐项核验。
- 发布仍不通过：完整 real-AI verify 被 Provider `ReadTimeout` 阻塞。该外部稳定性风险需要单独重新验收，不能通过放宽 JSON、证据、HITL 或错误语义解决。
- 本报告不包含密钥、简历/JD 原文、模型原文或 Provider 原始请求标识。
