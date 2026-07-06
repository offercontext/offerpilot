# AI Assistant Explainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build evidence-level explainability into the existing OfferPilot AI assistant workbench while preserving the current chat, confirmation, and three-pane layout.

**Architecture:** Normalize tool calls and tool results into `ToolStep` plus `EvidenceItem` objects in `web/src/components/ChatPanel/model.ts`, then render the normalized data in `ProcessTimeline`, `ProposalCard`, and `ContextPanel`. Keep the backend API mostly stable, with one additive `args` field on pending write actions so the confirmation UI can show target and proposed values reliably.

**Tech Stack:** Python 3.11 + FastAPI + pytest for the API contract, React 18 + TypeScript + Ant Design + Vite + Vitest for the frontend.

---

## File Structure

- Modify `src/offerpilot/api.py`: include write-action args in `pending_action` API responses.
- Modify `tests/test_chat_api.py`: verify pending actions expose args for both first-turn and chained confirmations.
- Modify `web/src/types/chat.ts`: add optional `args` to `PendingAction`.
- Modify `web/src/components/ChatPanel/model.ts`: add `EvidenceItem`, parse tool result messages, attach evidence to steps, and export aggregation helpers.
- Create `web/src/components/ChatPanel/model.test.ts`: unit tests for tool result evidence, malformed fallback, unknown tools, and evidence aggregation.
- Create `web/src/components/ChatPanel/EvidenceList.tsx`: shared compact evidence row renderer.
- Modify `web/src/components/ChatPanel/ProcessTimeline.tsx`: show step detail, evidence count, expandable evidence list, and fallback copy.
- Modify `web/src/components/ChatPanel/ProposalCard.tsx`: render action target/proposed values from args, show available evidence, and warn on thin evidence.
- Modify `web/src/components/ChatPanel/ContextPanel.tsx`: add current-thread evidence summary above capability shortcuts.
- Modify `web/src/components/ChatPanel/index.tsx`: derive and pass visible-thread evidence to `ContextPanel` and `ProposalCard`.
- Modify `web/src/components/ChatPanel/ChatPanel.module.css`: add dense, accessible evidence and confirmation styles with reduced-motion support.

---

### Task 1: Add Pending Action Args To The API

**Files:**
- Modify: `src/offerpilot/api.py`
- Modify: `tests/test_chat_api.py`
- Modify: `web/src/types/chat.ts`

- [ ] **Step 1: Write the failing API tests**

Add this assertion to `test_chat_write_tool_requires_confirmation_before_mutating` after the existing `tool_name` assertion:

```python
    assert response.json()["pending_action"]["args"] == {
        "id": application["id"],
        "status": "offer",
    }
```

Add this new test after `test_chat_confirm_executes_pending_write`:

```python
def test_chat_confirm_returns_args_for_chained_pending_write(tmp_path):
    app_client = TestClient(create_app(data_dir=tmp_path))
    first = app_client.post(
        "/api/applications",
        json={"company_name": "ByteDance", "position_name": "Backend", "status": "interview"},
    ).json()
    second = app_client.post(
        "/api/applications",
        json={"company_name": "OpenAI", "position_name": "Product", "status": "applied"},
    ).json()
    model = ScriptedModel(
        [
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="update_application_status",
                        args=json.dumps({"id": first["id"], "status": "offer"}),
                    )
                ]
            ),
            Assistant(
                tool_calls=[
                    ToolCall(
                        id="w2",
                        name="update_application_status",
                        args=json.dumps({"id": second["id"], "status": "interview"}),
                    )
                ]
            ),
        ]
    )
    client = TestClient(create_app(data_dir=tmp_path, chat_model=model))
    pending = client.post("/api/chat", json={"message": "update two", "conversation_id": 0}).json()

    response = client.post(
        "/api/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "confirmation_required"
    assert response.json()["pending_action"]["tool_name"] == "update_application_status"
    assert response.json()["pending_action"]["args"] == {
        "id": second["id"],
        "status": "interview",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_chat_api.py -q
```

Expected: the first edited test and the new chained pending test fail with missing `args` in `pending_action`.

- [ ] **Step 3: Add a helper in `src/offerpilot/api.py`**

Add this helper near `_dump_tool_calls`:

```python
def _pending_action_json(pending: PendingAction) -> dict[str, Any]:
    try:
        args = json.loads(pending.args) if pending.args else {}
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return {
        "tool_name": pending.tool_name,
        "human": pending.human,
        "args": args,
    }
```

Replace both inline pending payloads:

