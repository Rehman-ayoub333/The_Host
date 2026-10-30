/**
 * Phase 7o, 16 §2zk item 3 — the operator holds the microphone.
 *
 * At the 30 Oct faculty demo a level threshold could not tell a guest from a
 * hall, and Rehman had to repeat himself even into the handheld. So listening
 * became his decision: while he is listening nothing is filtered out at all,
 * and while he is not, nothing is sent. Automatic mode keeps the old behaviour
 * plus the presence gate, for a quiet room.
 *
 * The uplink never develops a gap in any of these: a held frame is sent as
 * silence of the same length, because Gemini's end-of-speech detection reads
 * the stream as one unbroken thing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { C } from "@/lib/booth/constants";
import { HostSession, SOCKET_OPEN, type SessionDeps, type SocketLike } from "@/lib/booth/session";
import type { AudioPort } from "@/lib/booth/audio";
import type { FaceReading, PresencePort } from "@/lib/booth/presence";

class FakeSocket implements SocketLike {
  readyState = SOCKET_OPEN;
  binaryType = "";
  sent: (string | ArrayBuffer)[] = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  deliver(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function fakeAudio(overrides: Partial<AudioPort> = {}): AudioPort {
  return {
    init: vi.fn(async () => {}),
    probeMic: vi.fn(async () => true),
    startMic: vi.fn(async () => {}),
    stopMic: vi.fn(),
    playPcm: vi.fn(),
    flushPlayback: vi.fn(),
    isPlaying: vi.fn(() => false),
    isRunning: vi.fn(() => true),
    getMicAmp: vi.fn(() => 0),
    getPlaybackAmp: vi.fn(() => 0),
    endPlaybackTurn: vi.fn(),
    takePlaybackStats: vi.fn(() => ({ chunks: 0, maxLateMs: 0, underruns: 0 })),
    ...overrides,
  };
}

function fakePresence(): PresencePort {
  return {
    get state() {
      return "present" as const;
    },
    get people() {
      return 1;
    },
    init: vi.fn(async () => {}),
    stop: vi.fn(),
  };
}

const FRONTAL_CLOSE: FaceReading = { x: 0.5, y: 0.5, ratio: 0.3, frontal: true };
const TURNED_AWAY: FaceReading = { ...FRONTAL_CLOSE, frontal: false };

/** A loud frame, as the microphone delivers one. */
function loudFrame() {
  const samples = new Int16Array(C.MIC_FRAME_SAMPLES);
  for (let i = 0; i < samples.length; i += 1) samples[i] = i % 2 === 0 ? 9000 : -9000;
  return samples.buffer;
}

function allZero(buffer: ArrayBuffer) {
  return new Int16Array(buffer).every((sample) => sample === 0);
}

