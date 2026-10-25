/**
 * 16 §2o item 8 / 20 §4 item 3 — the public display must never call a
 * token-protected endpoint. With role=smd it starts no analytics polling and
 * makes no authenticated request: only GET /api/menu (no token).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 16 §2z item 7 adds the two earnings endpoints: the money is the operator's,
// never the public display's.
const TOKEN_PROTECTED = ["/api/orders", "/api/visitors", "/api/activity", "/api/analytics", "/api/metrics", "/api/operator", "/api/earnings", "/api/earnings.csv"];

type Call = { url: string; hasToken: boolean };

let calls: Call[] = [];
let sockets: FakeSocket[] = [];

class FakeSocket {
  static OPEN = 1;
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

beforeEach(() => {
  calls = [];
  sockets = [];
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({ url: String(url), hasToken: "X-Operator-Token" in headers });
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

/** Opens the socket for a role and lets the onopen work settle. */
async function connectAs(role: "dashboard" | "smd") {
  const service = await import("@/lib/agent/service");
  service.connectAgent(role);
  sockets.at(-1)?.onopen?.();
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  return service;
}

describe("role=smd (the public display)", () => {
  it("opens its socket without a token in the query", async () => {
    await connectAs("smd");

    expect(sockets.at(-1)!.url).toContain("role=smd");
    expect(sockets.at(-1)!.url).not.toContain("token=");
  });

  it("calls GET /api/menu and nothing else", async () => {
    await connectAs("smd");

    const paths = calls.map((c) => c.url.replace("http://localhost:8000", ""));
    expect(paths).toEqual(["/api/menu"]);
  });

  it("sends no X-Operator-Token on any request it makes", async () => {
    await connectAs("smd");

    expect(calls.every((c) => !c.hasToken)).toBe(true);
  });

  it("calls no token-protected endpoint at all", async () => {
    await connectAs("smd");

    for (const protectedPath of TOKEN_PROTECTED) {
      expect(calls.some((c) => c.url.includes(protectedPath))).toBe(false);
    }
  });

  it("starts no analytics polling: 60 s later it has still called only the menu", async () => {
    vi.useFakeTimers();
    try {
      const service = await import("@/lib/agent/service");
      service.connectAgent("smd");
      sockets.at(-1)?.onopen?.();
      await vi.advanceTimersByTimeAsync(60_000);

      expect(calls.filter((c) => c.url.includes("/api/analytics"))).toHaveLength(0);
      expect(calls.filter((c) => c.url.includes("/api/metrics"))).toHaveLength(0);
      // 16 §2z item 5: the Earnings panel refetches every 30 s, so a minute of
      // smd time would have caught it twice if the display ever loaded it.
      expect(calls.filter((c) => c.url.includes("/api/earnings"))).toHaveLength(0);
      service.disconnectAgent();
    } finally {
      vi.useRealTimers();
    }
  });

  it("makes no token-protected reload when an order event arrives", async () => {
    await connectAs("smd");
    calls = [];
    sockets.at(-1)!.onmessage?.({
      data: JSON.stringify({ type: "order_updated", event_id: 5, order: { id: 27, items: [], status: "READY" } }),
    });
    await new Promise((r) => setTimeout(r, 0));

    expect(calls.some((c) => c.url.includes("/api/orders"))).toBe(false);
  });
});

describe("role=dashboard (the operator)", () => {
  it("does use the token-protected endpoints, so the smd result is a real difference", async () => {
    await connectAs("dashboard");

    const joined = calls.map((c) => c.url).join(" ");
    expect(joined).toContain("/api/orders");
    expect(joined).toContain("/api/visitors");
    expect(joined).toContain("/api/activity");
    expect(calls.some((c) => c.hasToken)).toBe(true);
  });

  it("carries the token in its socket query", async () => {
    await connectAs("dashboard");

    expect(sockets.at(-1)!.url).toContain("role=dashboard");
    expect(sockets.at(-1)!.url).toContain("token=");
  });
});
