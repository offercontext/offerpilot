# 简历上传与简历库 — 设计文档

- **日期**: 2026-07-02
- **分支**: `feat/resume-upload`
- **Worktree**: `D:\Users\yuqi.chen\offerpilot\.worktrees\feat-resume-upload`
- **状态**: 经 brainstorming 流程逐节确认,待实现

## 1. 第一性原理定位

在 OfferPilot 中,求职者的「简历」是一份**可管理、可回溯的文档资产**:既保留原始 PDF 文件,也产出可被 AI 消费的提取文本,且一个用户可持有**多份**简历以应对不同岗位。

这区别于现状(简历仅是喂给 JD 匹配的纯文本输入)。本设计将简历升级为独立资产,核心动作是「上传 PDF → 提取文本 → 可随时校正 → 喂给下游匹配/面试复盘」。

### 决策摘要

| 维度 | 决策 |
|---|---|
| 简历本质 | 文档资产(原件 + 提取文本 + 多份归档) |
| 文件格式 | PDF 为主,纯 Go 解析,无 CGO |
| 人在回路 | 预览 + 可随时编辑(非阻断) |
| 信息架构 | 简历库主页 + TopBar/命令面板快捷上传 + 匹配模态从库选 |
| 多份建模 | 独立多份记录,复用现有 Resume 表 |

## 2. 架构与数据流

### 后端(沿用 knowledge import 范式 + 同步解析)

- **新增路由** `POST /api/resumes/upload`(multipart,字段 `file`)
  - 复用 `r.MultipartReader()` + 体积上限 10MB + 扩展名校验(仅 `.pdf`)
  - 用纯 Go PDF 文本提取库(候选:`github.com/ledongiatk/pdf`,无 CGO 依赖)同步抽取文本
  - 原文件落 `dataDir/resumes/{id}_{原文件名}`,提取文本存 `parsed_data`
  - 提取成功且非空 → `parse_status = text-ready`
  - 提取为空或失败 → `parse_status = parse-failed`(卡片呈现失败态 + 手动校正入口)
- **保留** `POST /api/resumes`(粘贴文本路径),与 upload 并列为两条入库路径,均置 `parse_status = text-ready`
- **新增** `GET /api/resumes/{id}/file` 下载原件(流式二进制,`Content-Disposition: attachment`)
- **新增** `PUT /api/resumes/{id}/text` 校正提取文本(对应编辑抽屉保存)

### 前端数据流

- `services/resumes.ts` 新增:
  - `uploadResume(file: File)`: `FormData` → `POST /api/resumes/upload`,超时 30s
  - `downloadResumeFile(id: number)`: 触发 `GET /api/resumes/{id}/file` 下载
  - `updateResumeText(id: number, text: string)`: `PUT /api/resumes/{id}/text`
- React Query 作为唯一数据源:`useQuery(['resumes'], listResumes)` 拉列表;上传/编辑/删除用 `useMutation`,成功后 `queryClient.invalidateQueries(['resumes'])`。
- 组件内仅持有 UI 态:选中卡 ID、拖拽高亮、编辑抽屉开闭、上传承知。

### 数据模型

**复用现有 `Resume` 表,不新建表。** 字段语义:

| 字段 | 含义 |
|---|---|
| `id` | 主键 |
| `name` | 用户命名(由上传时原文件名派生,可改) |
| `file_path` | 相对路径,指向 `dataDir/resumes/{id}_{原文件名}`(粘贴路径留空) |
| `parsed_data` | 提取/粘贴的文本 |
| `parse_status` | `text-ready`(粘贴或提取成功) \| `parse-failed`(提取为空/失败) |
| `created_at` | 入库时间 |

## 3. 前端组件结构

新增组件放在 `web/src/components/`,与 `KnowledgeBaseView.tsx` 同构。状态边界清晰,单一职责,均可独立测试。

### 新增组件

