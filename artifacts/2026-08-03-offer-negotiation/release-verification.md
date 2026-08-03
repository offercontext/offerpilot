# Offer 谈薪双入口发布验证报告

## 结论

本轮控件修复、定向前端测试和隔离浏览器截图复核已完成。截图已重新生成并逐张检查为亮色、中文、单视口宽屏；UI/Pilot 的已确认历史可读和既有单 Offer 谈薪教练入口均已复核。但完整后端分组门禁未通过：`misc` 组有一个与本切片无关的既有日历测试失败；本次前端全量串行运行也在工具时限内未完成。因此本分支当前不能作为已发布版本推送或合并。

本报告只记录脱敏命令、结果和截图路径，不记录密钥、简历/JD 原文或模型原文。

## 代码与环境

- 分支：`feat/20260801-offer-negotiation`
- UI 代码验证基线：`2d718e3`
- 服务：隔离临时数据目录中的本地 OfferPilot；真实浏览器端口为本次临时服务端口
- 配置：从现有配置静默复制到隔离目录；未输出或修改密钥
- 案例：中文候选人“筱哲”；Offer 为“星云数据｜后端工程师”和“远山科技｜平台工程师”
- 浏览器：亮色模式；截图均为单视口原始截图，尺寸为 `1440×900` 或 `1455×909`，未拼接长图、未缩放或补白

## UI 入口

此前隔离真实验收已完成：

1. Offer 中心选择两个不同且可见的 Offer，并按用户选择顺序打开比较表。
2. 从比较表进入“为星云数据准备谈薪”，确认 Offer 固定事实、用户目标、顾虑和沟通场景。
3. 生成真实 Proposal，选择建议区块，编辑用户文本并确认保存。
4. 重新打开历史，查看已确认 Brief、用户最终编辑内容和冻结输入。

同时点击验证了既有单 Offer“谈薪教练”入口，仍可直接打开，未被新流程替换。

## Pilot 入口

已完成：

1. 用户主动触发谈薪准备，在选择器中明确选择星云数据；未猜测 Offer。
2. 分别记录 Pilot 的询问和用户选择后的 Offer 上下文卡。
3. 点击“准备谈薪”，确认来源后生成真实 Proposal。
4. Provider 结果未知时点击“使用原尝试重试”，继续使用同一 Attempt/key；随后选择、编辑并确认保存。
5. 关闭并重新进入历史，查看已确认 Brief。本次截图重录只复核入口、冻结来源和既有历史，不把新的 Provider 调用作为成功证据。

UI 与 Pilot 的 Proposal/Brief 和幂等上下文相互隔离，但都复用同一谈薪业务 API。两次成功尝试的 key 哈希不同。

## 浏览器与 Provider 边界

- 内置浏览器专用目标启用 CDP Network 审计；关键请求序列覆盖 UI/Pilot 的预览、生成、确认和历史读取。
- 浏览器只访问本地静态资源与本地 `/api`；未访问招聘平台。
- 浏览器控制台在最终 Offer 流程中未记录错误或警告。
- Provider 受控出站仅允许实际配置候选端点；代理记录到配置的 HTTPS Provider 端点，并拒绝了非业务辅助外联。该环境事实作为剩余风险保留，不扩大为“所有外部连接均成功”。
- 本地服务、Provider 代理、浏览器标签和临时数据均已清理；源用户数据目录未作为运行目录使用。

## 本轮代码复审收口

- Evidence 展开只读，不会改变 Proposal 区块选择。
- Pilot 的已选 Offer 会随上下文 Offer 变化清除，避免跨 Offer 残留选择。
- 预览阶段确定性 `422` 会清理持久化草稿和旧幂等键；Provider 未知结果仍保留原尝试和原 key。
- `signing_bonus=0` 作为真实 Offer 数值展示，不再被当作缺失。

## 零跨领域写入

隔离库验收时，除本功能前置 Offer/比较数据与谈薪 Proposal/Brief 外，以下领域均无新增写入：

| 领域 | 结果 |
| --- | ---: |
| Application / Event / Resume | 0 |
| Knowledge、Interview、复盘 Proposal | 0 |
| Opportunity Fit v1/v2 | 0 |
| Question、Mock Interview、Memory、Reminder/Wakeup | 0 |
| Chat messages | 0 |
| Offers | 2（验收前置数据） |
| Offer negotiation Proposal | 4 |
| Offer negotiation Brief | 2 |
| Comparison dimensions / values | 2 / 4（验收前置数据） |

## 发布门禁

### 后端分组

完整收集 manifest：`1737` 个 node id，分组覆盖未去重前无重复。

| 分组 | 收集 | 测试 | 通过 | 失败 | 允许 skip | 退出码 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| agent | 423 | 423 | 423 | 0 | 0 | 0 |
| domain | 70 | 70 | 70 | 0 | 0 | 0 |
| knowledge | 658 | 658 | 654 | 0 | 4 | 0 |
| proposals | 283 | 283 | 283 | 0 | 0 | 0 |
| misc | 303 | 303 | 302 | 1 | 0 | 1 |

