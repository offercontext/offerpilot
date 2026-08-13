import { describe, expect, it, vi } from 'vitest';
import { OfflineWhisperControllerImpl } from './offlineWhisperController';
import type { OfflineWhisperWorkerLike } from './offlineWhisperTypes';

class FakeWorker implements OfflineWhisperWorkerLike {
  listeners = new Set<(event: MessageEvent) => void>();
  messages: unknown[] = [];
  postMessage(message: unknown) { this.messages.push(message); }
  addEventListener(_type: 'message', listener: (event: MessageEvent) => void) { this.listeners.add(listener); }
  removeEventListener(_type: 'message', listener: (event: MessageEvent) => void) { this.listeners.delete(listener); }
  terminate = vi.fn();
  emit(data: unknown) { this.listeners.forEach((listener) => listener({ data } as MessageEvent)); }
}

describe('OfflineWhisperController', () => {
  it('publishes honest download progress and marks ready only after worker completion', async () => {
    const worker = new FakeWorker();
    const store = {
      inspect: vi.fn(async () => ({ ready: false, cachedBytes: 0 })),
      checkCapacity: vi.fn(async () => 'sufficient' as const),
      markReady: vi.fn(async () => undefined),
      remove: vi.fn(async () => undefined),
    };
    const controller = new OfflineWhisperControllerImpl({ createWorker: () => worker, store });
    const preparing = controller.prepare();
    await Promise.resolve();
    worker.emit({ type: 'download_progress', generation: 1, loaded: 20, total: 100 });
    expect(controller.getState()).toEqual({ status: 'downloading', receivedBytes: 20, totalBytes: 100 });
    worker.emit({ type: 'ready', generation: 1, backend: 'webgpu', cachedBytes: 100 });
    await expect(preparing).resolves.toBe('webgpu');
    expect(store.markReady).toHaveBeenCalledWith(100);
    expect(controller.getState()).toMatchObject({ status: 'ready', backend: 'webgpu' });
  });

  it('blocks download when capacity is known to be insufficient', async () => {
    const worker = new FakeWorker();
    const controller = new OfflineWhisperControllerImpl({
      createWorker: () => worker,
      store: {
        inspect: vi.fn(async () => ({ ready: false, cachedBytes: 0 })),
        checkCapacity: vi.fn(async () => 'insufficient' as const),
        markReady: vi.fn(async () => undefined),
        remove: vi.fn(async () => undefined),
      },
    });
    await expect(controller.prepare()).rejects.toThrow('存储空间不足');
    expect(worker.messages).toHaveLength(0);
  });

  it('removes cached data and ignores late worker messages', async () => {
    const worker = new FakeWorker();
    const store = {
      inspect: vi.fn(async () => ({ ready: true, cachedBytes: 100 })),
      checkCapacity: vi.fn(async () => 'sufficient' as const),
      markReady: vi.fn(async () => undefined),
      remove: vi.fn(async () => undefined),
    };
    const controller = new OfflineWhisperControllerImpl({ createWorker: () => worker, store });
    await controller.check();
    await controller.remove();
    worker.emit({ type: 'ready', generation: 1, backend: 'wasm', cachedBytes: 100 });
    expect(store.remove).toHaveBeenCalledOnce();
    expect(controller.getState()).toEqual({ status: 'not_downloaded' });
  });
});
