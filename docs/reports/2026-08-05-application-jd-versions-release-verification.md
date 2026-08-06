# JD 单一事实源发布验证报告

验证日期：2026-08-06
分支：`feat/20260805-application-jd-versions`
功能基线：`455e081`
验证代码 HEAD：`3fe4588`
状态：代码与本地门禁完成；真实 Provider 与浏览器验收未完成，因此不构成发布批准。

## 变更范围

- 为 Application 增加不可变 JD 版本、当前版本 CAS、UI/Pilot 来源归属和各下游流程的版本冻结/继承校验。
- 收紧 Opportunity Fit、材料、面试准备、模拟面试及 Pilot 的 JD 版本边界。
- 修正 real-AI smoke 对材料 Proposal 冻结来源中 `jd_version_id` 的脱敏响应校验。
- 未新增招聘平台访问、URL 抓取、跨领域自动写入或新的 Provider 重试语义。

## 后端门禁

结果目录：`D:\Users\yuqi.chen\AppData\Local\Temp\jd-backend-gate-final-c99878e-r2`
完整 manifest：1799 个 node id；五组并集无重复且与 manifest 完全一致；aggregate 退出码为 0。

| 分组 | 收集 | 通过 | 允许 skip | 退出码 |
| --- | ---: | ---: | ---: | ---: |
| agent | 424 | 424 | 0 | 0 |
| domain | 71 | 71 | 0 | 0 |
| knowledge | 659 | 655 | 4 | 0 |
| proposals | 311 | 311 | 0 | 0 |
| misc | 334 | 334 | 0 | 0 |
| 合计 | 1799 | 1795 | 4 | 0 |

Knowledge 的 4 个 skip 均为既定 Windows 符号链接权限限制，node id 与原因由分组脚本逐项核验：

- `tests/test_knowledge_ingest_integrity.py::test_failed_commit_cleanup_does_not_follow_symlink`
- `tests/test_knowledge_reset.py::test_cli_rejects_knowledge_root_symlink_with_external_sentinels`
- `tests/test_knowledge_reset.py::test_cli_rejects_legacy_reset_root_symlink_with_external_sentinels`
- `tests/test_knowledge_reset.py::test_cli_does_not_follow_nested_escape_symlink`

## 静态、前端与隔离门禁

| 命令 | 结果 |
| --- | --- |
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过，65 个源文件 |
| 前端分组 aggregate | 通过，104 个文件、730 个测试 |
| `npm.cmd run build` | 通过，3746 个模块转换 |
| `uv run pytest tests/test_calendar_api.py -q` | 通过，3 passed |
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过；临时隔离数据清理完成 |
| `git diff --check origin/main..HEAD` | 通过（最终报告提交前后均检查） |

前端分组脚本验证了当前 manifest、实际执行文件集合、源码指纹、配置/锁文件和分组脚本；所有分组退出码均为 0。

## 真实 AI 验收

最终执行：

```powershell
uv run oc verify --profile real-ai --static-dir web/dist
```

退出码：1。面试准备流程已越过 JD 版本 CAS；随后材料 Proposal Provider 请求发生 `ReadTimeout`，因此完整 real-AI verify 未完成。报告只保留失败类别和阶段，不记录模型原文、JD/简历内容、请求体或密钥。此前一次运行暴露的 smoke 响应契约过时问题已在 `3fe4588` 修正并由 57 条 smoke 测试覆盖；修正后的最终重跑仍因 Provider 超时失败。

## 浏览器验收

执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1 -Stage jd-only
```

退出码：1。Harness 在启动前 fail-closed：未设置 `APPLICATION_JD_CDP_URL`，当前环境没有可用的 browser-level CDP endpoint，因此没有声称浏览器闭环通过，也没有生成浏览器业务数据或截图证据。

## 清理与剩余风险

- local smoke、local verify 的隔离数据库和应用服务均已清理。
- 后端/前端门禁进程已结束；本轮 real-AI 进程也已确认停止。审计结果目录保留在临时目录中供复核，未写入产品数据目录。
- baseline 文件 `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` 仍保留，因为 real-AI 和浏览器门禁未全部通过；不得据此重新计算基线。
- 未输出或保存 Provider 密钥、JD/简历原文、模型原文或完整请求。
- 当前剩余发布阻塞：Provider `ReadTimeout`；browser-level CDP endpoint 不可用。不得把 API/local 门禁结果或失败重跑当作真实浏览器闭环通过。
