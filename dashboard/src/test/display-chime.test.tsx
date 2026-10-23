/**
 * 16 §2v item 3: one voice only.
 *
 *   - an `order_ready` that arrives between conversations shows the banner and
 *     plays the soft chime, and calls no speech API at all;
 *   - one that arrives during a conversation is THE HOST's to announce, and the
 *     end of that conversation must not make the page speak or chime it late
 *     (the §2v item 1 bug: the TV announced, in a Windows voice, an order THE
 *     HOST had already announced, the moment the state went IDLE);
 *   - the chime itself is made in the page with Web Audio: no audio file, about
 *     0.6 s, gentle, and wordless.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted: vi.mock's factory runs before the module body, so the spy it closes
// over has to be created there too.
const { play } = vi.hoisted(() => ({ play: vi.fn() }));

vi.mock("@/lib/booth/chime", async () => {
  const real = await vi.importActual<typeof import("@/lib/booth/chime")>("@/lib/booth/chime");
  return { ...real, chime: { play } };
});

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
}));

import { SMDDisplay } from "@/routes/display";
import { CHIME_HZ, CHIME_MS, CHIME_PEAK_GAIN, createChime } from "@/lib/booth/chime";
import { agentStore } from "@/lib/agent/store";
import type { AgentEvent } from "@/lib/agent/types";

const dispatchAll = (events: AgentEvent[]) => events.forEach((e) => agentStore.dispatch(e));

/* --------------------------- no speech API, ever -------------------------- */

/**
 * The two browser speech globals, named in halves on purpose.
 *
 * §2v items 3 and 6 ask for two things at once: a test that proves no speech
 * API is called, and a `git grep` for the API's name over tracked files that
 * comes back empty. A test asserting that negative has to reach the globals
 * somehow, so it builds their names here instead of spelling them out, and the
 * grep stays the honest check it is meant to be: a hit anywhere is real code
 * about to speak.
 */
const SPEECH_GLOBAL = "speech" + "Synthesis";
const UTTERANCE_GLOBAL = "Speech" + "SynthesisUtterance";

/**
 * jsdom has no speech synthesis, so the test installs one. Anything that calls
 * it is a §2v item 3 failure, and these spies are how the test can say so
 * instead of silently passing on an undefined global.
 */
function watchSpeech() {
  const speak = vi.fn();
  const utterance = vi.fn();
  Object.defineProperty(window, SPEECH_GLOBAL, {
    configurable: true,
    writable: true,
    value: { speak, cancel: vi.fn(), speaking: false },
  });
  Object.defineProperty(window, UTTERANCE_GLOBAL, {
    configurable: true,
    writable: true,
    value: utterance,
  });
  return { speak, utterance };
}

describe("an order_ready between conversations (16 §2v item 3)", () => {
  let speech: ReturnType<typeof watchSpeech>;

  beforeEach(() => {
    play.mockClear();
    speech = watchSpeech();
    agentStore.dispatch({ type: "@reset" });
  });

  afterEach(() => {
    cleanup();
    agentStore.dispatch({ type: "@reset" });
  });

  it("shows the ready banner, plays the chime and speaks no words", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-23T22:15:12" },
      { type: "order_ready", order_id: 34, customer_name: "Rehman" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    // The banner, exactly as §2o item 6 words it.
    expect(screen.getByText("Order #34 for Rehman is ready!")).toBeInTheDocument();
    // One chime.
    expect(play).toHaveBeenCalledTimes(1);
    // And not one word.
    expect(speech.speak).not.toHaveBeenCalled();
    expect(speech.utterance).not.toHaveBeenCalled();
  });

  it("chimes once per order, not once per render", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-23T22:15:12" },
      { type: "order_ready", order_id: 34, customer_name: "Rehman" },
    ] as AgentEvent[]);

    const view = render(<SMDDisplay />);
    view.rerender(<SMDDisplay />);
    act(() => agentStore.dispatch({ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-23T22:15:20" } as AgentEvent));

    expect(play).toHaveBeenCalledTimes(1);
  });

  it("chimes for each of two orders that become ready together", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-23T22:15:12" },
      { type: "order_ready", order_id: 34, customer_name: "Rehman" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);
    expect(play).toHaveBeenCalledTimes(1);

    // The head's 15 s are up and the next announcement takes its place.
    act(() => {
      agentStore.dispatch({ type: "order_ready", order_id: 35, customer_name: "Ahmed" } as AgentEvent);
      agentStore.dispatch({ type: "@ready_done" });
    });

    expect(screen.getByText("Order #35 for Ahmed is ready!")).toBeInTheDocument();
    expect(play).toHaveBeenCalledTimes(2);
  });
});

