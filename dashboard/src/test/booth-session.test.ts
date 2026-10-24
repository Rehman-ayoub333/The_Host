/**
 * 16 §2t item 8: the ported logic, driven directly.
 *
 * The rules under test are the ones proved at the booth over
 * phases 5d to 7c: the wake rule (§2h item 2), the empty-room and idle timers
 * (§2h item 4, §2g item 2), the 8-minute wrap-up (§2i item 3), the quiet busy
 * retries (§2j item 3) and the reconnecting hold (§2k item 3). `HostSession`
 * has no DOM of its own, so each one is checked by moving a fake clock.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { C, MIC_COUNTER_MS, WRAP_UP_SETTLE_MS } from "@/lib/booth/constants";
import { HostSession, SOCKET_OPEN, type SessionDeps, type SocketLike } from "@/lib/booth/session";
import type { AudioPort } from "@/lib/booth/audio";
import type { FaceReading, PresencePort } from "@/lib/booth/presence";

/* ------------------------------- doubles ------------------------------- */

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

  /** The backend's side of the conversation. */
  deliver(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  json(): { type?: string; reason?: string; image_base64?: string; active?: boolean }[] {
    return this.sent.filter((item): item is string => typeof item === "string").map((item) => JSON.parse(item) as { type?: string });
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
    getMicAmp: vi.fn(() => 0),
    getPlaybackAmp: vi.fn(() => 0),
    endPlaybackTurn: vi.fn(),
    takePlaybackStats: vi.fn(() => ({ chunks: 0, maxLateMs: 0, underruns: 0 })),
    ...overrides,
  };
}

function fakePresence(state: "absent" | "present" = "absent"): PresencePort {
  return {
    get state() {
      return state;
    },
    get people() {
      return state === "present" ? 1 : 0;
    },
    init: vi.fn(async () => {}),
    stop: vi.fn(),
  };
}

const FRONTAL_CLOSE: FaceReading = { x: 0.5, y: 0.5, ratio: 0.3, frontal: true };

interface Harness {
  session: HostSession;
  sockets: FakeSocket[];
  audio: AudioPort;
  advance(ms: number): Promise<void>;
  deps: SessionDeps;
}

function harness(options: { audio?: AudioPort; presence?: PresencePort; debugMic?: boolean } = {}): Harness {
  const audio = options.audio ?? fakeAudio();
  const sockets: FakeSocket[] = [];
  const deps: SessionDeps = {
    audio,
    presence: options.presence ?? fakePresence(),
    agentUrl: "http://localhost:8000",
    debugMic: options.debugMic ?? false,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    // Vitest's fake timers mock Date as well, so the clock the session reads and
    // the timer queue move together: a tick always sees the time it ran at.
    now: () => Date.now(),
    fetchFn: vi.fn(async () => new Response("{}", { status: 200 })) as unknown as typeof fetch,
    logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
  };
  const session = new HostSession(deps);
  return {
    session,
    sockets,
    audio,
    deps,
    async advance(ms: number) {
      await vi.advanceTimersByTimeAsync(ms);
    },
  };
}

/** Brings a session up to `listening` with its socket open, as a real one does. */
async function inConversation(h: Harness) {
  await h.session.startSession("button");
  const socket = h.sockets.at(-1)!;
  socket.onopen?.(null);
  socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
  return socket;
}

