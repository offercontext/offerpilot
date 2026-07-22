# Pilot Guided Opportunity Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task with TDD checkpoints.

**Goal:** 将既有 Opportunity Fit 的 Triage、Deep Review 和冻结快照材料交接接入 Application 上下文的 Pilot，并保持证据门控、幂等、结果未知、人工确认和无外部平台访问边界。

**Architecture:** 保留现有 Opportunity Fit API、数据模型和 Material Kit 生命周期；新增前端原生 PilotOpportunityFitCard 作为 Application-scoped 流程卡。AppShell 持有唯一的 applicationId/pilotDraftKey 草稿和一次性交接引用，ApplicationDetail 通过原子 consumeMaterialKitHandoff(applicationId) 消费冻结 Resume/JD。既有 OpportunityFitReviewDrawer 与新卡片共用固定中文文案和安全错误映射，但不共用可变表单状态。

**Tech Stack:** React 18、TypeScript、Ant Design、TanStack Query、Vitest/jsdom；现有 FastAPI/SQLAlchemy Opportunity Fit API；PowerShell 本地部署脚本与内置浏览器验收。

---

### Task 1: 固化设计状态并建立实现基线

**Files:**
- Modify: docs/superpowers/specs/2026-07-21-pilot-guided-opportunity-fit-design.md
- Create: docs/superpowers/plans/2026-07-22-pilot-guided-opportunity-fit.md

- [ ] **Step 1: 标记设计已通过复审**

将设计文档的状态改为 已复审通过，不改变已批准的接口、边界和验收条款。

- [ ] **Step 2: 运行实现前基线检查**

```powershell
git status --short --branch
uv run pytest tests/test_opportunity_fit_reviews_ai.py tests/test_opportunity_fit_reviews_repository.py tests/test_opportunity_fit_reviews_api.py -q
Set-Location web
npm.cmd test -- --run src/components/OpportunityFitReviewDrawer.test.tsx src/components/ApplicationDetail.opportunityFit.render.test.tsx
Set-Location ..
```

Expected: 当前 Opportunity Fit 后端专项和既有抽屉/详情测试通过；已有失败必须记录为基线，而不能归因于 Pilot 改动。

- [ ] **Step 3: 提交计划与状态变更**

```powershell
git add -f docs/superpowers/specs/2026-07-21-pilot-guided-opportunity-fit-design.md docs/superpowers/plans/2026-07-22-pilot-guided-opportunity-fit.md
git commit -m "docs: AI plan Pilot opportunity fit implementation"
```

### Task 2: 先写共享中文文案与安全错误映射测试

**Files:**
- Create: web/src/components/opportunityFitCopy.ts
- Create: web/src/components/opportunityFitCopy.test.ts
- Modify: web/src/components/OpportunityFitReviewDrawer.tsx
- Test: web/src/components/OpportunityFitReviewDrawer.test.tsx

- [ ] **Step 1: 写 RED 测试，锁定错误透传边界**

新增纯函数测试，验证只根据稳定错误码/HTTP 状态返回固定中文，不返回 Axios message、服务端 error 或 Error.message：

```ts
it('maps only verified opportunity-fit errors', () => {
  expect(getOpportunityFitErrorMessage({
    response: { status: 502, data: {
      error_code: 'opportunity_fit_unverifiable',
      error: 'raw provider text',
    } },
  })).toContain('证据校验');

  expect(getOpportunityFitErrorMessage({
    response: { status: 502, data: { error: 'raw provider text' } },
  })).toBe('AI 服务暂不可用，请稍后重试');

  expect(getOpportunityFitErrorMessage({
    response: { status: 409, data: { error: 'raw conflict text' } },
  })).toBe('操作未完成，请稍后重试');

  expect(getOpportunityFitErrorMessage(new Error('raw axios message')))
    .toBe('操作失败，请稍后重试');
});
```

来源标签测试必须覆盖 resume -> 简历、jd -> 岗位描述（仅用于分析方向）、user_assertion -> 用户断言（用户提供，未外部核验）。材料提案的 evidence_bundle 不属于 Opportunity Fit 类型，不能映射成 JD。

- [ ] **Step 2: 运行 RED**

