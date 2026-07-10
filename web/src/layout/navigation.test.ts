import { describe, expect, it } from 'vitest';
import {
  MODULE_NAV,
  defaultViewForModule,
  moduleTabsForView,
  resolveModuleForView,
} from './navigation';

describe('module navigation contract', () => {
  it('keeps Pilot as a normal top-level tab and groups pages by product module', () => {
    expect(MODULE_NAV.map((item) => item.label)).toEqual([
      '工作台',
      '简历',
      '练习',
      '投递',
      '面试',
      '知识库',
      'Pilot',
      '设置',
    ]);

    expect(MODULE_NAV.some((item) => item.label === 'Pilot')).toBe(true);
    expect(MODULE_NAV.some((item) => item.label === '面试')).toBe(true);
    expect(resolveModuleForView('board')).toBe('pipeline');
    expect(resolveModuleForView('applications-list')).toBe('pipeline');
    expect(resolveModuleForView('calendar')).toBe('pipeline');
    expect(resolveModuleForView('questions')).toBe('practice');
    expect(resolveModuleForView('interview')).toBe('interview');
    expect(resolveModuleForView('pilot')).toBe('pilot');
  });

  it('selects stable defaults for module clicks', () => {
    expect(defaultViewForModule('workspace')).toBe('dashboard');
    expect(defaultViewForModule('resume')).toBe('resumes');
    expect(defaultViewForModule('pipeline')).toBe('board');
    expect(defaultViewForModule('interview')).toBe('interview');
    expect(defaultViewForModule('pilot')).toBe('pilot');
    expect(defaultViewForModule('settings')).toBe('settings');
  });

  it('exposes in-module tabs for secondary workflows', () => {
    expect(moduleTabsForView('calendar')).toEqual([
      { view: 'board', label: '看板' },
      { view: 'applications-list', label: '列表' },
      { view: 'calendar', label: '日历' },
      { view: 'offers', label: 'Offer' },
      { view: 'reminders', label: '提醒' },
    ]);
    expect(moduleTabsForView('interview')).toEqual([{ view: 'interview', label: '面试' }]);
    expect(moduleTabsForView('pilot')).toEqual([{ view: 'pilot', label: '会话中心' }]);
    expect(() => resolveModuleForView('mock')).toThrow('View mock is not part of v0.1 navigation');
  });
});
