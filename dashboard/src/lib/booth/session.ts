/**
 * 16 §2t item 3: the old booth page's conversation logic, ported for /display.
 *
 * This is `booth/app.js` without its DOM: the same state machine, the same
 * timers, the same wake rule, the same busy retries and the same `/ws/session`
 * protocol. Nothing here touches React, so the rules can be driven directly by
 * a test with fake timers and a fake socket (§2t item 8).
 *
 * Two things differ from `booth/`, both because of where the page now runs:
 *   - the socket goes to the configured agent link's host, not to the page's own
 *     host (§2t item 3), because the dashboard is served from :8080 and the
 *     backend lives on :8000;
 *   - the camera and microphone may be chosen by device id (§2t item 4).
 */
import { BUSY_REFUSAL, C, LONGTASK_MS, MIC_COUNTER_MS, MIC_DEBUG_PRINT_MS, MIC_DEBUG_WINDOW_MS, WRAP_UP_SETTLE_MS } from "./constants";
import type { AudioPort } from "./audio";
import type { FaceReading, PresencePort } from "./presence";

export type LocalState =
  | "booth_off"
  | "idle"
  | "noticed"
  | "connecting"
  | "listening"
  | "thinking"
  | "taking_order"
  | "needs_help"
  | "speaking"
  | "error";

export type Trigger = "presence" | "voice" | "button";

export const ACTIVE_STATES: ReadonlySet<LocalState> = new Set<LocalState>([
  "noticed",
  "connecting",
  "listening",
  "thinking",
  "taking_order",
  "needs_help",
  "speaking",
]);

/** The backend's states, as the old booth page mapped them (`booth/app.js`). */
export const BACKEND_STATE_MAP: Record<string, LocalState> = {
  LISTENING: "listening",
  THINKING: "thinking",
  SEEING: "thinking",
  REMEMBERING: "thinking",
  SPEAKING: "speaking",
  GREETING: "speaking",
  RECOMMENDING: "speaking",
  ANNOUNCING: "speaking",
  TAKING_ORDER: "taking_order",
  NEEDS_HELP: "needs_help",
};

/** What the page shows. Everything a guest can see is derived from this. */
export interface SessionView {
  state: LocalState;
  /** 16 §2k item 3: the backend is rebuilding its Gemini link. */
  reconnecting: boolean;
  errorMessage: string;
  /** 16 §2i item 6: THE HOST's latest line. A guest's line never reaches here. */
  hostLine: string;
  /**
   * 16 §2t item 4: the guest stopped speaking at least ONE_MOMENT_MS ago and
   * THE HOST has still not started. The caption says so until it does.
   */
  oneMoment: boolean;
  micAvailable: boolean;
  cameraAvailable: boolean;
  presenceAvailable: boolean;
  /** Camera or microphone trouble, for the Start screen only — never the TV. */
  notes: string[];
}

export interface SocketLike {
  readyState: number;
  binaryType?: string;
  send(data: string | ArrayBuffer): void;
  close(): void;
  onopen: ((this: unknown, ev: unknown) => void) | null;
  onmessage: ((this: unknown, ev: { data: unknown }) => void) | null;
  onerror: ((this: unknown, ev: unknown) => void) | null;
  onclose: ((this: unknown, ev: unknown) => void) | null;
}

export const SOCKET_OPEN = 1;

/** A control message from `/ws/session`, with only the fields the page reads. */
export interface ControlMessage {
  type?: string;
  state?: string;
  role?: string;
  text?: string;
  final?: boolean;
  active?: boolean;
  message?: string;
}

export interface SessionDeps {
  audio: AudioPort;
  presence: PresencePort;
  /** The configured agent link, for example http://localhost:8000. */
  agentUrl: string;
  /** ?debug=mic — the counters and the level readout (§2g item 5, §2r item 2a). */
  debugMic: boolean;
  createSocket(url: string): SocketLike;
  now(): number;
  fetchFn?: typeof fetch;
  logger?: Pick<Console, "info" | "warn" | "error">;
}

export interface StartOptions {
  video: HTMLVideoElement | null;
  cameraId?: string | undefined;
  micId?: string | undefined;
}

type Timer = ReturnType<typeof setTimeout> | null;

export class HostSession {
  private deps: SessionDeps;
  private listeners = new Set<() => void>();

  private view: SessionView = {
    state: "booth_off",
    reconnecting: false,
    errorMessage: "",
    hostLine: "",
    oneMoment: false,
    micAvailable: false,
    cameraAvailable: false,
    presenceAvailable: false,
    notes: [],
  };

  private ws: SocketLike | null = null;
  private endingByUs = false;
  private lastActivity = 0;
  private sessionStartedAt = 0;
  private armed = true;
  private lastAutoGreetAt = 0;
  private cameraStream: MediaStream | null = null;
  private videoEl: HTMLVideoElement | null = null;
  private micId: string | undefined;
  private lastRole: "visitor" | "agent" | null = null;
  private lastFinal = true;

