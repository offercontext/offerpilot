# Application JD Versions Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each step uses checkbox syntax and must be completed in order.

**Goal:** Add an immutable, Application-bound JD version chain and make every new Application-bound workflow consume and freeze the current confirmed JD without URL fetching, implicit AI writes, or cross-domain side effects.

**Architecture:** Create one application_jd_versions table and one shared ApplicationJDService/Repository. The save transaction uses idempotency replay before an expected_current_version_id CAS; UI and Pilot supply a server-owned source_kind while sharing the same service. New domain rows store a plain integer jd_version_id plus a self-contained immutable snapshot, and parent workflows inherit the parent snapshot instead of accepting a second JD.

**Tech Stack:** Python, SQLAlchemy, SQLite migrations, FastAPI, pytest, FastAPI TestClient, React, TypeScript, Vitest, existing Pilot tool/confirmation infrastructure, PowerShell browser harnesses.

---

## 0. Execution boundary and immutable implementation baseline

**Files:**
- Read: AGENTS.md
- Read: docs/superpowers/specs/2026-08-05-application-jd-versions-design.md
- No product file changes in this task.

- [ ] **Step 1: Verify the worktree and capture a stable baseline.**

Run from D:\Users\yuqi.chen\offerpilot\.worktrees\feat-20260805-application-jd-versions before changing code. The plan commit, not a hard-coded hash, is the implementation baseline:

~~~powershell
$planPath = 'docs/superpowers/plans/2026-08-05-application-jd-versions.md'
$baselineFile = Join-Path $env:TEMP 'offerpilot-application-jd-versions-baseline.txt'
$implementationBase = (git log -1 --format=%H -- $planPath).Trim()
if (-not $implementationBase) { throw 'Cannot resolve approved plan baseline' }
if (@(git status --short).Count -ne 0) { throw 'Worktree must be clean before implementation' }
git cat-file -e "$implementationBase^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'Implementation baseline is not a commit' }
$implementationBase | Set-Content -LiteralPath $baselineFile -Encoding ascii
~~~

The plan and design become read-only after this step. Every subsequent PowerShell process must load and validate the same file before running an allowlist or diff check:

~~~powershell
$baselineFile = Join-Path $env:TEMP 'offerpilot-application-jd-versions-baseline.txt'
$implementationBase = (Get-Content -LiteralPath $baselineFile -Raw).Trim()
git cat-file -e "$implementationBase^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'Recorded implementation baseline is invalid' }
~~~

- [ ] **Step 2: Freeze the implementation allowlist.**

Only these product files may change in the implementation slice:

~~~text
src/offerpilot/db.py
src/offerpilot/models.py
src/offerpilot/repositories/application_jd_versions.py
src/offerpilot/repositories/jd.py
src/offerpilot/repositories/opportunity_fit_reviews.py
src/offerpilot/repositories/material_kits.py
src/offerpilot/repositories/material_revision_proposals.py
src/offerpilot/repositories/interview_preparation_proposals.py
src/offerpilot/repositories/mock_interviews.py
src/offerpilot/api.py
src/offerpilot/cli.py
src/offerpilot/ai/tools.py
src/offerpilot/ai/agent.py
web/src/components/ApplicationDetail.tsx
web/src/components/ApplicationDetail.module.css
web/src/services/applicationJdVersions.ts
web/src/services/applicationJdVersions.test.ts
web/src/types/applicationJdVersion.ts
tests/test_application_jd_versions_migrations.py
tests/test_application_jd_versions_repository.py
tests/test_application_jd_versions_api.py
tests/test_jd_resume_ai_api.py
tests/test_material_kits_api.py
tests/test_material_revision_proposals_api.py
tests/test_opportunity_fit_reviews_api.py
tests/test_interview_preparation_api.py
tests/test_mock_interview_api.py
tests/test_smoke.py
web/src/components/ApplicationDetail.jdVersions.test.tsx
web/src/components/ApplicationDetail.jdVersions.integration.test.tsx
web/src/components/ChatPanel/PilotTaskCard.tsx
web/src/components/ChatPanel/MessageBubble.tsx
web/src/components/ChatPanel/model.ts
web/src/components/ChatPanel/PilotApplicationJdCard.test.tsx
web/src/features/pilot/applicationJdVersion.ts
web/src/features/pilot/applicationJdVersion.test.ts
scripts/application-jd-real-ai-browser-harness.ps1
scripts/browser-network-audit.py
docs/reports/2026-08-05-application-jd-versions-release-verification.md
~~~

