// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import VoiceAnswerComposer, { type VoiceAnswerBrowser } from './VoiceAnswerComposer';
import type { SpeechRecognitionLike } from './voiceInterviewCapability';
import type { OfflineModelState, OfflineWhisperController } from './offlineWhisperTypes';
import type { VoiceCaptureFrame } from './voiceCaptureRuntime';

let root: Root | undefined;
let host: HTMLDivElement | undefined;

function click(label: string): void {
  const button = Array.from(host!.querySelectorAll<HTMLElement>('button,[role="radio"]'))
    .find((item) => item.textContent?.includes(label));
  if (!button) throw new Error(`missing button: ${label}`);
  act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
}

function changeTextarea(textarea: HTMLTextAreaElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set;
  if (!setter) throw new Error('missing textarea value setter');
  act(() => {
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function browserFixture(options: { local?: boolean; localState?: 'available' | 'downloadable' | 'downloading' | 'unavailable' } = {}) {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  const recorder = {
    state: 'inactive',
    ondataavailable: null as ((event: { data: Blob }) => void) | null,
    onstop: null as (() => void) | null,
    start: vi.fn(function start(this: typeof recorder) { this.state = 'recording'; }),
    pause: vi.fn(function pause(this: typeof recorder) { this.state = 'paused'; }),
    resume: vi.fn(function resume(this: typeof recorder) { this.state = 'recording'; }),
    stop: vi.fn(function stop(this: typeof recorder) {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) });
      this.onstop?.();
    }),
  };
  const recognition: SpeechRecognitionLike = {
    processLocally: false,
    lang: '',
    continuous: true,
    interimResults: false,
    onresult: null,
    onerror: null,
    onend: null,
    start: vi.fn(),
    stop: vi.fn(),
    abort: vi.fn(),
  };
  const SpeechRecognition = Object.assign(vi.fn(() => recognition), {
    available: vi.fn().mockResolvedValue(options.localState ?? (options.local ? 'available' : 'unavailable')),
    install: vi.fn().mockResolvedValue(true),
  });
  const utterances: Array<{ text: string; onend?: () => void; onerror?: () => void }> = [];
  const speechSynthesis = {
    speak: vi.fn((utterance: { text: string; onend?: () => void; onerror?: () => void }) => utterances.push(utterance)),
    cancel: vi.fn(),
    pause: vi.fn(function pause(this: { paused: boolean }) { this.paused = true; }),
    resume: vi.fn(function resume(this: { paused: boolean }) { this.paused = false; }),
    paused: false,
  };
  const browser: VoiceAnswerBrowser = {
    getUserMedia: vi.fn().mockResolvedValue(stream),
    createMediaRecorder: vi.fn(() => recorder),
    createObjectURL: vi.fn(() => 'blob:voice'),
    revokeObjectURL: vi.fn(),
    speechSynthesis,
    createUtterance: vi.fn((text) => ({ text })),
    SpeechRecognition: SpeechRecognition as never,
    now: vi.fn(() => 10_000),
  };
  return { browser, recorder, recognition, track, utterances, SpeechRecognition };
}

function offlineControllerFixture(state: OfflineModelState = {
  status: 'ready',
  modelVersion: 'test',
  cachedBytes: 100,
  backend: 'webgpu',
}): OfflineWhisperController {
  return {
    getState: () => state,
    subscribe: () => () => undefined,
    check: vi.fn(async () => undefined),
    prepare: vi.fn(async () => 'webgpu' as const),
    transcribe: vi.fn(async () => ({ text: '我先定位日志，再完成回滚。', backend: 'webgpu' as const })),
    cancel: vi.fn(),
    remove: vi.fn(async () => undefined),
    dispose: vi.fn(),
  };
}

async function renderComposer(overrides: Partial<React.ComponentProps<typeof VoiceAnswerComposer>> = {}, options = {}) {
  const fixture = browserFixture(options);
  const props: React.ComponentProps<typeof VoiceAnswerComposer> = {
    question: '请介绍一次你解决线上故障的经历。',
    disabled: false,
    submitRevision: 0,
    onConfirmTranscript: vi.fn(),
    onDirtyChange: vi.fn(),
    onActivityChange: vi.fn(),
    browser: fixture.browser,
    ...overrides,
  };
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root!.render(<VoiceAnswerComposer {...props} />); });
  return { ...fixture, props, rerender: async (next: Partial<typeof props>) => {
    await act(async () => { root!.render(<VoiceAnswerComposer {...props} {...next} />); });
  } };
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
});

