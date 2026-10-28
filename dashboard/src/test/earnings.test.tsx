/**
 * 16 §2z and §2zf item 4 — the money, on the operator's screen only.
 *
 * Rehman asked to see exactly what the orders brought in and from where, so
 * there is no confusion at the end of the day. Since pay-first the money is
 * taken before the food, so what is proved here is: the two "Paid" presses on
 * an order waiting for payment send the right body, collection is one press
 * again, a card says how it was paid, the panel's figures, formatting and
 * warnings, and the summary refetches after an order event without ever
 * writing to the order store (§2o item 10a).
 */
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const calls: { url: string; body: unknown; hasToken: boolean }[] = [];

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { EarningsPanel, OrderCard, fmtRs } from "@/components/host/panels";
// Imported statically on purpose: a dynamic import after vi.resetModules()
// would hand the service a second copy of the store, and the assertions here
// are about the store the panel actually reads.
import { loadEarnings, scheduleEarningsRefresh, setOrderStatus } from "@/lib/agent/service";
import { toast } from "sonner";
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
  awaiting_payment: 1850,
  on_the_house: 600,
  on_the_house_orders: 2,
  paid_orders: 24,
  cancelled_orders: 1,
  refunded: 250,
  refunded_orders: 1,
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

/* -------------------- 16 §2zf item 4: taking the money -------------------- */

const UNPAID: Order = {
  id: 27,
  items: [{ name: "Chicken Burger", quantity: 1, price: "Rs. 650" }],
  status: "AWAITING_PAYMENT",
  guest_name: "Ahmed",
  total: "Rs. 650",
  payment_method: "CASH",
};