| 组件 | 职责 | 大致行数 |
|---|---|---|
| `ResumeLibraryView.tsx` | 简历库主页:Query 拉数、整页拖拽落地、空状态、搜索/过滤态、卡片网格渲染、上传承知与编辑抽屉态 LiftUp | 150-200 |
| `ResumeCard.tsx` | 单张卡片:名称/格式徽章/时间/文本摘要/状态 + 三操作(匹配·编辑·下载);失败态切换为(手动校正·删除)。纯受控 props,无自身 fetch | 80 |
| `ResumeUploadModal.tsx` | 上传模态(AntD `Upload.Dragger`):数据集成与 KnowledgeImportModal 一致;成功后关闭并 invalidate 列表;整页拖拽共享同一 `useMutation`) | 70 |
| `ResumeTextEditorDrawer.tsx` | 右侧抽屉(AntD `Drawer width=560`):展示选中简历 `parsed_data`(可编辑 `Input.TextArea`)+ 原文件信息 + 「保存」触发 `updateResumeText` | 90 |

### 改造组件

- **`ResumeMatchModal.tsx`**:不强拆重建。「选择已有简历」改为从库查 `listResumes`;新增「上传 PDF」次按钮(共享上传承知);保留「粘贴文本」分支向后兼容。
- **`layout/AppShell.tsx`**: `ViewMode` 联合类型加 `'resumes'`;`view === 'resumes'` 时渲染 `<ResumeLibraryView/>`;TopBar「+」菜单加「上传简历」项触发全局面 `ResumeUploadModal`(与现有 `AddApplicationForm` 同 LiftUp 模式)。
- **`layout/Sidebar.tsx`**: `NAV` 数组加「简历库」导航项(图标 `@ant-design/icons` `FileTextOutlined`)。
- **`layout/CommandPalette.tsx`**: 新增命令「上传简历」「打开简历库」。
- **`layout/TopBar.tsx`**: 「+」下拉项加「上传简历」。

### 状态归属

- 编辑抽屉的「所属简历 ID / open」**lift 到 `ResumeLibraryView`** —— 列表刷新导致卡片销毁时抽屉应保持。
- 上传承知(tastatus)放在 `ResumeLibraryView`,通过 props 下发给 `ResumeUploadModal`。
- `ResumeCard` 完全受控:点击操作通过 callback 上抛,不自持 fetch,便于复用与测试。
- 整页拖拽高亮是一个布尔 `useState` + dragenter/leave 计数防抖,在 `ResumeLibraryView` 内自持。

### 关键依赖

- **无新前端库**。整页拖拽用原生 `ondragenter/over/leave/drop` + 高亮遮罩 `useState`。
- AntD `Upload.Dragger` 仅在 modal 内用作文件选择可视化封装(与 `KnowledgeImportModal.tsx` 一致)。
- 后端 PDF 解析库 `github.com/ledongiatk/pdf`(纯 Go,无 CGO),也已评估 `pdfcpu`(备选)。

## 4. UI/交互细节

综合 frontend-design、make-interfaces-feel-better、ui-ux-pro-max 三个 skill 的可落地条款。

### 视觉层

- **同心圆角**: 外层卡片 12px → 内部 PDF 徽章/Tag 8px → 内部按钮 6px。
- **阴影替代硬边框**: 卡片 `0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06)`;失败态卡片用浅红描边 `#fecaca` 仅作状态区分,hover 仍 shadow 抬升。
- **主题色 CTA**: `linear-gradient(135deg, #6366f1, #8b5cf6)`,与现有 `--op-gradient-brand` 一致。
- **选中态**: 左侧 3px 色条 + `#eef2ff` 填充;颜色非唯一指示(配合键盘聚焦环)。
- **正文摘要**: `text-wrap: pretty` 防 orphans;计数「共 N 份」用 `font-variant-numeric: tabular-nums` 防数字跳位。

### 交互层