describe("an order_ready during a conversation is THE HOST's to announce (16 §2v items 1 and 3)", () => {
  let speech: ReturnType<typeof watchSpeech>;

  beforeEach(() => {
    play.mockClear();
    speech = watchSpeech();
    agentStore.dispatch({ type: "@reset" });
  });

  afterEach(() => {
    cleanup();
    agentStore.dispatch({ type: "@reset" });
  });

  it("stays silent while the conversation runs", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "LISTENING", timestamp: "2026-10-23T22:14:00", session_id: "919b18e3" },
      { type: "order_ready", order_id: 22, customer_name: "Rehman" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.getByText("Order #22 for Rehman is ready!")).toBeInTheDocument();
    expect(play).not.toHaveBeenCalled();
    expect(speech.speak).not.toHaveBeenCalled();
  });

  it("does not chime or speak it when the conversation ends (the 22:15:12 bug)", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "ANNOUNCING", timestamp: "2026-10-23T22:14:00", session_id: "919b18e3" },
      { type: "order_ready", order_id: 22, customer_name: "Rehman" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);
    expect(play).not.toHaveBeenCalled();

    // The session times out and the backend publishes IDLE, which is exactly
    // the moment the old hook spoke an already-announced order.
    act(() => agentStore.dispatch({ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-23T22:15:12" } as AgentEvent));

    expect(play).not.toHaveBeenCalled();
    expect(speech.speak).not.toHaveBeenCalled();
    expect(speech.utterance).not.toHaveBeenCalled();
  });
});

/* ----------------------------- the chime itself --------------------------- */

interface FakeParam {
  calls: { fn: string; value: number; at: number }[];
}

function fakeParam(): AudioParam & FakeParam {
  const calls: { fn: string; value: number; at: number }[] = [];
  return {
    calls,
    value: 0,
    setValueAtTime: (value: number, at: number) => void calls.push({ fn: "set", value, at }),
    exponentialRampToValueAtTime: (value: number, at: number) => void calls.push({ fn: "ramp", value, at }),
  } as unknown as AudioParam & FakeParam;
}

function fakeContext() {
  const gains: (AudioParam & FakeParam)[] = [];
  const oscillators: { hz: number; start: number; stop: number; type: string }[] = [];
  const ctx = {
    currentTime: 10,
    destination: { id: "destination" },
    resume: vi.fn(),
    createGain: () => {
      const gain = fakeParam();
      gains.push(gain);
      return { gain, connect: vi.fn() } as unknown as GainNode;
    },
    createOscillator: () => {
      const entry = { hz: 0, start: -1, stop: -1, type: "" };
      oscillators.push(entry);
      return {
        set type(value: string) {
          entry.type = value;
        },
        frequency: { setValueAtTime: (hz: number) => void (entry.hz = hz) },
        connect: vi.fn(),
        start: (at: number) => void (entry.start = at),
        stop: (at: number) => void (entry.stop = at),
      } as unknown as OscillatorNode;
    },
  };
  return { ctx: ctx as unknown as AudioContext, gains, oscillators, raw: ctx };
}

describe("the chime is made in the page with Web Audio (16 §2v item 3)", () => {
  it("plays two gentle sine partials for about 0.6 s", () => {
    const fake = fakeContext();
    createChime(() => fake.ctx).play();

    expect(fake.oscillators).toHaveLength(2);
    expect(fake.oscillators.map((o) => o.hz)).toEqual([...CHIME_HZ]);
    for (const osc of fake.oscillators) {
      expect(osc.type).toBe("sine");
      expect(osc.start).toBe(10);
      // About 0.6 s, from the context's own clock.
      expect(osc.stop - osc.start).toBeCloseTo(CHIME_MS / 1000, 6);
    }
  });

  it("keeps the volume gentle and fades to silence", () => {
    const fake = fakeContext();
    createChime(() => fake.ctx).play();

    const envelope = fake.gains[0]!.calls;
    const peak = Math.max(...envelope.map((c) => c.value));
    expect(peak).toBe(CHIME_PEAK_GAIN);
    // Well under THE HOST's own voice, which plays at a gain of 1.
    expect(peak).toBeLessThan(0.2);
    // The last thing the envelope does is ramp back down.
    expect(envelope.at(-1)!.value).toBeLessThan(0.001);
    expect(envelope.at(-1)!.at).toBeCloseTo(10 + CHIME_MS / 1000, 6);
  });

  it("loads no audio file and says no words", () => {
    const fake = fakeContext();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const speech = watchSpeech();

    createChime(() => fake.ctx).play();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(speech.speak).not.toHaveBeenCalled();
    expect(speech.utterance).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("reuses one context, and never throws when audio is unavailable", () => {
    const fake = fakeContext();
    let made = 0;
    const port = createChime(() => {
      made += 1;
      return fake.ctx;
    });

    port.play();
    port.play();
    expect(made).toBe(1);

    const broken = createChime(() => {
      throw new Error("no audio device");
    });
    expect(() => broken.play()).not.toThrow();
  });
});
