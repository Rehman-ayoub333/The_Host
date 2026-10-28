/**
 * 16 §2zf item 8 — the display recovers by itself.
 *
 * Rehman's complaint 2(e): "After a connection drop the TV must not need F5
 * and 'Tap to begin'." The 8(a) diagnosis found that a Gemini recovery
 * failure left `/display` on its error screen with nothing retrying the
 * conversation, so the guest at the counter had to be rescued by an operator
 * or a reload.
 *
 * Proved here: both sockets use the one backoff (1, 2, 4, 8, 10 s, then every
 * 10 s); the conversation socket is retried on it while a guest is still in
 * front of the camera; an empty room gets the armed idle screen instead; and
 * the page only calls itself started when the browser really gave it sound.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backoffAt, SOCKET_BACKOFF_MS } from "@/lib/booth/constants";
import { HostSession, SOCKET_OPEN, type SessionDeps, type SocketLike } from "@/lib/booth/session";
import type { AudioPort } from "@/lib/booth/audio";
import type { PresencePort } from "@/lib/booth/presence";

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

  /** The socket going away under the page, as a dropped connection does. */
  die() {
    this.readyState = 3;
    this.onclose?.(null);
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

/** Presence the test can move, as a guest arriving and leaving does. */
function movablePresence(initial: "absent" | "present" = "present") {
  const box = { state: initial as "absent" | "present" };
  const port: PresencePort = {
    get state() {
      return box.state;
    },
    get people() {
      return box.state === "present" ? 1 : 0;
    },
    init: vi.fn(async () => {}),
    stop: vi.fn(),
  };
  return { port, box };
}

function harness(options: { audio?: AudioPort; presence?: PresencePort } = {}) {
  const sockets: FakeSocket[] = [];
  const deps: SessionDeps = {
    audio: options.audio ?? fakeAudio(),
    presence: options.presence ?? movablePresence().port,
    agentUrl: "http://localhost:8000",
    debugMic: false,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    now: () => Date.now(),
    logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
  };
  return {
    session: new HostSession(deps),
    sockets,
    deps,
    async advance(ms: number) {
      await vi.advanceTimersByTimeAsync(ms);
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-28T19:00:00"));
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/* ------------------------------ the backoff ------------------------------ */

describe("the one backoff both sockets use (§2zf item 8(b))", () => {
  it("is 1, 2, 4, 8, 10 seconds", () => {
    expect([...SOCKET_BACKOFF_MS]).toEqual([1000, 2000, 4000, 8000, 10_000]);
  });

  it("repeats the last step, so it is every 10 s after that", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(backoffAt)).toEqual([
      1000, 2000, 4000, 8000, 10_000, 10_000, 10_000, 10_000,
    ]);
  });
});

/* -------------------- the conversation socket comes back ----------------- */

describe("a conversation whose socket went (§2zf item 8(b))", () => {
  async function dropped(presence: PresencePort) {
    const h = harness({ presence });
    await h.session.startSession("button");
    const socket = h.sockets.at(-1)!;
    socket.onopen?.(null);
    socket.die();
    return h;
  }

  it("is retried on the backoff while a guest is still there", async () => {
    const { port } = movablePresence("present");
    const h = await dropped(port);
    expect(h.sockets.length).toBe(1);

    // 1 s: the first retry.
    await h.advance(1100);
    expect(h.sockets.length).toBe(2);
    h.sockets.at(-1)!.die();

    // 2 s: the second.
    await h.advance(900);
    expect(h.sockets.length).toBe(2);
    await h.advance(1200);
    expect(h.sockets.length).toBe(3);
    h.sockets.at(-1)!.die();

    // 4 s: the third.
    await h.advance(4200);
    expect(h.sockets.length).toBe(4);
  });

  it("stops and shows the armed idle screen once the room is empty", async () => {
    const { port, box } = movablePresence("present");
    const h = await dropped(port);

    box.state = "absent";
    await h.advance(1200);

    // No new conversation was opened into an empty room.
    expect(h.sockets.length).toBe(1);
    expect(h.session.getView().state).toBe("idle");
    // And a long wait afterwards opens nothing either.
    await h.advance(60_000);
    expect(h.sockets.length).toBe(1);
  });

  it("stops retrying as soon as a conversation is running again", async () => {
    const { port } = movablePresence("present");
    const h = await dropped(port);

    await h.advance(1100);
    expect(h.sockets.length).toBe(2);
    // This one stays up.
    h.sockets.at(-1)!.onopen?.(null);
    await h.advance(60_000);
    expect(h.sockets.length).toBe(2);
  });

  it("is never retried after an end the page meant", async () => {
    const { port } = movablePresence("present");
    const h = harness({ presence: port });
    await h.session.startSession("button");
    h.sockets.at(-1)!.onopen?.(null);

    h.session.endSession("user");
    await h.advance(60_000);

    expect(h.sockets.length).toBe(1);
    expect(h.session.getView().state).toBe("idle");
  });

  it("needs no reload: the page is left armed either way", async () => {
    const { port, box } = movablePresence("present");
    const h = await dropped(port);
    box.state = "absent";
    await h.advance(2000);

    // A guest walks up again: the ordinary presence path still works.
    box.state = "present";
    h.session.setStateForTest("idle");
    await h.session.startSession("presence");

    expect(h.sockets.length).toBe(2);
  });
});

/* ------------------------- no tap after a reload -------------------------- */

describe("the Start screen after a reload (§2zf item 8(d))", () => {
  it("reports ready when the browser really gave the page sound", async () => {
    const h = harness({ audio: fakeAudio({ isRunning: () => true }) });

    await h.session.start({ video: null });

    expect(h.session.audioReady()).toBe(true);
  });

  it("reports not ready when the browser is still waiting for a gesture", async () => {
    // What a browser without --autoplay-policy=no-user-gesture-required does:
    // resume() does not raise, the context simply stays suspended.
    const h = harness({ audio: fakeAudio({ isRunning: () => false }) });

    await h.session.start({ video: null });

    expect(h.session.audioReady()).toBe(false);
  });
});
