import type { ChatMessage } from '@/types/chat';
import { toolMeta } from './capabilities';

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
  /** Backend tool call id used to associate result messages. */
  toolCallId?: string;
  /** Optional short detail extracted from the call arguments or result. */
  detail?: string;
  /** Verifiable records returned by the tool. */
  evidence?: EvidenceItem[];
  /** True when the tool returned a result that could not be parsed for evidence. */
  evidenceUnavailable?: boolean;
}

export interface UITurn {
  role: 'user' | 'assistant';
  content: string;
  /** Tool steps the assistant ran before producing this answer. */
  steps?: ToolStep[];
}

interface RawToolCall {
  id?: string;
  function?: { name?: string; arguments?: string };
  name?: string;
  arguments?: string;
  args?: string | Record<string, unknown>;
}

/** Parse the stored tool_calls JSON into normalized {name, detail} steps. */
function parseToolCalls(raw?: string): ToolStep[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  const calls: RawToolCall[] = Array.isArray(parsed) ? parsed : [parsed as RawToolCall];
  const steps: ToolStep[] = [];
  for (const c of calls) {
    const name = c?.function?.name ?? c?.name;
    if (!name) continue;
    const argsStr = c?.function?.arguments ?? c?.arguments ?? stringifyArgs(c?.args);
    steps.push({ name, toolCallId: c?.id, detail: extractDetail(argsStr) });
  }
  return steps;
}

/** Best-effort short label from a JSON arguments string (status / query / id). */
function extractDetail(argsStr?: string): string | undefined {
  if (!argsStr) return undefined;
  try {
    const args = JSON.parse(argsStr) as Record<string, unknown>;
    for (const key of ['status', 'query', 'event_type', 'title', 'company_name']) {
      const v = args[key];
      if (typeof v === 'string' && v.trim()) return v.trim().slice(0, 24);
    }
    const ids = args['ids'] ?? args['offer_ids'];
    if (Array.isArray(ids)) return `${ids.length} 项`;
  } catch {
    /* ignore malformed args */
  }
  return undefined;
}

function stringifyArgs(args?: string | Record<string, unknown>): string | undefined {
  if (!args) return undefined;
  if (typeof args === 'string') return args;
  return JSON.stringify(args);
}

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
          meta: compact([position, amount, text(record.deadline), text(record.status)]).join(' \u00b7 '),
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
        meta: compact([position, text(record.status), text(record.applied_at)]).join(' \u00b7 '),
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
        meta: compact([text(record.event_type), text(record.scheduled_at), text(record.date)]).join(' \u00b7 '),
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

/**
 * Rebuild displayable turns from the full stored message list, attaching the
 * tool steps that preceded each assistant answer so ProcessTimeline can render
 * "what the AI did". Tool-result turns and empty tool-call turns are folded in.
 */
export function buildTurns(stored: ChatMessage[]): UITurn[] {
  const turns: UITurn[] = [];
  let pending: ToolStep[] = [];
  let nextFallbackToolIndex = 0;
  for (const m of stored) {
    if (m.role === 'user') {
      turns.push({ role: 'user', content: m.content });
      pending = [];
      nextFallbackToolIndex = 0;
    } else if (m.role === 'assistant') {
      const steps = parseToolCalls(m.tool_calls);
      if (steps.length) pending = pending.concat(steps);
      if (m.content.trim()) {
        turns.push({ role: 'assistant', content: m.content, steps: pending.length ? pending : undefined });
        pending = [];
        nextFallbackToolIndex = 0;
      }
    } else if (m.role === 'tool') {
      const toolIndex = resolveToolResultIndex(pending, m.tool_call_id, nextFallbackToolIndex);
      const step = pending[toolIndex];
      if (step) {
        if (!m.tool_call_id) nextFallbackToolIndex = toolIndex + 1;
        const parsed = parseToolResult(m.content, step.name);
        pending[toolIndex] = {
          ...step,
          detail: parsed.detail ?? step.detail,
          evidence: parsed.evidence,
          evidenceUnavailable: parsed.evidenceUnavailable,
        };
      }
    }
  }
  return turns;
}

function resolveToolResultIndex(pending: ToolStep[], toolCallId: string | undefined, fallbackIndex: number): number {
  if (toolCallId) {
    const match = pending.findIndex((step) => step.toolCallId === toolCallId);
    if (match >= 0) return match;
  }
  const unfilled = pending.findIndex((step, index) => index >= fallbackIndex && !hasToolResult(step));
  if (unfilled >= 0) return unfilled;
  return pending.findIndex((step) => !hasToolResult(step));
}

function hasToolResult(step: ToolStep): boolean {
  return Boolean(step.evidence?.length || step.evidenceUnavailable);
}

export function collectEvidence(turns: UITurn[], limit = 8): EvidenceItem[] {
  const seen = new Set<string>();
  const out: EvidenceItem[] = [];
  for (const turn of [...turns].reverse()) {
    for (const step of [...(turn.steps ?? [])].reverse()) {
      for (const item of step.evidence ?? []) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        out.push(item);
        if (out.length >= limit) return out;
      }
    }
  }
  return out;
}

export { toolMeta };
