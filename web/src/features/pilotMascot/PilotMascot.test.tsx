// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PilotMascot, { type PilotMascotRuntime } from './PilotMascot';
import type { PilotMascotRuntimeController } from './live2dRuntime';

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
    mount: vi.fn().mockResolvedValue({
      setActivity: vi.fn(),
      setZoom: vi.fn(),
      dispose: vi.fn(),
    }),
  };
}

function runtimeController(): PilotMascotRuntimeController {
  return { setActivity: vi.fn(), setZoom: vi.fn(), dispose: vi.fn() };
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

  it.each([
    ['preparing_voice', '正在准备离线语音'],
    ['speaking', '正在朗读'],
    ['waiting_for_speech', '等你开口'],
    ['listening', '正在聆听'],
    ['speech_paused', '检测到停顿'],
    ['transcribing', '正在整理语音'],
  ] as const)('describes the %s voice activity', async (activity, label) => {
    await renderMascot({ activity });
    expect(container.textContent).toContain(label);
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
    const controller = runtimeController();
    const mounted: PilotMascotRuntime = { mount: vi.fn().mockResolvedValue(controller) };
    await renderMascot({ runtime: mounted });
    act(() => root.unmount());
    expect(controller.dispose).toHaveBeenCalledTimes(1);
    root = createRoot(container);
  });

  it('aborts an in-flight runtime before a StrictMode-style remount', async () => {
    const signals: AbortSignal[] = [];
    const pending: PilotMascotRuntime = {
      mount: vi.fn((_canvas: HTMLCanvasElement, signal?: AbortSignal): Promise<PilotMascotRuntimeController> => {
        if (signal) signals.push(signal);
        return new Promise<PilotMascotRuntimeController>(() => undefined);
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

  it('synchronizes activity and zoom with the mounted runtime controller', async () => {
    const controller = runtimeController();
    const mounted: PilotMascotRuntime = { mount: vi.fn().mockResolvedValue(controller) };
    const base = {
      panelOpen: false,
      onHide: vi.fn(),
      onTogglePilot: vi.fn(),
      onZoomChange: vi.fn(),
      runtime: mounted,
    };
    await act(async () => {
      root.render(<PilotMascot {...base} activity="thinking" zoom={1.1} />);
      await Promise.resolve();
    });
    expect(controller.setActivity).toHaveBeenLastCalledWith('thinking');
    expect(controller.setZoom).toHaveBeenLastCalledWith(1);

    await act(async () => {
      root.render(<PilotMascot {...base} activity="success" zoom={1.2} />);
      await Promise.resolve();
    });
    expect(controller.setActivity).toHaveBeenLastCalledWith('success');
    expect(controller.setZoom).toHaveBeenLastCalledWith(1);
  });

  it('enlarges the mascot frame so zoom never crops the model inside a fixed canvas', async () => {
    const controller = runtimeController();
    const mounted: PilotMascotRuntime = { mount: vi.fn().mockResolvedValue(controller) };
    await renderMascot({ runtime: mounted, zoom: 1.3 });

    const mascot = container.querySelector<HTMLElement>('aside');
    expect(mascot?.style.width).toBe('309.4px');
    expect(mascot?.style.height).toBe('481px');
    expect(controller.setZoom).toHaveBeenLastCalledWith(1);
  });

  it('offers bounded zoom controls and reset in the context menu', async () => {
    const onZoomChange = vi.fn();
    const props = await renderMascot({ zoom: 1, onZoomChange });
    const trigger = container.querySelector<HTMLButtonElement>('.characterButton')
      ?? container.querySelector<HTMLButtonElement>('button')!;
    act(() => trigger.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })));
    const buttons = [...container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    const smaller = buttons.find((button) => button.getAttribute('aria-label') === '缩小角色');
    const reset = buttons.find((button) => button.getAttribute('aria-label') === '恢复默认大小');
    const larger = buttons.find((button) => button.getAttribute('aria-label') === '放大角色');
    expect(container.textContent).toContain('100%');
    act(() => smaller!.click());
    act(() => larger!.click());
    expect(onZoomChange.mock.calls.map(([value]) => value)).toEqual([0.9, 1.1]);

    await act(async () => {
      root.render(<PilotMascot {...props} zoom={1.2} />);
      await Promise.resolve();
    });
    act(() => reset!.click());
    expect(onZoomChange).toHaveBeenLastCalledWith(1);
  });

  it('disables zoom controls at the limits and announces a completed reply', async () => {
    await renderMascot({
      activity: 'success',
      zoom: 1.3,
      notification: { status: 'success', conversationId: 42 },
    });
    const trigger = container.querySelector<HTMLButtonElement>('button')!;
    expect(container.textContent).toContain('Pilot 已完成回答，点击查看');
    act(() => trigger.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })));
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="放大角色"]')?.disabled).toBe(true);
  });
});