```powershell
Set-Location web
npm.cmd test -- --run src/components/opportunityFitCopy.test.ts
Set-Location ..
```

Expected: FAIL，因为共享映射模块尚未存在，且现有抽屉仍直接返回服务端错误文本。

- [ ] **Step 3: 实现最小共享映射模块**

导出 getOpportunityFitErrorMessage、opportunityFitEvidenceLabel 和固定 UI 文案对象。映射顺序必须是稳定 error_code，再按 HTTP 状态 404/409/422/502，最后统一中文兜底。未知 5xx 不显示服务端内容；opportunity_fit_provider_error 与无错误码的 502 使用不同文案；只有 opportunity_fit_unverifiable 显示“未通过证据校验”。

- [ ] **Step 4: 接入既有抽屉并验证 GREEN**

删除 OpportunityFitReviewDrawer.tsx 内的 response.data.error、Error.message 直接展示路径，改为共享映射；证据摘录、JD、Resume 标题和 AI 正文仍原样渲染。

```powershell
Set-Location web
npm.cmd test -- --run src/components/opportunityFitCopy.test.ts src/components/OpportunityFitReviewDrawer.test.tsx
Set-Location ..
```

### Task 3: 先写 Pilot 卡片状态机与输入/幂等测试

**Files:**
- Create: web/src/features/pilot/PilotOpportunityFitCard.tsx
- Create: web/src/features/pilot/PilotOpportunityFitCard.test.tsx
- Create: web/src/features/pilot/PilotOpportunityFitCard.module.css
- Create: web/src/features/pilot/opportunityFitDraft.ts
- Create: web/src/features/pilot/opportunityFitDraft.test.ts
- Reuse: web/src/services/opportunityFitReviews.ts
- Reuse: web/src/types/opportunityFitReview.ts

- [ ] **Step 1: 写纯函数 RED 测试**

opportunityFitDraft.ts 只负责输入归一化、断言校验和失败分类，不执行请求：

```ts
it('normalizes assertions by trim and empty-line removal', () => {
  expect(normalizeOpportunityFitAssertions('  one  \n\n two '))
    .toEqual(['one', 'two']);
});

it('classifies unknown transport and server failures', () => {
  expect(classifyOpportunityFitFailure({ response: { status: 500 } }))
    .toBe('unknown');
  expect(classifyOpportunityFitFailure({ response: { status: 502, data: {} } }))
    .toBe('unknown');
  expect(classifyOpportunityFitFailure(new Error('Network Error')))
    .toBe('unknown');
  expect(classifyOpportunityFitFailure({ response: { status: 422 } }))
    .toBe('definite_failure');
  expect(classifyOpportunityFitFailure({
    response: { status: 502, data: {
      error_code: 'opportunity_fit_provider_error',
    } },
  })).toBe('definite_failure');
});
```

- [ ] **Step 2: 写卡片 RED 测试**

必须覆盖 11 条断言、501 字断言、trim 后请求体、确认取消不请求、Triage 成功后才可 Deep Review、未知 500/网关 502/无效响应体/超时保留 key、422/调用前 404/稳定错误码 502 清除 key、用户修改输入生成新 key，以及历史只读不能猜测命中。

核心重试断言：

```tsx
it('reuses triageAttemptKey after a timeout', async () => {
  createOpportunityFitReview
    .mockRejectedValueOnce(new Error('timeout'))
    .mockResolvedValueOnce(validReview);

  // confirm, observe “结果未知”, click retry
  expect(createOpportunityFitReview).toHaveBeenNthCalledWith(
    1, 7, expect.objectContaining({ idempotency_key: 'attempt-1' }),
  );
  expect(createOpportunityFitReview).toHaveBeenNthCalledWith(
    2, 7, expect.objectContaining({ idempotency_key: 'attempt-1' }),
  );
});
```

