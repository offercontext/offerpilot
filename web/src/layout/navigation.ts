export type ViewMode =
  | 'dashboard'
  | 'board'
  | 'applications-list'
  | 'calendar'
  | 'reminders'
  | 'interview'
  | 'reviews'
  | 'mock'
  | 'offers'
  | 'knowledge'
  | 'questions'
  | 'resumes'
  | 'pilot'
  | 'settings';

export type ModuleKey =
  | 'workspace'
  | 'resume'
  | 'practice'
  | 'pipeline'
  | 'interview'
  | 'knowledge'
  | 'pilot'
  | 'settings';

export interface ModuleNavItem {
  key: ModuleKey;
  label: string;
  defaultView: ViewMode;
}

export interface ModuleTabItem {
  view: ViewMode;
  label: string;
}

export const MODULE_NAV: ModuleNavItem[] = [
  { key: 'workspace', label: '工作台', defaultView: 'dashboard' },
  { key: 'resume', label: '简历', defaultView: 'resumes' },
  { key: 'practice', label: '练习', defaultView: 'questions' },
  { key: 'pipeline', label: '投递', defaultView: 'board' },
  { key: 'interview', label: '面试', defaultView: 'interview' },
  { key: 'knowledge', label: '知识库', defaultView: 'knowledge' },
  { key: 'pilot', label: 'Pilot', defaultView: 'pilot' },
  { key: 'settings', label: '设置', defaultView: 'settings' },
];

export const MODULE_TABS: Record<ModuleKey, ModuleTabItem[]> = {
  workspace: [{ view: 'dashboard', label: '总览' }],
  resume: [{ view: 'resumes', label: '简历库' }],
  practice: [{ view: 'questions', label: '题库' }],
  pipeline: [
    { view: 'board', label: '看板' },
    { view: 'applications-list', label: '列表' },
    { view: 'calendar', label: '日历' },
    { view: 'offers', label: 'Offer' },
    { view: 'reminders', label: '提醒' },
  ],
  interview: [{ view: 'interview', label: '面试' }],
  knowledge: [{ view: 'knowledge', label: '知识库' }],
  pilot: [{ view: 'pilot', label: '会话中心' }],
  settings: [{ view: 'settings', label: '设置' }],
};

const VIEW_TO_MODULE: Partial<Record<ViewMode, ModuleKey>> = {
  dashboard: 'workspace',
  resumes: 'resume',
  questions: 'practice',
  board: 'pipeline',
  'applications-list': 'pipeline',
  calendar: 'pipeline',
  reminders: 'pipeline',
  offers: 'pipeline',
  interview: 'interview',
  knowledge: 'knowledge',
  pilot: 'pilot',
  settings: 'settings',
};

const DEFAULT_VIEW_BY_MODULE = MODULE_NAV.reduce(
  (acc, item) => {
    acc[item.key] = item.defaultView;
    return acc;
  },
  {} as Record<ModuleKey, ViewMode>
);

export function resolveModuleForView(view: ViewMode): ModuleKey {
  const module = VIEW_TO_MODULE[view];
  if (!module) throw new Error(`View ${view} is not part of v0.1 navigation`);
  return module;
}

export function defaultViewForModule(module: ModuleKey): ViewMode {
  return DEFAULT_VIEW_BY_MODULE[module];
}

export function moduleTabsForView(view: ViewMode): ModuleTabItem[] {
  return MODULE_TABS[resolveModuleForView(view)];
}
