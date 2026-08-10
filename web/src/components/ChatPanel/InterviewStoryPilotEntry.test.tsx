// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContextPanel from './ContextPanel';

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({ matches: false, addListener: () => undefined, removeListener: () => undefined }),
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
});

describe('Interview Story Pilot entry', () => {
  it('opens the local Story workflow only after an explicit click', () => {
    const open = vi.fn();
    act(() => root?.render(<ContextPanel
      isNego={false}
      offer={null}
      capabilities={[]}
      evidence={[]}
      autoApprove={false}
      hasKey
      degraded={false}
      disabled={false}
      onCapability={() => {}}
      onToggleAutoApprove={() => {}}
      onOpenInterviewStoryLibrary={open}
    />));

    expect(open).not.toHaveBeenCalled();
    const trigger = container?.querySelector('[data-testid="pilot-open-interview-story-library"]') as HTMLButtonElement;
    act(() => trigger.click());
    expect(open).toHaveBeenCalledTimes(1);
  });
});
