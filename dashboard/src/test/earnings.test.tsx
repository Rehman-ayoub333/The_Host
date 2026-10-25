/**
 * 16 §2z — the money, on the operator's screen only.
 *
 * Rehman asked to see exactly what the orders brought in and from where, so
 * there is no confusion at the end of the day. Four things are proved here:
 * the two collection buttons send the right body and a complimentary order
 * keeps one; a collected card says how it was paid; the panel's figures,
 * formatting and warnings; and the summary refetches after an order event
 * without ever writing to the order store (§2o item 10a).
 */
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const calls: { url: string; body: unknown; hasToken: boolean }[] = [];

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { EarningsPanel, OrderCard, fmtRs } from "@/components/host/panels";
// Imported statically on purpose: a dynamic import after vi.resetModules()
// would hand the service a second copy of the store, and the assertions here
// are about the store the panel actually reads.
import { loadEarnings, scheduleEarningsRefresh } from "@/lib/agent/service";
import { agentStore, initialSnapshot, reduce } from "@/lib/agent/store";
import type { AgentEvent, AgentSnapshot, Earnings, Order } from "@/lib/agent/types";

const READY: Order = {
  id: 27,
  items: [{ name: "Chicken Burger", quantity: 1, price: "Rs. 650" }],
  status: "READY",
  guest_name: "Ahmed",
  total: "Rs. 650",
};

const EARNINGS: Earnings = {
  date: "2026-10-25",
  earned: 12450,
  earned_cash: 7200,
  earned_qr: 5250,
  earned_unrecorded: 0,
  to_collect: 1850,
  on_the_house: 600,
  on_the_house_orders: 2,
  paid_orders: 24,
  cancelled_orders: 1,
  by_item: [
    { name: "Chicken Burger", quantity: 9, amount: 5850 },
    { name: "Blue Lemonade", quantity: 6, amount: 1500 },
  ],
  unpriced_orders: 0,
};

