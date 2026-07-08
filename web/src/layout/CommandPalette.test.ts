import { describe, expect, it } from 'vitest';
import source from './CommandPalette.tsx?raw';

describe('CommandPalette resume commands', () => {
  it('uses resume-library/new-resume wording instead of resume-match wording', () => {
    expect(source).toContain('打开简历库');
    expect(source).toContain('新建简历');
    expect(source).toContain('上传简历');
    expect(source).not.toContain('简历匹配');
  });
});