```python
"pending_action": {"tool_name": pending.tool_name, "human": pending.human},
```

and

```python
"pending_action": {
    "tool_name": new_pending.tool_name,
    "human": new_pending.human,
},
```

with:

```python
"pending_action": _pending_action_json(pending),
```

and:

```python
"pending_action": _pending_action_json(new_pending),
```

- [ ] **Step 4: Update the frontend pending action type**

Change `web/src/types/chat.ts`:

```ts
export interface PendingAction {
  tool_name: string;
  human: string;
  args?: Record<string, unknown>;
}
```

- [ ] **Step 5: Run the focused API tests**

Run:

```bash
uv run pytest tests/test_chat_api.py -q
```

Expected: all chat API tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/offerpilot/api.py tests/test_chat_api.py web/src/types/chat.ts
git commit -m "feat: AI expose pending action args"
```

---

### Task 2: Normalize Tool Evidence In Chat Model

**Files:**
- Modify: `web/src/components/ChatPanel/model.ts`
- Create: `web/src/components/ChatPanel/model.test.ts`

- [ ] **Step 1: Write failing model tests**

Create `web/src/components/ChatPanel/model.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import { buildTurns, collectEvidence } from './model';

function msg(patch: Partial<ChatMessage> & Pick<ChatMessage, 'role'>): ChatMessage {
  return {
    id: patch.id ?? 1,
    conversation_id: patch.conversation_id ?? 1,
    role: patch.role,
    content: patch.content ?? '',
    tool_calls: patch.tool_calls,
    tool_call_id: patch.tool_call_id,
    created_at: patch.created_at ?? '2026-07-06T12:00:00+08:00',
  };
}

describe('buildTurns evidence normalization', () => {
  it('attaches application evidence from tool results to the assistant turn', () => {
    const turns = buildTurns([
      msg({ role: 'user', content: 'show apps' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([
          {
            id: 7,
            company_name: 'ByteDance',
            position_name: 'Backend Engineer',
            status: 'interview',
            source: 'manual',
            applied_at: '2026-07-01',
          },
        ]),
      }),
      msg({ role: 'assistant', content: 'You have one active interview.' }),
    ]);

    expect(turns[1].steps?.[0]).toMatchObject({
      name: 'list_applications',
      detail: 'ByteDance',
      evidence: [
        {
          id: 'application-7',
          kind: 'application',
          title: 'ByteDance',
          meta: 'Backend Engineer · interview · 2026-07-01',
          source: 'list_applications',
        },
      ],
    });
  });

  it('keeps malformed tool results as an unavailable detail instead of throwing', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'search_knowledge', args: { query: 'system design' } }]),
      }),
      msg({ role: 'tool', content: '{bad json' }),
      msg({ role: 'assistant', content: 'I searched.' }),
    ]);

    expect(turns[0].steps?.[0]).toMatchObject({
      name: 'search_knowledge',
      detail: 'system design',
      evidenceUnavailable: true,
    });
  });

  it('aggregates newest evidence first across visible turns', () => {
    const turns = buildTurns([
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_offers', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 3, company_name: 'OpenAI', position_name: 'PM', total_cash: 600000 }]),
      }),
      msg({ role: 'assistant', content: 'Offer found.' }),
      msg({
        role: 'assistant',
        tool_calls: JSON.stringify([{ name: 'list_applications', args: {} }]),
      }),
      msg({
        role: 'tool',
        content: JSON.stringify([{ id: 4, company_name: 'Anthropic', position_name: 'PM', status: 'applied' }]),
      }),
      msg({ role: 'assistant', content: 'Application found.' }),
    ]);

    expect(collectEvidence(turns).map((item) => item.title)).toEqual(['Anthropic', 'OpenAI']);
  });
});
```

- [ ] **Step 2: Run the model test to verify it fails**

Run:

```bash
npm.cmd test -- model.test.ts
```

Expected: TypeScript errors or test failures because `EvidenceItem`, `evidence`, `evidenceUnavailable`, and `collectEvidence` do not exist.

- [ ] **Step 3: Add evidence types to `model.ts`**

Update the interfaces near the top of `web/src/components/ChatPanel/model.ts`:

```ts
export type EvidenceKind =
  | 'application'
  | 'event'
  | 'note'
  | 'knowledge'
  | 'offer'
  | 'resume'
  | 'unknown';

export interface EvidenceItem {
  id: string;
  kind: EvidenceKind;
  title: string;
  meta?: string;
  snippet?: string;
  source: string;
}

