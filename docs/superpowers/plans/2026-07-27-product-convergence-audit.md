# Product Convergence Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution; do not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛现有 AI 与面试/Offer 入口，先完成三个 P0-A 子任务、P0-B、P0-C，再单独完成 P1 的行动规则、Proposal 终态矩阵和固定中文扫描；不新增外部访问或业务能力。

**Architecture:** 先以测试锁定直接 API、Agent 控制面、Opportunity Fit v1/v2 持久化、面试索引和 Offer 比较的边界；每个 P0 任务独立提交并通过对应后端/前端回归后再进入下一个 P0。P1 任务不与 P0 混合，继续沿用各领域已有 repository、Proposal 和中文文案模块，只抽取必要的最小共享契约。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy/SQLite、Pydantic、pytest；React/TypeScript、Vitest、Axios；PowerShell 隔离 smoke 与现有本地/真实 AI harness。

---

## 0. 执行约束与基线

**Files:**

- Read: `docs/superpowers/specs/2026-07-27-product-convergence-audit-design.md`
- Read: `src/offerpilot/api.py`, `src/offerpilot/models.py`, `src/offerpilot/schemas.py`
- Read: `tests/test_jd_resume_ai_api.py`, `tests/test_ai_agent.py`, `tests/test_ai_tools.py`, `tests/test_opportunity_fit_reviews_{ai,api,repository}.py`, `tests/test_offers_api.py`

- [ ] 确认 `git status --short --branch` 干净，确认工作在 `feat/20260724-evidence-gated-interview-preparation`，每个任务只修改其列出的文件。
- [ ] 每项先写失败测试，运行该项最小测试集确认失败，再写最小实现；每项通过后单独提交，提交格式使用 `test: AI ...` 或 `fix: AI ...`。
- [ ] P0-A1、P0-A2、P0-A3、P0-B、P0-C 按顺序完成；P1-A、P1-B、P1-C 在 P0 全部通过后才开始。

## 1. P0-A1：JD/Resume 分析 URL fallback 零外联

**Files:**

- Modify: `src/offerpilot/api.py`, `src/offerpilot/ai/workflows.py`, `src/offerpilot/cli.py`
- Test: `tests/test_jd_resume_ai_api.py`, `tests/test_cli.py`, `tests/test_module_workflows.py`

- [ ] **Step 1: 写 URL 负向测试。** 在两个 HTTP 路由各加入四类断言：`{}` 与仅 URL 返回 `422`/`jd_text_required`，非空 `jd_text + jd_url` 返回 `422`/`jd_url_not_supported`，并用 `monkeypatch` 将 `httpx.get` 替换为抛错函数，证明它从未被调用；AI provider fake 也必须为零调用。

```python
def fail_external_request(*args: object, **kwargs: object) -> None:
    raise AssertionError("URL fallback must not issue an external request")

monkeypatch.setattr("httpx.get", fail_external_request)
response = client.post("/api/jd/analyze", json={"jd_url": "https://jobs.invalid/a"})
assert response.status_code == 422
assert response.json()["code"] == "jd_text_required"
```