Any other changed path fails the implementation gate. Do not touch the root worktree's existing uncommitted tests/test_smoke.py; all work stays in this worktree.

- [ ] **Step 3: Commit the approved plan.**

~~~powershell
git add -f docs/superpowers/plans/2026-08-05-application-jd-versions.md
git commit -m "docs: AI plan application JD versions"
~~~

Expected result: one plan-only commit, a clean worktree, and no implementation tests run yet.

## 1. Migration and model contract

**Files:**
- Create: tests/test_application_jd_versions_migrations.py
- Modify: src/offerpilot/models.py
- Modify: src/offerpilot/db.py
- Modify: tests/test_applications_repository.py for the model registration and deletion regression.

- [ ] **Step 1: Add failing migration tests from real prior DDL.**

Create a fixture that builds the last pre-feature schema, including schema_migrations through 0017_offer_comparison_negotiation, applications, and every table receiving jd_version_id. Do not call create_all before the upgrade. Assert the pre-upgrade DDL has no application_jd_versions table and no new columns.

Add tests with these exact assertions:

~~~python
assert _table_columns(db_path, 'application_jd_versions') == {
    'id', 'application_id', 'version_number', 'jd_text', 'content_sha256',
    'source_url', 'source_kind', 'idempotency_key',
    'request_fingerprint_sha256', 'created_at',
}
assert _table_columns(db_path, 'mock_interview_attempts') >= {'jd_version_id'}
assert _table_columns(db_path, 'opportunity_fit_review_stages') >= {'jd_version_id'}
assert _schema_migration_count(db_path, '0018_application_jd_versions') == 1
~~~

Also assert the added identity columns are nullable ordinary integers with no foreign-key entry, while application_jd_versions.application_id is the only new JD-version foreign key and uses ON DELETE CASCADE. Test the migration twice and compare all pre-existing application, JD analysis, resume match, Proposal, and Attempt bytes before and after.

Add one deletion test that creates an Application, one JD version, a JDAnalysis, and a ResumeMatch, then deletes the Application. Assert the JD version is cascaded, JDAnalysis/ResumeMatch remain with application_id set to NULL while their plain-integer jd_version_id and snapshot bytes remain, and no deletion is blocked by any added identity column. Assert the snapshot-bearing history rows retain their original bytes whenever their existing parent deletion rules retain them.

Run:

~~~powershell
uv run pytest tests/test_application_jd_versions_migrations.py -q
~~~

Expected before implementation: FAIL because the table, columns, and migration do not exist.

- [ ] **Step 2: Add the SQLAlchemy model and migration.**

Add ApplicationJDVersion to src/offerpilot/models.py with these constraints:

~~~python
__table_args__ = (
    UniqueConstraint('application_id', 'version_number'),
    UniqueConstraint('application_id', 'idempotency_key'),
    Index('idx_application_jd_versions_app_version', 'application_id', 'version_number'),
)
~~~

Use Text for jd_text, String for hashes and metadata, and a nullable source URL. Add nullable Integer columns named jd_version_id to the exact tables in the approved design without ForeignKey declarations. Add JDAnalysis.jd_version_id and ResumeMatch.jd_version_id as nullable ordinary integers too.

Extend src/offerpilot/db.py with 0018_application_jd_versions: create the new table and use the existing migration helpers to add missing columns idempotently. Preserve old rows as NULL; do not infer a version from any existing jd_text, jd_snapshot, or Proposal snapshot. Keep Application deletion behavior exactly as the existing parent tables define it.

- [ ] **Step 3: Run migration and model tests.**

~~~powershell
uv run pytest tests/test_application_jd_versions_migrations.py -q
uv run pytest tests/test_applications_repository.py -q
~~~

