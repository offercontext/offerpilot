# Offer 谈薪双入口发布验证报告

## 结论

本轮控件修复、定向前端测试和隔离浏览器截图复核已完成。截图已重新生成并逐张检查为亮色、中文、单视口宽屏；UI/Pilot 的已确认历史可读和既有单 Offer 谈薪教练入口均已复核。后端五组分组门禁及聚合、前端十组分组门禁及聚合均已通过；真实 Provider 验收仍有 ReadTimeout 与 `topic_evidence_mismatch`，因此本分支当前仍不能作为已发布版本推送或合并。

本报告只记录脱敏命令、结果和截图路径，不记录密钥、简历/JD 原文或模型原文。

## 代码与环境

- 分支：`feat/20260801-offer-negotiation`
- UI 代码验证基线：`8c93815`
- 服务：隔离临时数据目录中的本地 OfferPilot；真实浏览器端口为本次临时服务端口
- 配置：从现有配置静默复制到隔离目录；未输出或修改密钥
- 案例：中文候选人“筱哲”；Offer 为“星云数据｜后端工程师”和“远山科技｜平台工程师”
- 浏览器：亮色模式；`02` 保持此前已复核版本，`10` 已基于 `9fe0efc` 重新录制，均为 `1455×1200` 单视口原始截图；未拼接长图、未缩放或补白

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

完整收集 manifest：`1748` 个 node id，分组覆盖未去重前无重复。

| 分组 | 收集 | 测试 | 通过 | 失败 | 允许 skip | 退出码 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| agent | 423 | 423 | 423 | 0 | 0 | 0 |
| domain | 70 | 70 | 70 | 0 | 0 | 0 |
| knowledge | 659 | 659 | 655 | 0 | 4 | 0 |
| proposals | 287 | 287 | 287 | 0 | 0 | 0 |
| misc | 309 | 309 | 309 | 0 | 0 | 0 |

Knowledge 的 4 个 skip 均为既定 Windows 无符号链接权限条件，并由 JUnit node id 与原因校验。五组退出码均为 0，`-Aggregate` 通过，且覆盖集合与完整 manifest 完全一致；总计 1744 个通过、4 个允许 skip。每组完成标记绑定收集结果、JUnit 内容和退出状态。

本轮后端分组未发现失败项；日期敏感日历测试在本次完整分组中通过。

### 其他命令

| 命令 | 结果 |
| --- | --- |
| `uv run ruff check .` | 通过 |
| `uv run mypy src` | 通过；64 source files |
| `git diff --check` | 通过 |
| `scripts/windows-vitest-groups.ps1 -Collect/-Group/-Aggregate` | 退出码 0；10 组、103 文件、727 tests；实际 Vitest JSON 文件集合与 manifest 完全一致，无重复，聚合通过；fingerprint 覆盖 `web/src`、前端配置/锁文件及分组脚本 |
| `uv run pytest tests/test_frontend_vitest_groups.py tests/test_smoke.py -q` | 退出码 0；61 passed、49 warnings；新增前端门禁负向覆盖与 worker dispose 顺序/未退出保护 |
| `npm.cmd run build` | 通过 |
| `uv run oc smoke --static-dir web/dist` | 通过 |
| `uv run oc verify --profile local --static-dir web/dist` | 通过；隔离目录 |
| `uv run oc verify --profile real-ai --static-dir web/dist` | 失败；面试准备 Provider 请求 `httpx.ReadTimeout`，隔离目录清理完成，不能宣称 real-AI 全量通过 |
| `uv run oc verify-offer-negotiation --static-dir web/dist` | 失败；真实 Provider 返回 `502 offer_negotiation_unverifiable:topic_evidence_mismatch`，保持证据门控，不能宣称 Offer real-AI 通过 |

## 截图矩阵

以下截图均为中文、亮色、宽屏单视口，并已逐张检查，没有暗色模式、乱码、拼接长图或不必要的裁切：

| 文件 | 尺寸 | 证明内容 |
| --- | ---: | --- |
| [01-ui-offer-center-light.png](./01-ui-offer-center-light.png) | 1440×900 | UI：Offer 中心、比较维度与两张中文 Offer 卡 |
| [02-ui-offer-comparison.png](./02-ui-offer-comparison.png) | 1455×1200 | UI：用户选择后的并排比较，含当前自定义比较维度，无排名或推荐结论；SHA-256 `d4337e97d48944a904dc0ba4eafb4ad31adf61315814a24c921e2e592389c647` |
| [03-ui-source-confirmation-frozen.png](./03-ui-source-confirmation-frozen.png) | 1440×900 | UI：生成前来源确认与冻结提示 |
| [04-ui-input-confirmation.png](./04-ui-input-confirmation.png) | 1455×909 | UI：确认发送前核对冻结 Offer 事实与本次谈薪输入 |
| [05-ui-confirmed-history.png](./05-ui-confirmed-history.png) | 1455×909 | UI：确认后的 Brief 与历史只读查看 |
| [06-pilot-question-select-offer.png](./06-pilot-question-select-offer.png) | 1455×909 | Pilot：主动触发后询问选择 Offer |
| [07-pilot-answer-selected-offer.png](./07-pilot-answer-selected-offer.png) | 1455×909 | Pilot：用户选择后展示明确 Offer 上下文，并可更换 Offer |
| [08-pilot-source-confirmation-frozen.png](./08-pilot-source-confirmation-frozen.png) | 1440×900 | Pilot：来源确认与冻结提示 |
| [09-pilot-input-confirmation.png](./09-pilot-input-confirmation.png) | 1455×909 | Pilot：确认发送前查看已选 Offer、冻结事实与本次谈薪输入 |
| [10-pilot-confirmed-history.png](./10-pilot-confirmed-history.png) | 1455×1200 | Pilot：确认保存后的 Brief 入口与冻结事实，谈薪工作区以覆盖式 Drawer 展示，窄栏标题与来源卡保持可读；历史只读已在同一会话回看；SHA-256 `33074a77926db090a0ac7fddf4d88be51718533f1409a4a88d8805a840fc6925` |
| [11-single-offer-coach.png](./11-single-offer-coach.png) | 1455×909 | 既有单 Offer“谈薪教练”入口保持可用 |

## 剩余风险与下一步

- Provider 输出仍存在偶发未知结果；系统按既有协议保留原尝试，未扩大重试或放宽证据校验。
- 本次截图重录使用同一隔离中文案例；`04` 与 `09` 明确展示发送前确认，不冒充已生成 Proposal，`05` 展示 UI 已确认历史，`10` 展示 Pilot 已确认历史入口与冻结事实。截图不把新的 Provider 波动表述为稳定通过；此前已确认的 Provider 成功闭环不因本次重录被改写。
- 完整后端五组门禁及聚合已通过；仅允许 4 个既定 Windows 符号链接权限 skip。
- 前端分组门禁及聚合已通过；不再使用单次全量命令作为结论，且旧结果、漏文件、新测试文件和生产源码变更均有拒绝回归。
- 全量 real-AI verify 仍受 Provider `ReadTimeout` 阻塞；独立 Offer real-AI 本轮受 `topic_evidence_mismatch` 阻塞，均未放宽契约或重试白名单。
- 当前未推送、未合并；本报告不构成发布批准。