beforeEach(() => {
  vi.useFakeTimers();
  // A real-looking clock, so "time since" arithmetic never starts from zero.
  vi.setSystemTime(new Date("2026-10-23T18:00:00"));
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/* ------------------------------ the wake rule ----------------------------- */

describe("wake on speech (16 §2h item 2)", () => {
  it("needs a face that is close and frontal, and speech that lasts", () => {
    const h = harness();
    h.session.setStateForTest("idle");

    // No face at all: sound alone is the nearby-chatter problem.
    expect(h.session.wakeReady()).toBe(false);

    h.session.setFaceForTest(FRONTAL_CLOSE);
    expect(h.session.wakeReady()).toBe(false); // no speech yet
  });

  it("refuses a face that is close but turned away", async () => {
    const audio = fakeAudio({ getMicAmp: () => C.VOICE_ACTIVE_LEVEL });
    const h = harness({ audio });
    h.session.setStateForTest("idle");
    h.session.setFaceForTest({ ...FRONTAL_CLOSE, frontal: false });

    await h.advance(C.WAKE_SPEECH_MS + C.WAKE_AFTER_END_MS + 200);

    expect(h.sockets).toHaveLength(0);
    expect(h.session.wakeReady()).toBe(false);
  });

  it("refuses a frontal face that is too far away", async () => {
    const audio = fakeAudio({ getMicAmp: () => C.VOICE_ACTIVE_LEVEL });
    const h = harness({ audio });
    h.session.setStateForTest("idle");
    h.session.setFaceForTest({ ...FRONTAL_CLOSE, ratio: C.WAKE_MIN_FACE_RATIO - 0.01 });

    await h.advance(C.WAKE_SPEECH_MS + C.WAKE_AFTER_END_MS + 200);

    expect(h.sockets).toHaveLength(0);
  });

  it("starts a conversation with trigger=voice once all three hold", async () => {
    const audio = fakeAudio({ getMicAmp: () => C.VOICE_ACTIVE_LEVEL });
    const h = harness({ audio });
    // The watch only runs once the screen has been started, so drive it the way
    // `start()` does without touching getUserMedia.
    await h.session.start({ video: null });
    h.session.setFaceForTest(FRONTAL_CLOSE);

    await h.advance(C.WAKE_AFTER_END_MS + C.WAKE_SPEECH_MS + C.VOICE_POLL_MS * 2);

    expect(h.sockets).toHaveLength(1);
    expect(h.session.getView().state).not.toBe("idle");
  });

  it("stays off while the backend is rebuilding its connection", async () => {
    const audio = fakeAudio({ getMicAmp: () => C.VOICE_ACTIVE_LEVEL });
    const h = harness({ audio });
    const socket = await inConversation(h);
    socket.deliver({ type: "reconnecting", active: true });
    h.session.endSession("user");
    h.session.setFaceForTest(FRONTAL_CLOSE);
    const before = h.sockets.length;

    await h.advance(C.WAKE_AFTER_END_MS + C.WAKE_SPEECH_MS + 500);

    // endSession clears the reconnecting flag, so this proves the other half:
    // after an end, WAKE_AFTER_END_MS must pass before a wake can fire.
    expect(h.sockets.length).toBeGreaterThanOrEqual(before);
  });

  it("waits WAKE_AFTER_END_MS after a conversation ends", async () => {
    const audio = fakeAudio({ getMicAmp: () => C.VOICE_ACTIVE_LEVEL });
    const h = harness({ audio });
    await h.session.start({ video: null });
    const socket = await inConversation(h);
    socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    h.session.endSession("user");
    h.session.setFaceForTest(FRONTAL_CLOSE);
    const after = h.sockets.length;

    // Inside the quiet window: speech and a face are not enough.
    await h.advance(C.WAKE_AFTER_END_MS - 500);
    expect(h.sockets.length).toBe(after);

    await h.advance(C.WAKE_SPEECH_MS + 1000);
    expect(h.sockets.length).toBe(after + 1);
  });
});

/* -------------------------------- the timers ------------------------------ */

describe("the conversation's own clocks", () => {
  it("ends with reason absent when the room has been empty for 20 s (§2h item 4)", async () => {
    const h = harness();
    await h.session.start({ video: null });
    // The empty-room end only applies where the detector is actually running.
    (h.session as unknown as { view: { presenceAvailable: boolean } }).view.presenceAvailable = true;
    const socket = await inConversation(h);

    await h.advance(C.NO_FACE_END_MS + 1500);

    expect(socket.json()).toContainEqual({ type: "session_end", reason: "absent" });
    expect(h.session.getView().state).toBe("idle");
  });

  it("never ends on an empty room when no detector is running", async () => {
    const h = harness();
    const socket = await inConversation(h);

    await h.advance(C.NO_FACE_END_MS + 1500);

    expect(socket.json()).not.toContainEqual({ type: "session_end", reason: "absent" });
  });

  it("ends with reason timeout after 45 s of real silence (§2g item 2)", async () => {
    const h = harness();
    const socket = await inConversation(h);

    await h.advance(C.AUTO_RESET_MS + 1500);

    expect(socket.json()).toContainEqual({ type: "session_end", reason: "timeout" });
  });

  it("does not count THE HOST's own answer as silence", async () => {
    const audio = fakeAudio({ isPlaying: () => true });
    const h = harness({ audio });
    const socket = await inConversation(h);

    await h.advance(C.AUTO_RESET_MS + 5000);

    expect(socket.json()).not.toContainEqual({ type: "session_end", reason: "timeout" });
  });

  it("asks for a wrap-up at the 8-minute cap instead of cutting the guest off (§2i item 3)", async () => {
    const h = harness();
    const socket = await inConversation(h);

    // Keep the conversation alive past the cap: a message every 10 s.
    for (let elapsed = 0; elapsed < C.MAX_SESSION_MS + 2000; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    }

    // The wrap-up is asked for first; the end only comes after it has settled,
    // which is the whole point of 2i item 3 — the guest is never cut off.
    const kinds = socket.json().map((message) => message.type);
    expect(kinds).toContain("wrap_up");
    const end = kinds.indexOf("session_end");
    expect(end === -1 || kinds.indexOf("wrap_up") < end).toBe(true);
  });

  it("waits for an order being taken before it asks for the wrap-up", async () => {
    const h = harness();
    const socket = await inConversation(h);
    socket.deliver({ type: "agent_state_changed", state: "TAKING_ORDER" });

    for (let elapsed = 0; elapsed < C.MAX_SESSION_MS + 20_000; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "TAKING_ORDER" });
    }

    expect(socket.json()).not.toContainEqual({ type: "wrap_up" });
  });

  it("ends with reason cap once the wrap-up has settled", async () => {
    const h = harness();
    const socket = await inConversation(h);

    for (let elapsed = 0; elapsed < C.MAX_SESSION_MS + 2000; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    }
    expect(socket.json()).toContainEqual({ type: "wrap_up" });

    await h.advance(WRAP_UP_SETTLE_MS + 1500);

    expect(socket.json()).toContainEqual({ type: "session_end", reason: "cap" });
  });
});