Expected result: all new migration tests and existing application repository tests pass; the migration is idempotent and old bytes are unchanged.

- [ ] **Step 4: Commit the migration slice.**

~~~powershell
git add src/offerpilot/models.py src/offerpilot/db.py tests/test_application_jd_versions_migrations.py tests/test_applications_repository.py
git commit -m "feat: AI add application JD version storage"
~~~

## 2. JD version service, repository, and deterministic validation

**Files:**
- Create: src/offerpilot/repositories/application_jd_versions.py
- Create: tests/test_application_jd_versions_repository.py

- [ ] **Step 1: Add failing repository tests for validation and fingerprinting.**

The new module must expose ApplicationJDService; its public operations must be named and typed as:

~~~python
get_current(application_id: int) -> ApplicationJDVersion | None
require_current(application_id: int) -> ApplicationJDVersion
list_versions(application_id: int, offset: int, limit: int) -> list[ApplicationJDVersionSummary]
get_version(application_id: int, version_id: int) -> ApplicationJDVersion | None
freeze(version: ApplicationJDVersion) -> FrozenApplicationJD
create_version(
    application_id: int,
    *,
    jd_text: str,
    source_url: str | None,
    source_kind: Literal['ui', 'pilot'],
    expected_current_version_id: int | None,
    idempotency_key: str,
) -> VersionCreateResult
~~~

Add tests that reject all of the following with no row inserted: non-string or blank JD, UTF-8 bytes over 60,000, non-string or invalid URL, relative URL, javascript:, data:, file:, missing host, and idempotency keys not matching ^[A-Za-z0-9_-]{16,128}$.

Use explicit Python assertions proving bool, string, 0, and negative values are rejected for expected_current_version_id, while a strict positive int and None are accepted:

~~~python
valid = {
    'application_id': app_id,
    'jd_text': '后端工程师\\n负责 API 设计',
    'source_url': None,
    'source_kind': 'ui',
    'idempotency_key': 'jd-key-00000001',
}
with pytest.raises(JDVersionValidationError):
    service.create_version(**valid, expected_current_version_id=True)
with pytest.raises(JDVersionValidationError):
    service.create_version(**valid, expected_current_version_id='1')
with pytest.raises(JDVersionValidationError):
    service.create_version(**valid, expected_current_version_id=0)
~~~

Add a fingerprint table test for raw CJK/emoji/newline/leading-space bytes, None/empty/whitespace URL normalization, and source_kind differences. Assert the stored content_sha256 hashes the exact original UTF-8 bytes and request_fingerprint_sha256 follows the approved Base64-plus-canonical-JSON algorithm.

- [ ] **Step 2: Add failing CAS and idempotency tests.**

Cover these exact outcomes:

1. First save with expected_current_version_id=None returns version 1.
2. Same key and identical normalized input returns the original row with no new version.
3. Same key and different JD/source/entry fingerprint returns idempotency conflict semantics without mutating the original row.
4. Two connections both expecting v1 produce exactly one v2 and one application_jd_stale_current_version; no v3 is created.
5. A successful key replay still returns its original row even after another key creates a newer current version.

- [ ] **Step 3: Implement the minimum service and repository.**

Implement strict validators, URL normalization, the 240-code-point preview helper, and the fingerprint helper in the new repository module. The transaction must execute in this order:

~~~text
BEGIN IMMEDIATE
  load application and reject invisible/deleted application
  load (application_id, idempotency_key)
  if found: compare request_fingerprint_sha256 and replay or raise idempotency conflict
  load current version
  compare expected_current_version_id using strict integer/null semantics
  allocate max(version_number) + 1
  insert immutable row
COMMIT
~~~

source_kind is a trusted service argument only; it is never parsed from the public JSON body. The repository returns summaries without jd_text and returns full text only from get_version/get_current detail data.

- [ ] **Step 4: Run repository tests.**

~~~powershell
uv run pytest tests/test_application_jd_versions_repository.py -q
~~~

Expected result: all validation, fingerprint, CAS, replay, ordering, and preview tests pass.