- **主 CTA 点击反馈**: `scale(0.96)` + `transition: transform 150ms`。非交互卡片不 scale(避免布局 shift)。
- **进入动画**: 卡片 split + stagger 100ms,`animation-delay: var(--i, 0)` 递增;首次渲染后 `initial={false}`,刷新不重播。
- **整页拖拽**: `dragenter` 弹「松开以发送 PDF」虚线半透明遮罩覆盖整页;`dragleave` 按 dragenter 计数防抖消除(防子元素误关);`drop` 调 `uploadResume`。无第三方库。
- **失败态卡片不灰化**: 保留暖色 PDF 徽章 + 红边 + 「手动校正 / 删除」双操作就近反馈。
- **抽屉保存**: 保存按钮带 loading 态防双击。

### 无障碍 / 响应式

- 主操作命中区 ≥ 40px;卡片底部三分隔操作每段单独可点(分隔条之间整段命中)。
- 键盘:Tab 进入卡片 → Enter 触发主操作「匹配」→ Shift+Tab 反向;图标按钮带 `aria-label`。
- 响应式断点复用现有:3 列 → 2 列(≤1100px) → 1 列(≤768px)。
- `prefers-reduced-motion`: 禁用 stagger 与遮罩过渡。

### 入口分布

- **主入口**: 简历库页顶部「+ 上传简历」CTA + 整页拖拽。
- **全局快捷**: TopBar「+」菜单「上传简历」项触发全局面 `ResumeUploadModal`。
- **命令面板**: Cmd/Ctrl+K 新增「上传简历」「打开简历库」。
- **匹配模态**: `ResumeMatchModal` 保留「粘贴文本」,新增「上传 PDF」次按钮,共享上传承知。

## 5. 错误处理

| 场景 | 处理 |
|---|---|
| 文件超大(>10MB) | 后端 multipart size cap 拒绝,前端 `beforeUpload` 也校验,就近提示 |
| 非 PDF 扩展名 | 后端拒绝;前端 `accept=".pdf"` |
| 提取文本为空(扫描版/图片式) | 入库 `parse_status=parse-failed`,卡片显示失败态 + 手动校正入口 |
| 上传中断/网络错 | `useMutation` 的 `onError` 弹 `message.error`,文件可重传 |
| 下载文件失败 | 卡片「下载」按钮就近错误提示,不影响其它操作 |
| 编辑保存冲突 | 极简乐观更新 + 失败回退为原值,提示重试 |

## 6. 测试边界

- **后端**: `uploadResume` handler 测试覆盖 happy path / 大文件 / 非法扩展 / 提取为空;`PUT /resumes/{id}/text` 覆盖正常与不存在 ID;`GET /resumes/{id}/file` 覆盖下载存在与不存在。
- **前端**: `ResumeCard` 纯组件渲染快照(成功/失败态);`ResumeLibraryView` 集成测试(空状/列表/拖拽高亮/上传成功 invalidate);`ResumeTextEditorDrawer` 表单校验 + 保存调用 mock。
- **不引入**: E2E 框架(MVP 阶段以单元/集成为主,与 codebase 现状一致)。

## 7. 与现有功能的关系

- **`ResumeMatchModal`** 不删除,逻辑扩展,向后兼容现有「粘贴文本 → 匹配」流。
- **Job description 匹配** (`/api/resumes/{id}/match`) 不变,消费 `parsed_data`,上传后的简历立即可被选来匹配。
- **knowledge import 范式** 是本设计的同构参考:multipart + size cap + 扩展名校验 + 服务端落盘,贡献了可复刻的实现路径。
- **Dashboard** 不改动;简历库是独立页,不与 dashboard widget 耦合。

## 8. 范围之外(YAGNI)

明确不做:

- DOCX/DOC/图片 OCR 等其它格式(MVP 仅 PDF)。
- 简历版本化/diff 对比(独立多份已覆盖求职场景)。
- 浏览器端预解析(双套解析弊大于利)。
- 异步解析 + 状态轮询(PDF 解析耗时可控,`parse_status` 已为升级预留)。
- 与面试题/复盘的自动联动(后续按需迭代)。
- E2E 测试框架。