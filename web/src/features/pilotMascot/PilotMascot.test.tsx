// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PilotMascot, { type PilotMascotRuntime } from './PilotMascot';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

function runtime(): PilotMascotRuntime {
  return {
    mount: vi.fn().mockResolvedValue(() => undefined),
  };
}

async function renderMascot(overrides: Partial<React.ComponentProps<typeof PilotMascot>> = {}) {
  const props: React.ComponentProps<typeof PilotMascot> = {
    activity: 'idle',
    panelOpen: false,
    onHide: vi.fn(),
    onTogglePilot: vi.fn(),
    runtime: runtime(),
    ...overrides,
  };
  await act(async () => {
    root.render(<PilotMascot {...props} />);
    await Promise.resolve();
  });
  return props;
}

describe('PilotMascot', () => {
  it('toggles Pilot with an accessible button and exposes activity text', async () => {
    const props = await renderMascot({ activity: 'thinking' });
    const button = container.querySelector<HTMLButtonElement>('button[aria-label="打开 OfferPilot 领航员"]');
    expect(button).not.toBeNull();
    expect(container.textContent).toContain('正在思考');
    act(() => button!.click());
    expect(props.onTogglePilot).toHaveBeenCalledTimes(1);
  });

  it('opens a custom context menu and hides the character', async () => {
    const props = await renderMascot();
    const button = container.querySelector('button')!;
    act(() => button.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })));
    const hide = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((item) => item.textContent?.includes('隐藏角色'));
    expect(hide).toBeDefined();
    act(() => hide!.click());
    expect(props.onHide).toHaveBeenCalledTimes(1);
  });

  it('closes the context menu with Escape', async () => {
    await renderMascot();
    const button = container.querySelector('button')!;
    act(() => button.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })));
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(container.textContent).not.toContain('隐藏角色');
    expect(document.activeElement).toBe(button);
  });

  it('opens the context menu from the keyboard and moves focus to its action', async () => {
    await renderMascot();
    const button = container.querySelector<HTMLButtonElement>('button')!;
    act(() => button.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true })));
    expect(document.activeElement?.textContent).toContain('隐藏角色');
  });

  it('keeps Pilot usable when the Live2D runtime fails', async () => {
    const broken: PilotMascotRuntime = { mount: vi.fn().mockRejectedValue(new Error('model failed')) };
    const props = await renderMascot({ runtime: broken });
    expect(container.textContent).toContain('Haru 暂时休息中');
    act(() => container.querySelector('button')!.click());
    expect(props.onTogglePilot).toHaveBeenCalledTimes(1);
  });

  it('disposes the runtime on unmount', async () => {
    const dispose = vi.fn();
    const mounted: PilotMascotRuntime = { mount: vi.fn().mockResolvedValue(dispose) };
    await renderMascot({ runtime: mounted });
    act(() => root.unmount());
    expect(dispose).toHaveBeenCalledTimes(1);
    root = createRoot(container);
  });

  it('aborts an in-flight runtime before a StrictMode-style remount', async () => {
    const signals: AbortSignal[] = [];
    const pending: PilotMascotRuntime = {
      mount: vi.fn((_canvas: HTMLCanvasElement, signal?: AbortSignal): Promise<() => void> => {
        if (signal) signals.push(signal);
        return new Promise<() => void>(() => undefined);
      }),
    };
    await act(async () => {
      root.render(
        <PilotMascot
          activity="idle"
          panelOpen={false}
          onHide={vi.fn()}
          onTogglePilot={vi.fn()}
          runtime={pending}
        />,
      );
    });
    act(() => root.unmount());
    expect(signals[0]?.aborted).toBe(true);
    root = createRoot(container);
  });
});
