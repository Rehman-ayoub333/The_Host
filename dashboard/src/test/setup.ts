import "@testing-library/jest-dom/vitest";

Object.defineProperty(window, "scrollTo", {
  writable: true,
  value: () => {},
});

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});

// jsdom has no Web Audio at all, and since 16 §2zf item 8(d) `/display` tries to
// start the moment it loads, every display test reaches `audio.init()` and the
// missing constructor surfaced as an unhandled error inside a React effect --
// 22 of them, which vitest warns can cause false positives. This is the smallest
// stub that lets `init()` finish: a context that resumes, a gain node that
// connects, and the pieces the capture and playback paths ask for next. No test
// asserts on sound, so nothing here pretends to make any.
class StubAudioContext {
  sampleRate: number;
  currentTime = 0;
  state: AudioContextState = "running";
  destination = { channelCount: 1, connect: () => {}, disconnect: () => {} };
  audioWorklet = { addModule: async () => {} };

  constructor(options?: AudioContextOptions) {
    this.sampleRate = options?.sampleRate ?? 48000;
  }

  async resume() {
    this.state = "running";
  }

  async suspend() {
    this.state = "suspended";
  }

  async close() {
    this.state = "closed";
  }

  createGain() {
    return {
      gain: { value: 1, setValueAtTime: () => {} },
      connect: () => {},
      disconnect: () => {},
    };
  }

  createBuffer(channels: number, length: number, sampleRate: number) {
    return {
      length,
      sampleRate,
      numberOfChannels: channels,
      getChannelData: () => new Float32Array(length),
    };
  }

  createBufferSource() {
    return {
      buffer: null,
      onended: null,
      connect: () => {},
      disconnect: () => {},
      start: () => {},
      stop: () => {},
    };
  }

  createMediaStreamSource() {
    return { connect: () => {}, disconnect: () => {} };
  }
}

for (const name of ["AudioContext", "webkitAudioContext"]) {
  Object.defineProperty(window, name, {
    writable: true,
    configurable: true,
    value: StubAudioContext,
  });
  Object.defineProperty(globalThis, name, {
    writable: true,
    configurable: true,
    value: StubAudioContext,
  });
}