describe("an order waiting for payment (§2zf item 4)", () => {
  it("shows the total large, the method the guest named, and the three buttons", () => {
    render(<OrderCard order={UNPAID} now={Date.now()} />);

    // The status line, and the box under it naming the method the guest gave.
    expect(screen.getByText(/● Waiting for payment/)).toBeTruthy();
    expect(screen.getByText(/^Waiting for payment · Cash$/)).toBeTruthy();
    expect(screen.getAllByText("Rs. 650").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Paid · Cash/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Paid · QR/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("sends CONFIRMED with the payment the team really took", async () => {
    render(<OrderCard order={UNPAID} now={Date.now()} />);

    await act(async () => {
      screen.getByRole("button", { name: /Paid · Cash/ }).click();
    });
    expect(calls.at(-1)!.url).toContain("/api/orders/27/status");
    expect(calls.at(-1)!.body).toEqual({ status: "CONFIRMED", payment_method: "CASH" });
    expect(calls.at(-1)!.hasToken).toBe(true);

    await act(async () => {
      screen.getByRole("button", { name: /Paid · QR/ }).click();
    });
    expect(calls.at(-1)!.body).toEqual({ status: "CONFIRMED", payment_method: "QR" });
  });

  it("highlights the method the guest named, and still allows the other", () => {
    const { unmount } = render(<OrderCard order={UNPAID} now={Date.now()} />);
    expect(screen.getByRole("button", { name: /Paid · Cash/ }).className).toContain("text-gold");
    expect(screen.getByRole("button", { name: /Paid · QR/ }).className).not.toContain("bg-gold/10");
    unmount();

    render(<OrderCard order={{ ...UNPAID, payment_method: "QR" }} now={Date.now()} />);
    expect(screen.getByRole("button", { name: /Paid · QR/ }).className).toContain("text-gold");
  });

  it("offers no kitchen button at all: nothing starts before the money", () => {
    render(<OrderCard order={UNPAID} now={Date.now()} />);

    expect(screen.queryByRole("button", { name: "Preparing" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ready" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Collected/ })).toBeNull();
  });

  it("says so plainly when the guest was never asked how they would pay", () => {
    render(<OrderCard order={{ ...UNPAID, payment_method: null }} now={Date.now()} />);

    expect(screen.getByText(/● Waiting for payment/)).toBeTruthy();
    expect(screen.queryByText(/Waiting for payment · /)).toBeNull();
  });
});

/* ------------ 16 §2zf item 4: collection is one button again -------------- */

describe("collecting an order (§2zf item 4, replacing §2z item 3)", () => {
  it("is one press for every order, because the payment is already recorded", async () => {
    render(<OrderCard order={{ ...READY, payment_method: "CASH" }} now={Date.now()} />);

    expect(screen.queryByRole("button", { name: /Collected · Cash/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Collected · QR/ })).toBeNull();
    await act(async () => {
      screen.getByRole("button", { name: "Collected" }).click();
    });

    expect(calls.at(-1)!.url).toContain("/api/orders/27/status");
    expect(calls.at(-1)!.body).toEqual({ status: "COLLECTED" });
    expect(calls.at(-1)!.hasToken).toBe(true);
  });

  it("is one press for an order on the house too", async () => {
    render(<OrderCard order={{ ...READY, complimentary: true }} now={Date.now()} />);

    await act(async () => {
      screen.getByRole("button", { name: "Collected" }).click();
    });

    expect(calls.at(-1)!.body).toEqual({ status: "COLLECTED" });
  });

  it("sends no payment type with any other status", async () => {
    render(<OrderCard order={{ ...READY, status: "CONFIRMED", payment_method: "CASH" }} now={Date.now()} />);

    await act(async () => {
      screen.getByRole("button", { name: "Preparing" }).click();
    });

    expect(calls.at(-1)!.body).toEqual({ status: "PREPARING" });
  });

  it("shows the backend's own refusal to the operator", async () => {
    // An order from before pay-first, with no method on it at all: the
    // backend answers 400 and the operator reads why (§2ze item 6(a)).
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 400, json: async () => ({ detail: "Choose Cash or QR." }) }) as unknown as Response),
    );

    const ok = await setOrderStatus(27, "COLLECTED");

    expect(ok).toBe(false);
    expect(toast.error).toHaveBeenCalledWith("Choose Cash or QR.");
  });
});

describe("a paid card says how it was paid", () => {
  it.each([
    ["CASH" as const, "Paid · Cash"],
    ["QR" as const, "Paid · QR"],
  ])("shows %s as %s", (method, label) => {
    render(<OrderCard order={{ ...READY, status: "COLLECTED", payment_method: method }} now={Date.now()} />);
    expect(screen.getByText(label)).toBeTruthy();
  });

  // 16 §2zf item 4: a CONFIRMED order has been paid for since this phase, so
  // the badge appears the moment the money is taken, not at collection.
  it.each(["CONFIRMED", "PREPARING", "READY"] as const)("shows it on a %s order too", (status) => {
    render(<OrderCard order={{ ...READY, status, payment_method: "QR" }} now={Date.now()} />);
    expect(screen.getByText("Paid · QR")).toBeTruthy();
  });

  it("says nothing of the kind while the order is still waiting for payment", () => {
    render(<OrderCard order={UNPAID} now={Date.now()} />);
    // The two "Paid ·" presses are there; the badge that states a payment as
    // a fact is not, because no payment has been taken yet.
    const labelled = screen.queryAllByText(/^Paid · (Cash|QR|not recorded)$/);
    expect(labelled.length).toBeGreaterThan(0);
    for (const el of labelled) expect(el.tagName).toBe("BUTTON");
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
    expect(screen.getByText("Waiting for payment")).toBeTruthy();
    expect(screen.getByText(/On the house/)).toBeTruthy();
    expect(screen.getByText(/Paid orders/)).toBeTruthy();
    expect(screen.getByText(/Cancelled/)).toBeTruthy();
    // 16 §2zf item 4: money taken and then given back has a line of its own.
    expect(screen.getByText(/Refunded/)).toBeTruthy();
    expect(screen.getByText("Rs. 250")).toBeTruthy();

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
      earnings: { ...EARNINGS, earned: 777, earned_cash: 777, earned_qr: 0, awaiting_payment: 0 },
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