export interface ToolStep {
  /** Backend tool name, e.g. list_offers. */
  name: string;
  /** Optional short detail extracted from the call arguments or result. */
  detail?: string;
  /** Verifiable records returned by the tool. */
  evidence?: EvidenceItem[];
  /** True when the tool returned a result that could not be parsed for evidence. */
  evidenceUnavailable?: boolean;
}
```

- [ ] **Step 4: Update stored tool-call parsing and add result parsing helpers to `model.ts`**

First update `RawToolCall` so it supports the stored API shape from `_dump_tool_calls`:

```ts
interface RawToolCall {
  function?: { name?: string; arguments?: string };
  name?: string;
  arguments?: string;
  args?: string | Record<string, unknown>;
}
```

Then update `parseToolCalls` to read either OpenAI-style arguments or stored `args`:

```ts
    const argsStr = c?.function?.arguments ?? c?.arguments ?? stringifyArgs(c?.args);
    steps.push({ name, detail: extractDetail(argsStr) });
```

Add this helper after `extractDetail`:

```ts
function stringifyArgs(args?: string | Record<string, unknown>): string | undefined {
  if (!args) return undefined;
  if (typeof args === 'string') return args;
  return JSON.stringify(args);
}
```

Then add these helpers after `stringifyArgs`:

```ts
function parseToolResult(content: string, source: string): Pick<ToolStep, 'detail' | 'evidence' | 'evidenceUnavailable'> {
  if (!content.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return { evidenceUnavailable: true };
  }
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  const evidence = rows.flatMap((row, index) => evidenceFromRecord(row, source, index));
  return {
    detail: evidence[0]?.title,
    evidence: evidence.length ? evidence : undefined,
  };
}

function evidenceFromRecord(row: unknown, source: string, index: number): EvidenceItem[] {
  if (!row || typeof row !== 'object') return [];
  const record = row as Record<string, unknown>;
  const id = String(record.id ?? `${source}-${index}`);
  const company = text(record.company_name);
  const position = text(record.position_name);
  if (company) {
    if ('total_cash' in record || 'deadline' in record) {
      const amount = typeof record.total_cash === 'number' ? `${Math.round(record.total_cash / 10000)}w` : '';
      return [
        {
          id: `offer-${id}`,
          kind: 'offer',
          title: company,
          meta: compact([position, amount, text(record.deadline), text(record.status)]).join(' · '),
          snippet: text(record.assessment) || text(record.notes),
          source,
        },
      ];
    }
    return [
      {
        id: `application-${id}`,
        kind: 'application',
        title: company,
        meta: compact([position, text(record.status), text(record.applied_at)]).join(' · '),
        snippet: text(record.notes),
        source,
      },
    ];
  }
  const title = text(record.title) || text(record.round) || text(record.name);
  if (title) {
    return [
      {
        id: `${source}-${id}`,
        kind: source.includes('knowledge') ? 'knowledge' : source.includes('event') ? 'event' : 'note',
        title,
        meta: compact([text(record.event_type), text(record.scheduled_at), text(record.date)]).join(' · '),
        snippet: text(record.content) || text(record.summary) || text(record.weak_points),
        source,
      },
    ];
  }
  return [];
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function compact(values: Array<string | undefined>): string[] {
  return values.filter((value): value is string => Boolean(value));
}
```

- [ ] **Step 5: Attach tool results inside `buildTurns`**

Change the loop in `buildTurns` so `tool` messages enrich the latest pending step:

```ts
    } else if (m.role === 'tool') {
      const last = pending[pending.length - 1];
      if (last) {
        const parsed = parseToolResult(m.content, last.name);
        pending[pending.length - 1] = {
          ...last,
          detail: parsed.detail ?? last.detail,
          evidence: parsed.evidence,
          evidenceUnavailable: parsed.evidenceUnavailable,
        };
      }
    }
```

Keep the existing assistant handling after this branch.

- [ ] **Step 6: Export the evidence aggregator**

Add this function before the final export:

```ts
export function collectEvidence(turns: UITurn[], limit = 8): EvidenceItem[] {
  const seen = new Set<string>();
  const out: EvidenceItem[] = [];
  for (const turn of [...turns].reverse()) {
    for (const step of [...(turn.steps ?? [])].reverse()) {
      for (const item of [...(step.evidence ?? [])].reverse()) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        out.push(item);
        if (out.length >= limit) return out;
      }
    }
  }
  return out;
}
```

- [ ] **Step 7: Run focused frontend tests**

Run:

```bash
npm.cmd test -- model.test.ts
```

Expected: the new model tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add web/src/components/ChatPanel/model.ts web/src/components/ChatPanel/model.test.ts
git commit -m "feat: AI normalize chat evidence"
```