beforeEach(() => {
  calls.length = 0;
  window.localStorage.setItem(
    "thehost.agent.config",
    JSON.stringify({ agentUrl: "http://localhost:8000", token: "operator-token-for-this-test" }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({
        url: String(url),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        hasToken: "X-Operator-Token" in headers,
      });
      if (String(url).includes("/api/earnings.csv")) {
        return { ok: true, status: 200, text: async () => "order_id,time\n27,19:05:00\n" } as unknown as Response;
      }
      if (String(url).includes("/api/earnings")) {
        return { ok: true, status: 200, json: async () => EARNINGS } as unknown as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as unknown as Response;
    }),
  );
  agentStore.dispatch({ type: "@reset" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

/* ----------------------------- the two buttons ---------------------------- */

describe("collecting an order records how it was paid (§2z item 3)", () => {
  it("offers Cash and QR, and sends payment_method with COLLECTED", async () => {
    render(<OrderCard order={READY} now={Date.now()} />);

    const cash = screen.getByRole("button", { name: /Collected · Cash/ });
    const qr = screen.getByRole("button", { name: /Collected · QR/ });
    expect(screen.queryByRole("button", { name: /^Collected$/ })).toBeNull();

    await act(async () => {
      cash.click();
    });
    expect(calls.at(-1)!.url).toContain("/api/orders/27/status");
    expect(calls.at(-1)!.body).toEqual({ status: "COLLECTED", payment_method: "CASH" });
    expect(calls.at(-1)!.hasToken).toBe(true);

    await act(async () => {
      qr.click();
    });
    expect(calls.at(-1)!.body).toEqual({ status: "COLLECTED", payment_method: "QR" });
  });

  it("gives a complimentary order one plain Collected button and no payment type", async () => {
    render(<OrderCard order={{ ...READY, complimentary: true }} now={Date.now()} />);

    expect(screen.queryByRole("button", { name: /Collected · Cash/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Collected · QR/ })).toBeNull();
    await act(async () => {
      screen.getByRole("button", { name: "Collected" }).click();
    });

    expect(calls.at(-1)!.body).toEqual({ status: "COLLECTED" });
  });

  it("sends no payment type with any other status", async () => {
    render(<OrderCard order={{ ...READY, status: "CONFIRMED" }} now={Date.now()} />);

    await act(async () => {
      screen.getByRole("button", { name: "Preparing" }).click();
    });

    expect(calls.at(-1)!.body).toEqual({ status: "PREPARING" });
  });
});

describe("a collected card says how it was paid", () => {
  it.each([
    ["CASH" as const, "Paid · Cash"],
    ["QR" as const, "Paid · QR"],
  ])("shows %s as %s", (method, label) => {
    render(<OrderCard order={{ ...READY, status: "COLLECTED", payment_method: method }} now={Date.now()} />);
    expect(screen.getByText(label)).toBeTruthy();
  });

  it("says not recorded for a row from before this phase", () => {
    render(<OrderCard order={{ ...READY, status: "COLLECTED" }} now={Date.now()} />);
    expect(screen.getByText("Paid · not recorded")).toBeTruthy();
  });

  it("says On the house instead, and never a payment type", () => {
    render(<OrderCard order={{ ...READY, status: "COLLECTED", complimentary: true }} now={Date.now()} />);
    expect(screen.getByText("On the house")).toBeTruthy();
    expect(screen.queryByText(/^Paid · /)).toBeNull();
  });
});

/* ------------------------------- the panel -------------------------------- */

describe("the Earnings panel (§2z item 5)", () => {
  it("formats every amount as Rs. 12,450", () => {
    expect(fmtRs(12450)).toBe("Rs. 12,450");
    expect(fmtRs(0)).toBe("Rs. 0");
    expect(fmtRs(1234567)).toBe("Rs. 1,234,567");
  });

  it("shows the four figures, the smaller counts and the By item table", () => {
    agentStore.dispatch({ type: "@earnings", earnings: EARNINGS });
    render(<EarningsPanel />);

    expect(screen.getByText("Rs. 12,450")).toBeTruthy();
    expect(screen.getByText("Rs. 7,200")).toBeTruthy();
    expect(screen.getByText("Rs. 5,250")).toBeTruthy();
    expect(screen.getByText("Rs. 1,850")).toBeTruthy();
    expect(screen.getByText(/On the house/)).toBeTruthy();
    expect(screen.getByText(/Paid orders/)).toBeTruthy();
    expect(screen.getByText(/Cancelled/)).toBeTruthy();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Chicken Burger")).toBeTruthy();
    expect(within(table).getByText("Rs. 5,850")).toBeTruthy();
    expect(within(table).getByText("Blue Lemonade")).toBeTruthy();
  });

  it("shows the unrecorded line only when there is something unrecorded", () => {
    agentStore.dispatch({ type: "@earnings", earnings: EARNINGS });
    const { unmount } = render(<EarningsPanel />);
    expect(screen.queryByText(/collected without a payment type/)).toBeNull();
    unmount();

    agentStore.dispatch({ type: "@earnings", earnings: { ...EARNINGS, earned_unrecorded: 900 } });
    render(<EarningsPanel />);
    expect(screen.getByText("Rs. 900 collected without a payment type")).toBeTruthy();
  });

  it("warns about an unpriced order", () => {
    agentStore.dispatch({ type: "@earnings", earnings: { ...EARNINGS, unpriced_orders: 2 } });
    render(<EarningsPanel />);
    expect(screen.getByText(/2 orders had no price and are in none of these figures/)).toBeTruthy();
  });

  it("asks for the CSV with the token when the button is pressed", async () => {
    agentStore.dispatch({ type: "@earnings", earnings: EARNINGS });
    const createUrl = vi.fn(() => "blob:sales");
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    render(<EarningsPanel />);

    await act(async () => {
      screen.getByRole("button", { name: /Download today's sales/ }).click();
    });

    const csv = calls.find((c) => c.url.includes("/api/earnings.csv"))!;
    expect(csv).toBeTruthy();
    expect(csv.hasToken).toBe(true);
    expect(createUrl).toHaveBeenCalled();
  });

  it("shows Demo Mode's own figures, never the real ones", () => {
    // A real figure nothing in the demo set could produce, so the two cannot
    // be confused: if the panel showed it, it would be showing the takings.
    agentStore.dispatch({
      type: "@earnings",
      earnings: { ...EARNINGS, earned: 777, earned_cash: 777, earned_qr: 0, to_collect: 0 },
    });
    agentStore.dispatch({ type: "@mode", mode: "demo" });
    render(<EarningsPanel />);

    // The tag's own words, uppercased by CSS rather than in the markup.
    expect(screen.getByText("Demo data")).toBeTruthy();
    expect(screen.queryByText("Rs. 777")).toBeNull();
    expect(screen.getByText("Rs. 12,450")).toBeTruthy();
    // And the CSV of real sales is not offered while a demo is running.
    expect(screen.getByRole("button", { name: /Download today's sales/ })).toHaveProperty("disabled", true);
  });

  it("says so plainly when there are no figures yet", () => {
    render(<EarningsPanel />);
    expect(screen.getByText("No figures yet")).toBeTruthy();
  });
});

/* ------------------------- the refetch, and §2o item 10(a) ----------------- */

describe("the summary follows the orders without owning them", () => {
  it("refetches once, 1 s after a burst of order events", async () => {
    vi.useFakeTimers();
    try {
      scheduleEarningsRefresh();
      scheduleEarningsRefresh();
      scheduleEarningsRefresh();
      expect(calls.filter((c) => c.url.includes("/api/earnings"))).toHaveLength(0);

      await vi.advanceTimersByTimeAsync(1_000);

      expect(calls.filter((c) => c.url.includes("/api/earnings"))).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("puts the figures in the store and leaves the orders to the events", async () => {
    await loadEarnings();

    expect(agentStore.get().earnings).toEqual(EARNINGS);
    // 16 §2o item 10(a): orders come from events alone, and this summary is
    // not one of them.
    expect(agentStore.get().orders).toEqual([]);
    expect(calls.some((c) => c.url.includes("/api/orders"))).toBe(false);
  });

  it("never loads in demo mode", async () => {
    agentStore.dispatch({ type: "@mode", mode: "demo" });

    await loadEarnings();

    expect(calls.filter((c) => c.url.includes("/api/earnings"))).toHaveLength(0);
  });

  it("keeps the last figures when the request fails", async () => {
    agentStore.dispatch({ type: "@earnings", earnings: EARNINGS });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as unknown as Response));

    await loadEarnings();

    expect(agentStore.get().earnings).toEqual(EARNINGS);
  });
});

describe("the order store still carries payment_method through an event", () => {
  it("keeps it on the stored order", () => {
    const feed = (events: AgentEvent[]): AgentSnapshot => events.reduce<AgentSnapshot>((s, e) => reduce(s, e), initialSnapshot);
    const s = feed([
      { type: "order_created", order: READY },
      { type: "order_updated", order: { ...READY, status: "COLLECTED", payment_method: "QR" } },
    ] as AgentEvent[]);

    expect(s.orders[0]!.payment_method).toBe("QR");
    expect(s.orders).toHaveLength(1);
  });
});