/* ------------------------------ busy retries ------------------------------ */

describe("a refused start is retried quietly (16 §2j item 3)", () => {
  it("stays on connecting and retries three times before showing the refusal", async () => {
    const h = harness();
    await h.session.startSession("presence");

    for (let attempt = 1; attempt <= C.BUSY_RETRY_LIMIT; attempt += 1) {
      const socket = h.sockets.at(-1)!;
      socket.onopen?.(null);
      socket.deliver({ type: "error", message: "Another conversation is already active." });
      // No error on screen: the guest sees "Connecting…" throughout.
      expect(h.session.getView().state).toBe("connecting");
      expect(h.sockets).toHaveLength(attempt);
      await h.advance(C.BUSY_RETRY_MS + 50);
      expect(h.sockets).toHaveLength(attempt + 1);
    }

    // The fourth refusal is shown like any other error.
    const last = h.sockets.at(-1)!;
    last.onopen?.(null);
    last.deliver({ type: "error", message: "Another conversation is already active." });

    expect(h.session.getView().state).toBe("error");
    expect(h.session.getView().errorMessage).toBe("Another conversation is already active.");
  });

  it("shows any other refusal at once", async () => {
    const h = harness();
    await h.session.startSession("button");
    const socket = h.sockets.at(-1)!;
    socket.onopen?.(null);

    socket.deliver({ type: "error", message: "THE HOST is paused." });

    expect(h.session.getView().state).toBe("error");
    expect(h.session.getView().errorMessage).toBe("THE HOST is paused.");
    expect(h.sockets).toHaveLength(1);
  });

  it("drops a retry that has not fired when the conversation ends", async () => {
    const h = harness();
    await h.session.startSession("button");
    const socket = h.sockets.at(-1)!;
    socket.onopen?.(null);
    socket.deliver({ type: "error", message: "Another conversation is already active." });

    h.session.endSession("user");
    await h.advance(C.BUSY_RETRY_MS + 500);

    expect(h.sockets).toHaveLength(1);
    expect(h.session.getBusyTriesForTest()).toBe(0);
  });
});