---

### Task 3: Render Evidence In The Process Timeline

**Files:**
- Create: `web/src/components/ChatPanel/EvidenceList.tsx`
- Modify: `web/src/components/ChatPanel/ProcessTimeline.tsx`
- Modify: `web/src/components/ChatPanel/ChatPanel.module.css`

- [ ] **Step 1: Create the shared evidence renderer**

Create `web/src/components/ChatPanel/EvidenceList.tsx`:

```tsx
import { BookOutlined, CalendarOutlined, DollarOutlined, FileTextOutlined, ProfileOutlined } from '@ant-design/icons';
import { createElement } from 'react';
import type { EvidenceItem } from './model';
import styles from './ChatPanel.module.css';

interface Props {
  items: EvidenceItem[];
  compact?: boolean;
}

const ICONS = {
  application: ProfileOutlined,
  event: CalendarOutlined,
  note: FileTextOutlined,
  knowledge: BookOutlined,
  offer: DollarOutlined,
  resume: FileTextOutlined,
  unknown: FileTextOutlined,
} satisfies Record<EvidenceItem['kind'], typeof FileTextOutlined>;

export default function EvidenceList({ items, compact }: Props) {
  if (!items.length) return null;
  return (
    <ul className={`${styles.evidenceList} ${compact ? styles.evidenceListCompact : ''}`}>
      {items.map((item) => {
        const icon = ICONS[item.kind] ?? ICONS.unknown;
        return (
          <li key={`${item.source}-${item.id}`} className={styles.evidenceItem}>
            <span className={styles.evidenceIcon} aria-hidden="true">
              {createElement(icon)}
            </span>
            <span className={styles.evidenceMain}>
              <span className={styles.evidenceTitle}>{item.title}</span>
              {item.meta ? <span className={styles.evidenceMeta}>{item.meta}</span> : null}
              {item.snippet ? <span className={styles.evidenceSnippet}>{item.snippet}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 2: Update `ProcessTimeline.tsx` to render evidence**

Import the renderer:

```tsx
import EvidenceList from './EvidenceList';
```

Replace the `<li>` body inside `steps.map` with:

```tsx
                <li key={i} className={`${styles.step} ${meta.kind === 'write' ? styles.stepWrite : styles.stepRead}`}>
                  <div className={styles.stepLine}>
                    <span className={styles.stepIcon} aria-hidden="true">
                      {createElement(meta.icon)}
                    </span>
                    <span className={styles.stepText}>
                      <b>{meta.label}</b>
                      {s.detail ? <span className={styles.stepDetail}> · {s.detail}</span> : null}
                    </span>
                    {s.evidence?.length ? <span className={styles.stepCount}>{s.evidence.length} sources</span> : null}
                  </div>
                  {s.evidence?.length ? <EvidenceList items={s.evidence} compact /> : null}
                  {s.evidenceUnavailable ? <div className={styles.stepFallback}>Details unavailable for this step.</div> : null}
                </li>
```

- [ ] **Step 3: Add timeline and evidence styles**

Append these rules to `web/src/components/ChatPanel/ChatPanel.module.css` near the timeline section:

```css
.step {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}

.stepLine {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 28px;
}

.stepText {
  min-width: 0;
  flex: 1;
}

.stepDetail {
  color: var(--op-muted);
}

.stepCount {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--op-muted);
  font-variant-numeric: tabular-nums;
}

.stepFallback {
  margin-left: 30px;
  font-size: 12px;
  color: var(--op-muted);
}

