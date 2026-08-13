import { describe, expect, it, vi } from 'vitest';
import { createVoiceCaptureRuntime, type VoiceCaptureRuntimeDependencies } from './voiceCaptureRuntime';

function fixture(options: { worklet?: 'ok' | 'fail'; sourceFails?: boolean } = {}) {
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const analyser = {
    fftSize: 0,
    connect: vi.fn(),
    disconnect: vi.fn(),
    getFloatTimeDomainData: vi.fn((values: Float32Array) => values.fill(0.1)),
  };
  const port = { onmessage: null as ((event: MessageEvent) => void) | null };
  const worklet = { port, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    sampleRate: 16_000,
    currentTime: 1,
    audioWorklet: options.worklet ? {
      addModule: options.worklet === 'ok' ? vi.fn(async () => undefined) : vi.fn(async () => { throw new Error('blocked'); }),
    } : undefined,
    createMediaStreamSource: vi.fn(() => {
      if (options.sourceFails) throw new Error('source failed');
      return source;
    }),
    createAnalyser: vi.fn(() => analyser),
    close: vi.fn(async () => undefined),
  };
  let animationCallback: FrameRequestCallback | undefined;
  const dependencies: VoiceCaptureRuntimeDependencies = {
    createAudioContext: vi.fn(() => context),
    createWorkletNode: vi.fn(() => worklet),
    requestFrame: vi.fn((callback) => { animationCallback = callback; return 4; }),
    cancelFrame: vi.fn(),
    now: vi.fn(() => 1_000),
    workletUrl: 'local-worklet.js',
  };
  return { dependencies, context, source, analyser, worklet, port, runFrame: () => animationCallback?.(0) };
}

describe('voice capture runtime', () => {
  it('prefers AudioWorklet and forwards local PCM without network access', async () => {
    const target = fixture({ worklet: 'ok' });
    const frames = vi.fn();
    const runtime = await createVoiceCaptureRuntime({} as MediaStream, frames, target.dependencies);
    expect(runtime.batchOnly).toBe(false);
    expect(target.context.audioWorklet?.addModule).toHaveBeenCalledWith('local-worklet.js');
    const pcm = new Float32Array([0.1, -0.2]);
    target.port.onmessage?.({ data: { pcm, atMs: 12, durationMs: 0.125, rms: 0.15, peak: 0.2 } } as MessageEvent);
    expect(frames).toHaveBeenCalledWith(expect.objectContaining({ pcm, atMs: 12, sampleRate: 16_000 }));
    await runtime.dispose();
    expect(target.worklet.disconnect).toHaveBeenCalledOnce();
    expect(target.context.close).toHaveBeenCalledOnce();
  });

  it('falls back to analyser batch mode and emits levels', async () => {
    const target = fixture({ worklet: 'fail' });
    const frames = vi.fn();
    const runtime = await createVoiceCaptureRuntime({} as MediaStream, frames, target.dependencies);
    expect(runtime.batchOnly).toBe(true);
    target.runFrame();
    const emitted = frames.mock.calls[0][0] as { rms: number; peak: number; sampleRate: number };
    expect(emitted.rms).toBeCloseTo(0.1);
    expect(emitted.peak).toBeCloseTo(0.1);
    expect(emitted.sampleRate).toBe(16_000);
    await runtime.dispose();
    expect(target.dependencies.cancelFrame).toHaveBeenCalledWith(4);
    expect(target.analyser.disconnect).toHaveBeenCalledOnce();
  });

  it('cleans a partially initialized context when source setup fails', async () => {
    const target = fixture({ sourceFails: true });
    await expect(createVoiceCaptureRuntime({} as MediaStream, vi.fn(), target.dependencies)).rejects.toThrow('source failed');
    expect(target.context.close).toHaveBeenCalledOnce();
  });
});