- [ ] **Step 3: 运行 RED**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/opportunityFitDraft.test.ts src/features/pilot/PilotOpportunityFitCard.test.tsx
Set-Location ..
```

Expected: FAIL，因为卡片、草稿 reducer 和错误分类尚未实现。

- [ ] **Step 4: 实现最小状态机与草稿 reducer**

定义 PilotOpportunityFitCardProps：application、稳定 pilotDraftKey、onPrepareMaterials、onCancel。状态只允许 collect_input、confirm_triage、triage_loading、triage_ready、confirm_deep_review、deep_review_loading、deep_review_ready、material_handoff。临时输入和当前结果只存 React 状态。首次确认生成 crypto.randomUUID() 并保存到当前草稿；未知结果重试复用；只有错误 allowlist 明确失败时清除。每次 Resume/JD/断言变更和显式取消使 key 失效。

- [ ] **Step 5: 实现结构化卡片界面**

使用 Ant Design Form、Input、Select、Alert、Button、Card、Tag、Modal，不使用 Markdown。输入区显示 Resume、粘贴 JD、断言限制、发送给当前 AI 服务提示和人工确认提示；结果区显示证据摘要、岗位约束、匹配信号、gap、问题、截止日期、Deep Review 结果和证据引用。固定文案来自共享 copy；动态 JD、Resume、AI 正文和 excerpt 原样显示。

- [ ] **Step 6: GREEN**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/opportunityFitDraft.test.ts src/features/pilot/PilotOpportunityFitCard.test.tsx
Set-Location ..
```

### Task 4: 实现 Deep Review 人工确认与材料交接选择

**Files:**
- Modify: web/src/features/pilot/PilotOpportunityFitCard.tsx
- Modify: web/src/features/pilot/PilotOpportunityFitCard.test.tsx

- [ ] **Step 1: 写 RED 测试**

```tsx
it('requires a second confirmation before Deep Review', async () => {
  expect(screen.getByText('确认深入分析')).toBeInTheDocument();
  // cancel confirmation
  expect(createOpportunityFitDeepReview).not.toHaveBeenCalled();
});

it('requires explicit confirmation for a divergent material choice', async () => {
  // valid deep review returns clarify_first
  const button = screen.getByRole('button', { name: '仍要准备材料' });
  expect(button).not.toHaveAttribute('type', 'primary');
  // first click opens divergence confirmation; only confirm calls handoff
});
```

另测 prepare_materials 使用主按钮“准备材料”；任意 Deep Review 结果都不能被模型建议阻断；handoff 只调用 onPrepareMaterials，不调用 Material Kit generate/update 或 Proposal accept service。

- [ ] **Step 2: 运行 RED**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/PilotOpportunityFitCard.test.tsx
Set-Location ..
```

- [ ] **Step 3: 实现 Deep Review 与一次性交接回调**

Deep Review 需要 Triage 成功和用户确认；失败保留 review_id 并沿用既有后端幂等语义。完成后按 recommended_path 选择主/次按钮；次按钮先说明该选择与 AI 建议路径不同，确认后才回调冻结 review.source.resume.id 与 review.source.jd.text。空结果显示安全空状态，不自动推进。

- [ ] **Step 4: GREEN**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/PilotOpportunityFitCard.test.tsx
Set-Location ..
```

### Task 5: 在 AppShell 建立唯一 Application 草稿和原子 handoff

**Files:**
- Create: web/src/features/pilot/materialKitHandoff.ts
- Create: web/src/features/pilot/materialKitHandoff.test.ts
- Modify: web/src/layout/AppShell.tsx
- Modify: web/src/components/ApplicationDetail.tsx
- Modify: web/src/components/ApplicationDetail.opportunityFit.render.test.tsx
- Modify: web/src/layout/AppShell.test.ts

- [ ] **Step 1: 写 handoff RED 测试**

```ts
it('consumes only a matching application handoff once', () => {
  const store = createMaterialKitHandoffStore();
  const handoff = Object.freeze({
    applicationId: 7,
    reviewId: 8,
    resumeId: 11,
    jdText: 'Frozen JD',
  });

  store.write(handoff);
  expect(store.consume(8)).toBeNull();
  expect(store.consume(7)).toEqual(handoff);
  expect(store.consume(7)).toBeNull();
});
```

ApplicationDetail 回归测试验证：consumeMaterialKitHandoff(application.id) 返回冻结 resumeId/jdText 后自动打开 Material Kit；不检查 token、不访问 job_url、不调用生成/更新接口；同一 handoff 重挂载不重复消费。