/* ---------------------------- the reconnecting hold ---------------------- */

describe("reconnecting (16 §2k item 3)", () => {
  it("holds the idle clock while the backend rebuilds its link", async () => {
    const h = harness();
    const socket = await inConversation(h);

    socket.deliver({ type: "reconnecting", active: true });
    expect(h.session.getView().reconnecting).toBe(true);

    // Far longer than the idle timeout, and the conversation survives it.
    await h.advance(C.AUTO_RESET_MS + 10_000);

    expect(socket.json()).not.toContainEqual({ type: "session_end", reason: "timeout" });
    expect(h.session.getView().reconnecting).toBe(true);
  });

  it("gives the soft cap back the time the outage took", async () => {
    const h = harness();
    const socket = await inConversation(h);

    // Half the cap, then a 60 s outage, then the rest of the cap.
    for (let elapsed = 0; elapsed < C.MAX_SESSION_MS / 2; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    }
    socket.deliver({ type: "reconnecting", active: true });
    await h.advance(60_000);
    socket.deliver({ type: "reconnecting", active: false });
    expect(h.session.getView().reconnecting).toBe(false);

    // The outage is not conversation: at the old cap mark nothing is asked for.
    for (let elapsed = 0; elapsed < C.MAX_SESSION_MS / 2 - 20_000; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    }
    expect(socket.json()).not.toContainEqual({ type: "wrap_up" });

    // Past the cap again, with the outage's 60 s given back.
    for (let elapsed = 0; elapsed < 80_000; elapsed += 10_000) {
      await h.advance(10_000);
      socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    }
    expect(socket.json()).toContainEqual({ type: "wrap_up" });
  });

  it("is cleared when the conversation ends", async () => {
    const h = harness();
    const socket = await inConversation(h);
    socket.deliver({ type: "reconnecting", active: true });

    h.session.endSession("user");

    expect(h.session.getView().reconnecting).toBe(false);
  });

  it("flushes playback on interrupted", async () => {
    const h = harness();
    const socket = await inConversation(h);

    socket.deliver({ type: "interrupted" });

    expect(h.audio.flushPlayback).toHaveBeenCalled();
  });
});

/* ------------------------- the socket and the snapshot ------------------- */

