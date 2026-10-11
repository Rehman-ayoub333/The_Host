import { C } from "./constants.js";

let playCtx = null;
let capCtx = null;
let master = null;
let nextPlayTime = 0;
let envelope = [];
let active = new Set();
let micAmp = 0;
let stream = null;
let src = null;
let proc = null;
let mute = null;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export const audio = {
  async init() {
    if (playCtx && capCtx) {
      await playCtx.resume();
      await capCtx.resume();
      return;
    }
    playCtx = new AudioContext({ sampleRate: C.OUTPUT_SAMPLE_RATE });
    capCtx = new AudioContext();
    await playCtx.resume();
    await capCtx.resume();
    master = playCtx.createGain();
    master.connect(playCtx.destination);
    nextPlayTime = 0;
  },

  async probeMic() {
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
      probe.getTracks().forEach((track) => track.stop());
      return true;
    } catch {
      return false;
    }
  },

  async startMic(onFrame) {
    if (!capCtx) throw new Error("Audio capture is not initialized.");
    this.stopMic();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    src = capCtx.createMediaStreamSource(stream);
    proc = capCtx.createScriptProcessor(C.MIC_BUFFER_SIZE, 1, 1);
    mute = capCtx.createGain();
    mute.gain.value = 0;
    src.connect(proc);
    proc.connect(mute);
    mute.connect(capCtx.destination);

    proc.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      let squares = 0;
      for (let i = 0; i < input.length; i += 1) squares += input[i] * input[i];
      const rms = input.length ? Math.sqrt(squares / input.length) : 0;
      micAmp = clamp(rms * 6, 0, 1);

      const ratio = capCtx.sampleRate / C.INPUT_SAMPLE_RATE;
      const outLength = Math.floor(input.length / ratio);
      const output = new Int16Array(outLength);
      for (let i = 0; i < outLength; i += 1) {
        const start = Math.floor(i * ratio);
        const end = Math.floor((i + 1) * ratio);
        let total = 0;
        for (let j = start; j < end; j += 1) total += input[j];
        const average = end > start ? total / (end - start) : 0;
        const sample = clamp(average, -1, 1);
        output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      onFrame(output.buffer);
    };
  },

  stopMic() {
    if (src) {
      try { src.disconnect(); } catch {}
    }
    if (proc) {
      proc.onaudioprocess = null;
      try { proc.disconnect(); } catch {}
    }
    if (mute) {
      try { mute.disconnect(); } catch {}
    }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    src = null;
    proc = null;
    mute = null;
    micAmp = 0;
  },

  playPcm(arrayBuffer) {
    if (!playCtx || !master) return;
    const byteLength = arrayBuffer.byteLength - (arrayBuffer.byteLength % 2);
    if (byteLength === 0) return;
    const i16 = new Int16Array(arrayBuffer, 0, byteLength / 2);
    const f32 = new Float32Array(i16.length);
    let squares = 0;
    for (let i = 0; i < i16.length; i += 1) {
      f32[i] = i16[i] / 32768;
      squares += f32[i] * f32[i];
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
  },

  flushPlayback() {
    for (const node of active) {
      try { node.stop(); } catch {}
    }
    active.clear();
    nextPlayTime = 0;
    envelope.length = 0;
  },

  isPlaying() {
    // 16 section 2g item 2: THE HOST's reply arrives far faster than it plays,
    // so "scheduled audio is still to come" is what the idle clock must see.
    return Boolean(playCtx) && nextPlayTime > playCtx.currentTime;
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