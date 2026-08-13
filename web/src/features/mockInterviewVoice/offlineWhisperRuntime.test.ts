import { describe, expect, it, vi } from 'vitest';
import { OfflineWhisperRuntime } from './offlineWhisperRuntime';

function pipeline(text = '转写结果') {
  return Object.assign(vi.fn(async () => ({ text })), { dispose: vi.fn(async () => undefined) });
}

describe('OfflineWhisperRuntime', () => {
  it('falls back from WebGPU to WASM exactly once', async () => {
    const wasm = pipeline();
    const createPipeline = vi.fn(async (backend: 'webgpu' | 'wasm') => {
      if (backend === 'webgpu') throw new Error('GPU unavailable');
      return wasm;
    });
    const runtime = new OfflineWhisperRuntime({ createPipeline });
    await expect(runtime.prepare('webgpu')).resolves.toBe('wasm');
    expect(createPipeline.mock.calls.map(([backend]) => backend)).toEqual(['webgpu', 'wasm']);
  });

  it('rebuilds once on WebGPU inference failure and returns normalized text', async () => {
    const webgpu = pipeline();
    webgpu.mockRejectedValueOnce(new Error('device lost'));
    const wasm = pipeline('  我负责了稳定性治理。  ');
    const createPipeline = vi.fn(async (backend: 'webgpu' | 'wasm') => backend === 'webgpu' ? webgpu : wasm);
    const runtime = new OfflineWhisperRuntime({ createPipeline });
    await runtime.prepare('webgpu');
    await expect(runtime.transcribe(new Float32Array([0.1]))).resolves.toEqual({ text: '我负责了稳定性治理。', backend: 'wasm' });
    expect(webgpu.dispose).toHaveBeenCalledOnce();
    expect(createPipeline).toHaveBeenCalledTimes(2);
  });

  it('disposes partial resources after terminal failure', async () => {
    const broken = pipeline();
    broken.mockRejectedValue(new Error('failed'));
    const runtime = new OfflineWhisperRuntime({ createPipeline: vi.fn(async () => broken) });
    await runtime.prepare('wasm');
    await expect(runtime.transcribe(new Float32Array([0.1]))).rejects.toThrow('failed');
    await runtime.dispose();
    expect(broken.dispose).toHaveBeenCalledOnce();
  });
});