- [ ] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_jd_resume_ai_api.py -q`；当前 URL fallback 会尝试读取 URL，测试应失败。
- [ ] **Step 3: 写最小实现。** 在 API 入参校验最前面拒绝 URL；只接受 `isinstance(jd_text, str) and jd_text.strip()`，保留原始文本给快照；删除 `api.py` 和 `ai/workflows.py` 的 URL fallback。CLI 的 `--jd-url`/等价参数改为稳定本地 422/错误退出，不调用 workflow；历史 `job_url` 保存、展示和审计不改。
- [ ] **Step 4: 补 CLI/workflow 回归并运行。** 增加 CLI URL 拒绝和 workflow 不调用 fetch 的测试，运行 `uv run pytest tests/test_jd_resume_ai_api.py tests/test_cli.py tests/test_module_workflows.py -q`；预期全绿。
- [ ] **Step 5: 提交。** `git add src/offerpilot/api.py src/offerpilot/ai/workflows.py src/offerpilot/cli.py tests/test_jd_resume_ai_api.py tests/test_cli.py tests/test_module_workflows.py && git commit -m "fix: AI block JD URL analysis fallback"`

**验收门槛：** 两个 HTTP 路由和 CLI 均不能触发 `httpx.get`；非空文本无 URL 的既有分析仍可调用 provider；历史 `job_url` 不被迁移或删除。

## 2. P0-A2：Agent 写工具逐次确认与旧配置归一

**Files:**

- Modify: `src/offerpilot/ai/agent.py`, `src/offerpilot/ai/tools.py`, `src/offerpilot/config.py`, `src/offerpilot/api.py`, `src/offerpilot/cli.py`
- Test: `tests/test_ai_agent.py`, `tests/test_ai_tools.py`, `tests/test_config.py`, `tests/test_settings_api.py`, `tests/test_chat_api.py`, `tests/test_cli.py`

- [ ] **Step 1: 写控制面失败测试。** 遍历 registry 中 `write is True` 的工具，在 `auto_approve=True` 时断言仍产生 pending confirmation 且 handler 未调用；批准后才调用一次。拒绝、取消、过期只写控制面审计并清除 pending，不改变 Application/Event/Resume/Offer/Material Kit/Knowledge/Question/Memory。

```python
for name, tool in registry.items():
    if tool.get("write"):
        _, _, pending = runner.run_turn(script_for(name), auto_approve=True, max_iter=8)
        assert pending is not None
        assert writes[name] == 0
