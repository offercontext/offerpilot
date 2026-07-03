# 投递材料包设计文档

- **日期**: 2026-07-03
- **分支**: `feat/product-gap-analysis`
- **Worktree**: `D:\Users\yuqi.chen\offerpilot\.worktrees\feat-product-gap-analysis`
- **状态**: 已完成 brainstorming 确认，待实现计划

## 1. 第一性原理定位

OfferPilot 的核心目标不是“记录投递”，而是帮助求职者持续提高拿到合适 offer 的概率。现有系统已经覆盖投递看板、JD 分析、简历库、日程提醒、面试复盘、题库刷题、模拟面试和 offer 谈判，但在“把目标岗位转化为可提交材料”这一环仍然断开。

**投递材料包**补齐的是投递执行中的关键产物层：围绕一个已存在的投递记录，把 JD、选中简历和 AI 分析结果转化为可保存、可编辑、可推进的岗位材料工作区。

### 决策摘要

| 维度 | 决策 |
|---|---|
| 功能名称 | 投递材料包 |
| 绑定对象 | 已有投递记录，不单独存在 |
| 入口 | 投递详情页动作区，打开全屏编辑 Drawer |
| 数据形态 | 底层结构化 JSON + 界面卡片编辑 + 每块自由备注 |
| MVP 输入 | 当前投递 + JD 分析/JD 文本 + 选中简历 |
| MVP 输出 | 简历优化建议、沟通话术、投递检查清单 |
| 推荐方案 | 材料包 + 清单状态 |

## 2. 用户路径与产品行为

用户从现有投递记录进入材料包：

`看板 / 仪表盘 / 命令面板 -> 打开某个投递 -> 点击“材料包” -> 全屏 Drawer 编辑`

材料包不是一次性 AI 结果弹窗，而是一个可持续编辑的工作区。用户可以生成初稿、修改内容、复制话术、勾选清单、保存状态，并在之后继续回到同一个材料包。

### 三块核心内容

1. **简历优化建议**
   - 基于目标 JD 和选中简历生成。
   - 包含岗位匹配摘要、建议突出点、可替换 bullet、能力缺口和用户备注。
   - 不直接修改简历文件，只提供建议和候选表达。

2. **沟通话术**
   - MVP 固定生成 2-3 类话术：HR 邮件、内推私信、投递备注。
   - 每条话术可复制、编辑、保存备注。
   - 不做复杂模板市场或多渠道发送。

3. **投递检查清单**
   - 每项可勾选，状态保存到材料包。
   - 默认项包括：确认 JD、选择简历、完成简历建议、准备沟通话术、完成投递、设置跟进提醒。
   - 未完成清单可进入今日行动队列。

## 3. 数据模型

新增 `application_material_kits` 表，不修改现有 `applications` 主表。

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `application_id` | 绑定的投递记录，唯一约束 |
| `resume_id` | 生成或编辑时选中的简历 |
| `jd_analysis_id` | 可选，关联生成时使用的 JD 分析 |
| `jd_snapshot` | 生成时使用的 JD 文本或摘要快照 |
| `status` | `draft`、`ready`、`submitted` |
| `content_json` | 三块内容的结构化 JSON |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

`content_json` 示例：

```json
{
  "resume_advice": {
    "summary": "",
    "highlights": [],
    "rewrite_bullets": [],
    "gaps": [],
    "notes": ""
  },
  "messages": [
    {
      "type": "recruiter_email",
      "title": "",
      "body": "",
      "notes": ""
    }
  ],
  "checklist": [
    {
      "id": "select_resume",
      "label": "选择用于投递的简历",
      "done": true
    }
  ]
}
```

### 状态语义

| 状态 | 含义 |
|---|---|
| `draft` | 已创建但仍有关键清单未完成 |
| `ready` | 关键材料已准备好，可用于投递 |
| `submitted` | 用户标记已提交 |

状态可由用户手动切换，也可由清单完成度辅助推荐，但 MVP 不需要自动强制转换。

## 4. 后端 API

新增材料包路由：

- `GET /api/applications/{id}/material-kit`
  - 获取某个投递的材料包。
  - 没有材料包时返回明确空状态，例如 `404` 或 `{ "exists": false }`。实现时应统一前端服务约定。

- `POST /api/applications/{id}/material-kit/generate`
  - 输入 `resume_id`、可选 `jd_text` 或 `jd_analysis_id`。
  - 调用 AI 生成材料包并保存。
  - 如果已存在材料包，需要避免静默覆盖用户编辑内容。建议要求前端显式传 `overwrite: true`，否则返回冲突提示。

- `PUT /api/material-kits/{id}`
  - 保存用户编辑后的 `content_json`、`status`、`resume_id`。
  - 用于普通编辑和 checklist 勾选。