- [ ] **Step 2: 运行 RED**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/materialKitHandoff.test.ts src/components/ApplicationDetail.opportunityFit.render.test.tsx src/layout/AppShell.test.ts
Set-Location ..
```

- [ ] **Step 3: 实现 AppShell 原子 handoff store**

用 useRef 保存 pending handoff，以同步 read-match-clear 保证同一事件循环只能消费一次；暴露稳定的 consumeMaterialKitHandoff(applicationId)，不把原始可写对象传给子组件。AppShell 在同一 Application 上下文只生成一次 pilotDraftKey 并只渲染一个 PilotOpportunityFitCard；切换 Application 时冻结/丢弃旧草稿引用，历史评估不共享输入和幂等 key。

- [ ] **Step 4: 接入入口与材料交接**

在 ApplicationDetail 增加“在 Pilot 中评估”按钮，调用 AppShell 的 Application-context Pilot 启动回调；AppShell 切换至 Pilot 视图并挂载该 application 的卡片。卡片 handoff 写入后，AppShell 打开该 ApplicationDetail；Detail 在 effect 中调用原子 consumer，设置现有 materialKitPrefill 并仅打开 MaterialKitDrawer。MaterialKitDrawer 只读使用 initialResumeID/initialJdSnapshot，不发写请求。

- [ ] **Step 5: GREEN 与唯一归属回归**

测试入口传递正确 applicationId；Pilot 侧栏/抽屉切换和组件重挂载不产生第二个 pilotDraftKey；Application 不匹配 handoff 不消费；点击 handoff 后没有 materialKits、materialRevisionProposals 或 Application status mutation。

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/materialKitHandoff.test.ts src/components/ApplicationDetail.opportunityFit.render.test.tsx src/layout/AppShell.test.ts
Set-Location ..
```

### Task 6: 历史冻结恢复、现有入口与固定文案回归

**Files:**
- Modify: web/src/features/pilot/PilotOpportunityFitCard.tsx
- Modify: web/src/features/pilot/PilotOpportunityFitCard.test.tsx
- Modify: web/src/components/OpportunityFitReviewDrawer.tsx
- Modify: web/src/components/OpportunityFitReviewDrawer.test.tsx
- Modify: web/src/components/ApplicationDetail.opportunityFit.test.ts
- Modify: web/src/components/ApplicationDetail.opportunityFit.render.test.tsx

- [ ] **Step 1: 写历史恢复 RED 测试**

模拟列表只返回 summary，再通过详情读取冻结 source.jd.text、source.resume.id、候选人断言和已生成结果。断言历史评估以只读标签展示；当前 Application 备注/JD 或 Material Kit 当前 JD 不会替代冻结文本；历史“准备材料”只使用冻结文本。

- [ ] **Step 2: 写旧 URL 边界和固定文案回归测试**

```ts
it('does not start legacy URL JD analysis from ApplicationDetail', () => {
  expect(applicationDetailSource).not.toContain('analyzeJD');
  expect(applicationDetailSource).not.toContain('application.job_url');
});
```

组件测试覆盖 Triage/Deep Review 成功、空结果、证据来源标签、路径和摘录原文，以及 404/422/409/502/未知错误不显示原始英文。动态英文 JD、公司名、Resume 标题和 excerpt 必须仍存在。

- [ ] **Step 3: 实现历史只读加载**

首次挂载只查询 Resume 列表和 Opportunity Fit summary 列表；点击“查看”才请求详情。详情成功后进入 triage_ready/deep_review_ready 只读状态，不创建新的 idempotency key；404 清理当前卡片并使用安全中文提示。

- [ ] **Step 4: GREEN**

```powershell
Set-Location web
npm.cmd test -- --run src/features/pilot/PilotOpportunityFitCard.test.tsx src/components/OpportunityFitReviewDrawer.test.tsx src/components/ApplicationDetail.opportunityFit.test.ts src/components/ApplicationDetail.opportunityFit.render.test.tsx
Set-Location ..
```

### Task 7: Real-AI 隔离 smoke 与本地浏览器验收

