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
  /** Short label reconstructed from the most recent user request. */
  taskTitle?: string;
  /** Structured Pilot conclusion and actions reconstructed from persisted Markdown. */
  presentation?: TurnPresentation;
}

export interface TurnPresentation {
  conclusion: string;
  actions: string[];
  detailMarkdown: string;
}

const EVIDENCE_SNIPPET_MAX = 180;
const TASK_TITLE_MAX_LENGTH = 36;
const MARKDOWN_HEADING = /^ {0,3}(#{1,6})[\t ]+(.+?)[\t ]*$/;
const PRESENTATION_ACTION = /^([\t ]*)[-*+][\t ]+(.+?)\s*$/;

interface MarkdownHeading {
  level: number;
  text: string;
}

interface ParsedPresentationActions {
  actions: string[];
  literalMarkdown: string;
}

/** Reconstruct the structured conclusion and actions from a persisted Pilot reply. */
export function parseTurnPresentation(content: string): TurnPresentation | undefined {
  const lines = content.replace(/\r\n?/g, '\n').split('\n');
  const fencedLines = fencedLineIndexes(lines);
  let conclusionIndex = -1;
  let nextStepsIndex = -1;
  let nextStepsLevel = 0;

  for (let index = 0; index < lines.length; index += 1) {
    if (fencedLines[index]) continue;
    const heading = markdownHeading(lines[index]);
    if (!heading || heading.level < 2 || heading.level > 3) continue;
    if (heading.text === '结论' && conclusionIndex < 0) conclusionIndex = index;
    if (heading.text === '下一步' && nextStepsIndex < 0) {
      nextStepsIndex = index;
      nextStepsLevel = heading.level;
    }
  }

  if (conclusionIndex < 0 || nextStepsIndex < 0 || conclusionIndex > nextStepsIndex) return undefined;

  const conclusion = lines.slice(conclusionIndex + 1, nextStepsIndex).join('\n').trim();
  const tailIndex = lines.findIndex(
    (line, index) =>
      index > nextStepsIndex &&
      !fencedLines[index] &&
      (markdownHeading(line)?.level ?? Number.POSITIVE_INFINITY) <= nextStepsLevel,
  );
  const actionEndIndex = tailIndex < 0 ? lines.length : tailIndex;
  const parsedActions = parsePresentationActions(lines, fencedLines, nextStepsIndex + 1, actionEndIndex);

  if (!conclusion || parsedActions.actions.length === 0) return undefined;

  const detailMarkdown = [
    lines.slice(0, conclusionIndex).join('\n').trim(),
    parsedActions.literalMarkdown,
    lines.slice(actionEndIndex).join('\n').trim(),
  ]
    .filter(Boolean)
    .join('\n\n');

  return {
    conclusion,
    actions: parsedActions.actions,
    detailMarkdown,
  };
}

function markdownHeading(line: string): MarkdownHeading | undefined {
  const match = line.match(MARKDOWN_HEADING);
  if (!match) return undefined;
  return {
    level: match[1].length,
    text: match[2].replace(/[\t ]+#+[\t ]*$/, '').trim(),
  };
}

function fencedLineIndexes(lines: string[]): boolean[] {
  const fenced = Array<boolean>(lines.length).fill(false);
  let marker: string | undefined;
  let markerLength = 0;
  let containerContentStart: number | undefined;
  let nestedFence = false;

  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^([\t ]*)(`{3,}|~{3,})(.*)$/);
    if (!marker) {
      if (!match) continue;
      const indent = visualIndent(match[1]);
      const contentStart = listContainerContentStart(lines, index, indent);
      if (indent > 3 && contentStart === undefined) continue;
      fenced[index] = true;
      marker = match[2][0];
      markerLength = match[2].length;
      containerContentStart = contentStart;
      nestedFence = contentStart !== undefined;
      continue;
    }

    fenced[index] = true;
    const closingIndent = match ? visualIndent(match[1]) : 0;
    const canClose = match && (
      nestedFence
        ? containerContentStart !== undefined &&
          closingIndent >= containerContentStart &&
          closingIndent <= containerContentStart + 3
        : closingIndent <= 3
    );
    if (canClose && match[2][0] === marker && match[2].length >= markerLength && /^[\t ]*$/.test(match[3])) {
      marker = undefined;
      markerLength = 0;
      containerContentStart = undefined;
      nestedFence = false;
    }
  }

  return fenced;
}

function listContainerContentStart(lines: string[], index: number, indent: number): number | undefined {
  for (let previousIndex = index - 1; previousIndex >= 0; previousIndex -= 1) {
    const previousLine = lines[previousIndex];
    if (!previousLine.trim()) continue;
    const previousIndent = visualIndent(previousLine);
    if (previousIndent >= indent) continue;
    const contentStart = listItemContentStart(previousLine);
    if (contentStart !== undefined && indent >= contentStart) return contentStart;
    if (previousIndent === 0) return undefined;
  }
  return undefined;
}

function listItemContentStart(line: string): number | undefined {
  const match = line.match(/^[\t ]*(?:[-*+]|\d+[.)])[\t ]+/);
  return match ? visualWidth(match[0]) : undefined;
}

function parsePresentationActions(
  lines: string[],
  fencedLines: boolean[],
  startIndex: number,
  endIndex: number,
): ParsedPresentationActions {
  const actions: string[][] = [];
  const literalLines: string[] = [];
  let actionIndent: number | undefined;
  let currentAction: string[] | undefined;

  for (let index = startIndex; index < endIndex; index += 1) {
    if (fencedLines[index]) continue;
    const line = lines[index];
    const action = line.match(PRESENTATION_ACTION);
    const indent = action ? visualIndent(action[1]) : undefined;

    if (actionIndent === undefined && indent !== undefined && indent >= 4) {
      literalLines.push(line);
      continue;
    }
    if (actionIndent === undefined && visualIndent(line) >= 4) {
      literalLines.push(line);
      continue;
    }

    if (action && (actionIndent === undefined || indent === actionIndent)) {
      actionIndent ??= indent;
      if (actions.length >= 3) {
        currentAction = undefined;
        continue;
      }
      currentAction = [action[2].trim()];
      actions.push(currentAction);
      continue;
    }

    if (currentAction && actionIndent !== undefined && line.trim() && visualIndent(line) > actionIndent) {
      currentAction.push(line.trimEnd());
    }
  }

  return {
    actions: actions.map((action) => action.join('\n').trim()),
    literalMarkdown: trimMarkdown(literalLines),
  };
}

function visualIndent(line: string): number {
  const whitespace = line.match(/^[\t ]*/)?.[0] ?? '';
  return visualWidth(whitespace);
}

function visualWidth(text: string): number {
  let column = 0;
  for (const character of text) {
    column += character === '\t' ? 4 - (column % 4) : 1;
  }
  return column;
}

function trimMarkdown(lines: string[]): string {
  let first = 0;
  let last = lines.length;
  while (first < last && !lines[first].trim()) first += 1;
  while (last > first && !lines[last - 1].trim()) last -= 1;
  return lines.slice(first, last).join('\n');
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
  const id = String(
    record.id ?? record.resume_match_id ?? record.search_result_id ?? record.chunk_id ?? record.document_id ?? `${source}-${index}`,
  );
  const recordType = text(record.record_type);
  const isResumeMatch = source.includes('resume_match') || recordType === 'resume_match';
  if (isResumeMatch) {
    return [
      {
        id: `${source}-${id}`,
        kind: 'resume',
        title: `简历匹配 #${id}`,
        meta: compact([numericMeta(record.resume_id, '简历'), numericMeta(record.application_id, '投递')]).join(' · '),
        snippet: previewText(jdSummary(record.result) || text(record.jd_text)),
        source,
      },
    ];
  }
  const isResume = source.includes('resume') || recordType === 'resume';
  if (isResume) {
    const title = text(record.name) || `简历 #${id}`;
    return [
      {
        id: `${source}-${id}`,
        kind: 'resume',
        title,
        meta: text(record.parse_status),
        snippet: previewText(record.parsed_data),
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
        snippet: previewText(jdSummary(record.result) || text(record.jd_text)),
        source,
      },
    ];
  }
  const isEvent = source.includes('event') || recordType === 'event' || recordType === 'application_event';
  if (isEvent) {
    const title = text(record.company_name) || text(record.title) || `日程 #${id}`;
    return [
      {
        id: `${source}-${id}`,
        kind: 'event',
        title,
        meta: compact([
          text(record.position_name),
          text(record.event_type),
          text(record.subtype),
          text(record.scheduled_at),
        ]).join(' \u00b7 '),
        snippet: previewText(record.notes),
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
          snippet: previewText(text(record.assessment) || text(record.notes)),
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
        snippet: previewText(record.notes),
        source,
      },
    ];
  }
  const title = text(record.title) || text(record.document_title) || text(record.round) || text(record.name);
  if (title) {
    const isKnowledge = source.includes('knowledge') || recordType?.startsWith('knowledge');
    const rawSnippet = isKnowledge
      ? text(record.snippet) || text(record.summary) || text(record.content) || text(record.weak_points)
      : text(record.snippet) || text(record.content) || text(record.summary) || text(record.weak_points);
    return [
      {
        id: `${source}-${id}`,
        kind: isKnowledge ? 'knowledge' : source.includes('event') ? 'event' : 'note',
        title,
        meta: compact([
          text(record.source_name),
          text(record.event_type),
          text(record.subtype),
          text(record.scheduled_at),
          text(record.date),
        ]).join(' \u00b7 '),
        snippet: previewText(rawSnippet),
        source,
      },
    ];
  }
  return [];
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function previewText(value: unknown, maxLength = EVIDENCE_SNIPPET_MAX): string | undefined {
  const raw = text(value);
  if (!raw) return undefined;
  const normalized = raw.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
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
  let latestUserContent: string | undefined;
  for (const m of stored) {
    if (m.role === 'user') {
      turns.push({ role: 'user', content: m.content });
      latestUserContent = m.content;
      pending = [];
      nextFallbackToolIndex = 0;
      assignedToolIndexes = new Set();
    } else if (m.role === 'assistant') {
      const steps = parseToolCalls(m.tool_calls);
      if (steps.length) pending = pending.concat(steps);
      if (m.content.trim()) {
        const hasPendingToolResults = pending.length > 0 && steps.length === 0;
        const isFinalAssistantReply = steps.length === 0;
        const presentation = isFinalAssistantReply ? parseTurnPresentation(m.content) : undefined;
        turns.push({
          role: 'assistant',
          content: presentation?.detailMarkdown ?? m.content,
          steps: hasPendingToolResults ? pending : undefined,
          taskTitle: isFinalAssistantReply ? taskTitleFor(latestUserContent) : undefined,
          presentation,
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

function taskTitleFor(content: string | undefined): string {
  const normalized = content?.replace(/\s+/g, ' ').trim() ?? '';
  if (!normalized) return '本轮任务';
  const codePoints = Array.from(normalized);
  if (codePoints.length <= TASK_TITLE_MAX_LENGTH) return normalized;
  return `${codePoints.slice(0, TASK_TITLE_MAX_LENGTH - 1).join('')}…`;
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