- `POST /api/material-kits/{id}/regenerate-section`
  - 局部重新生成 `resume_advice`、`messages` 或 `checklist`。
  - MVP 可先预留接口设计，第一版可以不实现。

### AI 生成边界

MVP 只依赖：

- 当前投递记录。
- 最近一次 JD 分析，或用户粘贴的 JD 文本。
- 用户选中的简历。

预留扩展但不进入 MVP：

- 知识库增强。
- 面试复盘和题库薄弱点增强。
- 多版本比较。

## 5. 前端交互与 UI

入口放在 `ApplicationDetail` 顶部动作区，和“分析 JD”“模拟面试”同级，按钮名为 **材料包**。点击后打开全屏 Drawer，宽度建议为 `min(1120px, calc(100vw - 32px))`。

### Drawer 布局

左侧是上下文栏：

- 公司、岗位、当前状态。
- JD 分析状态。
- 简历选择器。
- 生成或重新生成按钮。
- 材料包完成度。

右侧是三块编辑区：

- **简历建议**：摘要、建议突出点、可替换 bullet、能力缺口、备注。
- **沟通话术**：每种话术一张编辑卡，支持复制、编辑、保存。
- **投递清单**：checkbox list，每项点击区域不小于 44px，勾选后保存。

### UI 设计原则

综合当前 OfferPilot 设计、`frontend-design`、`ui-ux-pro-max` 和 `make-interfaces-feel-better` 的约束：

- 延续 Ant Design + 当前 token，不引入新 UI 框架。
- 工作台应偏克制、密度高、可扫描，不做营销式大卡片。
- 避免继续强化单一紫色渐变，核心 CTA 可以使用现有品牌色，其余区域保持中性。
- 不做卡片套卡片；内容分区用清晰标题、间距和浅背景表达层级。
- 动态数字如完成度使用 `font-variant-numeric: tabular-nums`。
- 所有交互控件需要 visible focus、明确 disabled/loading 状态。
- 生成失败在 Drawer 内就近显示，不只依赖 toast。
- 支持 `prefers-reduced-motion`，避免不必要的入场动画。

## 6. 仪表盘与提醒联动

`deriveActionItems` 新增 `material_kit_incomplete` 类型。

触发条件建议：

- 投递状态处于 `applied`、`assessment` 或 `written_test`。
- 存在材料包但清单未完成，或尚未创建材料包。
- 优先级低于 offer deadline 和临近面试，高于普通长期停滞投递。

行动文案示例：

- 标题：`完善 {company} · {position} 的投递材料包`
- 详情：`简历建议、沟通话术或投递清单尚未完成。`
- 主按钮：`打开材料包`

第一版如果跨 Drawer 精确跳转复杂，可以先打开投递详情并突出“材料包”按钮；后续再直接打开材料包 Drawer。

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| 未配置 API key | 生成按钮显示明确提示，引导配置，不创建空材料包 |
| 没有简历 | 左侧提示先上传或选择简历，生成按钮 disabled |
| 没有 JD | 允许用户粘贴 JD 文本；已有 JD 分析时优先使用最近一次 |
| AI 生成失败 | 保留已有材料包，不覆盖用户编辑内容 |
| 保存失败 | 编辑区显示错误状态，提供重试 |
| JSON 解析失败 | 后端返回可读错误，前端不渲染半坏数据 |
| 已存在材料包时重新生成 | 默认不覆盖；需要用户确认覆盖或局部重新生成 |

## 8. 测试范围

### 后端

- migration 创建 `application_material_kits` 表和必要索引。
- 创建、读取、更新材料包。
- `application_id` 唯一约束行为。
- generate 请求校验：无简历、无 JD、无 API key。
- checklist 状态更新不丢失其它 `content_json` 字段。
- AI 输出解析失败时不覆盖旧材料包。

### 前端

- material kit service API。
- Drawer 在无材料包、有材料包、生成中、保存失败时的状态。
- 简历选择器无数据状态。
- checklist 勾选后触发保存并保留其它内容。
- `deriveActionItems` 对未完成材料包生成今日行动。

## 9. MVP 范围之外

明确不做：

- 不直接修改或导出 PDF 简历。
- 不做多版本比较。
- 不做职位抓取或机会收件箱。
- 不做知识库增强。
- 不做面试复盘/题库薄弱点增强。
- 不做通用任务系统。
- 不把材料包做成左侧独立导航页面。
- 不做模板市场或外部消息发送。

## 10. 后续升级方向

- 从“机会收件箱”草稿生成材料包，再升级为正式投递。
- 引入知识库作为个人项目和技术素材来源。
- 将复盘、模拟面试和题库薄弱点转为备考建议，而不是混入材料包主流程。
- 提供材料包版本比较和导出。
- 当材料包使用频率足够高时，升级为独立“材料工作台”导航页。