**Files:**
- Modify: src/offerpilot/smoke.py
- Modify: tests/test_smoke.py

- [ ] **Step 1: 先写 smoke RED 回归**

保留现有 run_http_smoke(real_ai=True) 的临时数据目录复制配置行为，新增断言：空数据目录运行结束后无 active Resume、无 master、无 Application Material Kit、无 Material Revision Proposal、无 Opportunity Fit Review；local profile 不使用真实 Provider。API smoke 只校验公共字段，不输出完整 Resume/JD、断言或模型原文。

- [ ] **Step 2: 运行 RED**

```powershell
uv run pytest tests/test_smoke.py -q
```

- [ ] **Step 3: 实现或确认隔离 smoke**

真实 profile 将 config.json 复制到 TemporaryDirectory(prefix="offerpilot-real-ai-verify-")，只在该目录创建合成数据；finally 删除临时目录并调用现有清理/残留断言。real-AI API smoke 调用 Triage/Deep Review，允许安全空结果；local profile 保持 fake model。若当前实现已经满足这些断言，只保留回归测试而不添加重复生产逻辑。

- [ ] **Step 4: 运行真实服务与内置浏览器闭环**

```powershell
Set-Location web
npm.cmd run build
Set-Location ..
uv run oc verify --profile local --static-dir web/dist
uv run oc verify --profile real-ai --static-dir web/dist
uv run oc start --port 18766
```

在内置浏览器从绑定 Application 的“在 Pilot 中评估”进入；完成输入确认、Triage 确认、Deep Review 确认和材料交接。记录 Triage 重试沿用同一 key；材料包只获得冻结 Resume/JD 预填；没有自动 Material Kit/Proposal/Application 状态写入；没有招聘平台请求；真实模型返回空结果时记录为安全空结果，不强行推进。

### Task 8: 全量验证、代码审查与交付

**Files:**
- All files touched by Tasks 2–7

- [ ] **Step 1: 运行完整自动化 gate**

```powershell
uv run pytest
uv run ruff check src tests
uv run mypy src
Set-Location web
npm.cmd test -- --run
npm.cmd run build
Set-Location ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-smoke.ps1
uv run oc verify --profile local --static-dir web/dist
uv run oc verify --profile real-ai --static-dir web/dist
```

- [ ] **Step 2: 做安全边界检查**

```powershell
git diff --check
git status --short --branch
rg -n "job_url|analyzeJD|external|apply|auto.?submit|match.?score" web/src/features/pilot web/src/components/ApplicationDetail.tsx
```

确认 Pilot 新路径不读取 URL、不访问招聘平台、不改变投递状态、不自动生成/接受材料；固定文案扫描只检查已知英文短语，不能禁止动态英文数据。

- [ ] **Step 3: 请求独立代码审查**

复审范围：Pilot 状态机、triageAttemptKey 未知结果语义、AppShell 草稿唯一性、handoff 原子消费、历史冻结交接、错误透传、无 URL/外部平台边界和 real-AI 隔离清理。所有 P0/P1/P2 问题修复后重新执行定向测试和 git diff --check。

- [ ] **Step 4: 提交开发成果**

```powershell
git add src tests web docs/superpowers/specs/2026-07-21-pilot-guided-opportunity-fit-design.md docs/superpowers/plans/2026-07-22-pilot-guided-opportunity-fit.md
git commit -m "feat: AI add Pilot opportunity fit flow"
```

## Self-review

- API、数据模型和 Material Kit 写入契约保持不变；所有新增状态均为前端 Application-scoped 临时状态。
- triageAttemptKey 只有契约明确保证不写入的 422、调用前 404 和稳定错误码 502 才清除；未知 5xx、无效响应体和传输失败永不换 key。
- 历史评估只读恢复冻结快照，不能按时间或摘要猜测当前尝试，也不能清除当前 key。
- AppShell 用单一草稿 key 和 ref-backed handoff 防止重复卡片/重复消费；ApplicationDetail 不自行校验 token。
- 真实 AI 通过隔离数据目录运行；浏览器验收必须检查 Pilot 前端闭环和网络边界，不能以 API-only smoke 替代。