  private timers: {
    tick: Timer;
    recover: Timer;
    snapshot: Timer;
    voiceActivity: Timer;
    micDebug: Timer;
    wake: Timer;
    busy: Timer;
    micCounters: Timer;
    vision: Timer;
    oneMoment: Timer;
    caption: Timer;
    playCounters: Timer;
  } = {
    tick: null,
    recover: null,
    snapshot: null,
    voiceActivity: null,
    micDebug: null,
    wake: null,
    busy: null,
    micCounters: null,
    vision: null,
    oneMoment: null,
    caption: null,
    playCounters: null,
  };

  private vision = { sentPeople: -1, sentAt: 0, warned: false };
  private voice = { onPolls: 0, belowSince: 0, sent: false };
  // 16 §2h item 2: what wake-on-speech is watching.
  private wake: { face: FaceReading | null; speechSince: number; lastEndAt: number; lastFaceAt: number } = {
    face: null,
    speechSince: 0,
    lastEndAt: 0,
    lastFaceAt: 0,
  };
  private cap = { sentAt: 0 };
  private busy: { tries: number; trigger: Trigger | null } = { tries: 0, trigger: null };
  // 16 §2k item 3: true between the backend's `reconnecting` true and false.
  private link = { reconnecting: false, since: 0 };
  // 16 §2u item 3: when THE HOST's own audio was last seen in flight, which is
  // what the echo gate's 300 ms tail is measured from. 0 means it has not played
  // since the page loaded.
  private echo = { lastPlayingAt: 0 };
  // 16 §2u item 4: when the caption was last rewritten, and the newest text
  // still waiting for the rate limit to allow it through.
  private caption: { lastAt: number; pending: string | null } = { lastAt: 0, pending: null };
  private playCounters = { since: 0 };
  private micDebug: { samples: { at: number; level: number }[] } = { samples: [] };
  private micCounters = { frames: 0, maxGapMs: 0, longTasks: 0, lastFrameAt: 0, since: 0 };
  private longTaskObserver: PerformanceObserver | null = null;

  constructor(deps: SessionDeps) {
    this.deps = deps;
    // 16 §2i item 2: printed once at load, so Rehman can see at a glance that
    // the flag took effect even before the screen is started.
    if (deps.debugMic) this.log().info("mic debug on");
  }

