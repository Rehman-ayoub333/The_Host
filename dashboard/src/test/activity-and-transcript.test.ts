/**
 * 16 §2o item 8 — the activity feed has exactly one source, and a line still
 * being spoken is replaced rather than appended to.
 */
import { describe, expect, it } from "vitest";

import { agentStore, initialSnapshot, reduce } from "@/lib/agent/store";
import type { AgentEvent, AgentSnapshot, Order } from "@/lib/agent/types";

const order: Order = { id: 27, items: [{ name: "Chicken Burger", quantity: 1 }], status: "CONFIRMED", guest_name: "Ahmed", total: "Rs. 650" };

const feed = (events: AgentEvent[]): AgentSnapshot => events.reduce<AgentSnapshot>((s, e) => reduce(s, e), initialSnapshot);

describe("the activity feed comes only from agent_activity", () => {
  it("adds nothing of its own for any other event (20 §4 item 2)", () => {
    const s = feed([
      { type: "order_ready", order_id: 27, customer_name: "Ahmed" },
      { type: "operational_mode_changed", mode: "PAUSED", reason: "operator" },
      { type: "order_created", order: { ...order, status: "PENDING_CONFIRMATION" } },
      { type: "order_updated", order },
      { type: "visitor_identified", name: "Ahmed", returning: true, visits: 3 },
      { type: "memory_updated", name: "Ahmed", visits: 3, returning: true, last_seen: "2026-10-16T10:06:10" },
      { type: "person_detected", person_id: "p-1" },
      { type: "person_left", person_id: "p-1" },
      { type: "recommendation", item: "Loaded Fries", reason: "Guests often pair them" },
      { type: "system_status_changed", component: "ai_agent", status: "degraded" },
      { type: "error", message: "Something went wrong." },
    ] as AgentEvent[]);

    expect(s.activity).toEqual([]);
  });

  it("still applies those events to the rest of the state", () => {
    const s = feed([
      { type: "order_updated", order },
      { type: "operational_mode_changed", mode: "PAUSED", reason: "operator" },
      { type: "visitor_identified", name: "Ahmed", returning: true, visits: 3 },
    ] as AgentEvent[]);

    expect(s.orders[0]!.id).toBe(27);
    expect(s.opMode).toEqual({ mode: "PAUSED", reason: "operator" });
    expect(s.focus?.name).toBe("Ahmed");
  });

  it("adds exactly one row per agent_activity event, newest first", () => {
    const s = feed([
      { type: "agent_activity", kind: "order", label: "Order #27 created", detail: "Chicken Burger", timestamp: "2026-10-16T10:06:10" },
      { type: "agent_activity", kind: "order", label: "Order #27 ready", detail: "ready", timestamp: "2026-10-16T10:12:00" },
    ] as AgentEvent[]);

    expect(s.activity).toHaveLength(2);
    expect(s.activity[0]!.label).toBe("Order #27 ready");
    expect(s.activity[1]!.label).toBe("Order #27 created");
  });

  it("keeps the backend's own time string on each row", () => {
    const s = feed([
      { type: "agent_activity", kind: "system", label: "Conversation started", timestamp: "2026-10-16T10:06:10" },
    ] as AgentEvent[]);

    expect(s.activity[0]!.timestamp).toBe("2026-10-16T10:06:10");
  });

  it("does not duplicate a row when an order event and its agent_activity both arrive", () => {
    const s = feed([
      { type: "order_updated", order },
      { type: "agent_activity", kind: "order", label: "Order #27 updated", detail: "confirmed", timestamp: "2026-10-16T10:07:00" },
    ] as AgentEvent[]);

    expect(s.activity).toHaveLength(1);
  });
});