.evidenceList {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.evidenceListCompact {
  margin-left: 30px;
}

.evidenceItem {
  display: flex;
  gap: 9px;
  padding: 9px 10px;
  border-radius: 9px;
  background: var(--chat-tint-soft);
}

.evidenceIcon {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  background: var(--op-surface);
  color: var(--op-primary);
  font-size: 11px;
}

.evidenceMain {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.evidenceTitle {
  color: var(--op-ink);
  font-weight: 600;
  font-size: 12.5px;
}

.evidenceMeta,
.evidenceSnippet {
  color: var(--op-muted);
  font-size: 12px;
  line-height: 1.45;
  text-wrap: pretty;
}
```

- [ ] **Step 4: Build to verify component wiring**

Run:

```bash
npm.cmd run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add web/src/components/ChatPanel/EvidenceList.tsx web/src/components/ChatPanel/ProcessTimeline.tsx web/src/components/ChatPanel/ChatPanel.module.css
git commit -m "feat: AI show evidence in timeline"
```

---

### Task 4: Upgrade The Write Confirmation Card

**Files:**
- Modify: `web/src/components/ChatPanel/ProposalCard.tsx`
- Modify: `web/src/components/ChatPanel/index.tsx`
- Modify: `web/src/components/ChatPanel/ChatPanel.module.css`

- [ ] **Step 1: Update `ProposalCard` props and imports**

Change imports:

```tsx
import { Alert, Button } from 'antd';
import type { EvidenceItem } from './model';
import EvidenceList from './EvidenceList';
```

Change props:

```tsx
interface Props {
  action: PendingAction;
  loading: boolean;
  evidence: EvidenceItem[];
  onConfirm: () => void;
  onCancel: () => void;
}
```

- [ ] **Step 2: Add action summary helpers in `ProposalCard.tsx`**

Add these helpers below `parseDiff`:

```tsx
function actionTarget(action: PendingAction): string | null {
  const id = action.args?.id;
  if (typeof id === 'number' || typeof id === 'string') return `Record #${id}`;
  const company = action.args?.company_name;
  const role = action.args?.position_name;
  if (typeof company === 'string' && typeof role === 'string') return `${company} · ${role}`;
  if (typeof company === 'string') return company;
  return null;
}

function proposedValue(action: PendingAction): string | null {
  const status = action.args?.status;
  if (typeof status === 'string' && status.trim()) return `Status -> ${status}`;
  const title = action.args?.title;
  if (typeof title === 'string' && title.trim()) return `Title -> ${title}`;
  return null;
}
```

- [ ] **Step 3: Render target, proposed value, evidence, and warning**

Inside `ProposalCard`, add:

```tsx
  const target = actionTarget(action);
  const proposed = proposedValue(action);
  const thinEvidence = evidence.length === 0;
```

In the body after the existing diff or description block, add:

```tsx
        <div className={styles.prFacts}>
          {target ? (
            <div>
              <span>Target</span>
              <b>{target}</b>
            </div>
          ) : null}
          {proposed ? (
            <div>
              <span>Proposed</span>
              <b>{proposed}</b>
            </div>
          ) : null}
        </div>
        {thinEvidence ? (
          <Alert
            className={styles.prAlert}
            type="warning"
            showIcon
            message="Evidence is limited. Review this change carefully before confirming."
          />
        ) : (
          <div className={styles.prEvidence}>
            <div className={styles.panelLabel}>Evidence used</div>
            <EvidenceList items={evidence.slice(0, 3)} compact />
          </div>
        )}
```

- [ ] **Step 4: Pass evidence from `index.tsx`**

Import:

```tsx
import { buildTurns, collectEvidence, type UITurn } from './model';
```

Add after `showEmpty`:

```tsx
  const threadEvidence = collectEvidence(turns);
```

Change the `ProposalCard` call:

```tsx
                <ProposalCard
                  action={pending}
                  loading={loading}
                  evidence={threadEvidence}
                  onConfirm={() => handleConfirm(true)}
                  onCancel={() => handleConfirm(false)}
                />
```

- [ ] **Step 5: Add confirmation card styles**

Append near the proposal card CSS:

```css
.prFacts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.prFacts div {
  min-width: 0;
  padding: 9px 10px;
  border-radius: 9px;
  background: var(--chat-tint-soft);
}

.prFacts span {
  display: block;
  color: var(--op-muted);
  font-size: 11px;
  margin-bottom: 2px;
}

.prFacts b {
  display: block;
  color: var(--op-ink);
  font-size: 12.5px;
  overflow-wrap: anywhere;
}

.prAlert {
  margin-top: 12px;
}

.prEvidence {
  margin-top: 12px;
}
```

- [ ] **Step 6: Build to verify**

Run:

```bash
npm.cmd run build
```

Expected: build passes.

- [ ] **Step 7: Commit**

Run:

```bash
git add web/src/components/ChatPanel/ProposalCard.tsx web/src/components/ChatPanel/index.tsx web/src/components/ChatPanel/ChatPanel.module.css
git commit -m "feat: AI explain write confirmations"
```

---

### Task 5: Add Current-Thread Evidence To The Context Panel

**Files:**
- Modify: `web/src/components/ChatPanel/ContextPanel.tsx`
- Modify: `web/src/components/ChatPanel/index.tsx`
- Modify: `web/src/components/ChatPanel/ChatPanel.module.css`

- [ ] **Step 1: Update `ContextPanel` props**

Add imports:

```tsx
import type { EvidenceItem } from './model';
import EvidenceList from './EvidenceList';
```

Add prop:

```ts
  evidence: EvidenceItem[];
```

Destructure it:

```tsx
  evidence,
```

- [ ] **Step 2: Render evidence summary above capabilities**

Add this block after the bound-offer section and before capabilities:

```tsx
      <div>
        <div className={styles.panelLabel}>Current evidence</div>
        {evidence.length ? (
          <EvidenceList items={evidence.slice(0, 5)} />
        ) : (
          <div className={styles.evidenceEmpty}>
            No evidence collected yet. Ask a question or choose a capability to let the assistant inspect your local data.
          </div>
        )}
      </div>
```

- [ ] **Step 3: Pass evidence from `index.tsx`**

Add the prop to `ContextPanel`:

```tsx
            evidence={threadEvidence}
```

- [ ] **Step 4: Add empty-state style**

Append near context panel CSS:

```css
.evidenceEmpty {
  color: var(--op-muted);
  font-size: 12px;
  line-height: 1.5;
  padding: 10px 11px;
  border-radius: 9px;
  background: var(--chat-tint-soft);
}
```

- [ ] **Step 5: Build to verify**

Run:

```bash
npm.cmd run build
```

Expected: build passes.

- [ ] **Step 6: Commit**

Run:

```bash
git add web/src/components/ChatPanel/ContextPanel.tsx web/src/components/ChatPanel/index.tsx web/src/components/ChatPanel/ChatPanel.module.css
git commit -m "feat: AI add evidence context panel"
```

---

### Task 6: Polish Responsive And Accessibility Details

**Files:**
- Modify: `web/src/components/ChatPanel/ProcessTimeline.tsx`
- Modify: `web/src/components/ChatPanel/EvidenceList.tsx`
- Modify: `web/src/components/ChatPanel/ChatPanel.module.css`

- [ ] **Step 1: Improve dynamic update semantics**

In `ProcessTimeline.tsx`, change the root timeline element:

```tsx
    <div className={`${styles.timeline} ${open ? styles.timelineOpen : ''}`} aria-label="AI work summary">
```

In `EvidenceList.tsx`, change the `<ul>`:

```tsx
    <ul className={`${styles.evidenceList} ${compact ? styles.evidenceListCompact : ''}`} aria-label="Evidence sources">
```

- [ ] **Step 2: Add mobile constraints and press feedback**

Append:

```css
.tlHead:active,
.capItem:active,
.noticeAction:active {
  transform: scale(0.96);
}

@media (max-width: 720px) {
  .msg {
    max-width: 100%;
  }

  .stream {
    padding: 16px 14px;
  }

  .prFacts {
    grid-template-columns: 1fr;
  }

  .evidenceListCompact {
    margin-left: 0;
  }
}
```

Ensure no rule uses `transition: all`.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
npm.cmd test -- model.test.ts
npm.cmd run build
```

Expected: model tests and build pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add web/src/components/ChatPanel/ProcessTimeline.tsx web/src/components/ChatPanel/EvidenceList.tsx web/src/components/ChatPanel/ChatPanel.module.css
git commit -m "style: AI polish evidence workbench"
```

---

### Task 7: Final Verification

**Files:**
- No planned code changes unless verification reveals a defect.

- [ ] **Step 1: Run backend tests**

Run:

```bash
uv run pytest
```

Expected: all pytest tests pass.

- [ ] **Step 2: Run frontend tests**

Run:

```bash
npm.cmd test
```

Expected: all Vitest tests pass, including `model.test.ts`.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm.cmd run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 4: Inspect final state**

Run:

```bash
git status --short
git log --oneline -8
```

Expected: clean working tree after task commits; recent commits show the implementation broken into small conventional commits with `AI` after the type.

---

## Self-Review

- Spec coverage: the plan covers step skeletons, evidence details, write-risk confirmation, context panel evidence, responsive behavior, error fallback, and verification.
- Completeness scan: no task uses unresolved markers or fill-in instructions; every code-changing step includes concrete code.
- Type consistency: `EvidenceItem`, `ToolStep.evidence`, `PendingAction.args`, `collectEvidence`, and `EvidenceList` are introduced before dependent tasks consume them.
- Scope check: the plan keeps provider behavior and chain-of-thought out of scope, matching the approved design.