- [ ] **Step 5: Commit the repository slice.**

~~~powershell
git add src/offerpilot/repositories/application_jd_versions.py tests/test_application_jd_versions_repository.py
git commit -m "feat: AI enforce application JD version CAS"
~~~

## 3. JD version API and ApplicationDetail data contract

**Files:**
- Create: tests/test_application_jd_versions_api.py
- Modify: src/offerpilot/api.py
- Modify: web/src/types/applicationJdVersion.ts
- Create: web/src/services/applicationJdVersions.ts
- Create: web/src/services/applicationJdVersions.test.ts

- [ ] **Step 1: Add failing API tests for route shape and status semantics.**

Cover:

~~~text
GET  /api/applications/{id}/job-description
GET  /api/applications/{id}/job-description/versions?offset=0&limit=50
GET  /api/applications/{id}/job-description/versions/{version_id}
POST /api/applications/{id}/job-description/versions
~~~

Assert current-empty returns 200 with {"current": null}, current/detail return full text, history returns metadata plus preview but never jd_text, and detail rejects another Application's version with 404.

Assert request bodies containing source_kind are rejected rather than trusted. UI requests always persist source_kind='ui'; the response includes it. Assert 201, idempotent 200, stable 404, 409 application_jd_idempotency_conflict, 409 application_jd_stale_current_version, and 422 validation errors. There must be no 202 response for this synchronous save.

Send expected_current_version_id as true, '1', 0, and -1 through TestClient and assert each returns 422 without an inserted version; send null and a positive JSON integer through the same route and assert they reach the repository.

- [ ] **Step 2: Implement API serializers, route order, and UI service types.**

Define discriminated TypeScript shapes:

~~~typescript
export type ApplicationJdVersionSummary = {
  id: number;
  application_id: number;
  version_number: number;
  content_sha256: string;
  source_url: string | null;
  source_kind: 'ui' | 'pilot';
  utf8_byte_length: number;
  preview: string;
  created_at: string;
};

export type ApplicationJdVersion = ApplicationJdVersionSummary & { jd_text: string };
~~~

The public UI POST body contains jd_text, source_url, expected_current_version_id, and idempotency_key, but not source_kind. Register static job-description routes before any dynamic application child route that could consume versions as an ID. Map errors to fixed Chinese copy and preserve the original key/input on network, timeout, response-loss, and bare-5xx unknown outcomes.

- [ ] **Step 3: Run API tests and type/service tests.**

~~~powershell
uv run pytest tests/test_application_jd_versions_api.py -q
cd web
npm.cmd test -- --run src/services/applicationJdVersions.test.ts
cd ..
~~~

Expected result: API and client contract tests pass; no existing endpoint response changes outside the new JD routes.

- [ ] **Step 4: Commit the API contract slice.**

~~~powershell
git add src/offerpilot/api.py tests/test_application_jd_versions_api.py web/src/types/applicationJdVersion.ts web/src/services/applicationJdVersions.ts web/src/services/applicationJdVersions.test.ts
git commit -m "feat: AI expose application JD version API"
~~~

## 4. Application-bound domain handoff and legacy write closure

**Files:**
- Modify: src/offerpilot/api.py
- Modify: src/offerpilot/repositories/opportunity_fit_reviews.py
- Modify: src/offerpilot/repositories/material_kits.py
- Modify: src/offerpilot/repositories/material_revision_proposals.py
- Modify: src/offerpilot/repositories/interview_preparation_proposals.py
- Modify: src/offerpilot/repositories/mock_interviews.py
- Modify: src/offerpilot/repositories/jd.py
- Modify: tests/test_jd_resume_ai_api.py
- Modify: tests/test_material_kits_api.py
- Modify: tests/test_material_revision_proposals_api.py
- Modify: tests/test_opportunity_fit_reviews_api.py
- Modify: tests/test_interview_preparation_api.py
- Modify: tests/test_mock_interview_api.py

- [ ] **Step 1: Add failing integration tests for the version matrix.**

Create v1 and v2 JD records for one Application and verify:

