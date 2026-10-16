/**
 * 16 §2o item 10(a) — where the dashboard's orders come from.
 *
 * Orders are kept current by the events themselves. GET /api/orders is called
 * only when the /ws/events socket (re)connects, never in response to an order
 * event, so a slow reload can never land after a newer event and overwrite it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initialSnapshot, reduce } from "@/lib/agent/store";
import type { AgentEvent, AgentSnapshot, Order } from "@/lib/agent/types";

/* ------------------------------------------------------------------ */
/* service level: which events cause a REST reload                     */
/* ------------------------------------------------------------------ */

let calls: string[] = [];
let sockets: FakeSocket[] = [];

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    sockets.push(this);
  }
  close() {
    /* nothing to tear down in the double */
  }
}

const ordersCalls = () => calls.filter((u) => u.includes("/api/orders"));

beforeEach(() => {
  calls = [];
  sockets = [];
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      calls.push(String(url));
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ menu: [], orders: [], counts: {}, visitors: [], activity: [] }),
      } as unknown as Response);
    }),
  );
  window.localStorage.setItem("thehost.agent.config", JSON.stringify({ agentUrl: "http://localhost:8000", token: "unused-in-this-test" }));
});

afterEach(async () => {
  const { disconnectAgent } = await import("@/lib/agent/service");
  disconnectAgent();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  vi.resetModules();
});

async function connectDashboard() {
  const service = await import("@/lib/agent/service");
  service.connectAgent("dashboard");
  sockets.at(-1)?.onopen?.();
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  return service;
}

const send = (event: unknown) => sockets.at(-1)!.onmessage?.({ data: JSON.stringify(event) });

describe("GET /api/orders is tied to the connection, not to order events", () => {
  it("a (re)connect triggers exactly one GET /api/orders", async () => {
    await connectDashboard();

    expect(ordersCalls()).toHaveLength(1);
  });

  it("each reconnect triggers exactly one more", async () => {
    const service = await connectDashboard();
    expect(ordersCalls()).toHaveLength(1);

    service.connectAgent("dashboard");
    sockets.at(-1)?.onopen?.();
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(ordersCalls()).toHaveLength(2);
  });

  it("an order_created event triggers no GET /api/orders", async () => {
    await connectDashboard();
    calls = [];

    send({ type: "order_created", event_id: 10, order: { id: 27, items: [], status: "PENDING_CONFIRMATION" } });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(ordersCalls()).toHaveLength(0);
  });

  it("an order_updated event triggers no GET /api/orders", async () => {
    await connectDashboard();
    calls = [];

    send({ type: "order_updated", event_id: 11, order: { id: 27, items: [], status: "CONFIRMED" } });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(ordersCalls()).toHaveLength(0);
  });

  it("a whole order lifetime of events triggers no reload at all", async () => {
    await connectDashboard();
    calls = [];

    let id = 20;
    for (const status of ["PENDING_CONFIRMATION", "CONFIRMED", "PREPARING", "READY", "COLLECTED"]) {
      send({ type: "order_updated", event_id: id++, order: { id: 27, items: [], status } });
    }
    send({ type: "order_ready", event_id: id++, order_id: 27, customer_name: "Ahmed" });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));

    expect(ordersCalls()).toHaveLength(0);
  });

  it("the order list still ends up right, from the events alone", async () => {
    await connectDashboard();

    send({ type: "order_created", event_id: 30, order: { id: 27, items: [{ name: "Blue Lemonade", quantity: 1 }], status: "PENDING_CONFIRMATION" } });
    send({ type: "order_updated", event_id: 31, order: { id: 27, items: [{ name: "Blue Lemonade", quantity: 1 }], status: "CONFIRMED", guest_name: "Ahmed" } });
    await new Promise((r) => setTimeout(r, 0));

    const { agentStore } = await import("@/lib/agent/store");
    const orders = agentStore.get().orders;
    expect(orders).toHaveLength(1);
    expect(orders[0]!.status).toBe("CONFIRMED");
    expect(orders[0]!.guest_name).toBe("Ahmed");
  });
});

/* ------------------------------------------------------------------ */
/* store level: replace, never merge; the snapshot replaces the active */
/* ------------------------------------------------------------------ */

