/**
 * 16 §2t item 3: the old booth page's audio, ported.
 *
 * Capture runs on the audio thread through `public/mic-worklet.js` (§2r item 4),
 * at 16 kHz Int16 frames of 1600 samples. Playback is THE HOST's voice, played
 * in this page. The level meters feed the orb and the ?debug=mic readout.
 *
 * The device ids come from the Start screen's two drop-downs (§2t item 4);
 * `undefined` means the system default, which is what the old booth page always had.
 */
import { C } from "./constants";

/**
 * 16 §2u item 4: what the debug playback line reports.
 *
 * `maxLateMs` is the worst lateness seen in the window: how long after the
 * previous chunk's audio ended the next chunk could first be scheduled. Zero
 * means playback was continuous -- each chunk was already queued behind the one
 * before it. `underruns` counts the chunks whose lateness passed
 * PLAYBACK_UNDERRUN_MS, which is audible as THE HOST's voice breaking up.
 */
export interface PlaybackStats {
  chunks: number;
  maxLateMs: number;
  underruns: number;
}

export interface AudioPort {
  init(): Promise<void>;
  probeMic(deviceId?: string): Promise<boolean>;
  startMic(onFrame: (frame: ArrayBuffer) => void, deviceId?: string): Promise<void>;
  stopMic(): void;
  playPcm(buffer: ArrayBuffer): void;
  flushPlayback(): void;
  isPlaying(): boolean;
  getMicAmp(): number;
  getPlaybackAmp(): number;
  /**
   * 16 §2u item 4: the turn is over, so the silence until THE HOST speaks again
   * is a guest talking rather than starved playback. Does not stop any audio
   * that is still playing out -- a turn ends at the backend long before the last
   * chunk of it has been heard.
   */
  endPlaybackTurn(): void;
  /** Reads the counters for the last window and starts a fresh one. */
  takePlaybackStats(): PlaybackStats;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

let playCtx: AudioContext | null = null;
let capCtx: AudioContext | null = null;
let master: GainNode | null = null;
let nextPlayTime = 0;
let envelope: { start: number; end: number; amp: number }[] = [];
const active = new Set<AudioBufferSourceNode>();
let micAmp = 0;
let stream: MediaStream | null = null;
let src: MediaStreamAudioSourceNode | null = null;
let proc: AudioWorkletNode | null = null;
let mute: GainNode | null = null;
let workletReady = false;
// 16 §2u item 4: the playback meter. `turnEndAt` is where the previous chunk of
// THIS turn finished, in the playback context's own clock; null means the turn
// has no chunk before this one, so there is nothing to be late against.
let turnEndAt: number | null = null;
let stats: PlaybackStats = { chunks: 0, maxLateMs: 0, underruns: 0 };

export const audio: AudioPort = {
  async init() {
    if (playCtx && capCtx) {
      await playCtx.resume();
      await capCtx.resume();
      return;
    }
    playCtx = new AudioContext({ sampleRate: C.OUTPUT_SAMPLE_RATE });
    capCtx = new AudioContext();
    // The worklet module is registered against a context, so a fresh capture
    // context needs it added again.
    workletReady = false;
    await playCtx.resume();
    await capCtx.resume();
    master = playCtx.createGain();
    master.connect(playCtx.destination);
    nextPlayTime = 0;
  },

  async probeMic(deviceId?: string) {
    try {
      const probe = await navigator.mediaDevices.getUserMedia({
        audio: deviceId ? { deviceId: { exact: deviceId } } : true,
      });
      probe.getTracks().forEach((track) => track.stop());
      return true;
    } catch {
      return false;
    }
  },

  async startMic(onFrame: (frame: ArrayBuffer) => void, deviceId?: string) {
    if (!capCtx) throw new Error("Audio capture is not initialized.");
    this.stopMic();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      },
    });
    // 16 §2r item 4: capture runs on the audio thread. The module is added once
    // per capture context; a second addModule for the same URL is harmless but
    // pointless. The worklet is served from the dashboard's own public/ (§2t
    // item 3), so this path is absolute rather than relative to a module.
    if (!workletReady) {
      await capCtx.audioWorklet.addModule("/mic-worklet.js");
      workletReady = true;
    }

    src = capCtx.createMediaStreamSource(stream);
    // One frame is 1600 samples at 16 kHz, about 100 ms. The worklet gathers
    // the matching number of samples at the capture device's own rate so the
    // downsampler below yields exactly that.
    const frameRatio = capCtx.sampleRate / C.INPUT_SAMPLE_RATE;
    proc = new AudioWorkletNode(capCtx, "mic-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: {
        blockSamples: Math.round(C.MIC_FRAME_SAMPLES * frameRatio),
      },
    });
    // The silent path to the destination is kept from the ScriptProcessorNode
    // days: it is what guarantees the graph is pulled, and at gain 0 nothing
    // of the guest's voice is ever played back into the room.
    mute = capCtx.createGain();
    mute.gain.value = 0;
    src.connect(proc);
    proc.connect(mute);
    mute.connect(capCtx.destination);

    proc.port.onmessage = (event: MessageEvent<Float32Array>) => {
      const input = event.data;
      let squares = 0;
      for (let i = 0; i < input.length; i += 1) squares += input[i]! * input[i]!;
      const rms = input.length ? Math.sqrt(squares / input.length) : 0;
      micAmp = clamp(rms * 6, 0, 1);

      const ratio = capCtx!.sampleRate / C.INPUT_SAMPLE_RATE;
      const outLength = Math.floor(input.length / ratio);
      const output = new Int16Array(outLength);
      for (let i = 0; i < outLength; i += 1) {
        const start = Math.floor(i * ratio);
        const end = Math.floor((i + 1) * ratio);
        let total = 0;
        for (let j = start; j < end; j += 1) total += input[j]!;
        const average = end > start ? total / (end - start) : 0;
        const sample = clamp(average, -1, 1);
        output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      onFrame(output.buffer);
    };
  },

  stopMic() {
    if (src) {
      try {
        src.disconnect();
      } catch {
        /* already gone */
      }
    }
    if (proc) {
      proc.port.onmessage = null;
      try {
        proc.port.close();
      } catch {
        /* already gone */
      }
      try {
        proc.disconnect();
      } catch {
        /* already gone */
      }
    }
    if (mute) {
      try {
        mute.disconnect();
      } catch {
        /* already gone */
      }
    }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    src = null;
    proc = null;
    mute = null;
    micAmp = 0;
  },

  playPcm(arrayBuffer: ArrayBuffer) {
    if (!playCtx || !master) return;
    const byteLength = arrayBuffer.byteLength - (arrayBuffer.byteLength % 2);
    if (byteLength === 0) return;
    const i16 = new Int16Array(arrayBuffer, 0, byteLength / 2);
    const f32 = new Float32Array(i16.length);
    let squares = 0;
    for (let i = 0; i < i16.length; i += 1) {
      f32[i] = i16[i]! / 32768;
      squares += f32[i]! * f32[i]!;
    }
    const rms = f32.length ? Math.sqrt(squares / f32.length) : 0;
    const amp = clamp(rms * 3, 0, 1);
    const buffer = playCtx.createBuffer(1, f32.length, C.OUTPUT_SAMPLE_RATE);
    buffer.copyToChannel(f32, 0);
    const node = playCtx.createBufferSource();
    node.buffer = buffer;
    node.connect(master);
    const startAt = Math.max(nextPlayTime, playCtx.currentTime + 0.02);
    const endAt = startAt + buffer.duration;
    node.start(startAt);
    nextPlayTime = endAt;
    envelope.push({ start: startAt, end: endAt, amp });
    active.add(node);
    node.onended = () => active.delete(node);

    // 16 §2u item 4: measure, in the same clock the audio is scheduled on. A
    // chunk that had to be pushed past the previous one's end is a gap the guest
    // hears -- THE HOST's voice breaking up between words.
    stats.chunks += 1;
    if (turnEndAt !== null) {
      const lateMs = Math.max(0, (startAt - turnEndAt) * 1000);
      if (lateMs > stats.maxLateMs) stats.maxLateMs = lateMs;
      if (lateMs > C.PLAYBACK_UNDERRUN_MS) stats.underruns += 1;
    }
    turnEndAt = endAt;
  },

  endPlaybackTurn() {
    turnEndAt = null;
  },

  takePlaybackStats() {
    const taken = stats;
    stats = { chunks: 0, maxLateMs: 0, underruns: 0 };
    return taken;
  },

  flushPlayback() {
    for (const node of active) {
      try {
        node.stop();
      } catch {
        /* already finished */
      }
    }
    active.clear();
    nextPlayTime = 0;
    envelope.length = 0;
    // Nothing of this turn is left to be late against.
    turnEndAt = null;
  },

  isPlaying() {
    // 16 §2g item 2: THE HOST's reply arrives far faster than it plays,
    // so "scheduled audio is still to come" is what the idle clock must see.
    return Boolean(playCtx) && nextPlayTime > playCtx!.currentTime;
  },

  getMicAmp() {
    return micAmp;
  },

  getPlaybackAmp() {
    if (!playCtx) return 0;
    const now = playCtx.currentTime;
    envelope = envelope.filter((item) => item.end >= now - 0.5);
    const item = envelope.find((entry) => entry.start <= now && now < entry.end);
    return item ? item.amp : 0;
  },
};