```

- [ ] **Step 2: 写旧配置和备份失败测试。** `Config` 从 `True`、`"true"`、`1` 读取都归一为 `False`；`GET/PUT /api/settings`、设置备份导出/恢复和 CLI config 更新永远返回/写入 false，手工保存接口不经过 Agent gate。
- [ ] **Step 3: 运行失败测试。** 运行 `uv run pytest tests/test_ai_agent.py tests/test_ai_tools.py tests/test_config.py tests/test_settings_api.py tests/test_chat_api.py tests/test_cli.py -q`；当前 `auto_approve` 分支和设置转换应暴露失败。
- [ ] **Step 4: 写最小实现。** 将写工具的 confirmation 判定固定为 true，保留 `always_confirm` 语义但不能被配置绕过；pending 的 approved/rejected/cancelled/expired 使用现有 generation/token CAS。加载配置时固定 `chat_auto_approve_writes=False`，设置、备份和恢复只读兼容旧字段并重新写 false，不让 `bool("false")` 绕过。
- [ ] **Step 5: 运行专项测试并提交。** 重新运行上面的 pytest 命令，再运行 `uv run ruff check src tests`；全绿后提交 `fix: AI require confirmation for every agent write`。

**验收门槛：** 所有 registry 写工具都必须先 pending；网络/超时未知保持原 pending/token；任何自动批准配置不能改变该结论，旧 config/backup 仍可启动。

## 3. P0-A3：Opportunity Fit v2 中性化契约及 v1 历史兼容

**Files:**

- Modify: `src/offerpilot/models.py`, `src/offerpilot/schemas.py`, `src/offerpilot/ai/opportunity_fit_reviews.py`, `src/offerpilot/repositories/opportunity_fit_reviews.py`, `src/offerpilot/api.py`
- Modify: `web/src/types/opportunityFitReview.ts`, `web/src/services/opportunityFitReviews.ts`, `web/src/features/pilot/PilotOpportunityFitCard.tsx`, `web/src/components/ApplicationDetail.tsx`
- Create: `tests/test_opportunity_fit_reviews_migrations.py`
- Test: `tests/test_opportunity_fit_reviews_ai.py`, `tests/test_opportunity_fit_reviews_repository.py`, `tests/test_opportunity_fit_reviews_api.py`, `web/src/features/pilot/PilotOpportunityFitCard.test.tsx`, `web/src/features/pilot/pilotOpportunityFitLifecycle.test.ts`

- [ ] **Step 1: 写 v2 AI 契约失败测试。** 断言新输出只含 `schema_version=2`、固定 `source`、`summary`、四数组；拒绝 `recommendation`、score、概率、旧枚举、额外字段、重复 id、超限数组、伪造/空白/不连续 evidence excerpt；固定 `question_id` 由服务端派生文本，非 allowlist 问题必须引用。
- [ ] **Step 2: 写 v1/v2 数据兼容测试。** 建立一条现有 v1 行，断言读取不迁移、不重算 `source_fingerprint_sha256`、旧 canonical JSON、`triage_sha256`、`deep_review_sha256`；迁移新增 `proposal_schema_version`、`proposal_json`、`proposal_sha256`，v1 行仍使用旧列，v2 行只使用新列；同 key 同快照重放原行，不同快照/版本返回 `409 opportunity_fit_idempotency_conflict`。
- [ ] **Step 3: 写 API/前端联合类型失败测试。** v1 响应保留 `recommendation/triage/deep_review` 并只读显示；v2 响应含 `schema_version:2`、`proposal/source/proposal_hash` 且没有 recommendation。前端只能对 v1 显示“历史事实”，不渲染决策按钮；v2 显示条件、风险、问题和下一步。
- [ ] **Step 4: 运行失败测试。** 运行 `uv run pytest tests/test_opportunity_fit_reviews_ai.py tests/test_opportunity_fit_reviews_repository.py tests/test_opportunity_fit_reviews_api.py tests/test_opportunity_fit_reviews_migrations.py -q` 与 `cd web; npm.cmd test -- --run ...` 对应文件，确认当前 v1-only 实现失败。
- [ ] **Step 5: 写最小实现。** 按设计新增可空兼容列和迁移，不改写旧行；v2 使用严格 canonical JSON 与独立 `proposal_sha256`，输入快照独立计算 `source_fingerprint_sha256`，idempotency 以 `application_id + idempotency_key` 为唯一边界。API 使用 `schema_version` discriminator，Chat prompt、Pydantic schema、repository validator、API 和 TypeScript union 同批切换；历史 v1 只读，不产生状态动作。
- [ ] **Step 6: 运行专项并提交。** 运行后端专项、前端定向测试、`uv run ruff check src tests`、`uv run mypy src`；全绿后提交 `feat: AI add neutral opportunity fit v2 contract`。

**验收门槛：** v1 历史字节和哈希不变；新生成永不持久化 recommendation；证据门控、幂等冲突和历史只读均由后端强制，不能只靠 UI 隐藏。

## 4. P0-B：顶层面试索引

**Files:**

- Create: `src/offerpilot/repositories/interview_index.py`, `web/src/services/interviews.ts`, `web/src/types/interviewIndex.ts`
- Modify: `src/offerpilot/api.py`, `web/src/components/InterviewV01View.tsx`, `web/src/layout/AppShell.tsx`
- Create: `tests/test_interview_index_api.py`
- Test: `web/src/components/InterviewV01View.test.tsx`, `web/src/layout/AppShell.interviewReview.test.tsx`

- [ ] **Step 1: 写 API 失败测试。** 为 `GET /api/interviews?limit=&cursor=` 锁定只返回可见 Application 的 interview event、可见绑定 Note、历史 Proposal/已确认 Knowledge 摘要和准备入口；Application 软删除返回 404；事件/Note 删除或解绑保留历史摘要并标 `source_changed`，不允许新生成/handoff；standalone note 不进入索引。
- [ ] **Step 2: 写分页/排序/错误测试。** 断言默认 limit 50、最大 200、`scheduled_at` 非空优先后升序、`created_at DESC`、id DESC；返回 `{items,next_cursor}`，越界参数 422，跳转资源变不可见为 404。
- [ ] **Step 3: 写 UI 失败测试。** `InterviewV01View` 消费索引而非固定空状态；展示中文空状态、事件/历史只读状态并跳转详情；404 清除当前卡片/Drawer 且不创建 handoff。先验证 `ReviewManagementView` 可复用，否则不挂载半可达 Mock/Review 页面。
- [ ] **Step 4: 运行失败测试。** 运行 `uv run pytest tests/test_interview_index_api.py -q` 与 `cd web; npm.cmd test -- --run src/components/InterviewV01View.test.tsx src/layout/AppShell.interviewReview.test.tsx`。
- [ ] **Step 5: 写最小实现并回归。** repository 统一可见性、排序和 cursor；API 只读组合已有 Application/Event/Note/Proposal/Knowledge 数据；AppShell 保持当前 Pilot/Drawer 的 handoff 和 404 清理语义，不新增领域写入。
- [ ] **Step 6: 提交。** 运行专项、`npm.cmd run build`，提交 `feat: AI add top-level interview index`。

## 5. P0-C：Offer 比较护栏

**Files:**

- Modify: `src/offerpilot/api.py`, `web/src/services/offers.ts`, `web/src/components/OfferCompareDrawer.tsx`, `web/src/components/OfferCenterView.tsx`
- Create: `web/src/components/OfferCompareDrawer.test.tsx`, `web/src/components/OfferCenterView.test.tsx`
- Test: `tests/test_offers_api.py`

- [ ] **Step 1: 写 API/UI 失败测试。** `/api/offers/compare` 对无效/缺失/少于两个可见 Offer 返回稳定 `422 offer_comparison_requires_two_offers`；两条才保持请求顺序返回；UI 对 0/1 条不显示或禁用比较入口。
- [ ] **Step 2: 运行失败测试。** 运行 `uv run pytest tests/test_offers_api.py -q` 与对应 Vitest 文件，确认当前 endpoint 会接受少于两个结果。
- [ ] **Step 3: 写最小实现并验证。** API 解析并过滤后先计数，再比较；不增加 currency/pay_period/amount_basis 或平均/排名逻辑，不做税后、权益价值或“最优 Offer”推断。运行专项和 `npm.cmd run build`。
- [ ] **Step 4: 提交。** `git commit -m "fix: AI guard offer comparison inputs"`。

## 6. P1-A：行动提示单一事实源

**Files:**

- Create: `web/src/lib/actionHints.ts`, `web/src/lib/actionHints.test.ts`
- Modify: `web/src/lib/actionItems.ts`, `web/src/lib/missionControl.ts`, `web/src/lib/pipelineInsights.ts`
- Modify: `web/src/features/dashboard/DashboardView.tsx`, `web/src/features/reminders/RemindersView.tsx`, `web/src/layout/CommandPalette.tsx`
- Test: `web/src/lib/actionItems.test.ts`, `web/src/lib/missionControl.test.ts`, `web/src/lib/pipelineInsights.test.ts`, `web/src/features/dashboard/DashboardView.test.ts`, `web/src/layout/CommandPalette.test.ts`

- [ ] **Step 1: 写规则测试。** 先固定版本化阈值常量：Offer deadline 7 天、面试 72 小时、投递无更新 7/14 天、题目到期、材料包未完成；每个 `ActionHint` 必须带稳定 id、输入字段、阈值、原因、优先级、目标入口和确认要求。
- [ ] **Step 2: 运行失败测试。** 运行 `cd web; npm.cmd test -- --run src/lib/actionHints.test.ts src/lib/actionItems.test.ts src/lib/missionControl.test.ts src/lib/pipelineInsights.test.ts src/features/dashboard/DashboardView.test.ts src/layout/CommandPalette.test.ts`。
- [ ] **Step 3: 写最小实现。** 仅让 Dashboard、Reminders、Command Palette 的动态提示消费同一 `ActionHint` 规则；静态快捷命令保留为 command，不冒充提醒；点击只导航到原生查看/表单，不直接写领域数据。
- [ ] **Step 4: 提交。** 运行定向测试和 build，提交 `refactor: AI unify action hint rules`。

## 7. P1-B：五类 Proposal 终态一致性矩阵

**Files:**

- Modify: `src/offerpilot/ai/material_proposals.py`, `src/offerpilot/ai/opportunity_fit_reviews.py`, `src/offerpilot/ai/interview_review_proposals.py`, `src/offerpilot/ai/interview_preparation_proposals.py`, `src/offerpilot/repositories/interview_knowledge_capture.py`, `src/offerpilot/api.py`, `src/offerpilot/smoke.py`
- Test: existing `tests/test_material_revision_proposals_{ai,api,repository}.py`, `tests/test_opportunity_fit_reviews_{ai,api,repository}.py`, `tests/test_interview_review_proposals_{ai,api,repository}.py`, `tests/test_interview_knowledge_capture_{ai,api,repository}.py`, `tests/test_interview_preparation_{ai,api,repository}.py`, `tests/test_smoke.py`

- [ ] **Step 1: 写每领域终态表测试。** 分别锁定 Provider/网络未知、模型契约失败、严格校验后的安全空结果、无证据可用四类结果：材料契约失败仍为 `502 material_proposal_unverifiable`，只有合法 `changes=[]` 才 safe_empty；机会评估契约失败不写 Review；复盘两次契约失败按既有安全空语义；知识沉淀 AI 失败不阻塞 direct save；面试准备保留 `202/502` key 并只对两次契约失败落 safe_empty。
- [ ] **Step 2: 写未知结果重试测试。** 断言所有 Provider/网络未知路径保留原 key、冻结输入和必要 lease；同 key 重试不生成第二条 Proposal/Attempt；禁止将未知结果映射成确定失败或清除 key。
- [ ] **Step 3: 运行失败测试。** 分别运行五组后端专项和 `uv run pytest tests/test_smoke.py -q`，确认矩阵中错误码/空结果不一致处失败。
- [ ] **Step 4: 写最小实现。** 只统一诊断字段和测试断言，不合并各领域输入快照、证据路径或 repository；保留各流程已有错误码、HITL、原子写入和外部访问禁止边界。
- [ ] **Step 5: 验证并提交。** 运行五组专项、smoke、Ruff、Mypy，提交 `test: AI codify proposal terminal semantics`。

## 8. P1-C：固定系统文案中文扫描

**Files:**

- Modify: `web/src/components/materialFlowCopy.ts`, `web/src/components/opportunityFitCopy.ts`, `web/src/components/MaterialKitDrawer.tsx`, `web/src/components/InterviewReviewProposalDrawer.tsx`, `web/src/components/InterviewPreparationProposalDrawer.tsx`, `web/src/components/InterviewKnowledgeCaptureDrawer.tsx`
- Create: `web/src/components/systemCopyRegression.test.ts`
- Test: `web/src/components/materialFlowCopy.test.ts`, `web/src/components/opportunityFitCopy.test.ts`, affected component tests, `web/src/components/systemCopyRegression.test.ts`

- [ ] **Step 1: 写扫描测试。** 只列版本化固定英文短语集合，覆盖标题、说明、按钮、加载/空状态、状态、证据来源、无障碍标签和安全错误；测试源代码/渲染固定文案不含这些短语，同时用英文 JD、职位名、Resume 标题、用户断言和证据摘录 fixture 证明任意英文不会被禁止。
- [ ] **Step 2: 写错误映射测试。** 仅按错误码/HTTP 状态映射中文；不透传 Axios、`response.data.error` 或 `Error.message`。覆盖材料/复盘/准备的未知、不可验证、冲突、404/409/422/502 与 safe_empty。
- [ ] **Step 3: 写最小实现并回归。** 文案只进入材料流程专用 copy 模块；固定证据来源按流程映射，`evidence_bundle` 显示“已确认的投递证据快照”；空 changes 只显示中文“暂无可用改写”且不渲染模型 summary。动态用户数据和证据摘录保持原文。
- [ ] **Step 4: 提交。** 运行前端全量测试与 `npm.cmd run build`，提交 `fix: AI finalize Chinese material flow copy`。

## 9. 最终门禁与真实验收

- [ ] P0 每项单独验收后，按 P1-A、P1-B、P1-C 顺序运行完整后端专项、前端全量和构建；任何 P1 不得在 P0 提交中顺手修改。
- [ ] 运行 `uv run pytest`、`uv run ruff check .`、`uv run mypy src`、`cd web; npm.cmd test -- --run`、`npm.cmd run build`、`uv run oc smoke --static-dir web/dist`、`uv run oc verify --profile local --static-dir web/dist`。
- [ ] 使用临时隔离数据目录执行 real-AI verify 和浏览器走查；断言 URL 输入零外联、Agent 写入逐次确认、Opportunity Fit v1 历史/v2 新结果、面试索引软删除 404、Offer 0/1/2 护栏，且无自动状态变更、投递、知识扩张或招聘平台请求。停止精确服务进程并清理临时目录，最后验证源数据目录未变化。
- [ ] 完成独立 CR 和问题回归后，再提交发布报告；本计划阶段不执行代码、不运行实现测试。
