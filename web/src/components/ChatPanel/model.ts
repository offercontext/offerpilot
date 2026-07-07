import type { ChatMessage, Conversation, PendingAction } from '@/types/chat';
import { toolMeta } from './capabilities';

export type EvidenceKind =
  | 'application'
  | 'event'
  | 'jd'
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
  /** Plain text returned by the tool when it is not structured evidence. */
  resultText?: string;
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

function parseToolResult(
  content: string,
  source: string,
): Pick<ToolStep, 'detail' | 'evidence' | 'resultText' | 'evidenceUnavailable'> {
  const trimmed = content.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      return { evidenceUnavailable: true };
    }
    return { resultText: trimmed.slice(0, 160) };
  }
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  if (Array.isArray(parsed) && parsed.length === 0) {
    return { resultText: '没有匹配结果' };
  }
  const evidence = rows.flatMap((row, index) => evidenceFromRecord(row, source, index));
  const resultText = evidence.length ? undefined : plainResultText(parsed);
  return {
    detail: evidence[0]?.title,
    evidence: evidence.length ? evidence : undefined,
    resultText,
    evidenceUnavailable: evidence.length || resultText ? undefined : true,
  };
}

function evidenceFromRecord(row: unknown, source: string, index: number): EvidenceItem[] {
  if (!row || typeof row !== 'object') return [];
  const record = row as Record<string, unknown>;
  const id = String(record.id ?? record.search_result_id ?? record.chunk_id ?? record.document_id ?? `${source}-${index}`);
  const recordType = text(record.record_type);
  const isResume = source.includes('resume') || recordType === 'resume';
  if (isResume) {
    const title = text(record.name) || `简历 #${id}`;
    return [
      {
        id: `${source}-${id}`,
        kind: 'resume',
        title,
        meta: text(record.parse_status),
        snippet: text(record.parsed_data),
        source,
      },
    ];
  }
  const isJD = source.includes('jd') || recordType === 'jd_analysis';
  if (isJD) {
    return [
      {
        id: `${source}-${id}`,
        kind: 'jd',
        title: `JD 分析 #${id}`,
        meta: compact([text(record.jd_source), numericMeta(record.application_id, '投递')]).join(' \u00b7 '),
        snippet: jdSummary(record.result) || text(record.jd_text),
        source,
      },
    ];
  }
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
  const title = text(record.title) || text(record.document_title) || text(record.round) || text(record.name);
  if (title) {
    const isKnowledge = source.includes('knowledge') || recordType?.startsWith('knowledge');
    return [
      {
        id: `${source}-${id}`,
        kind: isKnowledge ? 'knowledge' : source.includes('event') ? 'event' : 'note',
        title,
        meta: compact([
          text(record.knowledge_base_name),
          text(record.source_name),
          text(record.event_type),
          text(record.scheduled_at),
          text(record.date),
        ]).join(' \u00b7 '),
        snippet: text(record.snippet) || text(record.content) || text(record.summary) || text(record.weak_points),
        source,
      },
    ];
  }
  return [];
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function numericMeta(value: unknown, label: string): string | undefined {
  return typeof value === 'number' && value > 0 ? `${label} #${value}` : undefined;
}

function jdSummary(value: unknown): string | undefined {
  const raw = text(value);
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return text(parsed.summary);
  } catch {
    return raw.slice(0, 160);
  }
}

function compact(values: Array<string | undefined>): string[] {
  return values.filter((value): value is string => Boolean(value));
}

function plainResultText(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim().slice(0, 160);
  if (!value || typeof value !== 'object') return undefined;
  const record = value as Record<string, unknown>;
  return text(record.error) || text(record.message);
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
  let assignedToolIndexes = new Set<number>();
  for (const m of stored) {
    if (m.role === 'user') {
      turns.push({ role: 'user', content: m.content });
      pending = [];
      nextFallbackToolIndex = 0;
      assignedToolIndexes = new Set();
    } else if (m.role === 'assistant') {
      const steps = parseToolCalls(m.tool_calls);
      if (steps.length) pending = pending.concat(steps);
      if (m.content.trim()) {
        const hasPendingToolResults = pending.length > 0 && steps.length === 0;
        turns.push({
          role: 'assistant',
          content: m.content,
          steps: hasPendingToolResults ? pending : undefined,
        });
        if (hasPendingToolResults) {
          pending = [];
          nextFallbackToolIndex = 0;
          assignedToolIndexes = new Set();
        }
      }
    } else if (m.role === 'tool') {
      const toolIndex = resolveToolResultIndex(pending, assignedToolIndexes, m.tool_call_id, nextFallbackToolIndex);
      const step = pending[toolIndex];
      if (step) {
        if (!m.tool_call_id) nextFallbackToolIndex = toolIndex + 1;
        assignedToolIndexes.add(toolIndex);
        const parsed = parseToolResult(m.content, step.name);
        pending[toolIndex] = {
          ...step,
          detail: parsed.detail ?? step.detail,
          evidence: parsed.evidence,
          resultText: parsed.resultText,
          evidenceUnavailable: parsed.evidenceUnavailable,
        };
      }
    }
  }
  return turns;
}

function resolveToolResultIndex(
  pending: ToolStep[],
  assignedIndexes: Set<number>,
  toolCallId: string | undefined,
  fallbackIndex: number,
): number {
  if (toolCallId) {
    const match = pending.findIndex((step) => step.toolCallId === toolCallId);
    if (match >= 0) return match;
  }
  const unfilled = pending.findIndex((_step, index) => index >= fallbackIndex && !assignedIndexes.has(index));
  if (unfilled >= 0) return unfilled;
  return pending.findIndex((_step, index) => !assignedIndexes.has(index));
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

export async function reloadConversationTurns(
  conversationId: number,
  loadConversation: (id: number) => Promise<ChatMessage[]>,
): Promise<UITurn[] | null> {
  try {
    return buildTurns(await loadConversation(conversationId));
  } catch {
    return null;
  }
}

export function pendingActionForConversation(
  conversations: Conversation[],
  conversationId: number,
): PendingAction | null {
  return conversations.find((conversation) => conversation.id === conversationId)?.pending_action ?? null;
}

export { toolMeta };
