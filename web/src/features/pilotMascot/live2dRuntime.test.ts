// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import {
  createLive2dPilotMascotRuntime,
  serializePilotMascotRuntime,
  type Live2dRuntimeDependencies,
  type PilotMascotRuntime,
} from './live2dRuntime';

describe('serializePilotMascotRuntime', () => {
  it('never initializes two runtimes concurrently on the same canvas', async () => {
    const canvas = document.createElement('canvas');
    const firstController = new AbortController();
    const secondController = new AbortController();
    let resolveFirst!: (dispose: () => void) => void;
    let active = 0;
    let maximumActive = 0;
    const firstDispose = vi.fn(() => {
      active -= 1;
    });
    const secondDispose = vi.fn(() => {
      active -= 1;
    });
    const underlying: PilotMascotRuntime = {
      mount: vi.fn()
        .mockImplementationOnce(() => {
          active += 1;
          maximumActive = Math.max(maximumActive, active);
          return new Promise<() => void>((resolve) => {
            resolveFirst = resolve;
          });
        })
        .mockImplementationOnce(async () => {
          active += 1;
          maximumActive = Math.max(maximumActive, active);
          return secondDispose;
        }),
    };
    const runtime = serializePilotMascotRuntime(underlying);

    const firstMount = runtime.mount(canvas, firstController.signal);
    const firstRejected = firstMount.catch((error: unknown) => error);
    await Promise.resolve();
    await Promise.resolve();
    expect(underlying.mount).toHaveBeenCalledTimes(1);
    firstController.abort();
    const secondMount = runtime.mount(canvas, secondController.signal);
    await Promise.resolve();
    expect(underlying.mount).toHaveBeenCalledTimes(1);

    resolveFirst(firstDispose);
    await expect(firstRejected).resolves.toMatchObject({ name: 'AbortError' });
    const disposeSecond = await secondMount;

    expect(underlying.mount).toHaveBeenCalledTimes(2);
    expect(maximumActive).toBe(1);
    expect(firstDispose).toHaveBeenCalledTimes(1);
    disposeSecond();
    expect(secondDispose).toHaveBeenCalledTimes(1);
  });

  it('does not start an aborted mount after a queued runtime releases', async () => {
    const canvas = document.createElement('canvas');
    let releaseFirst!: () => void;
    const underlying: PilotMascotRuntime = {
      mount: vi.fn()
        .mockResolvedValueOnce(() => releaseFirst?.())
        .mockResolvedValueOnce(() => undefined),
    };
    const runtime = serializePilotMascotRuntime(underlying);
    const firstDispose = await runtime.mount(canvas);
    const controller = new AbortController();
    const queued = runtime.mount(canvas, controller.signal);
    controller.abort();
    firstDispose();

    await expect(queued).rejects.toMatchObject({ name: 'AbortError' });
    expect(underlying.mount).toHaveBeenCalledTimes(1);
  });
});

function runtimeDependencies(overrides: Partial<Live2dRuntimeDependencies> = {}) {
  const application = {
    stage: { addChild: vi.fn() },
    render: vi.fn(),
    destroy: vi.fn(),
  };
  const model = {
    width: 500,
    height: 800,
    x: 0,
    y: 0,
    anchor: { set: vi.fn() },
    scale: { set: vi.fn() },
    destroy: vi.fn(),
  };
  const Application = vi.fn(function Application() {
    return application;
  });
  const Live2DModel = {
    registerTicker: vi.fn(),
    from: vi.fn().mockResolvedValue(model),
  };
  const observer = { observe: vi.fn(), disconnect: vi.fn() };
  const dependencies: Live2dRuntimeDependencies = {
    loadModules: vi.fn().mockResolvedValue({ Application, Ticker: {}, Live2DModel }),
    prefersReducedMotion: () => false,
    createResizeObserver: () => observer,
    ...overrides,
  };
  return { dependencies, Application, Live2DModel, application, model, observer };
}

describe('createLive2dPilotMascotRuntime', () => {
  it('destroys a partially initialized Pixi application when model loading fails', async () => {
    const fixture = runtimeDependencies();
    fixture.Live2DModel.from.mockRejectedValueOnce(new Error('model failed'));
    const host = document.createElement('div');
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);

    await expect(createLive2dPilotMascotRuntime(fixture.dependencies).mount(canvas)).rejects.toThrow('model failed');
    expect(fixture.application.destroy).toHaveBeenCalledTimes(1);
    expect(fixture.model.destroy).not.toHaveBeenCalled();
  });

  it('cleans up model and application when ResizeObserver setup fails', async () => {
    const fixture = runtimeDependencies({
      createResizeObserver: () => { throw new Error('observer failed'); },
    });
    const host = document.createElement('div');
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);

    await expect(createLive2dPilotMascotRuntime(fixture.dependencies).mount(canvas)).rejects.toThrow('observer failed');
    expect(fixture.model.destroy).toHaveBeenCalledTimes(1);
    expect(fixture.application.destroy).toHaveBeenCalledTimes(1);
  });

  it('renders one static frame without auto updates when reduced motion is requested', async () => {
    const fixture = runtimeDependencies({ prefersReducedMotion: () => true });
    const host = document.createElement('div');
    Object.defineProperties(host, {
      clientWidth: { configurable: true, value: 240 },
      clientHeight: { configurable: true, value: 360 },
    });
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);

    const dispose = await createLive2dPilotMascotRuntime(fixture.dependencies).mount(canvas);
    expect(fixture.Application).toHaveBeenCalledWith(expect.objectContaining({ autoStart: false }));
    expect(fixture.Live2DModel.from).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ autoUpdate: false }));
    expect(fixture.application.render).toHaveBeenCalledTimes(1);
    dispose();
  });
});
