import { describe, expect, it } from 'vitest';
import { darkTheme, lightTheme } from './antdTheme';

async function loadTokens(): Promise<string> {
  const fsModule = 'node:fs';
  const { readFileSync } = (await import(fsModule)) as {
    readFileSync: (path: URL, encoding: string) => string;
  };
  return readFileSync(new URL('./tokens.css', import.meta.url), 'utf8');
}

describe('control polish theme contract', () => {
  it('defines shared control tokens for both light and dark themes', async () => {
    const css = await loadTokens();

    const lightButton = lightTheme.components?.Button as { controlHeight?: number; borderRadius?: number };
    const darkButton = darkTheme.components?.Button as { controlHeight?: number; borderRadius?: number };
    const lightInput = lightTheme.components?.Input as { controlHeight?: number; borderRadius?: number };
    const darkInput = darkTheme.components?.Input as { controlHeight?: number; borderRadius?: number };
    const lightSelect = lightTheme.components?.Select as { controlHeight?: number; borderRadius?: number };
    const darkSelect = darkTheme.components?.Select as { controlHeight?: number; borderRadius?: number };

    expect(css).toContain('--op-control-height');
    expect(css).toContain('--op-control-radius');
    expect(css).toContain('--op-focus-ring');
    expect(lightButton.controlHeight).toBe(36);
    expect(darkButton.controlHeight).toBe(36);
    expect(lightInput.controlHeight).toBe(36);
    expect(darkInput.controlHeight).toBe(36);
    expect(lightSelect.controlHeight).toBe(36);
    expect(darkSelect.controlHeight).toBe(36);
    expect(lightButton.borderRadius).toBe(8);
    expect(darkButton.borderRadius).toBe(8);
    expect(lightInput.borderRadius).toBe(8);
    expect(darkInput.borderRadius).toBe(8);
    expect(lightSelect.borderRadius).toBe(8);
    expect(darkSelect.borderRadius).toBe(8);
  });
});