- Triage accepts only current v2, persists its jd_version_id and snapshot, and Deep Review accepts only the confirmed Triage parent, inheriting the same version.
- Triage POST without schema_version=2, with schema_version=1, or with another version returns 410 opportunity_fit_v1_write_disabled, makes zero Provider calls, and creates zero records.
- Material Kit freezes the current version; Material Proposal ignores client version input and inherits Kit; stale Kit generation returns the existing source conflict without Provider work.
- Interview Preparation accepts current version only and persists the version in its explicit column and input snapshot.
- Mock Interview claim stores the current version atomically; preparing from a proposal with a different version returns 409; after claim, changing the current JD does not invalidate the Attempt, and its next question/feedback still use the frozen JD.

Use two SQLite connections and a Provider barrier for the Mock case. The assertion must distinguish current JD changed from Attempt source changed: the Attempt remains usable and history reports source_changed.

- [ ] **Step 2: Add failing legacy endpoint tests.**

Assert:

~~~text
POST /api/jd/analyze without application_id + jd_text -> existing standalone behavior
POST /api/resumes/{id}/match without application_id + jd_text -> existing standalone behavior
same endpoints with application_id + jd_text -> 422 application_jd_version_required
same endpoints with application_id + current jd_version_id -> use version text
Application-bound material/fit/preparation/mock old jd_text -> 422, zero Provider calls
~~~

For Opportunity Fit, any new POST not carrying exact schema_version=2 returns 410 opportunity_fit_v1_write_disabled, including a body that carries jd_version_id; the v1 GET list/detail schema remains read-only.

- [ ] **Step 3: Implement one shared handoff helper and each domain adapter.**

The helper must provide these operations without exposing internal IDs to Provider payloads:

~~~python
current = jd_versions.require_current(application_id)
frozen = jd_versions.freeze(current)
assert frozen.jd_version_id == current.id
~~~

Each adapter writes the explicit jd_version_id and its existing snapshot in one transaction. Deep Review takes the parent Triage row only; Material Proposal takes the Kit only; Mock Interview takes the Attempt snapshot after claim. Remove application-bound use of free jd_text while preserving standalone JD analysis and Resume Match.

- [ ] **Step 4: Run the handoff and legacy suites.**

~~~powershell
uv run pytest tests/test_jd_resume_ai_api.py tests/test_material_kits_api.py tests/test_material_revision_proposals_api.py tests/test_opportunity_fit_reviews_api.py tests/test_interview_preparation_api.py tests/test_mock_interview_api.py -q
~~~

Expected result: new handoff tests pass, all old v1 write tests are updated to the stable disabled error, and no Provider is called on rejected requests.

- [ ] **Step 5: Commit the domain handoff slice.**

~~~powershell
git add src/offerpilot/api.py src/offerpilot/repositories/opportunity_fit_reviews.py src/offerpilot/repositories/material_kits.py src/offerpilot/repositories/material_revision_proposals.py src/offerpilot/repositories/interview_preparation_proposals.py src/offerpilot/repositories/mock_interviews.py tests/test_jd_resume_ai_api.py tests/test_material_kits_api.py tests/test_material_revision_proposals_api.py tests/test_opportunity_fit_reviews_api.py tests/test_interview_preparation_api.py tests/test_mock_interview_api.py
git commit -m "feat: AI hand off current JD to application workflows"
~~~

## 5. ApplicationDetail UI, history, CAS recovery, and zero-write behavior

**Files:**
- Modify: web/src/components/ApplicationDetail.tsx
- Modify: web/src/components/ApplicationDetail.module.css
- Create: web/src/components/ApplicationDetail.jdVersions.test.tsx
- Create: web/src/components/ApplicationDetail.jdVersions.integration.test.tsx

- [ ] **Step 1: Add failing mounted tests.**

Mount the real ApplicationDetail with the existing router/query providers and mock only the HTTP boundary. Cover these states:

