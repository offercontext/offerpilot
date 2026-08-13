export interface PilotMascotRuntime {
  mount(canvas: HTMLCanvasElement, signal?: AbortSignal): Promise<() => void>;
}

export function serializePilotMascotRuntime(runtime: PilotMascotRuntime): PilotMascotRuntime {
  const canvasQueues = new WeakMap<HTMLCanvasElement, Promise<void>>();

  return {
    async mount(canvas, signal) {
      const previous = canvasQueues.get(canvas) ?? Promise.resolve();
      let releaseQueue!: () => void;
      const current = new Promise<void>((resolve) => {
        releaseQueue = resolve;
      });
      canvasQueues.set(canvas, current);
      await previous.catch(() => undefined);

      let dispose: (() => void) | undefined;
      const release = () => {
        if (dispose) {
          dispose();
          dispose = undefined;
        }
        if (canvasQueues.get(canvas) === current) canvasQueues.delete(canvas);
        releaseQueue();
      };

      try {
        if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
        dispose = await runtime.mount(canvas, signal);
        if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
        return release;
      } catch (error) {
        release();
        throw error;
      }
    },
  };
}

const MODEL_URL = '/live2d/haru-receptionist/haru_greeter_t03.model3.json';
const CUBISM_CORE_URL = '/live2d/live2dcubismcore.min.js';
const CUBISM_CORE_SCRIPT_ID = 'offerpilot-live2d-cubism-core';

interface Live2dApplication {
  stage: { addChild: (model: Live2dModelInstance) => void };
  render: () => void;
  destroy: (removeView: boolean, options: Record<string, boolean>) => void;
}

interface Live2dModelInstance {
  width: number;
  height: number;
  x: number;
  y: number;
  anchor: { set: (x: number, y: number) => void };
  scale: { set: (scale: number) => void };
  destroy: (options: { children: boolean }) => void;
}

interface Live2dRuntimeModules {
  Application: new (options: Record<string, unknown>) => Live2dApplication;
  Ticker: unknown;
  Live2DModel: {
    registerTicker: (ticker: unknown) => void;
    from: (url: string, options: { autoInteract: boolean; autoUpdate: boolean }) => Promise<Live2dModelInstance>;
  };
}

export interface Live2dRuntimeDependencies {
  loadModules: () => Promise<Live2dRuntimeModules>;
  prefersReducedMotion: () => boolean;
  createResizeObserver: (callback: () => void) => Pick<ResizeObserver, 'observe' | 'disconnect'>;
}

let cubismCorePromise: Promise<void> | undefined;

function ensureCubismCore(): Promise<void> {
  if ('Live2DCubismCore' in globalThis) return Promise.resolve();
  if (cubismCorePromise) return cubismCorePromise;
  cubismCorePromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(CUBISM_CORE_SCRIPT_ID) as HTMLScriptElement | null;
    const script = existing ?? document.createElement('script');
    const onReady = () => resolve();
    const onError = () => {
      cubismCorePromise = undefined;
      script.remove();
      reject(new Error('Cubism Core failed to load'));
    };
    script.addEventListener('load', onReady, { once: true });
    script.addEventListener('error', onError, { once: true });
    if (!existing) {
      script.id = CUBISM_CORE_SCRIPT_ID;
      script.src = CUBISM_CORE_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });
  return cubismCorePromise;
}

export function createLive2dPilotMascotRuntime(
  dependencies: Live2dRuntimeDependencies,
): PilotMascotRuntime {
  return {
  async mount(canvas, signal) {
    const { Application, Ticker, Live2DModel } = await dependencies.loadModules();
    if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
    Live2DModel.registerTicker(Ticker);
    const host = canvas.parentElement;
    if (!host) throw new Error('Pilot mascot host is unavailable');

    const reduceMotion = dependencies.prefersReducedMotion();
    let application: Live2dApplication | undefined;
    let model: Live2dModelInstance | undefined;
    let observer: Pick<ResizeObserver, 'observe' | 'disconnect'> | undefined;
    const dispose = () => {
      observer?.disconnect();
      model?.destroy({ children: true });
      application?.destroy(false, { children: true, texture: false, baseTexture: false });
      observer = undefined;
      model = undefined;
      application = undefined;
    };

    try {
      application = new Application({
        view: canvas,
        autoStart: !reduceMotion,
        backgroundAlpha: 0,
        antialias: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
        autoDensity: true,
        resizeTo: host,
      });
      model = await Live2DModel.from(MODEL_URL, {
        autoInteract: false,
        autoUpdate: !reduceMotion,
      });
      if (signal?.aborted) throw new DOMException('Mascot mount aborted', 'AbortError');
      application.stage.addChild(model);
      model.anchor.set(0.5, 0.5);
      const naturalWidth = model.width;
      const naturalHeight = model.height;

      const fit = () => {
        const width = Math.max(host.clientWidth, 1);
        const height = Math.max(host.clientHeight, 1);
        const scale = Math.min((width * 0.94) / naturalWidth, (height * 0.96) / naturalHeight);
        model!.scale.set(scale);
        model!.x = width * 0.5;
        model!.y = height * 0.5;
        if (reduceMotion) application!.render();
      };
      fit();
      observer = dependencies.createResizeObserver(fit);
      observer.observe(host);
      return dispose;
    } catch (error) {
      dispose();
      throw error;
    }
  },
  };
}

const unsharedLive2dPilotMascotRuntime = createLive2dPilotMascotRuntime({
  async loadModules() {
    await ensureCubismCore();
    const [{ Application, Ticker }, { Live2DModel }] = await Promise.all([
      import('pixi.js'),
      import('pixi-live2d-display/cubism4'),
    ]);
    return {
      Application: Application as unknown as Live2dRuntimeModules['Application'],
      Ticker,
      Live2DModel: Live2DModel as unknown as Live2dRuntimeModules['Live2DModel'],
    };
  },
  prefersReducedMotion: () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  createResizeObserver: (callback) => new ResizeObserver(callback),
});

export const live2dPilotMascotRuntime = serializePilotMascotRuntime(unsharedLive2dPilotMascotRuntime);
