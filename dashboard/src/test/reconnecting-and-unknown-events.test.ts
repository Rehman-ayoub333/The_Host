/**
 * 16 §2s item 4(a) — the Command Center must not crash as a whole.
 *
 * Found by the ten-minute soak on 22 Oct 2026 (session 00428ef4): the Gemini
 * link stalled, the backend published `reconnecting`, and from that moment
 * every page threw "Cannot read properties of undefined (reading 'state')" and
 * the router's "Try again / Go home" page replaced the whole dashboard.
 *
 * The chain: live_session's _send_control publishes EVERY control event to the
 * bus, so `reconnecting` arrives on /ws/events; it was missing from the
 * AgentEvent union, so the reducer's switch looked exhaustive to TypeScript
 * while really falling out of the bottom and returning undefined; dispatch
 * stored that as the snapshot; and every useAgent selector then read a field of
 * undefined. These tests pin both halves: the event is handled, and the reducer
 * can never return anything but a snapshot.
 */
import { describe, expect, it } from "vitest";

import { agentStore, initialSnapshot, reduce } from "@/lib/agent/store";
import type { AgentEvent } from "@/lib/agent/types";

const reconnecting = (active: boolean) =>
  ({ type: "reconnecting", active, session_id: "00428ef4", event_id: 1 }) as AgentEvent;

describe("the reconnecting event the backend really sends", () => {
  it("leaves the snapshot alone instead of blanking it", () => {
    const next = reduce(initialSnapshot, reconnecting(true));

    expect(next).toBeDefined();
    expect(next).toBe(initialSnapshot);
  });

  it("is still a snapshot when recovery ends", () => {
    const started = reduce(initialSnapshot, reconnecting(true));
    const ended = reduce(started, reconnecting(false));

    expect(ended).toBeDefined();
    expect(ended.state).toBe("offline");
  });

  it("keeps the fields the selectors read, which is what used to throw", () => {
    const next = reduce(initialSnapshot, reconnecting(true));

    // The two selectors in the soak's stack traces: AppShell reads `state`,
    // the demo tag reads `mode`.
    expect(() => next.state).not.toThrow();
    expect(next.state).toBe("offline");
    expect(next.mode).toBe("live");
  });
});

describe("an event this build does not know about", () => {
  it("changes nothing rather than returning undefined", () => {
    const next = reduce(initialSnapshot, { type: "a_future_event" } as unknown as AgentEvent);

    expect(next).toBeDefined();
    expect(next).toBe(initialSnapshot);
  });

  it("never blanks the live store, however many arrive", () => {
    agentStore.dispatch({ type: "@reset" });
    for (const type of ["reconnecting", "a_future_event", "another_one"]) {
      agentStore.dispatch({ type } as unknown as AgentEvent);
    }

    const snap = agentStore.get();
    expect(snap).toBeDefined();
    // Before the fix this read threw, and went on throwing for the rest of
    // the session because the snapshot stayed undefined.
    expect(typeof snap.state).toBe("string");
    expect(typeof snap.mode).toBe("string");
  });

  it("does not stop the next real event from being applied", () => {
    agentStore.dispatch({ type: "@reset" });
    agentStore.dispatch(reconnecting(true));
    agentStore.dispatch({
      type: "agent_state_changed",
      state: "LISTENING",
      event_id: 2,
      timestamp: "2026-10-22T19:10:11",
    } as AgentEvent);

    expect(agentStore.get().state).toBe("listening");
    expect(agentStore.get().lastAgentState).toBe("LISTENING");
  });
});