- no current version: neutral empty state and “添加 JD”;
- current v1: read-only text, version/source metadata, update/history buttons;
- history list: metadata/240-code-point preview only, opening one version fetches full text, historical content stays unchanged after v2;
- stale CAS: v1 editor opened in two mounted instances, first save succeeds, second shows Chinese “岗位资料已更新，请重新加载后再保存” and keeps its text/key;
- unknown response: editor stays frozen with original key and input; no second key is generated;
- source URL is plain text/copy-only and no window.open, navigation, AI, Provider, or mutation service is called.

Use actual button clicks and request spies; do not satisfy these tests with JSX/source string scanning.

- [ ] **Step 2: Implement the controlled JD module.**

Store the editor draft as { jdText, sourceUrl, expectedCurrentVersionId, idempotencyKey, resultUnknown }. Generate one ASCII key matching ^[A-Za-z0-9_-]{16,128}$ when a save attempt begins; preserve it across remount/retry; clear it only after 201, idempotent 200, or a confirmed deterministic failure that did not create a version. Disable all downstream Application-bound generation controls when no current JD exists.

Render source_url as non-link text with copy action, render list preview using the shared 240-code-point helper, and never claim a version is current unless the API response contains that version.

- [ ] **Step 3: Run mounted UI tests.**

~~~powershell
cd web
npm.cmd test -- --run src/components/ApplicationDetail.jdVersions.test.tsx src/components/ApplicationDetail.jdVersions.integration.test.tsx
cd ..
~~~

Expected result: mounted tests pass, write-service spies remain at zero for read/navigation-only actions, and stale/unknown recovery preserves the original draft.

- [ ] **Step 4: Commit the ApplicationDetail slice.**

~~~powershell
git add web/src/components/ApplicationDetail.tsx web/src/components/ApplicationDetail.module.css web/src/components/ApplicationDetail.jdVersions.test.tsx web/src/components/ApplicationDetail.jdVersions.integration.test.tsx
git commit -m "feat: AI add application JD history UI"
~~~

## 6. Pilot confirmation and shared write path

**Files:**
- Modify: src/offerpilot/ai/tools.py
- Modify: src/offerpilot/ai/agent.py
- Modify: src/offerpilot/api.py
- Modify: web/src/components/ChatPanel/PilotTaskCard.tsx
- Modify: web/src/components/ChatPanel/MessageBubble.tsx
- Modify: web/src/components/ChatPanel/model.ts
- Create: web/src/features/pilot/applicationJdVersion.ts
- Create: web/src/features/pilot/applicationJdVersion.test.ts
- Create: web/src/components/ChatPanel/PilotApplicationJdCard.test.tsx
- Modify: tests/test_api_contract.py

- [ ] **Step 1: Add failing Pilot contract tests.**

Assert that ordinary Pilot messages do not create a JD pending card, Chat message, Provider call, or JD row. Only explicit intents such as “给这个投递补充 JD” or “查看 JD 历史” may enter the flow. When context_type=application does not identify one Application, the Pilot asks the user to choose and does not guess or enumerate-and-write.

The confirmation payload must contain only application_id, raw JD input, normalized source URL, frozen expected_current_version_id, and the original idempotency key. The client cannot send source_kind; the server-side Pilot handler passes source_kind='pilot' to the shared service. Confirmation after a new version appears returns application_jd_stale_current_version and does not write a new version.

- [ ] **Step 2: Implement Pilot using the existing pending-confirmation mechanism.**

The flow is exactly:

~~~text
explicit JD intent -> choose one Application when context is ambiguous -> collect JD/URL
-> pending confirmation card -> user confirms -> shared ApplicationJDService(source_kind='pilot')
-> read-only success/history card
~~~

Do not add a Chat jd_version_id field or a second persistence state machine. Do not trigger Fit, Material, Interview, Knowledge, Offer, Reminder, Application status, or Provider writes after a successful JD save.

- [ ] **Step 3: Run Pilot and API contract tests.**

~~~powershell
uv run pytest tests/test_api_contract.py -q
cd web
npm.cmd test -- --run src/features/pilot/applicationJdVersion.test.ts src/components/ChatPanel/PilotApplicationJdCard.test.tsx
cd ..
~~~

Expected result: UI and Pilot use the same save service contract, only explicit confirmation writes a JD version, and the server owns source_kind.

