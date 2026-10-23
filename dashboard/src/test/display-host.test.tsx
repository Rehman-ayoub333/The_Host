/**
 * 16 §2t items 4 and 8: what a guest sees on the TV.
 *
 *   - THE HOST's own words appear as a caption; the guest's never do;
 *   - the wait is visibly alive: THINKING the moment the guest stops, and
 *     "One moment…" if THE HOST has still not started 3 s later;
 *   - the Start screen asks once for the camera and the microphone;
 *   - Space starts a conversation, Escape ends one, and neither fires while the
 *     debug text box has the caret.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
}));

import { SMDDisplay, displayCaption, displayKeyAction, displayState } from "@/routes/display";
import { agentStore } from "@/lib/agent/store";
import { C } from "@/lib/booth/constants";
import { HostSession, SOCKET_OPEN, type SessionDeps, type SessionView, type SocketLike } from "@/lib/booth/session";
import type { AudioPort } from "@/lib/booth/audio";
import type { PresencePort } from "@/lib/booth/presence";

const GUEST_LINE = "I would like a chicken burger";
const HOST_LINE = "One Chicken Burger, coming up";

/* ------------------------------- doubles ------------------------------- */

class FakeSocket implements SocketLike {
  readyState = SOCKET_OPEN;
  binaryType = "";
  sent: (string | ArrayBuffer)[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  deliver(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function sessionHarness(micAmp = { value: 0 }) {
  const audio: AudioPort = {
    init: vi.fn(async () => {}),
    probeMic: vi.fn(async () => true),
    startMic: vi.fn(async () => {}),
    stopMic: vi.fn(),
    playPcm: vi.fn(),
    flushPlayback: vi.fn(),
    isPlaying: vi.fn(() => false),
    getMicAmp: vi.fn(() => micAmp.value),
    getPlaybackAmp: vi.fn(() => 0),
    endPlaybackTurn: vi.fn(),
    takePlaybackStats: vi.fn(() => ({ chunks: 0, maxLateMs: 0, underruns: 0 })),
  };
  const presence: PresencePort = {
    get state() {
      return "absent" as const;
    },
    get people() {
      return 0;
    },
    init: vi.fn(async () => {}),
    stop: vi.fn(),
  };
  const sockets: FakeSocket[] = [];
  const deps: SessionDeps = {
    audio,
    presence,
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
  };
  return { session: new HostSession(deps), sockets, audio, micAmp };
}

/** Brings the session to `listening` with the guest talking. */
async function talking(h: ReturnType<typeof sessionHarness>) {
  await h.session.startSession("button");
  const socket = h.sockets.at(-1)!;
  socket.onopen?.(null);
  socket.deliver({ type: "agent_state_changed", state: "LISTENING" });
  // The guest speaks: two polls above the threshold set the flag.
  h.micAmp.value = C.VOICE_ACTIVE_LEVEL;
  await vi.advanceTimersByTimeAsync(C.VOICE_POLL_MS * (C.VOICE_ON_POLLS + 1));
  return socket;
}

/** …and then stops, which is the page's own end-of-speech. */
async function stoppedTalking(h: ReturnType<typeof sessionHarness>) {
  h.micAmp.value = 0;
  await vi.advanceTimersByTimeAsync(C.VOICE_OFF_MS + C.VOICE_POLL_MS * 2);
}

/* ----------------------- the wait is visibly alive ---------------------- */

describe("the wait is always visibly alive (16 §2t item 4)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-23T18:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("switches the orb to THINKING the moment the guest stops speaking", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    expect(socket.sent.map(String)).toContain(JSON.stringify({ type: "voice_activity", active: true }));

    await stoppedTalking(h);

    expect(h.session.getView().state).toBe("thinking");
  });

  it("shows One moment… when THE HOST has not started 3 s later", async () => {
    const h = sessionHarness();
    await talking(h);
    await stoppedTalking(h);

    expect(h.session.getView().oneMoment).toBe(false);
    await vi.advanceTimersByTimeAsync(C.ONE_MOMENT_MS + 50);

    expect(h.session.getView().oneMoment).toBe(true);
    expect(displayCaption(h.session.getView())).toBe("One moment…");
  });

  it("never shows it when THE HOST starts talking inside the 3 s", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    await stoppedTalking(h);

    await vi.advanceTimersByTimeAsync(C.ONE_MOMENT_MS - 1000);
    socket.onmessage?.({ data: new Int16Array([1, 2, 3]).buffer });
    await vi.advanceTimersByTimeAsync(5000);

    expect(h.session.getView().oneMoment).toBe(false);
  });

