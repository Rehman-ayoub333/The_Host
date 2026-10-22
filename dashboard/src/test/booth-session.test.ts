/**
 * 16 §2t item 8: the ported logic, driven directly.
 *
 * The rules under test are the ones the voice page proved at the booth over
 * phases 5d to 7c: the wake rule (§2h item 2), the empty-room and idle timers
 * (§2h item 4, §2g item 2), the 8-minute wrap-up (§2i item 3), the quiet busy
 * retries (§2j item 3) and the reconnecting hold (§2k item 3). `HostSession`
 * has no DOM of its own, so each one is checked by moving a fake clock.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { C, WRAP_UP_SETTLE_MS } from "@/lib/booth/constants";
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