- [ ] **Step 4: Commit the Pilot slice.**

~~~powershell
git add src/offerpilot/ai/tools.py src/offerpilot/ai/agent.py src/offerpilot/api.py web/src/components/ChatPanel/PilotTaskCard.tsx web/src/components/ChatPanel/MessageBubble.tsx web/src/components/ChatPanel/model.ts web/src/features/pilot/applicationJdVersion.ts web/src/features/pilot/applicationJdVersion.test.ts web/src/components/ChatPanel/PilotApplicationJdCard.test.tsx tests/test_api_contract.py
git commit -m "feat: AI add Pilot JD confirmation"
~~~

## 7. Isolated smoke and browser evidence

**Files:**
- Create: scripts/application-jd-real-ai-browser-harness.ps1
- Modify: scripts/browser-network-audit.py to record the existing CDP request method, target/session identity, URL, status, and stable response code needed by this harness; do not add domain logic.
- Modify: src/offerpilot/smoke.py only for the isolated JD smoke flow and cleanup assertions.
- Create: tests/test_application_jd_browser_harness.py
- Create: tests/test_application_jd_smoke.py

- [ ] **Step 1: Add fake-audit tests before harness implementation.**

The harness must fail unless it observes, for one synthetic Application, these exact requests and response facts:

~~~text
UI: POST JD v1 -> GET current -> GET history/detail
UI: create Application-bound flow using v1
UI: POST JD v2 with expected_current_version_id=v1
Pilot: explicit JD intent -> confirmation -> POST v3 with source_kind=pilot in response
Pilot: history reads v3 and no downstream write occurs automatically
~~~

The audit must allow only local page/API URLs in the browser and configured Provider endpoints on server egress; it must reject any request to source_url, recruiting domains, or an unapproved target. Database snapshots must include JD versions, jd_analyses, Resume Match, Material, Fit, Interview, Mock, Knowledge, Offer, Reminder, Chat, and Application status tables. The JD-only path may change only its expected JD version/Application rows; all unrelated counts and hashes must remain unchanged.

- [ ] **Step 2: Implement isolated API smoke and cleanup.**

Run local and real-AI smoke in a temporary data directory. Copy the existing config.json silently; never print or persist the secret in logs/reports. Use Chinese synthetic values and a non-routable example URL. Assert the URL produces zero network events. On every failure, clean the synthetic Application and JD rows in dependency order and verify no background process remains.

- [ ] **Step 3: Implement the browser harness.**

Use the established browser-level CDP target binding and network audit. The harness must not treat API smoke as browser proof, must bind the same target used for all UI/Pilot actions, and must report only stage, HTTP status, stable error code, and hashed Provider request ID. It must not log JD text, resume content, configuration, secret, or model output.

- [ ] **Step 4: Run isolated tests and smoke.**

~~~powershell
uv run pytest tests/test_application_jd_smoke.py tests/test_application_jd_browser_harness.py -q
uv run oc smoke --static-dir web/dist
uv run oc verify --profile local --static-dir web/dist
~~~

Expected result: local smoke passes with zero external URL access and zero cross-domain writes. Real AI is run only after the deterministic suite passes:

~~~powershell
uv run oc verify --profile real-ai --static-dir web/dist
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1
~~~

A Provider failure is reported as a failure category; it is never converted into a pass by weakening the JD contract.

- [ ] **Step 5: Commit the isolated verification slice.**

~~~powershell
git add scripts/application-jd-real-ai-browser-harness.ps1 scripts/browser-network-audit.py src/offerpilot/smoke.py tests/test_application_jd_browser_harness.py tests/test_application_jd_smoke.py
git commit -m "test: AI verify application JD isolation"
~~~

## 8. Full gate, independent review, and release report

**Files:**
- Create/modify: docs/reports/2026-08-05-application-jd-versions-release-verification.md
- No further product changes after this task unless a gate finds a reproducible defect.

- [ ] **Step 1: Run the affected backend suites.**

