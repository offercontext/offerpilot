# Offer 谈薪双入口真实验收报告

## 结论

UI 与 Pilot 两条 Offer 谈薪路径均已在隔离数据目录完成真实中文案例验收。两条路径都使用亮色模式和宽屏视口；生成、编辑、人工确认、历史只读查看均完成。Provider 首次调用出现过 `provider_unknown` 时，系统保留原 Attempt 和幂等上下文，使用原尝试重试后完成，未放宽证据门控。

本报告只记录验收结论、脱敏元数据和截图路径，不记录密钥、简历/JD 原文或模型原文。

## 环境与范围

- 分支：`feat/20260801-offer-negotiation`
- 验收 HEAD：`94a39c4`
- 服务：隔离临时数据目录中的本地 OfferPilot，`http://localhost:65120/`
- 配置：从现有配置静默复制到隔离目录；未输出或修改密钥
- 案例：中文候选人“筱哲”；Offer 为“星云数据｜后端工程师”和“远山科技｜平台工程师”
- 浏览器：亮色模式，视口约 `1800×1125`；最终截图均不低于 `1440×900`

## UI 入口

已完成：

1. Offer 中心选择两个不同且可见的 Offer，按用户选择顺序打开比较表。
2. 从比较表进入“为星云数据准备谈薪”，确认 Offer 固定事实、用户目标、顾虑和沟通场景。
3. 生成真实 Proposal，选择建议区块，编辑用户文本并确认保存。
4. 重新打开历史，查看已确认 Brief、用户最终编辑内容和冻结输入。

结果：UI 成功 Proposal 为 `id=2`，对应确认 Brief 为 `id=1`。旧的单 Offer“谈薪教练”入口也已点击验证，仍可直接打开且未被新流程替换。

## Pilot 入口

已完成：

1. 用户主动点击“选择 Offer 后准备谈薪”，在选择器中明确选择星云数据；未猜测 Offer。
2. 分别记录 Pilot 的询问与用户选择后的 Offer 上下文卡。
3. 点击“准备谈薪”，确认来源后生成真实 Proposal。
4. Provider 结果未知时点击“使用原尝试重试”，继续使用同一 Attempt/key；随后选择、编辑并确认保存。
5. 关闭并重新进入历史，查看已确认 Brief。

结果：Pilot 成功 Proposal 为 `id=4`，对应确认 Brief 为 `id=2`。UI 与 Pilot 的 Proposal/Brief 和幂等上下文相互隔离，但都复用同一 Offer 谈薪业务 API；两次成功尝试的 key 哈希不同。

## 浏览器与 Provider 边界

- 内置浏览器目标页启用标签级 CDP Network 审计；最终重载捕获 26 个请求，外部 URL 数量为 0，全部为本地静态资源或 `localhost:65120` 的 `/api` 请求。
- 浏览器控制台错误/警告：0。
- Provider 受控出站仅允许配置端点 `api.deepseek.com:443`；代理记录到该端点的 HTTPS 连接。
- 代理拒绝了一次 `raw.githubusercontent.com:443` 的辅助 cost-map 请求；这不是浏览器页面请求，也未进入 OfferPilot 业务流程。该环境事实保留为剩余风险，不将其表述为“所有外部连接均成功”。
- 本次未将内置浏览器标签级 CDP 误称为仓库独立 browser-level harness 通过；证据范围是实际操作标签的请求审计和服务端/代理日志。

## 零跨领域写入

隔离库验收结束时的计数：

| 领域 | 结果 |
|---|---:|
| Application / Event / Resume | 0 |
| Knowledge、Interview、复盘 Proposal | 0 |
| Opportunity Fit v1/v2 | 0 |
| Question、Mock Interview、Memory、Reminder/Wakeup | 0 |
| Chat messages | 0 |
| Offers | 2（仅为验收前置数据） |
| Offer negotiation Proposal | 4 |
| Offer negotiation Brief | 2 |
| Comparison dimensions / values | 2 / 4（仅为验收前置数据） |

运行时的写请求仅属于 Offer 谈薪预览、Proposal 生成和用户确认；没有应用、事件、简历、材料、知识、面试、题库、提醒、Memory 或 Chat 写请求。隔离临时服务、Provider 代理、浏览器标签和临时数据已清理；源用户数据目录未作为运行目录使用。

## 截图矩阵

以下均为最终亮色、宽屏截图，截图正文与报告不包含密钥或模型原文：

| 文件 | 证明内容 |
|---|---|
| [01-ui-offer-center-light.png](./01-ui-offer-center-light.png) | UI：Offer 中心、比较维度与两张中文 Offer 卡 |
| [02-ui-offer-comparison.png](./02-ui-offer-comparison.png) | UI：用户选择后的并排比较，无排名或推荐结论 |
| [03-ui-source-confirmation-frozen.png](./03-ui-source-confirmation-frozen.png) | UI：生成前来源确认与冻结提示 |
| [04-ui-generated-edited-proposal.png](./04-ui-generated-edited-proposal.png) | UI：生成结果、证据引用和用户编辑区块 |
| [05-ui-confirmed-history.png](./05-ui-confirmed-history.png) | UI：确认后的 Brief 与历史只读查看 |
| [06-pilot-question-select-offer.png](./06-pilot-question-select-offer.png) | Pilot：主动触发后询问选择 Offer |
| [07-pilot-answer-selected-offer.png](./07-pilot-answer-selected-offer.png) | Pilot：用户选择后展示明确 Offer 上下文 |
| [08-pilot-source-confirmation-frozen.png](./08-pilot-source-confirmation-frozen.png) | Pilot：来源确认与冻结提示 |
| [09-pilot-generated-proposal.png](./09-pilot-generated-proposal.png) | Pilot：生成结果及历史入口 |
| [10-pilot-confirmed-history.png](./10-pilot-confirmed-history.png) | Pilot：确认后的 Brief 与历史只读查看 |
| [11-single-offer-coach.png](./11-single-offer-coach.png) | 既有单 Offer“谈薪教练”入口保持可用 |

## 剩余风险

- Provider 输出存在已观察到的偶发未知结果；系统按既有协议保留原尝试，不能据此扩大重试或放宽证据校验。
- 本报告覆盖本地 UI/Pilot 实际操作与标签级 CDP 审计；发布前仍需按仓库既定最终门禁汇总后端分组、前端全量、构建及 local/real-AI verify。未以本报告替代这些门禁。
