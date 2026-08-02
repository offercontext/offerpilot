# Offer 比较与谈薪准备发布验证报告

日期：2026-08-02

## 范围与提交

- 工作树：`feat/20260801-offer-negotiation`
- 功能基线：`14ec28b`
- 核心修复提交：`e2d6a5b5edd2f654a0f201cb18cac0498305880e`
- 报告后的最终 HEAD：`80aae9c`
- 未推送、未合并。
- 本轮未记录密钥、Offer 原文、用户输入、证据摘录、模型原文或 Provider 原始请求标识。

## 代码与静态门禁

| 命令 | 结果 |
|---|---|
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过，64 个源文件 |
| `npm.cmd run build`（`web`） | 通过 |
| `git diff --check 14ec28b..HEAD` | 通过 |
| 前端全量 `npm.cmd test -- --run` | 通过，98 个文件、688 个测试 |
| Offer 重点前端测试 | 通过，3 个文件、7 个测试 |

测试输出仍有既有 React `act()` 警告，不影响退出码。

## 后端分组门禁

最终 HEAD 重新收集到 1669 个 node id；分组结果目录为临时目录，按完成标记、JUnit、退出码、重复 node id 和覆盖集合执行聚合。

| 分组 | 收集 | 结果 |
|---|---:|---|
| agent | 423 | 423 通过，0 skip |
| domain | 70 | 70 通过，0 skip |
| proposals | 283 | 283 通过，0 skip |
| knowledge | 658 | 654 通过，4 个允许的 Windows 符号链接权限 skip |
| misc | 235 | 234 通过，1 失败 |

唯一失败为 `tests/test_calendar_api.py::test_calendar_includes_applications_and_events`。该测试和日历相关服务代码均未出现在 `14ec28b..HEAD` 的功能差异中；失败表现为日期敏感的“2026-07”查询未包含当前创建投递。该失败使 misc 没有成功完成标记，聚合命令按设计拒绝继续；因此后端全量聚合门禁未通过，不能宣称后端发布门禁全绿。

Knowledge 组的 4 个 skip 均为既定测试 ID，原因均为当前 Windows 无创建符号链接权限；没有新增 skip。

## 本地运行时验证

| 命令 | 结果 |
|---|---|
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过，隔离数据清理完成 |
| `uv run oc verify-offer-negotiation --static-dir web/dist` | 通过，隔离 Offer API 流程完成 |
| `uv run oc verify --profile real-ai --static-dir web/dist` | 未通过：Provider 网络超时，随后隔离运行时数据库打开失败；未将其记为通过 |

Offer 专项真实 Provider API 验收已通过；本报告不把它扩大解释为完整 real-AI verify 通过。

## 浏览器验收

本轮未完成 Offer 专用 Browser/CDP 闭环：当前环境未提供 `OFFER_NEGOTIATION_CDP_URL`，因此没有声称浏览器请求序列、Provider 出站三元组或真实 UI/Pilot 双入口已通过。已有 API smoke 不能替代浏览器级证据。

## 临时数据与剩余风险

- 分组测试结果、隔离服务和临时数据已清理；正式数据目录未作为验收写入目标。
- 发布阻塞：misc 后端分组的日期敏感基线失败、完整 real-AI verify 未通过、Offer 浏览器/CDP 闭环未执行。
- Provider/网络未知与严格证据失败仍按既定稳定错误码处理；本轮没有放宽 JSON、证据、HITL 或幂等语义。