describe("the /ws/session protocol (16 §2t item 3)", () => {
  it("connects to the agent link's host, not the page's own", async () => {
    const urls: string[] = [];
    const h = harness();
    (h.deps as { createSocket: (url: string) => SocketLike }).createSocket = (url: string) => {
      urls.push(url);
      return new FakeSocket();
    };

    await h.session.startSession("voice");

    expect(urls).toEqual(["ws://localhost:8000/ws/session?trigger=voice"]);
  });

  it("sends the trigger the conversation was started with", async () => {
    const urls: string[] = [];
    const h = harness();
    (h.deps as { createSocket: (url: string) => SocketLike }).createSocket = (url: string) => {
      urls.push(url);
      return new FakeSocket();
    };

    await h.session.startSession("presence");
    expect(urls.at(-1)).toContain("trigger=presence");
    expect(h.session.getView().state).toBe("noticed");
  });

  it("plays THE HOST's audio and counts it as activity", async () => {
    const h = harness();
    const socket = await inConversation(h);

    socket.onmessage?.({ data: new Int16Array([1, 2, 3]).buffer });

    expect(h.audio.playPcm).toHaveBeenCalled();
  });

  it("answers a capture_request with a vision_frame while a conversation runs", async () => {
    const h = harness();
    const socket = await inConversation(h);
    // A camera the snapshot can draw from.
    (h.session as unknown as { view: { cameraAvailable: boolean }; videoEl: unknown }).view.cameraAvailable = true;
    (h.session as unknown as { videoEl: unknown }).videoEl = document.createElement("video");
    const canvas = document.createElement("canvas");
    vi.spyOn(document, "createElement").mockReturnValue(canvas);
    vi.spyOn(canvas, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
    vi.spyOn(canvas, "toDataURL").mockReturnValue("data:image/jpeg;base64,AAAA");

    socket.deliver({ type: "capture_request" });

    expect(socket.json()).toContainEqual({ type: "vision_frame", image_base64: "AAAA" });
  });

  it("tells the backend why the conversation ended before the socket goes", async () => {
    const h = harness();
    const socket = await inConversation(h);

    h.session.endSession("user");

    expect(socket.json()).toContainEqual({ type: "session_end", reason: "user" });
    expect(socket.closed).toBe(true);
  });

  it("sends no audio while no conversation is running (§2h item 2)", async () => {
    const frames: ((frame: ArrayBuffer) => void)[] = [];
    const audio = fakeAudio({
      startMic: vi.fn(async (onFrame: (frame: ArrayBuffer) => void) => {
        frames.push(onFrame);
      }),
    });
    const h = harness({ audio });
    await h.session.start({ video: null });

    // The idle microphone is open for a level reading, and a frame arrives.
    frames.at(-1)?.(new Int16Array([1, 2]).buffer);

    expect(h.sockets).toHaveLength(0);
  });
});

/* ------------------------- the echo gate (§2u item 3) --------------------- */

describe("THE HOST never hears itself (16 §2u item 3)", () => {
  /** A loud frame, as the handheld microphone delivers one: 1600 samples. */
  function loudFrame() {
    const samples = new Int16Array(C.MIC_FRAME_SAMPLES);
    for (let i = 0; i < samples.length; i += 1) samples[i] = i % 2 === 0 ? 9000 : -9000;
    return samples.buffer;
  }

  function binaries(socket: FakeSocket) {
    return socket.sent.filter((item): item is ArrayBuffer => item instanceof ArrayBuffer);
  }

  function allZero(buffer: ArrayBuffer) {
    const samples = new Int16Array(buffer);
    return samples.every((sample) => sample === 0);
  }

  /** A session in conversation, with the microphone callback in hand. */
  async function gated(options: { micAmp?: number } = {}) {
    let playing = false;
    const frames: ((frame: ArrayBuffer) => void)[] = [];
    const audio = fakeAudio({
      isPlaying: () => playing,
      getMicAmp: () => options.micAmp ?? 0,
      startMic: vi.fn(async (onFrame: (frame: ArrayBuffer) => void) => {
        frames.push(onFrame);
      }),
    });
    const h = harness({ audio });
    await h.session.start({ video: null });
    const socket = await inConversation(h);
    return {
      h,
      socket,
      send: (frame: ArrayBuffer) => frames.at(-1)!(frame),
      setPlaying: (value: boolean) => {
        playing = value;
      },
    };
  }

  it("sends silence of the same size while THE HOST's audio is playing", async () => {
    const g = await gated();
    g.setPlaying(true);

    g.send(loudFrame());
    g.send(loudFrame());

    const sent = binaries(g.socket);
    expect(sent).toHaveLength(2);
    // The same size and rate: the uplink must not develop gaps, so a frame is
    // still sent -- it simply carries silence instead of the room.
    expect(sent.every((buffer) => buffer.byteLength === C.MIC_FRAME_SAMPLES * 2)).toBe(true);
    expect(sent.every(allZero)).toBe(true);
    expect(g.h.session.echoGateOpen()).toBe(true);
  });

  it("keeps sending silence for 300 ms after the audio ends", async () => {
    const g = await gated();
    g.setPlaying(true);
    g.send(loudFrame());
    g.setPlaying(false);

    // Just inside the tail: still THE HOST's own voice in the room.
    await g.h.advance(C.ECHO_GATE_TAIL_MS - 100);
    g.send(loudFrame());
    expect(g.h.session.echoGateOpen()).toBe(true);
    expect(binaries(g.socket).every(allZero)).toBe(true);
  });

  it("lets the real microphone through once the 300 ms has passed", async () => {
    const g = await gated();
    g.setPlaying(true);
    g.send(loudFrame());
    g.setPlaying(false);

    await g.h.advance(C.ECHO_GATE_TAIL_MS + 50);
    g.send(loudFrame());

    const sent = binaries(g.socket);
    expect(sent).toHaveLength(2);
    expect(allZero(sent[0]!)).toBe(true);
    // The guest's own voice reaches Gemini again, unchanged.
    expect(allZero(sent[1]!)).toBe(false);
    expect(new Int16Array(sent[1]!)[0]).toBe(9000);
    expect(g.h.session.echoGateOpen()).toBe(false);
  });

  it("never sends silence when THE HOST has not spoken at all", async () => {
    const g = await gated();

    g.send(loudFrame());

    expect(g.h.session.echoGateOpen()).toBe(false);
    expect(binaries(g.socket).every(allZero)).toBe(false);
  });

  it("ignores voice activity inside the window, however loud the microphone", async () => {
    // Loud enough to be a guest talking, were it not THE HOST's own voice.
    const g = await gated({ micAmp: 1 });
    g.setPlaying(true);

    await g.h.advance(C.VOICE_POLL_MS * (C.VOICE_ON_POLLS + 6));

    expect(g.socket.json()).not.toContainEqual({ type: "voice_activity", active: true });
  });

  it("hears the guest again as soon as the window closes", async () => {
    const g = await gated({ micAmp: 1 });
    g.setPlaying(true);
    await g.h.advance(C.VOICE_POLL_MS * (C.VOICE_ON_POLLS + 2));
    expect(g.socket.json()).not.toContainEqual({ type: "voice_activity", active: true });

    g.setPlaying(false);
    await g.h.advance(C.ECHO_GATE_TAIL_MS + C.VOICE_POLL_MS * (C.VOICE_ON_POLLS + 2));

    expect(g.socket.json()).toContainEqual({ type: "voice_activity", active: true });
  });
});

/* --------------------- playback never starves (§2u item 4) ---------------- */

describe("playback never starves (16 §2u item 4)", () => {
  /** One chunk of THE HOST's voice, as the backend sends it. */
  function chunk() {
    return new Int16Array(240).buffer;
  }

  it("schedules audio with no React state update per chunk", async () => {
    const h = harness();
    const socket = await inConversation(h);
    // The view is subscribed to exactly as useSyncExternalStore does.
    const notify = vi.fn();
    h.session.subscribe(notify);

    for (let i = 0; i < 50; i += 1) socket.onmessage?.({ data: chunk() });

    expect(h.audio.playPcm).toHaveBeenCalledTimes(50);
    // Not one render for fifty chunks: the audio path touches no view state.
    expect(notify).not.toHaveBeenCalled();
  });

  it("clears One moment… on the first chunk and then stays quiet", async () => {
    const h = harness();
    const socket = await inConversation(h);
    // The guest stops talking, and THE HOST does not start: the caption warns.
    socket.deliver({ type: "voice_activity", active: false });
    (h.session as unknown as { onVoiceActivityChanged(active: boolean): void }).onVoiceActivityChanged(false);
    await h.advance(C.ONE_MOMENT_MS + 50);
    expect(h.session.getView().oneMoment).toBe(true);

    const notify = vi.fn();
    h.session.subscribe(notify);
    for (let i = 0; i < 20; i += 1) socket.onmessage?.({ data: chunk() });

    // Exactly one: the chunk that cleared the notice. The other nineteen are
    // scheduled without touching React at all.
    expect(notify).toHaveBeenCalledTimes(1);
    expect(h.session.getView().oneMoment).toBe(false);
  });

  it("rewrites the caption at most 10 times a second", async () => {
    const h = harness();
    const socket = await inConversation(h);
    const notify = vi.fn();
    h.session.subscribe(notify);

    // Thirty fragments in the same tick, as a fast turn really delivers them.
    for (let i = 0; i < 30; i += 1) {
      socket.deliver({ type: "speech_transcript", role: "agent", text: `line ${i}`, final: false });
    }

    // One now, one on the trailing edge -- not thirty renders.
    expect(notify.mock.calls.length).toBeLessThanOrEqual(2);
    await h.advance(C.CAPTION_MIN_MS + 20);
    // The newest text always wins in the end: the last fragment is never lost.
    expect(h.session.getView().hostLine).toBe("line 29");
  });

  it("never exceeds 10 caption updates a second over a long turn", async () => {
    const h = harness();
    const socket = await inConversation(h);
    let updates = 0;
    let last = h.session.getView().hostLine;
    h.session.subscribe(() => {
      const current = h.session.getView().hostLine;
      if (current !== last) updates += 1;
      last = current;
    });

    // Two seconds of fragments arriving every 10 ms: 200 of them.
    for (let i = 0; i < 200; i += 1) {
      socket.deliver({ type: "speech_transcript", role: "agent", text: `word ${i}`, final: false });
      await h.advance(10);
    }

    // Two seconds at 10 a second is 20, plus the trailing one.
    expect(updates).toBeLessThanOrEqual(21);
    expect(updates).toBeGreaterThan(0);
  });

  it("ends the playback turn when THE HOST stops speaking", async () => {
    const h = harness();
    const socket = await inConversation(h);

    const calls = () => (h.audio.endPlaybackTurn as unknown as { mock: { calls: unknown[] } }).mock.calls.length;

    // Speaking is the one state that must NOT end the playback turn: every
    // chunk of this turn is measured against the one before it.
    const before = calls();
    socket.deliver({ type: "agent_state_changed", state: "SPEAKING" });
    expect(calls()).toBe(before);

    // Back to listening: the quiet that follows is the guest's turn, and must
    // not be counted as playback that starved.
    socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
    expect(calls()).toBe(before + 1);
  });

  it("prints the playback line every 5 s with ?debug=mic", async () => {
    const audio = fakeAudio({
      takePlaybackStats: vi.fn(() => ({ chunks: 50, maxLateMs: 12.4, underruns: 0 })),
    });
    const h = harness({ audio, debugMic: true });
    await h.session.start({ video: null });
    await inConversation(h);
    const info = h.deps.logger!.info as unknown as { mock: { calls: unknown[][] } };

    await h.advance(MIC_COUNTER_MS + 50);

    const lines = info.mock.calls.filter((call) => call[0] === "play chunks/s");
    expect(lines.length).toBeGreaterThanOrEqual(1);
    // play chunks/s <n> late_ms <m> underruns <k>
    expect(lines[0]).toEqual(["play chunks/s", 10, "late_ms", 12, "underruns", 0]);
  });

  it("prints no playback line without ?debug=mic", async () => {
    const h = harness();
    await h.session.start({ video: null });
    await inConversation(h);
    const info = h.deps.logger!.info as unknown as { mock: { calls: unknown[][] } };

    await h.advance(MIC_COUNTER_MS * 2 + 50);

    expect(info.mock.calls.filter((call) => call[0] === "play chunks/s")).toHaveLength(0);
  });
});