const feed = (events: AgentEvent[], from: AgentSnapshot = initialSnapshot): AgentSnapshot =>
  events.reduce<AgentSnapshot>((s, e) => reduce(s, e), from);

const draft: Order = {
  id: 35,
  items: [{ name: "Blue Lemonade", quantity: 1, price: "Rs. 250" }],
  status: "PENDING_CONFIRMATION",
  total: "Rs. 250",
  timestamp: "2026-10-16T19:50:23",
};

describe("an order event replaces the stored order with the same id", () => {
  it("adds the name when a later event carries it", () => {
    const s = feed([
      { type: "order_created", order: draft },
      { type: "order_updated", order: { ...draft, guest_name: "Ahmed" } },
    ] as AgentEvent[]);

    expect(s.orders).toHaveLength(1);
    expect(s.orders[0]!.guest_name).toBe("Ahmed");
    expect(s.orders[0]!.status).toBe("PENDING_CONFIRMATION");
  });

  it("replaces rather than merges, so a field the backend cleared really clears", () => {
    const s = feed([
      { type: "order_created", order: { ...draft, guest_name: "Ahmed" } },
      { type: "order_updated", order: { ...draft, guest_name: null } },
    ] as AgentEvent[]);

    expect(s.orders[0]!.guest_name).toBeNull();
  });

  it("adds an order it has never seen", () => {
    const s = feed([{ type: "order_updated", order: { ...draft, id: 99, status: "READY" } }] as AgentEvent[]);

    expect(s.orders.map((o) => o.id)).toEqual([99]);
  });

  it("never duplicates an id across created then updated", () => {
    const s = feed([
      { type: "order_created", order: draft },
      { type: "order_updated", order: { ...draft, status: "CONFIRMED" } },
      { type: "order_updated", order: { ...draft, status: "PREPARING" } },
    ] as AgentEvent[]);

    expect(s.orders).toHaveLength(1);
    expect(s.orders[0]!.status).toBe("PREPARING");
  });
});

describe("state_snapshot replaces the active set", () => {
  const snapshot = (active: Order[]): AgentEvent =>
    ({
      type: "state_snapshot",
      boot_id: "9f2c1a",
      operational_mode: "ONLINE",
      conversation_state: "IDLE",
      present: false,
      active_orders: active,
      timestamp: "2026-10-16T19:55:00",
    }) as AgentEvent;

  it("puts the snapshot's active orders in place of the stored active ones", () => {
    const before = feed([
      { type: "order_updated", order: { ...draft, id: 10, status: "PREPARING" } },
      { type: "order_updated", order: { ...draft, id: 11, status: "READY" } },
    ] as AgentEvent[]);

    const after = feed([snapshot([{ ...draft, id: 12, status: "CONFIRMED" }])], before);

    expect(after.orders.map((o) => o.id).sort()).toEqual([12]);
  });

  it("keeps finished orders, which a snapshot never carries", () => {
    const before = feed([
      { type: "order_updated", order: { ...draft, id: 10, status: "COLLECTED" } },
      { type: "order_updated", order: { ...draft, id: 11, status: "PREPARING" } },
    ] as AgentEvent[]);

    const after = feed([snapshot([{ ...draft, id: 12, status: "READY" }])], before);

    expect(after.orders.map((o) => o.id).sort()).toEqual([10, 12]);
  });

  it("keeps a draft still being taken", () => {
    const before = feed([{ type: "order_created", order: draft }] as AgentEvent[]);

    const after = feed([snapshot([])], before);

    expect(after.orders.map((o) => o.id)).toEqual([35]);
    expect(after.orders[0]!.status).toBe("PENDING_CONFIRMATION");
  });

  it("lets the snapshot win when it carries an id the store already holds", () => {
    const before = feed([{ type: "order_updated", order: { ...draft, id: 10, status: "CONFIRMED" } }] as AgentEvent[]);

    const after = feed([snapshot([{ ...draft, id: 10, status: "READY" }])], before);

    expect(after.orders).toHaveLength(1);
    expect(after.orders[0]!.status).toBe("READY");
  });

  it("empties the active set when the snapshot carries none", () => {
    const before = feed([{ type: "order_updated", order: { ...draft, id: 10, status: "PREPARING" } }] as AgentEvent[]);

    const after = feed([snapshot([])], before);

    expect(after.orders).toEqual([]);
  });
});
