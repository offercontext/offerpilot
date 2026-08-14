export type ReadinessStatus = 'ready' | 'needs_input' | 'source_changed' | 'unknown' | 'unavailable';

export interface ReadinessItem {
  key: 'application' | 'jd' | 'resume' | 'event' | 'preparation';
  label: string;
  status: ReadinessStatus;
  detail: string;
  actionLabel?: string;
}

export interface ReadinessResult {
  ready: boolean;
  items: ReadinessItem[];
}

export interface RealInterviewReadinessInput {
  application: { id: number } | null;
  jd: { status: 'ready' | 'missing' | 'source_changed' | 'unknown' | 'unavailable' };
  resume: { id: number } | null;
  event: { id: number } | null;
}

export interface QuickPracticeDraft {
  positionName: string;
  jdText: string;
  jdConfirmed: boolean;
  resumeId: number | undefined;
}

export function buildRealInterviewReadiness(input: RealInterviewReadinessInput): ReadinessResult {
  const items: ReadinessItem[] = [
    {
      key: 'application',
      label: '投递',
      status: input.application ? 'ready' : 'needs_input',
      detail: input.application ? '已选择当前可见的投递。' : '需要选择一条当前可见的投递。',
      actionLabel: input.application ? undefined : '选择投递',
    },
    {
      key: 'jd',
      label: '岗位资料',
      status: input.jd.status === 'ready' ? 'ready' : input.jd.status === 'missing' ? 'needs_input' : input.jd.status,
      detail: input.jd.status === 'ready'
        ? '当前 JD（只读）已确认。'
        : input.jd.status === 'source_changed'
          ? '岗位资料版本已变化，需要重新确认。'
          : input.jd.status === 'missing'
            ? '还没有当前已确认的岗位资料版本。'
            : '岗位资料状态暂时无法确认。',
      actionLabel: input.jd.status === 'ready' ? '更新岗位资料' : '补充岗位资料',
    },
    {
      key: 'resume',
      label: '简历',
      status: input.resume ? 'ready' : 'needs_input',
      detail: input.resume ? '已选择一份已保存简历。' : '需要显式选择一份当前可见的已保存简历。',
      actionLabel: input.resume ? undefined : '选择简历',
    },
    {
      key: 'event',
      label: '面试安排',
      status: input.event ? 'ready' : 'needs_input',
      detail: input.event ? '已选择已排期的面试事件。' : '需要选择一条已排期且可见的面试事件。',
      actionLabel: input.event ? undefined : '安排面试',
    },
  ];
  return {
    ready: items.slice(0, 4).every((item) => item.status === 'ready'),
    items,
  };
}

export function buildQuickPracticeReadiness(draft: QuickPracticeDraft): ReadinessResult {
  const draftStatus = validateQuickPracticeDraft(draft);
  const items: ReadinessItem[] = [
    {
      key: 'application',
      label: '练习档案',
      status: 'ready',
      detail: '快速练习不会创建投递或日程。',
    },
    {
      key: 'jd',
      label: '岗位资料',
      status: draft.positionName.trim() && draft.jdText.trim() && draft.jdConfirmed ? 'ready' : 'needs_input',
      detail: draft.jdConfirmed ? '已核对，本次按此岗位资料练习。' : '粘贴 JD 后请明确勾选已核对。',
      actionLabel: '粘贴 JD',
    },
    {
      key: 'resume',
      label: '简历',
      status: draft.resumeId ? 'ready' : 'needs_input',
      detail: draft.resumeId ? '将冻结当前已保存版本。' : '需要选择一份当前可见的已保存简历。',
      actionLabel: '选择简历',
    },
    {
      key: 'event',
      label: '写入边界',
      status: 'ready',
      detail: '只创建快速练习档案，不写入投递、日历、Knowledge、Memory、Story 或 Offer。',
    },
    {
      key: 'preparation',
      label: '输入边界',
      status: 'ready',
      detail: '仅发送冻结 JD、冻结简历和本次确认的问答。',
    },
  ];
  return { ready: draftStatus.ok && items.slice(1, 3).every((item) => item.status === 'ready'), items };
}

export function validateQuickPracticeDraft(
  draft: QuickPracticeDraft,
): { ok: true } | { ok: false; field: 'positionName' | 'jdText' | 'jdConfirmed' | 'resumeId' } {
  if (!draft.positionName.trim() || [...draft.positionName].length > 200) return { ok: false, field: 'positionName' };
  if (!draft.jdText.trim() || draft.jdText.length > 100_000) return { ok: false, field: 'jdText' };
  if (!draft.jdConfirmed) return { ok: false, field: 'jdConfirmed' };
  if (!draft.resumeId) return { ok: false, field: 'resumeId' };
  return { ok: true };
}