  it("clears it as soon as THE HOST's audio arrives (\"until it does\")", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    await stoppedTalking(h);
    await vi.advanceTimersByTimeAsync(C.ONE_MOMENT_MS + 50);
    expect(h.session.getView().oneMoment).toBe(true);

    socket.onmessage?.({ data: new Int16Array([1, 2, 3]).buffer });

    expect(h.session.getView().oneMoment).toBe(false);
  });

  it("leaves THE HOST's own state alone while it is already speaking", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    socket.deliver({ type: "agent_state_changed", state: "SPEAKING" });

    await stoppedTalking(h);

    expect(h.session.getView().state).toBe("speaking");
  });

  it("drops the wait when the conversation ends", async () => {
    const h = sessionHarness();
    await talking(h);
    await stoppedTalking(h);
    await vi.advanceTimersByTimeAsync(C.ONE_MOMENT_MS + 50);

    h.session.endSession("user");

    expect(h.session.getView().oneMoment).toBe(false);
  });

  it("drops the wait when the turn is interrupted", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    await stoppedTalking(h);
    await vi.advanceTimersByTimeAsync(C.ONE_MOMENT_MS + 50);

    socket.deliver({ type: "interrupted" });

    expect(h.session.getView().oneMoment).toBe(false);
  });
});

/* --------------------------- the caption itself ------------------------- */

describe("the caption is THE HOST's words only (16 §2t item 4, §2i item 6)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-23T18:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows a line THE HOST spoke", async () => {
    const h = sessionHarness();
    const socket = await talking(h);

    socket.deliver({ type: "speech_transcript", role: "agent", text: HOST_LINE, final: true });

    expect(h.session.getView().hostLine).toBe(HOST_LINE);
    expect(displayCaption(h.session.getView())).toBe(HOST_LINE);
  });

  it("shows a partial line THE HOST is still saying", async () => {
    const h = sessionHarness();
    const socket = await talking(h);

    socket.deliver({ type: "speech_transcript", role: "agent", text: "One Chicken", final: false });
    expect(h.session.getView().hostLine).toBe("One Chicken");

    socket.deliver({ type: "speech_transcript", role: "agent", text: HOST_LINE, final: true });
    // 16 §2u item 4: the caption is rewritten at most 10 times a second, so a
    // fragment this close behind the last one lands on the trailing edge. The
    // newest text still wins -- it is never dropped, only held back.
    await vi.advanceTimersByTimeAsync(C.CAPTION_MIN_MS + 20);

    expect(h.session.getView().hostLine).toBe(HOST_LINE);
  });

  it("never shows the guest's words, final or partial", async () => {
    const h = sessionHarness();
    const socket = await talking(h);

    socket.deliver({ type: "speech_transcript", role: "visitor", text: GUEST_LINE, final: false });
    socket.deliver({ type: "speech_transcript", role: "visitor", text: GUEST_LINE, final: true });

    expect(h.session.getView().hostLine).toBe("");
    expect(displayCaption(h.session.getView())).not.toContain(GUEST_LINE);
  });

  it("keeps THE HOST's line out of the way of a guest's that follows", async () => {
    const h = sessionHarness();
    const socket = await talking(h);

    socket.deliver({ type: "speech_transcript", role: "agent", text: HOST_LINE, final: true });
    socket.deliver({ type: "speech_transcript", role: "visitor", text: GUEST_LINE, final: true });

    // The guest's line changes nothing: the caption still holds what THE HOST said.
    expect(h.session.getView().hostLine).toBe(HOST_LINE);
  });

  it("is cleared when a new conversation starts", async () => {
    const h = sessionHarness();
    const socket = await talking(h);
    socket.deliver({ type: "speech_transcript", role: "agent", text: HOST_LINE, final: true });
    h.session.endSession("user");

    await h.session.startSession("button");

    expect(h.session.getView().hostLine).toBe("");
  });

  it("gives Reconnecting… the caption while the backend rebuilds its link", () => {
    const view: SessionView = {
      state: "listening",
      reconnecting: true,
      errorMessage: "",
      hostLine: HOST_LINE,
      oneMoment: true,
      micAvailable: true,
      cameraAvailable: true,
      presenceAvailable: true,
      notes: [],
    };

    expect(displayCaption(view)).toBe("Reconnecting…");
  });
});

