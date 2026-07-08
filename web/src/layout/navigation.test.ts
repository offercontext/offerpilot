import { describe, expect, it } from 'vitest';
import {
  MODULE_NAV,
  defaultViewForModule,
  moduleTabsForView,
  resolveModuleForView,
} from './navigation';

describe('module navigation contract', () => {
  it('keeps Pilot out of top-level navigation and groups pages by product module', () => {
    expect(MODULE_NAV.map((item) => item.label)).toEqual([
      '工作台',
      '简历',
      '练习',
      '投递',
      '知识库',
      '设置',
    ]);

    expect(MODULE_NAV.some((item) => item.label.includes('Pilot'))).toBe(false);
    expect(MODULE_NAV.some((item) => item.label === '面试')).toBe(false);
    expect(resolveModuleForView('board')).toBe('pipeline');
    expect(resolveModuleForView('calendar')).toBe('pipeline');
    expect(resolveModuleForView('questions')).toBe('practice');
  });

  it('selects stable defaults for module clicks', () => {
    expect(defaultViewForModule('workspace')).toBe('dashboard');
    expect(defaultViewForModule('resume')).toBe('resumes');
    expect(defaultViewForModule('pipeline')).toBe('board');
    expect(defaultViewForModule('settings')).toBe('settings');
  });

  it('exposes in-module tabs for secondary workflows', () => {
    expect(moduleTabsForView('calendar')).toEqual([
      { view: 'board', label: '看板' },
      { view: 'calendar', label: '日历' },
      { view: 'offers', label: 'Offer' },
      { view: 'reminders', label: '提醒' },
    ]);
    expect(() => resolveModuleForView('mock')).toThrow('View mock is not part of v0.1 navigation');
  });
});