describe("a partial line is replaced, never appended", () => {
  const line = (text: string, final: boolean, session = "a1b2c3d4"): AgentEvent =>
    ({ type: "speech_transcript", role: "visitor", text, final, session_id: session, timestamp: "2026-10-16T10:06:10" }) as AgentEvent;

  it("replaces the open line for the same role and keeps the whole text", () => {
    const s = feed([line("I'd like a", false), line("I'd like a chicken", false), line("I'd like a chicken burger", true)]);

    expect(s.transcript).toHaveLength(1);
    expect(s.transcript[0]!.text).toBe("I'd like a chicken burger");
    expect(s.transcript[0]!.final).toBe(true);
  });

  it("never concatenates the fragments", () => {
    const s = feed([line("I'd like a", false), line("I'd like a chicken burger", true)]);

    expect(s.transcript[0]!.text).not.toContain("I'd like aI'd like a");
  });

  it("starts a new line when the role changes", () => {
    const s = feed([
      line("A chicken burger please", true),
      { type: "speech_transcript", role: "agent", text: "One Chicken Burger", final: false, session_id: "a1b2c3d4" } as AgentEvent,
    ]);

    expect(s.transcript).toHaveLength(2);
    expect(s.transcript[0]!.speaker).toBe("visitor");
    expect(s.transcript[1]!.speaker).toBe("host");
    expect(s.transcript[1]!.final).toBe(false);
  });

  it("keeps at most the last 50 lines, in memory only", () => {
    const many: AgentEvent[] = [];
    for (let i = 0; i < 60; i++) many.push(line(`line ${i}`, true));
    const s = feed(many);

    expect(s.transcript).toHaveLength(50);
    expect(s.transcript.at(-1)!.text).toBe("line 59");
  });

  it("records the session id so a new conversation can be divided", () => {
    const s = feed([line("first", true, "aaaaaaaa"), line("second", true, "bbbbbbbb")]);

    expect(s.transcript[0]!.session_id).toBe("aaaaaaaa");
    expect(s.transcript[1]!.session_id).toBe("bbbbbbbb");
    expect(s.sessionId).toBe("bbbbbbbb");
  });
});

describe("spoken lines are held in memory only", () => {
  it("writes nothing to localStorage or sessionStorage (16 §2o item 5c)", () => {
    const secret = "I would like a chicken burger and a blue lemonade";
    window.localStorage.clear();
    window.sessionStorage.clear();

    agentStore.dispatch({ type: "speech_transcript", role: "visitor", text: secret, final: true, session_id: "a1b2c3d4" } as AgentEvent);

    expect(agentStore.get().transcript.at(-1)!.text).toBe(secret);
    const persisted = JSON.stringify([
      ...Object.entries({ ...window.localStorage }),
      ...Object.entries({ ...window.sessionStorage }),
    ]);
    expect(persisted).not.toContain("chicken burger");
    expect(persisted).not.toContain(secret);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});

describe("capture_request is ignored quietly", () => {
  it("changes nothing in the snapshot (20 §4 item 5)", () => {
    const before = reduce(initialSnapshot, { type: "agent_activity", kind: "system", label: "Conversation started" } as AgentEvent);
    const after = reduce(before, { type: "capture_request" } as AgentEvent);

    expect(after).toBe(before);
  });
});

describe("the ready queue never drops an announcement", () => {
  it("keeps both when two orders become ready together", () => {
    const s = feed([
      { type: "order_ready", order_id: 27, customer_name: "Ahmed" },
      { type: "order_ready", order_id: 28, customer_name: null },
    ] as AgentEvent[]);

    expect(s.readyQueue).toEqual([
      { order_id: 27, customer_name: "Ahmed" },
      { order_id: 28, customer_name: null },
    ]);
  });

  it("drops only the head once its 15 s are up", () => {
    const s = feed([
      { type: "order_ready", order_id: 27, customer_name: "Ahmed" },
      { type: "order_ready", order_id: 28 },
    ] as AgentEvent[]);
    const next = reduce(s, { type: "@ready_done" });

    expect(next.readyQueue).toEqual([{ order_id: 28, customer_name: undefined }]);
  });
});