  /* ------------------------------ plumbing ------------------------------ */

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  }

  getView(): SessionView {
    return this.view;
  }

  private log() {
    return this.deps.logger ?? console;
  }

  private now() {
    return this.deps.now();
  }

  private emit() {
    this.listeners.forEach((listener) => listener());
  }

  private patch(patch: Partial<SessionView>) {
    this.view = { ...this.view, ...patch };
    this.emit();
  }

  isSessionActive() {
    return ACTIVE_STATES.has(this.view.state);
  }

  private setState(next: LocalState, errorMessage = "") {
    this.patch({ state: next, errorMessage: next === "error" ? errorMessage : "" });
  }

  /* ---------------------------- presence feed ---------------------------- */

  private reportVision(force: boolean) {
    const payload = {
      present: this.deps.presence.state === "present",
      people: Math.min(this.deps.presence.people, 50),
      objects: [] as unknown[],
    };
    const changed = payload.people !== this.vision.sentPeople;
    const due = this.now() - this.vision.sentAt >= C.VISION_REPORT_MS;
    if (!force && !(changed && due)) return;

    this.vision.sentPeople = payload.people;
    this.vision.sentAt = this.now();
    const doFetch = this.deps.fetchFn ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    void doFetch(`${this.base()}/api/vision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((response) => {
        if (!response.ok && !this.vision.warned) {
          this.vision.warned = true;
          this.log().warn(`Presence reporting failed: HTTP ${response.status}`);
        }
      })
      .catch(() => {
        if (!this.vision.warned) {
          this.vision.warned = true;
          this.log().warn("Presence reporting is unavailable.");
        }
      });
  }

  private base() {
    return this.deps.agentUrl.replace(/\/$/, "");
  }

  /* --------------------------- voice activity --------------------------- */

  private sendVoiceActivity(active: boolean) {
    // Never the same value twice in a row, and never a level: the backend only
    // needs to know whether the guest is talking right now (16 §2f item 2).
    if (this.voice.sent === active) return;
    if (!this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    this.voice.sent = active;
    this.ws.send(JSON.stringify({ type: "voice_activity", active }));
    this.onVoiceActivityChanged(active);
  }

  /**
   * 16 §2t item 4: the wait is always visibly alive.
   *
   * The page's own voice-activity end is the earliest moment anything knows the
   * guest has finished -- the backend only learns it when Gemini transcribes
   * them, a second or more later, and the server's own 500 ms end-of-speech wait
   * comes before even that. So the orb goes to THINKING from here rather than
   * waiting for a state message, and if THE HOST has still not started talking
   * ONE_MOMENT_MS later the caption says so.
   */
  private onVoiceActivityChanged(active: boolean) {
    if (active) {
      // The guest is talking again: there is nothing to wait for yet.
      this.clearOneMoment();
      return;
    }
    if (!this.isSessionActive()) return;
    // THE HOST already talking is not a wait, so its state is left alone.
    if (this.view.state !== "speaking") this.setState("thinking");
    if (this.timers.oneMoment) clearTimeout(this.timers.oneMoment);
    this.timers.oneMoment = setTimeout(() => {
      if (this.isSessionActive()) this.patch({ oneMoment: true });
    }, C.ONE_MOMENT_MS);
  }

  private clearOneMoment() {
    if (this.timers.oneMoment) clearTimeout(this.timers.oneMoment);
    this.timers.oneMoment = null;
    if (this.view.oneMoment) this.patch({ oneMoment: false });
  }

  private pollVoiceActivity = () => {
    if (!this.isSessionActive() || !this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    if (this.deps.debugMic) this.recordMicSample(this.deps.audio.getMicAmp());
    // 16 §2u item 3: inside the echo window the microphone is carrying THE
    // HOST's own voice, so nothing it reports means anything. The window is
    // ignored outright -- not merely treated as "not the guest" -- so a level
    // that is still decaying cannot start the on-poll count either.
    if (this.echoGateOpen()) {
      this.voice.onPolls = 0;
      this.voice.belowSince = 0;
      return;
    }
    if (this.deps.audio.getMicAmp() >= C.VOICE_ACTIVE_LEVEL) {
      this.voice.belowSince = 0;
      this.voice.onPolls += 1;
      // 0.05 of playback means THE HOST is speaking, so this is its own voice
      // coming back through the microphone, not the guest.
      if (this.voice.onPolls >= C.VOICE_ON_POLLS && this.deps.audio.getPlaybackAmp() < 0.05) {
        this.sendVoiceActivity(true);
      }
      return;
    }
    this.voice.onPolls = 0;
    if (!this.voice.belowSince) this.voice.belowSince = this.now();
    if (this.now() - this.voice.belowSince >= C.VOICE_OFF_MS) this.sendVoiceActivity(false);
  };

  private startVoiceActivity() {
    // The backend hears the guest only when Gemini transcribes them, a second or
    // more after the first syllable, which is too late to hold an announcement
    // back. The mic meter the orb already uses knows sooner.
    this.stopVoiceActivity();
    this.voice.onPolls = 0;
    this.voice.belowSince = 0;
    this.voice.sent = false;
    this.timers.voiceActivity = setInterval(this.pollVoiceActivity, C.VOICE_POLL_MS);
  }

  private stopVoiceActivity() {
    if (this.timers.voiceActivity) clearInterval(this.timers.voiceActivity);
    this.timers.voiceActivity = null;
  }

  /* ------------------------------ ?debug=mic ---------------------------- */

  private recordMicSample(level: number) {
    const cutoff = this.now() - MIC_DEBUG_WINDOW_MS;
    this.micDebug.samples.push({ at: this.now(), level });
    this.micDebug.samples = this.micDebug.samples.filter((sample) => sample.at >= cutoff);
  }

  private printMicLevel = () => {
    // 16 §2h item 6 / §2i item 2: the readout runs whenever the screen is
    // started, idle or in a session, because the levels Rehman has to measure
    // are the idle ones too.
    const level = this.deps.audio.getMicAmp();
    this.recordMicSample(level);
    const peak = this.micDebug.samples.reduce((top, sample) => (sample.level > top ? sample.level : top), 0);
    this.log().info("mic level", Number(level.toFixed(2)), "peak", Number(peak.toFixed(2)));
    const face = this.wake.face;
    if (face) {
      this.log().info("face ratio", Number(face.ratio.toFixed(2)), "frontal", face.frontal);
    }
  };

  private countMicFrame() {
    // 16 §2r item 2(a): the gap is measured between consecutive frames, so the
    // first frame of a window only sets the mark it is measured from.
    if (!this.deps.debugMic) return;
    const at = this.now();
    if (this.micCounters.lastFrameAt) {
      const gap = at - this.micCounters.lastFrameAt;
      if (gap > this.micCounters.maxGapMs) this.micCounters.maxGapMs = gap;
    }
    this.micCounters.lastFrameAt = at;
    this.micCounters.frames += 1;
  }

  private printMicCounters = () => {
    // The rate is taken over the window that actually elapsed rather than the
    // nominal 5 s, because a main thread busy enough to delay microphone frames
    // is busy enough to make this very interval run late.
    const seconds = (this.now() - this.micCounters.since) / 1000;
    const rate = seconds > 0 ? this.micCounters.frames / seconds : 0;
    this.log().info("mic frames/s", Number(rate.toFixed(1)), "maxgap_ms", Math.round(this.micCounters.maxGapMs), "longtasks", this.micCounters.longTasks);
    this.micCounters.frames = 0;
    this.micCounters.maxGapMs = 0;
    this.micCounters.longTasks = 0;
    this.micCounters.since = this.now();
  };

  /**
   * 16 §2u item 4: the debug-only proof that playback does not starve.
   *
   * `late_ms` is the worst lateness in the window and `underruns` the number of
   * chunks that passed PLAYBACK_UNDERRUN_MS, which is the gap a guest hears as
   * THE HOST's voice breaking up. The rate is taken over the window that really
   * elapsed, for the same reason the microphone counters are.
   */
  private printPlaybackCounters = () => {
    const seconds = (this.now() - this.playCounters.since) / 1000;
    const stats = this.deps.audio.takePlaybackStats();
    const rate = seconds > 0 ? stats.chunks / seconds : 0;
    this.log().info(
      "play chunks/s",
      Number(rate.toFixed(1)),
      "late_ms",
      Math.round(stats.maxLateMs),
      "underruns",
      stats.underruns,
    );
    this.playCounters.since = this.now();
  };

  private startMicCounters() {
    if (!this.deps.debugMic) return;
    this.stopMicCounters();
    this.micCounters = { frames: 0, maxGapMs: 0, longTasks: 0, lastFrameAt: 0, since: this.now() };
    this.playCounters.since = this.now();
    this.deps.audio.takePlaybackStats();
    this.timers.playCounters = setInterval(this.printPlaybackCounters, MIC_COUNTER_MS);
    try {
      this.longTaskObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.duration >= LONGTASK_MS) this.micCounters.longTasks += 1;
        }
      });
      this.longTaskObserver.observe({ type: "longtask", buffered: false });
    } catch {
      // A browser without the long-task entry type still gets frames and gaps.
      this.longTaskObserver = null;
    }
    this.timers.micCounters = setInterval(this.printMicCounters, MIC_COUNTER_MS);
  }

  private stopMicCounters() {
    if (this.timers.micCounters) clearInterval(this.timers.micCounters);
    this.timers.micCounters = null;
    if (this.timers.playCounters) clearInterval(this.timers.playCounters);
    this.timers.playCounters = null;
    if (this.longTaskObserver) {
      try {
        this.longTaskObserver.disconnect();
      } catch {
        /* already gone */
      }
      this.longTaskObserver = null;
    }
  }

  private startMicDebug() {
    if (!this.deps.debugMic) return;
    this.stopMicDebug();
    this.micDebug.samples = [];
    this.timers.micDebug = setInterval(this.printMicLevel, MIC_DEBUG_PRINT_MS);
    this.startMicCounters();
  }

  private stopMicDebug() {
    if (this.timers.micDebug) clearInterval(this.timers.micDebug);
    this.timers.micDebug = null;
    this.stopMicCounters();
  }

  /* ------------------------------ wake watch ---------------------------- */

  private openIdleMic() {
    // 16 §2h item 2: while the screen sits idle the microphone stays open for a
    // level reading only. `onMicFrame` sends nothing while the socket is closed,
    // so no audio leaves the browser until a conversation starts.
    if (!this.view.micAvailable) return;
    this.deps.audio.startMic(this.onMicFrame, this.micId).catch(() => {
      this.patch({ micAvailable: false });
    });
  }

  wakeReady(): boolean {
    // 16 §2h item 2: a face that is close AND looking at the screen, with a
    // voice behind it. Sound on its own is the nearby-chatter problem, not a guest.
    const face = this.wake.face;
    return Boolean(
      face &&
        face.ratio >= C.WAKE_MIN_FACE_RATIO &&
        face.frontal &&
        this.wake.speechSince &&
        this.now() - this.wake.speechSince >= C.WAKE_SPEECH_MS &&
        this.now() - this.wake.lastEndAt >= C.WAKE_AFTER_END_MS,
    );
  }

  private wakeCheck = () => {
    // §2k item 3: no new conversation may start while one is being recovered.
    if (this.link.reconnecting) {
      this.wake.speechSince = 0;
      return;
    }
    if (this.view.state !== "idle" || !this.view.micAvailable || this.hidden()) {
      this.wake.speechSince = 0;
      return;
    }
    if (this.deps.audio.getMicAmp() >= C.VOICE_ACTIVE_LEVEL) {
      if (!this.wake.speechSince) this.wake.speechSince = this.now();
    } else {
      this.wake.speechSince = 0;
    }
    if (!this.wakeReady()) return;
    this.wake.speechSince = 0;
    // A refused start (paused, another conversation) arrives as the usual error
    // event and is handled like any other refusal (§2h item 2).
    void this.startSession("voice");
  };

  private hidden() {
    return typeof document !== "undefined" && document.visibilityState !== "visible";
  }

  private startWakeWatch() {
    if (this.timers.wake) clearInterval(this.timers.wake);
    this.timers.wake = setInterval(this.wakeCheck, C.VOICE_POLL_MS);
  }

  /* ---------------------------- control messages ------------------------ */

  handleControl(message: ControlMessage) {
    // 16 §2g item 2: anything the backend says is proof the conversation is
    // alive, whatever its type.
    if (this.isSessionActive()) this.lastActivity = this.now();
    if (message.type === "agent_state_changed") {
      if (!this.isSessionActive()) return;
      const local = BACKEND_STATE_MAP[String(message.state)];
      if (local) {
        // 16 §2u item 4: THE HOST has stopped producing audio, so the quiet
        // until it speaks again is the guest's turn, not starved playback. Any
        // audio still queued keeps playing: a turn ends at the backend long
        // before its last chunk has been heard.
        if (local !== "speaking") this.deps.audio.endPlaybackTurn();
        this.setState(local);
      }
    } else if (message.type === "speech_transcript") {
      this.appendTranscript(String(message.role), String(message.text), Boolean(message.final));
    } else if (message.type === "capture_request") {
      if (this.isSessionActive()) this.captureSnapshot();
    } else if (message.type === "reconnecting") {
      this.setReconnecting(Boolean(message.active));
    } else if (message.type === "interrupted") {
      this.deps.audio.flushPlayback();
      this.onInterrupted();
    } else if (message.type === "error") {
      // 16 §2j item 3: this one refusal, and only this one, is retried quietly.
      // A paused refusal shows its message at once, like any other.
      if (message.message === BUSY_REFUSAL && this.busy.tries < C.BUSY_RETRY_LIMIT) {
        this.retryAfterBusy();
        return;
      }
      this.fail(String(message.message ?? ""));
    }
  }

  /** The turn was cut short, so whatever was being waited for is moot. */
  private onInterrupted() {
    this.clearOneMoment();
  }

  private appendTranscript(role: string, text: string, final: boolean) {
    // 16 §2i item 6: this screen faces the queue, and at the 5c test it showed
    // garbled guest speech for the next guest to read. The backend still sends
    // and logs these lines; only this screen stops printing them. §2t item 4
    // keeps that for the guest and shows THE HOST's own words.
    if (!C.SHOW_GUEST_TRANSCRIPT && role === "visitor") return;
    const continuing = this.lastRole === role && this.lastFinal === false;
    this.lastRole = role as "visitor" | "agent";
    this.lastFinal = final;
    // The text is always the whole line, so a still-open line is replaced.
    void continuing;
    this.setCaption(text);
  }

  /**
   * 16 §2u item 4: the caption is rewritten at most 10 times a second.
   *
   * Gemini's output transcription arrives in fragments that can land far faster
   * than that, and every one of them used to be a React render -- on the same
   * main thread that has to decode and schedule THE HOST's audio. The limit has
   * a trailing edge, so the newest text is always shown in the end: the last
   * fragment of a line is never the one that gets dropped.
   */
  private setCaption(text: string) {
    const since = this.now() - this.caption.lastAt;
    if (since >= C.CAPTION_MIN_MS) {
      if (this.timers.caption) clearTimeout(this.timers.caption);
      this.timers.caption = null;
      this.caption.pending = null;
      this.caption.lastAt = this.now();
      this.patch({ hostLine: text });
      return;
    }
    this.caption.pending = text;
    if (this.timers.caption) return;
    this.timers.caption = setTimeout(() => {
      this.timers.caption = null;
      const pending = this.caption.pending;
      this.caption.pending = null;
      if (pending === null) return;
      this.caption.lastAt = this.now();
      this.patch({ hostLine: pending });
    }, C.CAPTION_MIN_MS - since);
  }

  /** A caption still waiting its turn must not reappear over a cleared line. */
  private clearCaption() {
    if (this.timers.caption) clearTimeout(this.timers.caption);
    this.timers.caption = null;
    this.caption = { lastAt: 0, pending: null };
  }

  private setReconnecting(active: boolean) {
    // 16 §2k item 3: the conversation is not over -- the backend is rebuilding
    // the connection underneath it, for up to 30 seconds.
    if (this.link.reconnecting === active) return;
    this.link.reconnecting = active;
    if (active) {
      this.link.since = this.now();
    } else {
      // The soft cap counts conversation, not outage: give back exactly the time
      // the rebuild took, so an 8-minute chat is still 8 minutes of talking.
      if (this.link.since) this.sessionStartedAt += this.now() - this.link.since;
      this.link.since = 0;
      this.lastActivity = this.now();
    }
    this.patch({ reconnecting: active });
  }

  private retryAfterBusy() {
    // The refused socket is already closing behind this message. It is taken
    // down the quiet way -- no error state, no "Connection lost." from onclose
    // -- and the page simply stays on "Connecting…" until the retry lands.
    this.busy.tries += 1;
    this.endingByUs = true;
    if (this.timers.tick) clearInterval(this.timers.tick);
    this.timers.tick = null;
    this.stopVoiceActivity();
    this.deps.audio.stopMic();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Already gone: the backend closes the socket straight after refusing.
      }
      this.ws = null;
    }
    this.openIdleMic();
    this.setState("connecting");
    if (this.timers.busy) clearTimeout(this.timers.busy);
    this.timers.busy = setTimeout(() => void this.startSession(this.busy.trigger ?? "button", true), C.BUSY_RETRY_MS);
  }

  /**
   * 16 §2u item 3: is THE HOST's own voice in the room right now?
   *
   * True while its audio is playing and for ECHO_GATE_TAIL_MS after it stops.
   * The tail covers the speakers' own decay and the microphone's path back, and
   * it is measured from the last moment playback was actually observed, so it is
   * accurate to within one poll (100 ms) rather than depending on an end event.
   */
  echoGateOpen(): boolean {
    if (this.deps.audio.isPlaying()) {
      this.echo.lastPlayingAt = this.now();
      return true;
    }
    if (!this.echo.lastPlayingAt) return false;
    return this.now() - this.echo.lastPlayingAt < C.ECHO_GATE_TAIL_MS;
  }

  private onMicFrame = (buffer: ArrayBuffer) => {
    this.countMicFrame();
    if (!this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    // 16 §2u item 3: THE HOST never hears itself. The frame still goes -- the
    // uplink must not develop gaps, and Gemini's own end-of-speech detection
    // reads a continuous stream -- but it carries silence instead of the room.
    // Accepted consequence: a guest cannot talk over THE HOST; they speak after
    // it finishes, as at a counter.
    if (this.echoGateOpen()) {
      this.ws.send(new ArrayBuffer(buffer.byteLength));
      return;
    }
    this.ws.send(buffer);
  };

  /* ----------------------------- the session ---------------------------- */

  async startSession(trigger: Trigger, retry = false) {
    // 16 §2j item 3: a quiet retry is the exception to the guard -- the page is
    // deliberately still showing `connecting` from the refused attempt.
    if (this.isSessionActive() && !retry) return;
    this.busy.trigger = trigger;
    if (!retry) this.busy.tries = 0;
    this.lastRole = null;
    this.lastFinal = true;
    this.clearOneMoment();
    this.clearCaption();
    this.patch({ hostLine: "" });
    if (this.timers.recover) clearTimeout(this.timers.recover);
    this.timers.recover = null;
    // A quiet retry stays on "Connecting…": the guest has already been noticed
    // once, and "Oh — hello!" a second time would be a tell (§2j item 3).
    this.setState(!retry && trigger === "presence" ? "noticed" : "connecting");

    if (this.view.micAvailable) {
      try {
        await this.deps.audio.startMic(this.onMicFrame, this.micId);
      } catch {
        this.patch({ micAvailable: false, notes: ["Microphone unavailable."] });
      }
    }

    this.endingByUs = false;
    this.cap.sentAt = 0;
    // A session may begin with nobody yet detected (the key, or a wake where the
    // detector is between ticks); the empty-room timer starts counting now.
    this.wake.lastFaceAt = this.now();
    // 16 §2t item 3: the socket goes to the agent link's host, not this page's.
    const wsBase = this.base().replace(/^http:/, "ws:").replace(/^https:/, "wss:");
    try {
      this.ws = this.deps.createSocket(`${wsBase}/ws/session?trigger=${trigger}`);
    } catch {
      this.fail("Connection lost.");
      return;
    }
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => {
      this.sessionStartedAt = this.lastActivity = this.now();
      if (this.timers.tick) clearInterval(this.timers.tick);
      this.timers.tick = setInterval(this.tickCheck, 1000);
      this.startVoiceActivity();
      this.startMicDebug();
    };
    this.ws.onmessage = (event: { data: unknown }) => {
      if (event.data instanceof ArrayBuffer) {
        // 16 §2u item 4: THE HOST's audio is decoded and scheduled here and
        // nowhere else -- straight into the Web Audio graph, with no React state
        // update per chunk. `lastActivity` is a plain field, and `onHostAudio`
        // can only patch the view on the one chunk that clears "One moment…".
        // Chunks arrive many times a second; a render on each of them is what
        // starved playback in the first place.
        this.lastActivity = this.now();
        this.deps.audio.playPcm(event.data);
        this.onHostAudio();
        return;
      }
      try {
        this.handleControl(JSON.parse(String(event.data)) as ControlMessage);
      } catch {
        this.log().error("Invalid control message from backend.");
      }
    };
    this.ws.onerror = () => {
      if (!this.endingByUs) this.fail("Connection lost.");
    };
    this.ws.onclose = () => {
      if (!this.endingByUs) this.fail("Connection lost.");
    };
  }

  /** 16 §2t item 4: "until it does" — THE HOST has started talking. */
  private onHostAudio() {
    this.clearOneMoment();
  }

  endSession(reason: "user" | "timeout" | "cap" | "absent" | "error") {
    this.endingByUs = true;
    if (this.timers.tick) clearInterval(this.timers.tick);
    this.timers.tick = null;
    this.link.reconnecting = false;
    this.link.since = 0;
    // 16 §2j item 3: a retry that has not fired yet is no longer wanted.
    if (this.timers.busy) clearTimeout(this.timers.busy);
    this.timers.busy = null;
    this.busy.tries = 0;
    this.stopVoiceActivity();
    // The ?debug=mic readout is not stopped: it keeps running while the screen
    // is idle (§2h item 6). Only the page unloading stops it.
    this.deps.audio.stopMic();
    this.deps.audio.flushPlayback();
    // 16 §2g item 3: tell the backend why before the socket goes. On the error
    // path the socket is already gone, so there is nothing to tell.
    if (this.ws && this.ws.readyState === SOCKET_OPEN) {
      if (reason !== "error") {
        try {
          this.ws.send(JSON.stringify({ type: "session_end", reason }));
        } catch {
          // The close below ends the conversation either way.
        }
      }
      this.ws.close();
    }
    this.log().info("session end reason=" + reason);
    this.ws = null;
    this.armed = this.deps.presence.state === "absent";
    // 16 §2h item 2: wake on speech waits WAKE_AFTER_END_MS from here, so the
    // guest's last words cannot immediately start the next conversation.
    this.wake.lastEndAt = this.now();
    this.wake.speechSince = 0;
    this.cap.sentAt = 0;
    this.clearOneMoment();
    this.clearCaption();
    this.patch({ reconnecting: false, hostLine: "", oneMoment: false });
    if (reason !== "error") this.setState("idle");
    this.openIdleMic();
  }

  private sendWrapUp() {
    // 16 §2i item 3: at the cap THE HOST says goodbye itself instead of the page
    // cutting the conversation off mid-answer, which is what Rehman saw.
    if (this.cap.sentAt) return;
    if (!this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    this.cap.sentAt = this.now();
    this.ws.send(JSON.stringify({ type: "wrap_up" }));
  }

  speechInFlight() {
    return this.deps.audio.isPlaying() || this.voice.sent === true;
  }

  private tickCheck = () => {
    const current = this.now();
    // 16 §2k item 3: while the backend is rebuilding the connection none of
    // these clocks may run out. The guest is still standing there, and the
    // conversation is meant to carry on when it comes back.
    if (this.link.reconnecting) {
      this.lastActivity = current;
      this.wake.lastFaceAt = current;
      return;
    }
    // 16 §2g item 2: the clock counts real silence only. THE HOST's audio
    // arrives long before it finishes playing, and a talking guest is activity
    // too -- without this a 30-second answer looked like 30 seconds of idling.
    if (this.speechInFlight()) this.lastActivity = current;
    // 16 §2j item 8: behind another window the detector is paused, so no face is
    // reported however many people are at the counter. The empty-room timer
    // pauses with it rather than counting a hidden page as an empty room.
    if (typeof document !== "undefined" && document.hidden) this.wake.lastFaceAt = current;
    // 16 §2h item 4: nobody has been in front of the camera for a long time and
    // nothing is being said, so THE HOST is talking to an empty room. Only when
    // the detector is actually running: without it no face is ever reported and
    // every conversation would end here.
    if (this.view.presenceAvailable && current - this.wake.lastFaceAt >= C.NO_FACE_END_MS && !this.speechInFlight()) {
      this.endSession("absent");
      return;
    }
    if (current - this.lastActivity >= C.AUTO_RESET_MS) {
      this.endSession("timeout");
      return;
    }
    const elapsed = current - this.sessionStartedAt;
    // 16 §2i item 3: the hard limit, however the wrap-up goes.
    if (elapsed >= C.MAX_SESSION_MS + C.CAP_GRACE_MS) {
      this.endSession("cap");
      return;
    }
    if (elapsed < C.MAX_SESSION_MS) return;
    if (!this.cap.sentAt) {
      // Never interrupt an order being taken, a question being worked on, or a
      // sentence being spoken: wait for the conversation to come up for air.
      if (this.view.state === "taking_order" || this.view.state === "thinking" || this.speechInFlight()) return;
      this.sendWrapUp();
      return;
    }
    if (current - this.cap.sentAt >= WRAP_UP_SETTLE_MS && this.view.state === "listening" && !this.speechInFlight()) {
      this.endSession("cap");
    }
  };

  private fail(message: string) {
    if (this.view.state === "error") {
      this.patch({ errorMessage: message });
    } else {
      this.setState("error", message);
    }
    if (!this.endingByUs) this.endSession("error");
    if (this.timers.recover) clearTimeout(this.timers.recover);
    this.timers.recover = setTimeout(() => {
      if (this.view.state === "error") this.setState("idle");
    }, C.ERROR_AUTO_RECOVER_MS);
  }

  /* ------------------------------- presence ----------------------------- */

  private onArrival = () => {
    this.reportVision(true);
    if (
      this.view.state === "idle" &&
      this.armed &&
      this.now() - this.lastAutoGreetAt >= C.GREET_COOLDOWN_MS &&
      !this.hidden()
    ) {
      this.lastAutoGreetAt = this.now();
      this.armed = false;
      void this.startSession("presence");
    }
  };

  private onAbsent = () => {
    this.reportVision(true);
    this.armed = true;
  };

  private onFace = (face: FaceReading | null) => {
    // 16 §2h items 2 and 4: the newest reading, for wake on speech, the
    // empty-room timer and the ?debug=mic readout.
    this.wake.face = face;
    if (face) this.wake.lastFaceAt = this.now();
  };

  /* -------------------------------- start -------------------------------- */

  /** The one click a browser needs before the microphone, camera and sound. */
  async start({ video, cameraId, micId }: StartOptions): Promise<void> {
    this.videoEl = video;
    this.micId = micId;
    await this.deps.audio.init();
    const micAvailable = await this.deps.audio.probeMic(micId);
    let cameraAvailable = false;
    let presenceAvailable = false;

    if (video) {
      try {
        this.cameraStream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: C.SNAPSHOT_WIDTH },
            height: { ideal: C.SNAPSHOT_HEIGHT },
            ...(cameraId ? { deviceId: { exact: cameraId } } : { facingMode: "user" }),
          },
        });
        video.srcObject = this.cameraStream;
        await video.play();
        cameraAvailable = true;
      } catch {
        cameraAvailable = false;
      }
    }
    this.patch({ micAvailable, cameraAvailable });

    if (cameraAvailable && video) {
      try {
        await this.deps.presence.init(video, {
          onArrival: this.onArrival,
          onAbsent: this.onAbsent,
          onFace: this.onFace,
        });
        presenceAvailable = true;
        this.reportVision(true);
        this.timers.vision = setInterval(() => this.reportVision(false), C.VISION_REPORT_MS);
      } catch (error) {
        this.log().error(error);
        presenceAvailable = false;
      }
    }

    const notes: string[] = [];
    if (!micAvailable) notes.push("Microphone blocked — THE HOST cannot hear.");
    if (!cameraAvailable) notes.push("Camera blocked — the greeting and snapshots are off.");
    else if (!presenceAvailable) notes.push("Presence detection unavailable — press Space to start a conversation.");

    this.patch({ presenceAvailable, notes, state: "idle" });
    // 16 §2h items 2 and 6: from here the microphone is open for a level
    // reading, wake on speech is watching, and the debug readout (if asked for)
    // prints while the screen is idle as well as in a conversation.
    this.wake.lastFaceAt = this.now();
    this.openIdleMic();
    this.startWakeWatch();
    this.startMicDebug();
  }

  sendText(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    this.ws.send(JSON.stringify({ type: "text_input", text: trimmed }));
    this.lastActivity = this.now();
  }

  captureSnapshot() {
    if (!this.view.cameraAvailable || !this.videoEl || !this.ws || this.ws.readyState !== SOCKET_OPEN) return;
    try {
      const canvas = document.createElement("canvas");
      canvas.width = C.SNAPSHOT_WIDTH;
      canvas.height = C.SNAPSHOT_HEIGHT;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.drawImage(this.videoEl, 0, 0, C.SNAPSHOT_WIDTH, C.SNAPSHOT_HEIGHT);
      const dataUrl = canvas.toDataURL("image/jpeg", C.SNAPSHOT_QUALITY);
      const imageBase64 = dataUrl.slice("data:image/jpeg;base64,".length);
      this.ws.send(JSON.stringify({ type: "vision_frame", image_base64: imageBase64 }));
      this.lastActivity = this.now();
    } catch {
      this.log().warn("The camera frame could not be sent.");
    }
  }

  /** Page unload, or the route unmounting. */
  destroy() {
    for (const key of Object.keys(this.timers) as (keyof typeof this.timers)[]) {
      const timer = this.timers[key];
      if (timer) {
        clearTimeout(timer);
        clearInterval(timer);
      }
      this.timers[key] = null;
    }
    this.stopMicDebug();
    this.endingByUs = true;
    if (this.ws && this.ws.readyState === SOCKET_OPEN) this.ws.close();
    this.ws = null;
    this.deps.audio.stopMic();
    this.deps.audio.flushPlayback();
    this.deps.presence.stop();
    if (this.cameraStream) this.cameraStream.getTracks().forEach((track) => track.stop());
    this.cameraStream = null;
  }

  /* --------------------------- test seams only --------------------------- */

  /** Used by the tests to stand in for the detector's readings. */
  setFaceForTest(face: FaceReading | null) {
    this.onFace(face);
  }

  setStateForTest(state: LocalState) {
    this.setState(state);
  }

  getBusyTriesForTest() {
    return this.busy.tries;
  }
}
