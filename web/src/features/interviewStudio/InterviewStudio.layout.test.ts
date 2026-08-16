import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const styles = readFileSync(new URL('./InterviewStudio.module.css', import.meta.url), 'utf8');

describe('InterviewStudio viewport layout', () => {
  it('keeps variable alerts and long questions in one bounded scrolling column', () => {
    expect(styles).toMatch(/\.timeline\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column[^}]*overflow:\s*hidden/s);
    expect(styles).toMatch(/\.turnList\s*\{[^}]*flex:\s*1 1 auto[^}]*overflow:\s*auto/s);
    expect(styles).toMatch(/\.turn h3\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  });

  it('makes a tall continuous-answer workspace independently scrollable', () => {
    expect(styles).toMatch(/\.composer\s*\{[^}]*max-height:[^;}]+;[^}]*overflow-y:\s*auto/s);
  });
});
