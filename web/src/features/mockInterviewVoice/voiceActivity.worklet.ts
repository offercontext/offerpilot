declare const currentTime: number;
declare const sampleRate: number;
declare function registerProcessor(name: string, processor: new (options?: { processorOptions?: { frameSamples?: number } }) => {
  process(inputs: Float32Array[][]): boolean;
}): void;
declare class AudioWorkletProcessor {
  readonly port: { postMessage(message: unknown, transfer?: Transferable[]): void };
}

class OfferPilotVoiceActivityProcessor extends AudioWorkletProcessor {
  private readonly frameSamples: number;
  private pending: number[] = [];

  constructor(options?: { processorOptions?: { frameSamples?: number } }) {
    super();
    this.frameSamples = Math.max(160, options?.processorOptions?.frameSamples ?? 320);
  }

  process(inputs: Float32Array[][]): boolean {
    const channels = inputs[0];
    const source = channels?.[0];
    if (!source) return true;
    for (const sample of source) this.pending.push(Number.isFinite(sample) ? sample : 0);
    while (this.pending.length >= this.frameSamples) {
      const pcm = new Float32Array(this.pending.splice(0, this.frameSamples));
      let squares = 0;
      let peak = 0;
      for (const sample of pcm) {
        squares += sample * sample;
        peak = Math.max(peak, Math.abs(sample));
      }
      const durationMs = pcm.length / sampleRate * 1_000;
      this.port.postMessage({
        pcm,
        atMs: currentTime * 1_000 - durationMs,
        durationMs,
        rms: Math.sqrt(squares / pcm.length),
        peak,
      }, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor('offerpilot-voice-activity', OfferPilotVoiceActivityProcessor);