Knowledge 的 4 个 skip 均为既定 Windows 无符号链接权限条件，并由 JUnit node id 与原因校验。`-Aggregate` 未通过，因为 `misc` 没有成功完成标记；它拒绝聚合是门禁预期行为，不是通过证据。

失败项：

```text
tests/test_calendar_api.py::test_calendar_includes_applications_and_events
```

该测试使用固定的 2026-07 月份，而创建投递使用运行时当前日期，导致日历月份不包含该投递；本切片没有修改后端代码或该测试。此失败仍是发布阻塞，不能通过新增 skip 或调整门禁掩盖。

### 其他命令

| 命令 | 结果 |
| --- | --- |
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过；64 source files |
| `git diff --check` | 通过 |
| `npm.cmd test -- --run src/components/ChatPanel/PilotOfferSelectionCard.test.tsx src/components/OfferCard.test.tsx src/components/OfferCenterView.test.tsx src/components/OfferCompareDrawer.test.tsx src/components/OfferComparisonDimensionPanel.test.tsx src/components/offer-negotiation/OfferNegotiationPresentation.test.tsx src/components/OfferNegotiationDrawer.test.tsx src/components/OfferPilotNegotiation.test.tsx src/layout/AppShell.offerNegotiation.test.tsx --reporter=dot` | 退出码 0；9 文件、43 passed；既有 React `act()` 警告 |
| `npm.cmd test -- --run --minWorkers=1 --maxWorkers=1 --reporter=json` | 未完成；180 秒工具时限超时，未生成 JSON 汇总，不宣称前端全量通过 |
| `npm.cmd run build` | 通过 |
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过；隔离目录 |
| `uv run oc verify-offer-negotiation --static-dir web/dist` | 通过；隔离 Offer API 流程 |
| `uv run oc verify --profile real-ai --static-dir web/dist` | 失败；知识/面试准备链路出现隔离数据库 `unable to open database file`，不能宣称 real-AI 全量通过 |

## 截图矩阵

以下截图均为中文、亮色、宽屏单视口，并已逐张检查，没有暗色模式、乱码、拼接长图或不必要的裁切：

| 文件 | 尺寸 | 证明内容 |
| --- | ---: | --- |
| [01-ui-offer-center-light.png](./01-ui-offer-center-light.png) | 1440×900 | UI：Offer 中心、比较维度与两张中文 Offer 卡 |
| [02-ui-offer-comparison.png](./02-ui-offer-comparison.png) | 1440×900 | UI：用户选择后的并排比较，无排名或推荐结论 |
| [03-ui-source-confirmation-frozen.png](./03-ui-source-confirmation-frozen.png) | 1440×900 | UI：生成前来源确认与冻结提示 |
| [04-ui-generated-edited-proposal.png](./04-ui-generated-edited-proposal.png) | 1455×909 | UI：确认生成前核对冻结 Offer 事实与用户输入 |
| [05-ui-confirmed-history.png](./05-ui-confirmed-history.png) | 1455×909 | UI：确认后的 Brief 与历史只读查看 |
| [06-pilot-question-select-offer.png](./06-pilot-question-select-offer.png) | 1455×909 | Pilot：主动触发后询问选择 Offer |
| [07-pilot-answer-selected-offer.png](./07-pilot-answer-selected-offer.png) | 1455×909 | Pilot：用户选择后展示明确 Offer 上下文，并可更换 Offer |
| [08-pilot-source-confirmation-frozen.png](./08-pilot-source-confirmation-frozen.png) | 1440×900 | Pilot：来源确认与冻结提示 |
| [09-pilot-generated-proposal.png](./09-pilot-generated-proposal.png) | 1455×909 | Pilot：生成 Proposal 后查看证据引用与建议区块 |
| [10-pilot-confirmed-history.png](./10-pilot-confirmed-history.png) | 1455×909 | Pilot：确认保存后的 Brief 与历史只读查看 |
| [11-single-offer-coach.png](./11-single-offer-coach.png) | 1455×909 | 既有单 Offer“谈薪教练”入口保持可用 |

## 剩余风险与下一步

- Provider 输出仍存在偶发未知结果；系统按既有协议保留原尝试，未扩大重试或放宽证据校验。
- 本次截图重录使用同一隔离中文案例；`04` 展示生成前确认，`05` 展示 UI 已确认历史，`09` 展示 Pilot Proposal 与证据，`10` 展示 Pilot 已确认历史。截图不把新的 Provider 波动表述为稳定通过；此前已确认的 Provider 成功闭环不因本次重录被改写。
- 完整后端门禁被 `test_calendar_includes_applications_and_events` 阻塞；在修复测试数据时序或得到明确上游修复前，不应推送或合并。
- 当前前端全量串行运行在工具时限内超时；定向受影响集合为 9 文件、43 passed，不能替代全量结果。
- 全量 real-AI verify 受隔离数据库打开失败阻塞；专用 Offer real-AI API 验收已通过，但不能替代全量 real-AI 或浏览器证据。
- 当前未推送、未合并；本报告不构成发布批准。