/** A session in conversation, with the microphone callback in hand. */
async function booth(options: { micAmp?: number; presenceAvailable?: boolean } = {}) {
  const frames: ((frame: ArrayBuffer) => void)[] = [];
  const urls: string[] = [];
  const sockets: FakeSocket[] = [];
  const audio = fakeAudio({
    getMicAmp: () => options.micAmp ?? 1,
    startMic: vi.fn(async (onFrame: (frame: ArrayBuffer) => void) => {
      frames.push(onFrame);
    }),
  });
  const deps: SessionDeps = {
    audio,
    presence: fakePresence(),
    agentUrl: "http://localhost:8000",
    debugMic: true,
    createSocket: (url: string) => {
      urls.push(url);
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    now: () => Date.now(),
    fetchFn: vi.fn(async () => new Response("{}", { status: 200 })) as unknown as typeof fetch,
    logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
  };
  const session = new HostSession(deps);
  await session.start({ video: null });
  // The presence detector's availability decides whether the gate has a camera
  // to ask; `start` sets it from the real getUserMedia, which a test has none of.
  session.setPresenceAvailableForTest(options.presenceAvailable ?? true);
  await session.startSession("button");
  const socket = sockets.at(-1)!;
  socket.onopen?.(null);
  socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
  return {
    session,
    socket,
    urls,
    send: (frame: ArrayBuffer) => frames.at(-1)!(frame),
    binaries: () => socket.sent.filter((item): item is ArrayBuffer => item instanceof ArrayBuffer),
    advance: (ms: number) => vi.advanceTimersByTimeAsync(ms),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-30T18:00:00"));
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/* ------------------------- item 3(a): operator mode ---------------------- */

describe("operator mode (16 §2zk item 3a)", () => {
  it("sends nothing but silence until the operator starts listening", async () => {
    const b = await booth();
    // Operator mode and NOT LISTENING are the defaults: a page that has heard
    // nothing from the dashboard must not have an open microphone.
    expect(b.session.listeningForTest().mode).toBe("operator");
    expect(b.session.listeningForTest().on).toBe(false);

    b.send(loudFrame());
    b.send(loudFrame());

    const sent = b.binaries();
    expect(sent).toHaveLength(2);
    // Silence, never a gap, and never a short frame.
    expect(sent.every((buffer) => buffer.byteLength === C.MIC_FRAME_SAMPLES * 2)).toBe(true);
    expect(sent.every(allZero)).toBe(true);
  });

  it("sends the real microphone the moment the operator starts listening", async () => {
    const b = await booth();
    b.session.setListening(true);

    b.send(loudFrame());

    const sent = b.binaries();
    expect(sent).toHaveLength(1);
    expect(allZero(sent[0]!)).toBe(false);
    expect(new Int16Array(sent[0]!)[0]).toBe(9000);
  });

  it("silences the uplink at once on Stop listening", async () => {
    const b = await booth();
    b.session.setListening(true);
    b.send(loudFrame());
    b.session.setListening(false);

    b.send(loudFrame());

    const sent = b.binaries();
    expect(allZero(sent[0]!)).toBe(false);
    expect(allZero(sent[1]!)).toBe(true);
  });

  it("ignores the noise gate and the presence gate while listening", async () => {
    // A quiet room, and nobody in front of the camera: in automatic mode both
    // gates would hold this frame. The operator has said otherwise.
    const b = await booth({ micAmp: 0 });
    b.session.setFaceForTest(null);
    b.session.setListening(true);

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(false);
  });

  it("shows the dot while listening, through the view", async () => {
    const b = await booth();
    expect(b.session.getView().listening).toBe(false);
    b.session.setListening(true);
    expect(b.session.getView().listening).toBe(true);
    b.session.setListening(false);
    expect(b.session.getView().listening).toBe(false);
  });

  it("asks the backend for operator sensitivity on the session URL", async () => {
    const b = await booth();
    expect(b.urls.at(-1)).toContain("listen=operator");
    expect(b.urls.at(-1)).toContain("trigger=button");
  });
});

/* ------------------------ item 3(b): automatic mode ---------------------- */

describe("automatic mode (16 §2zk item 3b, §2zj item 5)", () => {
  /** Automatic mode, listening decided by the gates rather than the operator. */
  async function automatic(options: { micAmp?: number; presenceAvailable?: boolean } = {}) {
    const b = await booth(options);
    b.session.setListeningMode("automatic");
    return b;
  }

  it("asks for the automatic sensitivity on the session URL", async () => {
    const b = await booth();
    expect(b.urls.at(-1)).toContain("listen=operator");
    // The next conversation, in the other mode. The running one has to end
    // first: a second socket while one is open is refused by the backend.
    b.session.setListeningMode("automatic");
    b.session.endSession("user");
    await b.session.startSession("button");
    expect(b.urls.at(-1)).toContain("listen=auto");
  });

  it("holds every frame while no face is in front of the screen", async () => {
    const b = await automatic();
    b.session.setFaceForTest(null);

    b.send(loudFrame());
    b.send(loudFrame());

    const sent = b.binaries();
    expect(sent).toHaveLength(2);
    expect(sent.every((buffer) => buffer.byteLength === C.MIC_FRAME_SAMPLES * 2)).toBe(true);
    expect(sent.every(allZero)).toBe(true);
  });

  it("sends audio while a face is close and facing the screen", async () => {
    const b = await automatic();
    b.session.setFaceForTest(FRONTAL_CLOSE);

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(false);
  });

  it("holds a face that is close but turned away", async () => {
    const b = await automatic();
    b.session.setFaceForTest(TURNED_AWAY);

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(true);
  });

  it("holds a frontal face that is too far away", async () => {
    const b = await automatic();
    b.session.setFaceForTest({ ...FRONTAL_CLOSE, ratio: C.WAKE_MIN_FACE_RATIO - 0.01 });

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(true);
  });

  it("keeps sending for the 1.5 s grace, so a turned head does not cut a sentence", async () => {
    const b = await automatic();
    b.session.setFaceForTest(FRONTAL_CLOSE);
    b.send(loudFrame());

    // The guest looks away mid-sentence.
    b.session.setFaceForTest(null);
    await b.advance(C.PRESENCE_GATE_GRACE_MS - 200);
    b.send(loudFrame());
    expect(allZero(b.binaries()[1]!)).toBe(false);

    // Long enough and they really have gone.
    await b.advance(400);
    b.send(loudFrame());
    expect(allZero(b.binaries()[2]!)).toBe(true);
  });

  it("falls back to the level gate alone when there is no camera", async () => {
    // §2zj item 5: a denied or broken camera must not mute THE HOST entirely.
    const b = await automatic({ presenceAvailable: false });
    b.session.setFaceForTest(null);

    b.send(loudFrame());

    expect(b.session.presenceGateOpen()).toBe(true);
    expect(allZero(b.binaries()[0]!)).toBe(false);
  });

  it("still applies the noise gate under a face", async () => {
    const b = await automatic({ micAmp: 0 });
    b.session.setFaceForTest(FRONTAL_CLOSE);

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(true);
  });

  it("takes the gate level from Settings, inside its range", async () => {
    const b = await automatic({ micAmp: 0.09 });
    b.session.setFaceForTest(FRONTAL_CLOSE);

    // Above the default, so the default would let this through.
    b.session.setGateLevel(0.2);
    b.send(loudFrame());
    expect(allZero(b.binaries()[0]!)).toBe(true);

    b.session.setGateLevel(0.02);
    b.send(loudFrame());
    expect(allZero(b.binaries()[1]!)).toBe(false);
  });

  it("clamps a level outside the documented range", async () => {
    const b = await automatic();
    b.session.setGateLevel(99);
    expect(b.session.listeningForTest().gateLevel).toBe(C.UPLINK_GATE_LEVEL_MAX);
    b.session.setGateLevel(-1);
    expect(b.session.listeningForTest().gateLevel).toBe(C.UPLINK_GATE_LEVEL_MIN);
    b.session.setGateLevel(Number.NaN);
    expect(b.session.listeningForTest().gateLevel).toBe(C.UPLINK_GATE_LEVEL_MIN);
  });

  it("has a default inside its own range", () => {
    expect(C.UPLINK_GATE_LEVEL_DEFAULT).toBeGreaterThanOrEqual(C.UPLINK_GATE_LEVEL_MIN);
    expect(C.UPLINK_GATE_LEVEL_DEFAULT).toBeLessThanOrEqual(C.UPLINK_GATE_LEVEL_MAX);
    expect(C.UPLINK_GATE_LEVEL_DEFAULT).toBe(0.05);
  });
});

/* --------------------------- switching between them --------------------- */

describe("switching listening mode", () => {
  it("never leaves the microphone open on the old rule", async () => {
    const b = await booth();
    b.session.setListening(true);
    expect(b.session.listeningForTest().on).toBe(true);

    b.session.setListeningMode("automatic");

    expect(b.session.listeningForTest().on).toBe(false);
    expect(b.session.getView().listening).toBe(false);
  });

  it("holds every frame in operator mode after coming back from automatic", async () => {
    const b = await booth();
    b.session.setListeningMode("automatic");
    b.session.setListeningMode("operator");
    b.session.setFaceForTest(FRONTAL_CLOSE);

    b.send(loudFrame());

    expect(allZero(b.binaries()[0]!)).toBe(true);
  });

  it("still lets THE HOST's own voice close the uplink", async () => {
    // The echo gate stays in both modes (§2zk item 3a): THE HOST never hears
    // itself, even while the operator is listening.
    const frames: ((frame: ArrayBuffer) => void)[] = [];
    let playing = true;
    const audio = fakeAudio({
      isPlaying: () => playing,
      getMicAmp: () => 1,
      startMic: vi.fn(async (onFrame: (frame: ArrayBuffer) => void) => {
        frames.push(onFrame);
      }),
    });
    const sockets: FakeSocket[] = [];
    const session = new HostSession({
      audio,
      presence: fakePresence(),
      agentUrl: "http://localhost:8000",
      debugMic: false,
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      now: () => Date.now(),
      fetchFn: vi.fn(async () => new Response("{}", { status: 200 })) as unknown as typeof fetch,
      logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
    });
    await session.start({ video: null });
    await session.startSession("button");
    sockets.at(-1)!.onopen?.(null);
    session.setListening(true);

    // Re-read each time: `filter` returns a snapshot, and the next frame lands
    // on the socket rather than on it.
    const binaries = () => sockets.at(-1)!.sent.filter((i): i is ArrayBuffer => i instanceof ArrayBuffer);

    frames.at(-1)!(loudFrame());
    expect(allZero(binaries()[0]!)).toBe(true);

    playing = false;
    await vi.advanceTimersByTimeAsync(C.ECHO_GATE_TAIL_MS + 50);
    frames.at(-1)!(loudFrame());
    expect(allZero(binaries()[1]!)).toBe(false);
  });
});
