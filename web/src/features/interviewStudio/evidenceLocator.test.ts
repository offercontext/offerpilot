import { describe, expect, it } from 'vitest';
import { buildEvidenceEntries, evidenceKey } from './evidenceLocator';

describe('interview studio evidence locator', () => {
  it('labels frozen source references and prior-answer follow-up references', () => {
    const refs = [
      { source: 'turn', path: '/turns/002/answer', excerpt: '我会先拆分接口边界。' },
      { source: 'jd', path: '/jd/text', excerpt: '负责 Python 服务的稳定性。' },
      { source: 'resume', path: '/resume/content_json/raw_text', excerpt: '维护过异步任务系统。' },
    ];

    expect(buildEvidenceEntries(refs)).toEqual([
      { key: evidenceKey(refs[0]), label: '上一轮回答 · 第 2 轮', ...refs[0] },
      { key: evidenceKey(refs[1]), label: '冻结 JD · /jd/text', ...refs[1] },
      { key: evidenceKey(refs[2]), label: '冻结简历 · /resume/content_json/raw_text', ...refs[2] },
    ]);
  });
});