/* ------------------------------ the orb state --------------------------- */

describe("the orb follows the page's own conversation (16 §2t item 3)", () => {
  it("maps every local state the page can be in", () => {
    expect(displayState("noticed", "idle")).toBe("seeing");
    expect(displayState("connecting", "idle")).toBe("seeing");
    expect(displayState("listening", "idle")).toBe("listening");
    expect(displayState("thinking", "idle")).toBe("thinking");
    expect(displayState("speaking", "idle")).toBe("speaking");
    expect(displayState("taking_order", "idle")).toBe("taking_order");
    expect(displayState("needs_help", "idle")).toBe("needs_help");
    expect(displayState("error", "idle")).toBe("offline");
  });

  it("leaves the screen to the event stream between conversations", () => {
    // A ready announcement arrives long after its conversation ended, so the
    // smd stream still decides what an idle screen shows (§2o item 6).
    expect(displayState("idle", "order_ready")).toBe("order_ready");
    expect(displayState("booth_off", "offline")).toBe("offline");
    expect(displayState("idle", "idle")).toBe("idle");
  });
});

/* -------------------------------- the keys ------------------------------ */

describe("the display's two keys (16 §2t item 4)", () => {
  it("starts on Space and ends on Escape", () => {
    expect(displayKeyAction({ code: "Space", key: " " })).toBe("start");
    expect(displayKeyAction({ key: "Escape" })).toBe("end");
  });

  it("ignores every other key", () => {
    expect(displayKeyAction({ key: "a" })).toBeNull();
    expect(displayKeyAction({ key: "Enter" })).toBeNull();
  });

  it("does nothing while the debug text box has the caret", () => {
    expect(displayKeyAction({ code: "Space", key: " ", targetTag: "INPUT" })).toBeNull();
    expect(displayKeyAction({ key: "Escape", targetTag: "TEXTAREA" })).toBeNull();
    expect(displayKeyAction({ code: "Space", key: " ", targetTag: "SELECT" })).toBeNull();
  });
});

/* ----------------------------- the Start screen ------------------------- */

describe("the Start screen (16 §2t item 4)", () => {
  beforeEach(() => {
    agentStore.dispatch({ type: "@reset" });
  });

  afterEach(() => {
    cleanup();
    agentStore.dispatch({ type: "@reset" });
  });

  it("asks for one click, with a camera and a microphone drop-down", () => {
    render(<SMDDisplay />);

    expect(screen.getByRole("button", { name: /start the host/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Camera")).toBeInTheDocument();
    expect(screen.getByLabelText("Microphone")).toBeInTheDocument();
  });

  it("offers the system default on both drop-downs", () => {
    render(<SMDDisplay />);

    expect(screen.getByLabelText("Camera")).toHaveValue("");
    expect(screen.getByLabelText("Microphone")).toHaveValue("");
  });

  it("shows no text box, because ?debug=mic is not set", () => {
    render(<SMDDisplay />);

    expect(screen.queryByLabelText("Type to THE HOST")).toBeNull();
  });

  it("renders no guest-facing conversation buttons", () => {
    render(<SMDDisplay />);

    expect(screen.queryByRole("button", { name: /tap to talk/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /i'm done/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /show it something/i })).toBeNull();
  });
});