afterEach(async () => {
  if (root) await act(async () => { root!.unmount(); });
  host?.remove();
  root = undefined;
  host = undefined;
  vi.useRealTimers();
});

describe('VoiceAnswerComposer', () => {
  it('reads the question aloud and cancels speech on unmount', async () => {
    const { browser, props } = await renderComposer();
    click('朗读题目');

    expect(browser.speechSynthesis.speak).toHaveBeenCalledTimes(1);
    expect(props.onActivityChange).toHaveBeenCalledWith('speaking');
    await act(async () => { root!.unmount(); root = undefined; });
    expect(browser.speechSynthesis.cancel).toHaveBeenCalled();
  });

  it('pauses, resumes and restarts question narration', async () => {
    const { browser } = await renderComposer();
    click('朗读题目');
    click('暂停朗读');
    expect(browser.speechSynthesis.pause).toHaveBeenCalledTimes(1);

    click('继续朗读');
    expect(browser.speechSynthesis.resume).toHaveBeenCalledTimes(1);

    click('重新朗读');
    expect(browser.speechSynthesis.cancel).toHaveBeenCalledTimes(2);
    expect(browser.speechSynthesis.speak).toHaveBeenCalledTimes(2);
  });

  it('records, pauses, resumes, stops and previews an answer without confirming it', async () => {
    const { browser, recorder, props } = await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    click('暂停');
    click('继续');
    await act(async () => { click('完成录音'); });

    expect(browser.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(recorder.pause).toHaveBeenCalled();
    expect(recorder.resume).toHaveBeenCalled();
    expect(host!.querySelector('audio')?.getAttribute('src')).toBe('blob:voice');
    expect(props.onConfirmTranscript).not.toHaveBeenCalled();
  });

  it('uses local-only recognition and confirms editable transcript explicitly', async () => {
    const { recognition, props } = await renderComposer({}, { local: true });
    click('语音回答');
    await act(async () => { click('开始录音'); });
    expect(recognition.processLocally).toBe(true);
    expect(recognition.start).toHaveBeenCalled();

    await act(async () => {
      recognition.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: '我先定位日志。' } }] });
    });
    const textarea = host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement;
    expect(textarea.value).toContain('我先定位日志');
    changeTextarea(textarea, '我先定位日志，再完成回滚。');
    click('确认使用这段文字');

    expect(props.onConfirmTranscript).toHaveBeenCalledWith('我先定位日志，再完成回滚。');
  });

  it('keeps manual transcription available when local recognition is unavailable', async () => {
    const { props } = await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { click('完成录音'); });

    expect(host!.textContent).toContain('本机转写不可用');
    const textarea = host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement;
    changeTextarea(textarea, '这是我核对后的手工文字。');
    click('确认使用这段文字');
    expect(props.onConfirmTranscript).toHaveBeenCalledWith('这是我核对后的手工文字。');
  });

  it('runs offline Whisper after recording and still requires explicit confirmation', async () => {
    const offlineController = offlineControllerFixture();
    const decodeAudio = vi.fn(async () => new Float32Array([0.1, 0.2]));
    const { props } = await renderComposer({ offlineController, decodeAudio });
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => {
      click('完成录音');
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(decodeAudio).toHaveBeenCalledOnce();
    expect(offlineController.transcribe).toHaveBeenCalledOnce();
    const textarea = host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement;
    expect(textarea.value).toBe('我先定位日志，再完成回滚。');
    expect(props.onConfirmTranscript).not.toHaveBeenCalled();
    click('确认使用这段文字');
    expect(props.onConfirmTranscript).toHaveBeenCalledWith('我先定位日志，再完成回滚。');
  });

  it('does not duplicate transcription when native local recognition already has text', async () => {
    const offlineController = offlineControllerFixture();
    const decodeAudio = vi.fn(async () => new Float32Array([0.1]));
    const { recognition } = await renderComposer({ offlineController, decodeAudio }, { local: true });
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => {
      recognition.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: '原生本地文字' } }] });
      click('完成录音');
      await Promise.resolve();
    });
    expect(decodeAudio).not.toHaveBeenCalled();
    expect(offlineController.transcribe).not.toHaveBeenCalled();
  });

  it('downloads an optional browser-managed local language pack only after consent', async () => {
    const { SpeechRecognition } = await renderComposer({}, { localState: 'downloadable' });
    click('语音回答');
    await act(async () => { await Promise.resolve(); });
    click('下载中文本机语言包');
    await act(async () => { await Promise.resolve(); });

    expect(SpeechRecognition.install).toHaveBeenCalledWith({ langs: ['zh-CN'] });
    expect(host!.textContent).toContain('本机转写已就绪');
  });

  it('freezes every answer control while the existing workflow is pending', async () => {
    await renderComposer({ disabled: true });
    const controls = [...host!.querySelectorAll<HTMLButtonElement | HTMLTextAreaElement>('button, textarea')];
    expect(controls.length).toBeGreaterThan(0);
    expect(controls.every((control) => control.disabled)).toBe(true);
  });

  it('never persists audio or invokes a network request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('unexpected network'));
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem');
    await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { click('完成录音'); });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
    storageSpy.mockRestore();
  });

  it('discards old audio and transcript before re-recording', async () => {
    const { browser } = await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { click('完成录音'); });
    const textarea = host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement;
    changeTextarea(textarea, '旧文字');
    await act(async () => { click('重录'); await Promise.resolve(); });

    expect(browser.revokeObjectURL).toHaveBeenCalledWith('blob:voice');
    expect(host!.querySelector('audio')).toBeNull();
    expect((host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement | null)?.value ?? '').toBe('');
  });

  it('falls back safely after microphone permission denial', async () => {
    const fixture = browserFixture();
    fixture.browser.getUserMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
    await renderComposer({ browser: fixture.browser });
    click('语音回答');
    await act(async () => { click('开始录音'); });

    expect(host!.textContent).toContain('未获得麦克风权限');
    expect(host!.textContent).toContain('文字回答仍可使用');
  });

  it('cleans tracks, object URLs and local recognition on unmount', async () => {
    const { browser, recognition, track } = await renderComposer({}, { local: true });
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { click('完成录音'); });
    await act(async () => { root!.unmount(); root = undefined; });

    expect(track.stop).toHaveBeenCalled();
    expect(recognition.abort).toHaveBeenCalled();
    expect(browser.revokeObjectURL).toHaveBeenCalledWith('blob:voice');
  });

  it('does not create a late object URL when unmounted during recording', async () => {
    const { browser, recorder, track } = await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { root!.unmount(); root = undefined; });

    expect(recorder.stop).toHaveBeenCalledTimes(1);
    expect(browser.createObjectURL).not.toHaveBeenCalled();
    expect(track.stop).toHaveBeenCalled();
  });

  it('clears audio only after a successful answer submission revision', async () => {
    const { browser, rerender } = await renderComposer();
    click('语音回答');
    await act(async () => { click('开始录音'); });
    await act(async () => { click('完成录音'); });
    await rerender({ submitRevision: 1 });

    expect(browser.revokeObjectURL).toHaveBeenCalledWith('blob:voice');
    expect(host!.querySelector('audio')).toBeNull();
  });

  it('shows local interim coaching, long-pause guidance and a review only after explicit confirmation', async () => {
    let frameCallback: ((frame: VoiceCaptureFrame) => void) | undefined;
    const captureRuntime = { batchOnly: false, pause: vi.fn(), resume: vi.fn(), dispose: vi.fn(async () => undefined) };
    const createCaptureRuntime = vi.fn(async (_stream, onFrame: (frame: VoiceCaptureFrame) => void) => {
      frameCallback = onFrame;
      return captureRuntime;
    });
    const offlineController = offlineControllerFixture();
    let now = 10_000;
    const fixture = browserFixture();
    fixture.browser.now = vi.fn(() => now);
    const { props } = await renderComposer({
      browser: fixture.browser,
      createCaptureRuntime,
      offlineController,
      decodeAudio: vi.fn(async () => new Float32Array([0.1, 0.2])),
    });

    click('语音回答');
    await act(async () => { click('开始录音'); await Promise.resolve(); });
    await act(async () => {
      frameCallback?.({ pcm: new Float32Array(12_800), sampleRate: 16_000, atMs: 0, durationMs: 800, rms: 0, peak: 0 });
      frameCallback?.({ pcm: new Float32Array(320_000).fill(0.08), sampleRate: 16_000, atMs: 800, durationMs: 20_000, rms: 0.08, peak: 0.08 });
      for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
    });
    expect(host!.textContent).toContain('临时字幕 · 仅供当前页面参考');
    await act(async () => {
      frameCallback?.({ pcm: new Float32Array(48_000), sampleRate: 16_000, atMs: 20_800, durationMs: 3_000, rms: 0, peak: 0 });
    });
    expect(host!.textContent).toContain('检测到停顿');
    expect(host!.textContent).toContain('可以继续，也可以完成回答');
    expect(props.onConfirmTranscript).not.toHaveBeenCalled();

    now = 82_000;
    await act(async () => { click('完成录音'); for (let turn = 0; turn < 8; turn += 1) await Promise.resolve(); });
    expect(captureRuntime.dispose).toHaveBeenCalledOnce();
    const textarea = host!.querySelector('textarea[aria-label="确认后的回答文字"]') as HTMLTextAreaElement;
    changeTextarea(textarea, '嗯我先定位日志，然后完成回滚。');
    click('确认使用这段文字');
    expect(props.onConfirmTranscript).toHaveBeenCalledOnce();
    expect(host!.textContent).toContain('表达节奏复盘');
    expect(host!.textContent).toContain('01:12');
  });

  it('stops at the five-minute boundary without confirming and keeps batch fallback explicit', async () => {
    let frameCallback: ((frame: VoiceCaptureFrame) => void) | undefined;
    const createCaptureRuntime = vi.fn(async (_stream, onFrame: (frame: VoiceCaptureFrame) => void) => {
      frameCallback = onFrame;
      return { batchOnly: true, pause: vi.fn(), resume: vi.fn(), dispose: vi.fn(async () => undefined) };
    });
    const { props, recorder } = await renderComposer({ createCaptureRuntime });
    click('语音回答');
    await act(async () => { click('开始录音'); await Promise.resolve(); });
    expect(host!.textContent).toContain('录完后批量转写');
    await act(async () => {
      frameCallback?.({ sampleRate: 16_000, atMs: 0, durationMs: 300_000, rms: 0.08, peak: 0.08 });
      await Promise.resolve();
    });
    expect(recorder.stop).toHaveBeenCalledOnce();
    expect(props.onConfirmTranscript).not.toHaveBeenCalled();
  });

  it('pauses local capture when the page becomes hidden', async () => {
    const captureRuntime = { batchOnly: false, pause: vi.fn(), resume: vi.fn(), dispose: vi.fn(async () => undefined) };
    const { recorder } = await renderComposer({
      createCaptureRuntime: vi.fn(async () => captureRuntime),
    });
    click('语音回答');
    await act(async () => { click('开始录音'); await Promise.resolve(); });

    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });

    expect(recorder.pause).toHaveBeenCalledOnce();
    expect(captureRuntime.pause).toHaveBeenCalledOnce();
    expect(host!.textContent).toContain('录音已暂停');
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  });

  it('resamples worklet PCM to the offline model sample rate', async () => {
    let frameCallback: ((frame: VoiceCaptureFrame) => void) | undefined;
    const offlineController = offlineControllerFixture();
    await renderComposer({
      offlineController,
      createCaptureRuntime: vi.fn(async (_stream, onFrame: (frame: VoiceCaptureFrame) => void) => {
        frameCallback = onFrame;
        return { batchOnly: false, pause: vi.fn(), resume: vi.fn(), dispose: vi.fn(async () => undefined) };
      }),
    });
    click('语音回答');
    await act(async () => { click('开始录音'); await Promise.resolve(); });

    await act(async () => {
      frameCallback?.({
        pcm: new Float32Array(48_000 * 20).fill(0.08),
        sampleRate: 48_000,
        atMs: 0,
        durationMs: 20_000,
        rms: 0.08,
        peak: 0.08,
      });
      for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
    });

    expect(offlineController.transcribe).toHaveBeenCalled();
    const pcm = vi.mocked(offlineController.transcribe).mock.calls[0][0];
    expect(pcm.length).toBe(320_000);
  });
});