~~~powershell
uv run pytest tests/test_application_jd_versions_migrations.py tests/test_application_jd_versions_repository.py tests/test_application_jd_versions_api.py tests/test_jd_resume_ai_api.py tests/test_material_kits_api.py tests/test_material_revision_proposals_api.py tests/test_opportunity_fit_reviews_api.py tests/test_interview_preparation_api.py tests/test_mock_interview_api.py -q
uv run ruff check .
uv run mypy src
~~~

Expected result: exit code 0 with no new warnings that hide failures.

- [ ] **Step 2: Run the complete backend grouped gate.**

Run the existing Windows five-group gate from the repository root. The aggregate must use the current complete manifest and reject duplicate node IDs, missing tests, stale markers, non-zero group exits, and anything beyond the four approved Windows symlink permission skips. Record collection counts, group counts, exit codes, skip node IDs/reasons, and aggregate result.

~~~powershell
.\scripts\windows-pytest-groups.ps1
~~~

- [ ] **Step 3: Run the complete frontend gate and build.**

~~~powershell
cd web
npm.cmd test -- --run
npm.cmd run build
cd ..
~~~

Run scripts/windows-vitest-groups.ps1 as the grouped frontend gate and verify its manifest/source fingerprint against the current web/src, configuration, lockfile, and gate script before aggregating.

- [ ] **Step 4: Run final local and real-AI verification.**

~~~powershell
uv run oc smoke --static-dir web/dist
uv run oc verify --profile local --static-dir web/dist
uv run oc verify --profile real-ai --static-dir web/dist
~~~

Do not claim real-AI success for a timeout, 4xx/5xx, contract failure, or missing audit evidence. All temporary data, Provider proxy, service processes, CDP targets, and copied configuration must be removed in finally blocks; source data must match its pre-run snapshot byte-for-byte.

- [ ] **Step 5: Perform independent code review and release-report commit.**

Review the final diff against the recorded baseline and verify the implementation allowlist:

~~~powershell
$baselineFile = Join-Path $env:TEMP 'offerpilot-application-jd-versions-baseline.txt'
$implementationBase = (Get-Content -LiteralPath $baselineFile -Raw).Trim()
git diff --name-only "$implementationBase..HEAD"
git diff --check "$implementationBase..HEAD"
git status --short
~~~

Update the report only after all gates and browser evidence finish. The report must include commands, exit codes, test counts, migration result, CAS/idempotency evidence, browser request sequence, zero-network/zero-cross-domain-write result, cleanup result, and remaining Provider risk. It must not include secrets, JD/resume text, model output, or raw request IDs. Because docs/* is ignored, stage it explicitly:

~~~powershell
git add -f docs/reports/2026-08-05-application-jd-versions-release-verification.md
git commit -m "docs: AI record application JD release verification"
~~~

Only after the report commit, a final clean status, successful git diff --check, and completed independent review may the baseline file be deleted:

~~~powershell
if (@(git status --short).Count -ne 0) { throw 'Final worktree is dirty' }
if ($LASTEXITCODE -ne 0) { throw 'Final diff check failed' }
Remove-Item -LiteralPath (Join-Path $env:TEMP 'offerpilot-application-jd-versions-baseline.txt') -Force
~~~

No push or merge is part of this plan.

## Self-review checklist

- [ ] Migration task covers 0018_application_jd_versions, all explicit jd_version_id columns, ordinary-integer deletion semantics, and real prior-DDL upgrade.
- [ ] Repository/API tasks cover ^[A-Za-z0-9_-]{16,128}$, strict positive integer/null CAS input, replay-before-CAS ordering, normalized fingerprint, URL validation, 240-code-point preview, and no 202 save state.
- [ ] Domain task covers Triage/Deep inheritance, Material Kit/Proposal inheritance, Interview Preparation, Mock claim freezing, v1 write closure, and standalone jd_text compatibility.
- [ ] UI/Pilot tasks cover confirmed writes only, server-owned source_kind, stale/unknown recovery, no link navigation, and no cross-domain writes.
- [ ] Browser/gate tasks cover isolated config, zero URL egress, complete request sequence, cleanup, grouped backend/frontend gates, independent review, and report commit.
- [ ] No unresolved placeholder or unspecified implementation step remains in this plan.
