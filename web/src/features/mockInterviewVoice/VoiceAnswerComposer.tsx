import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Tag } from 'antd';
import {
  AudioOutlined,
  DeleteOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import {
  createLocalSpeechRecognition,
  detectVoiceInterviewCapabilities,
  ensureLocalSpeechLanguage,
  queryLocalSpeechLanguage,
  type LocalSpeechLanguageState,
  type SpeechRecognitionConstructorLike,
  type SpeechRecognitionLike,
} from './voiceInterviewCapability';
import { decodeAudioBlob } from './audioDecoder';
import OfflineWhisperModelCard from './OfflineWhisperModelCard';
import {
  offlineWhisperController,
  useOfflineWhisperState,
} from './offlineWhisperController';
import type { OfflineWhisperController } from './offlineWhisperTypes';
import styles from './VoiceAnswerComposer.module.css';

export type VoiceAnswerActivity = 'idle' | 'speaking' | 'listening' | 'transcribing' | 'success' | 'error';
type AnswerMode = 'text' | 'voice';

interface MediaRecorderLike {
  state: string;
  ondataavailable: ((event: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  start(): void;
  pause(): void;
  resume(): void;
  stop(): void;
}

interface SpeechSynthesisLike {
  speak(utterance: SpeechUtteranceLike): void;
  cancel(): void;
  pause(): void;
  resume(): void;
  paused: boolean;
}

interface SpeechUtteranceLike {
  text: string;
  lang?: string;
  rate?: number;
  onend?: () => void;
  onerror?: () => void;
}

export interface VoiceAnswerBrowser {
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createMediaRecorder?: (stream: MediaStream) => MediaRecorderLike;
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  speechSynthesis: SpeechSynthesisLike;
  speechSynthesisSupported?: boolean;
  createUtterance: (text: string) => SpeechUtteranceLike;
  SpeechRecognition?: SpeechRecognitionConstructorLike;
  now: () => number;
}

interface Props {
  question: string;
  disabled: boolean;
  textValue?: string;
  onTextChange?: (value: string) => void;
  submitRevision: number;
  onConfirmTranscript: (text: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onActivityChange?: (activity: VoiceAnswerActivity) => void;
  browser?: VoiceAnswerBrowser;
  offlineController?: OfflineWhisperController;
  decodeAudio?: (blob: Blob) => Promise<Float32Array>;
}

function defaultBrowser(): VoiceAnswerBrowser {
  const target = globalThis as typeof globalThis & {
    webkitSpeechRecognition?: SpeechRecognitionConstructorLike;
    SpeechRecognition?: SpeechRecognitionConstructorLike;
  };
  const unavailableSpeechSynthesis: SpeechSynthesisLike = {
    speak: () => undefined,
    cancel: () => undefined,
    pause: () => undefined,
    resume: () => undefined,
    paused: false,
  };
  const speechSynthesis = typeof window !== 'undefined' && window.speechSynthesis
    ? window.speechSynthesis as unknown as SpeechSynthesisLike
    : unavailableSpeechSynthesis;
  return {
    getUserMedia: (constraints) => navigator.mediaDevices?.getUserMedia
      ? navigator.mediaDevices.getUserMedia(constraints)
      : Promise.reject(new DOMException('Microphone unavailable', 'NotSupportedError')),
    createMediaRecorder: typeof MediaRecorder === 'function'
      ? (stream) => new MediaRecorder(stream) as unknown as MediaRecorderLike
      : undefined,
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    speechSynthesis,
    speechSynthesisSupported: typeof window !== 'undefined' && Boolean(window.speechSynthesis),
    createUtterance: (text) => typeof SpeechSynthesisUtterance === 'function'
      ? new SpeechSynthesisUtterance(text) as unknown as SpeechUtteranceLike
      : { text },
    SpeechRecognition: target.SpeechRecognition ?? target.webkitSpeechRecognition,
    now: () => Date.now(),
  };
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`;
}

export default function VoiceAnswerComposer({
  question,
  disabled,
  textValue = '',
  onTextChange,
  submitRevision,
  onConfirmTranscript,
  onDirtyChange,
  onActivityChange,
  browser: suppliedBrowser,
  offlineController = offlineWhisperController,
  decodeAudio = decodeAudioBlob,
}: Props) {
  const browser = useMemo(() => suppliedBrowser ?? defaultBrowser(), [suppliedBrowser]);
  const capabilities = useMemo(() => detectVoiceInterviewCapabilities({
    MediaRecorder: browser.createMediaRecorder,
    speechSynthesis: browser.speechSynthesisSupported === false ? undefined : browser.speechSynthesis,
    SpeechRecognition: browser.SpeechRecognition,
  }), [browser]);
  const [mode, setMode] = useState<AnswerMode>('text');
  const [narrationState, setNarrationState] = useState<'idle' | 'speaking' | 'paused'>('idle');
  const [recordingState, setRecordingState] = useState<'idle' | 'recording' | 'paused' | 'ready'>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [localLanguageState, setLocalLanguageState] = useState<LocalSpeechLanguageState>('unavailable');
  const [error, setError] = useState<string | null>(null);
  const [transcriptionStatus, setTranscriptionStatus] = useState<'idle' | 'decoding' | 'transcribing' | 'success' | 'error'>('idle');
  const offlineModelState = useOfflineWhisperState(offlineController);
  const recorderRef = useRef<MediaRecorderLike>();
  const streamRef = useRef<MediaStream>();
  const recognitionRef = useRef<SpeechRecognitionLike>();
  const chunksRef = useRef<Blob[]>([]);
  const audioBlobRef = useRef<Blob>();
  const transcriptRef = useRef('');
  const transcriptionGenerationRef = useRef(0);
  const activeTranscriptionRef = useRef(false);
  const recognitionSettleRef = useRef<(() => void) | undefined>();
  const intervalRef = useRef<number>();
  const activityTimeoutRef = useRef<number>();
  const latestAudioUrlRef = useRef<string | null>(null);
  const disposedRef = useRef(false);

  const emitActivity = (activity: VoiceAnswerActivity) => onActivityChange?.(activity);

  const clearTimer = () => {
    if (intervalRef.current !== undefined) window.clearInterval(intervalRef.current);
    intervalRef.current = undefined;
  };

  const clearActivityTimeout = () => {
    if (activityTimeoutRef.current !== undefined) window.clearTimeout(activityTimeoutRef.current);
    activityTimeoutRef.current = undefined;
  };

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = undefined;
  };

  const clearAudio = () => {
    const currentUrl = latestAudioUrlRef.current;
    if (currentUrl) browser.revokeObjectURL(currentUrl);
    latestAudioUrlRef.current = null;
    setAudioUrl(null);
    audioBlobRef.current = undefined;
    chunksRef.current = [];
  };

  const resetVoiceDraft = () => {
    clearTimer();
    stopStream();
    recognitionRef.current?.abort();
    recognitionRef.current = undefined;
    clearAudio();
    setRecordingState('idle');
    setElapsed(0);
    setTranscript('');
    transcriptRef.current = '';
    setInterimTranscript('');
    setTranscriptionStatus('idle');
    transcriptionGenerationRef.current += 1;
    if (activeTranscriptionRef.current) offlineController.cancel();
    activeTranscriptionRef.current = false;
    setError(null);
    clearActivityTimeout();
    onDirtyChange?.(false);
    emitActivity('idle');
  };

  useEffect(() => {
    let active = true;
    void queryLocalSpeechLanguage(browser.SpeechRecognition, 'zh-CN').then((state) => {
      if (active) setLocalLanguageState(state);
    });
    return () => { active = false; };
  }, [browser]);

  useEffect(() => {
    if (submitRevision > 0) resetVoiceDraft();
    // submitRevision is a monotonic success signal; browser callbacks are stable for one mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitRevision]);

  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      clearTimer();
      clearActivityTimeout();
      browser.speechSynthesis.cancel();
      try { recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop(); } catch { /* cleanup only */ }
      recognitionRef.current?.abort();
      stopStream();
      const currentUrl = latestAudioUrlRef.current;
      if (currentUrl) browser.revokeObjectURL(currentUrl);
      onActivityChange?.('idle');
      transcriptionGenerationRef.current += 1;
      if (activeTranscriptionRef.current) offlineController.cancel();
      activeTranscriptionRef.current = false;
    };
  }, [browser, onActivityChange]);

  useEffect(() => {
    onDirtyChange?.(Boolean(audioUrl || transcript.trim() || recordingState !== 'idle'));
  }, [audioUrl, onDirtyChange, recordingState, transcript]);

  const readQuestion = () => {
    if (!capabilities.speechSynthesis || disabled || recordingState === 'recording' || recordingState === 'paused') return;
    browser.speechSynthesis.cancel();
    const utterance = browser.createUtterance(question);
    utterance.lang = 'zh-CN';
    utterance.rate = 0.94;
    utterance.onend = () => {
      setNarrationState('idle');
      emitActivity('idle');
    };
    utterance.onerror = () => {
      setNarrationState('idle');
      setError('当前浏览器无法朗读题目，你仍可阅读题目并继续回答。');
      emitActivity('error');
    };
    setNarrationState('speaking');
    emitActivity('speaking');
    browser.speechSynthesis.speak(utterance);
  };

  const pauseQuestion = () => {
    browser.speechSynthesis.pause();
    setNarrationState('paused');
    emitActivity('idle');
  };

  const resumeQuestion = () => {
    browser.speechSynthesis.resume();
    setNarrationState('speaking');
    emitActivity('speaking');
  };

  const startRecognition = () => {
    if (localLanguageState !== 'available' || !browser.SpeechRecognition) return;
    const recognition = createLocalSpeechRecognition(browser.SpeechRecognition, 'zh-CN');
    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += result[0].transcript;
        else interimText += result[0].transcript;
      }
      if (finalText.trim()) setTranscript((current) => {
        const next = `${current}${current ? ' ' : ''}${finalText.trim()}`;
        transcriptRef.current = next;
        return next;
      });
      setInterimTranscript(interimText.trim());
    };
    recognition.onerror = () => {
      setLocalLanguageState('unavailable');
      setError('本机转写没有完成，录音仍在，可试听后手工整理文字。');
    };
    recognition.onend = () => recognitionSettleRef.current?.();
    recognitionRef.current = recognition;
    try { recognition.start(); } catch { setLocalLanguageState('unavailable'); }
  };

  const runOfflineTranscription = async (blob: Blob) => {
    if (transcriptRef.current.trim()) return;
    if (offlineController.getState().status !== 'ready') {
      setTranscriptionStatus('idle');
      emitActivity('idle');
      return;
    }
    const generation = ++transcriptionGenerationRef.current;
    activeTranscriptionRef.current = true;
    setError(null);
    setTranscriptionStatus('decoding');
    emitActivity('transcribing');
    try {
      const pcm = await decodeAudio(blob);
      if (generation !== transcriptionGenerationRef.current || disposedRef.current) return;
      setTranscriptionStatus('transcribing');
      const result = await offlineController.transcribe(pcm);
      if (generation !== transcriptionGenerationRef.current || disposedRef.current) return;
      transcriptRef.current = result.text;
      setTranscript(result.text);
      setInterimTranscript('');
      setTranscriptionStatus('success');
      activeTranscriptionRef.current = false;
      emitActivity('success');
    } catch (transcriptionError) {
      if (generation !== transcriptionGenerationRef.current || disposedRef.current) return;
      setTranscriptionStatus('error');
      activeTranscriptionRef.current = false;
      setError(transcriptionError instanceof Error
        ? `${transcriptionError.message}。录音仍在，可重新转写或手工整理文字。`
        : '离线转写失败。录音仍在，可重新转写或手工整理文字。');
      emitActivity('error');
    }
  };

  const startRecording = async () => {
    if (!capabilities.recorder || disabled) return;
    browser.speechSynthesis.cancel();
    setNarrationState('idle');
    setError(null);
    clearAudio();
    setTranscript('');
    transcriptRef.current = '';
    setInterimTranscript('');
    setTranscriptionStatus('idle');
    try {
      const stream = await browser.getUserMedia({ audio: true });
      if (disposedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      const recorder = browser.createMediaRecorder!(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        if (disposedRef.current) {
          chunksRef.current = [];
          return;
        }
        const blob = new Blob(chunksRef.current, { type: chunksRef.current[0]?.type || 'audio/webm' });
        audioBlobRef.current = blob;
        const url = browser.createObjectURL(blob);
        latestAudioUrlRef.current = url;
        setAudioUrl(url);
        setRecordingState('ready');
        clearTimer();
        stopStream();
        const recognition = recognitionRef.current;
        if (recognition) {
          let settled = false;
          const continueAfterRecognition = () => {
            if (settled) return;
            settled = true;
            recognitionSettleRef.current = undefined;
            void runOfflineTranscription(blob);
          };
          recognitionSettleRef.current = continueAfterRecognition;
          recognition.stop();
          window.setTimeout(continueAfterRecognition, 350);
        } else {
          void runOfflineTranscription(blob);
        }
      };
      recorder.start();
      startRecognition();
      setElapsed(0);
      setRecordingState('recording');
      emitActivity('listening');
      intervalRef.current = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    } catch {
      stopStream();
      setRecordingState('idle');
      setError('未获得麦克风权限。文字回答仍可使用，也可以在浏览器设置中稍后允许。');
      emitActivity('error');
    }
  };

  const pauseRecording = () => {
    recorderRef.current?.pause();
    recognitionRef.current?.stop();
    clearTimer();
    setRecordingState('paused');
    emitActivity('idle');
  };

  const resumeRecording = () => {
    recorderRef.current?.resume();
    startRecognition();
    intervalRef.current = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    setRecordingState('recording');
    emitActivity('listening');
  };

  const stopRecording = () => recorderRef.current?.stop();

  const installLanguage = async () => {
    if (!browser.SpeechRecognition) return;
    setLocalLanguageState('downloading');
    const installed = await ensureLocalSpeechLanguage(browser.SpeechRecognition, 'zh-CN');
    setLocalLanguageState(installed ? 'available' : 'unavailable');
    if (!installed) setError('中文本机语言包下载失败。录音与手工输入仍可使用。');
  };

  const confirmTranscript = () => {
    const confirmed = transcript.trim();
    if (!confirmed || disabled) return;
    onConfirmTranscript(confirmed);
    emitActivity('success');
  };

  const cancelTranscription = () => {
    transcriptionGenerationRef.current += 1;
    offlineController.cancel();
    activeTranscriptionRef.current = false;
    setTranscriptionStatus('idle');
    emitActivity('idle');
  };

  const localLabel = localLanguageState === 'available'
    ? '本机转写已就绪'
    : localLanguageState === 'downloadable'
      ? '可下载中文本机语言包'
      : localLanguageState === 'downloading'
        ? '正在下载本机语言包'
      : '本机转写不可用';

  const changeMode = (nextMode: AnswerMode) => {
    setMode(nextMode);
    if (nextMode === 'text') emitActivity('idle');
  };

  return (
    <section className={styles.composer} aria-label="回答方式" data-testid="voice-answer-composer">
      <div className={styles.modeHeader}>
        <div>
          <span className={styles.eyebrow}>ANSWER STUDIO</span>
          <h4>选择你的回答方式</h4>
        </div>
        <div className={styles.modeSwitch} role="group" aria-label="回答方式">
          {(['text', 'voice'] as AnswerMode[]).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              disabled={disabled || recordingState === 'recording' || recordingState === 'paused'}
              onClick={() => changeMode(value)}
            >
              {value === 'text' ? '文字回答' : '语音回答'}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.readingBar}>
        <div>
          <SoundOutlined aria-hidden />
          <span>由系统音色朗读当前题目</span>
        </div>
        <div className={styles.readingActions}>
          {narrationState === 'idle' ? (
            <Button icon={<PlayCircleOutlined />} onClick={readQuestion} disabled={disabled || !capabilities.speechSynthesis || recordingState === 'recording' || recordingState === 'paused'}>
              朗读题目
            </Button>
          ) : null}
          {narrationState === 'speaking' ? (
            <Button icon={<PauseOutlined />} onClick={pauseQuestion} disabled={disabled}>暂停朗读</Button>
          ) : null}
          {narrationState === 'paused' ? (
            <Button icon={<PlayCircleOutlined />} onClick={resumeQuestion} disabled={disabled}>继续朗读</Button>
          ) : null}
          {narrationState !== 'idle' ? (
            <Button onClick={readQuestion} disabled={disabled}>重新朗读</Button>
          ) : null}
        </div>
      </div>

      {error ? <Alert showIcon type="warning" message={error} /> : null}

      {mode === 'voice' ? (
        <div className={styles.voiceStage}>
          <div className={styles.voiceStatus} data-state={recordingState}>
            <div className={styles.micOrb}><AudioOutlined /></div>
            <div className={styles.voiceCopy}>
              <strong>{recordingState === 'recording' ? '正在聆听你的回答' : recordingState === 'paused' ? '录音已暂停' : audioUrl ? '回答录音已就绪' : '准备好后开始录音'}</strong>
              <span>{audioUrl ? '先试听，再核对下方文字；系统不会保存原始录音。' : '录音仅保存在当前页面，未确认文字不会进入模拟面试。'}</span>
            </div>
            <span className={styles.timer}>{formatElapsed(elapsed)}</span>
          </div>

          <div className={styles.controls}>
            {recordingState === 'idle' ? (
              <Button type="primary" icon={<AudioOutlined />} onClick={() => void startRecording()} disabled={disabled || !capabilities.recorder}>开始录音</Button>
            ) : null}
            {recordingState === 'recording' ? (
              <>
                <Button icon={<PauseOutlined />} onClick={pauseRecording} disabled={disabled}>暂停</Button>
                <Button type="primary" onClick={stopRecording} disabled={disabled}>完成录音</Button>
              </>
            ) : null}
            {recordingState === 'paused' ? (
              <>
                <Button icon={<PlayCircleOutlined />} onClick={resumeRecording} disabled={disabled}>继续</Button>
                <Button type="primary" onClick={stopRecording} disabled={disabled}>完成录音</Button>
              </>
            ) : null}
            {audioUrl ? (
              <Button icon={<DeleteOutlined />} onClick={resetVoiceDraft} disabled={disabled}>重录</Button>
            ) : null}
          </div>

          {audioUrl ? <audio className={styles.audio} src={audioUrl} controls preload="metadata" /> : null}

          <div className={styles.transcriptPanel}>
            <div className={styles.transcriptHeader}>
              <div>
                <span className={styles.eyebrow}>TRANSCRIPT CHECK</span>
                <h4>核对回答文字</h4>
              </div>
              <Tag color={localLanguageState === 'available' ? 'green' : 'default'}>{localLabel}</Tag>
            </div>
            {localLanguageState === 'downloadable' ? (
              <Button onClick={() => void installLanguage()} disabled={disabled}>下载中文本机语言包</Button>
            ) : null}
            <OfflineWhisperModelCard controller={offlineController} compact />
            {transcriptionStatus === 'decoding' || transcriptionStatus === 'transcribing' ? (
              <div className={styles.offlineTranscriptionStatus} role="status" aria-live="polite">
                <div>
                  <strong>{transcriptionStatus === 'decoding' ? '正在整理录音格式' : '正在本地整理语音'}</strong>
                  <span>{offlineModelState.status === 'transcribing' && offlineModelState.backend === 'wasm' ? '兼容模式' : 'GPU 加速优先'}</span>
                </div>
                <Button onClick={cancelTranscription}>取消转写</Button>
              </div>
            ) : null}
            {audioUrl && transcriptionStatus !== 'decoding' && transcriptionStatus !== 'transcribing' && !transcript.trim() && offlineModelState.status === 'ready' ? (
              <Button onClick={() => audioBlobRef.current && void runOfflineTranscription(audioBlobRef.current)} disabled={disabled}>
                使用离线模型转写
              </Button>
            ) : null}
            <Input.TextArea
              aria-label="确认后的回答文字"
              value={`${transcript}${interimTranscript ? `${transcript ? ' ' : ''}${interimTranscript}` : ''}`}
              onChange={(event) => {
                transcriptRef.current = event.target.value;
                setTranscript(event.target.value);
                setInterimTranscript('');
              }}
              disabled={disabled}
              placeholder="本机或离线转写不可用时，可试听录音后在这里手工整理回答。"
              autoSize={{ minRows: 5, maxRows: 10 }}
            />
            <div className={styles.confirmRow}>
              <span>只有确认后的文字才会交给模拟面试。</span>
              <Button type="primary" onClick={confirmTranscript} disabled={disabled || !transcript.trim()}>
                确认使用这段文字
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className={styles.textPanel}>
          <div className={styles.textHint}>直接输入回答；语音能力不会改变现有文本提交流程。</div>
          <Input.TextArea
            aria-label="回答"
            value={textValue}
            onChange={(event) => onTextChange?.(event.target.value)}
            disabled={disabled}
            placeholder="输入你的回答"
            autoSize={{ minRows: 5, maxRows: 10 }}
          />
        </div>
      )}
    </section>
  );
}
