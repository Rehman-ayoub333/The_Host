/**
 * 16 §2o item 8 / 20 §4 item 1 — the backend's real value types.
 * Order ids are integers, price and total are already-formatted strings shown
 * exactly as sent, and every time field is a booth-local ISO string parsed
 * with new Date(value).getTime().
 */
import { describe, expect, it } from "vitest";

import { initialSnapshot, reduce } from "@/lib/agent/store";
import { fmtAgo, fmtClock, toMs } from "@/lib/agent/ui";
import type { AgentEvent, Order } from "@/lib/agent/types";

const draft: Order = {
  id: 27,
  items: [
    { name: "Chicken Burger", quantity: 1, price: "Rs. 650" },
    { name: "Blue Lemonade", quantity: 2, price: "Rs. 150" },
  ],
  status: "PENDING_CONFIRMATION",
  guest_name: "Ahmed",
  total: "Rs. 950",
  timestamp: "2026-10-16T10:06:10",
};

describe("order ids are integers", () => {
  it("keeps the id a number through order_created", () => {
    const s = reduce(initialSnapshot, { type: "order_created", order: draft } as AgentEvent);

    expect(s.orders).toHaveLength(1);
    expect(s.orders[0]!.id).toBe(27);
    expect(typeof s.orders[0]!.id).toBe("number");
  });

  it("matches an update to its draft by numeric id, without duplicating it", () => {
    const created = reduce(initialSnapshot, { type: "order_created", order: draft } as AgentEvent);
    const updated = reduce(created, {
      type: "order_updated",
      order: { ...draft, status: "CONFIRMED" },
    } as AgentEvent);

    expect(updated.orders).toHaveLength(1);
    expect(updated.orders[0]!.status).toBe("CONFIRMED");
  });

  it("keeps order_ready's order_id a number", () => {
    const s = reduce(initialSnapshot, { type: "order_ready", order_id: 27, customer_name: "Ahmed" } as AgentEvent);

    expect(s.orderReady?.order_id).toBe(27);
    expect(typeof s.orderReady?.order_id).toBe("number");
  });
});

describe("prices and totals are strings, shown exactly as sent", () => {
  it("stores the total unchanged, with no second Rs prefix and no arithmetic", () => {
    const s = reduce(initialSnapshot, { type: "order_created", order: { ...draft, total: "Rs. 1,300" } } as AgentEvent);

    expect(s.orders[0]!.total).toBe("Rs. 1,300");
    expect(typeof s.orders[0]!.total).toBe("string");
    expect(Number.isNaN(Number(s.orders[0]!.total))).toBe(true); // never used as a number
  });

  it("keeps each item price as its own formatted string", () => {
    const s = reduce(initialSnapshot, { type: "order_created", order: draft } as AgentEvent);

    expect(s.orders[0]!.items.map((i) => i.price)).toEqual(["Rs. 650", "Rs. 150"]);
  });

  it("accepts a null total, which the cards render as nothing", () => {
    const s = reduce(initialSnapshot, { type: "order_created", order: { ...draft, total: null } } as AgentEvent);

    expect(s.orders[0]!.total).toBeNull();
  });
});

describe("booth-local time strings", () => {
  it("parses a timezone-less ISO string to a number, as local time", () => {
    const ms = toMs("2026-10-16T10:06:10");

    expect(typeof ms).toBe("number");
    expect(Number.isNaN(ms)).toBe(false);
    expect(new Date(ms!).getHours()).toBe(10);
    expect(new Date(ms!).getMinutes()).toBe(6);
  });

  it("gives null — never NaN — for null, undefined, empty or nonsense", () => {
    expect(toMs(null)).toBeNull();
    expect(toMs(undefined)).toBeNull();
    expect(toMs("")).toBeNull();
    expect(toMs("not a time")).toBeNull();
  });

  it("shows no countdown and no ago text when the field is null", () => {
    // A null estimate must produce no countdown at all, rather than an
    // invented one: the card's `remaining` is derived from toMs().
    expect(toMs(null)).toBeNull();
    expect(fmtAgo(null, Date.now())).toBe("");
    expect(fmtClock(null)).toBe("--:--:--");
  });

  it("formats a real ago text from a real string", () => {
    const tenMinutesAgo = new Date(Date.now() - 10 * 60_000);
    const p = (n: number) => String(n).padStart(2, "0");
    const iso = `${tenMinutesAgo.getFullYear()}-${p(tenMinutesAgo.getMonth() + 1)}-${p(tenMinutesAgo.getDate())}T${p(tenMinutesAgo.getHours())}:${p(tenMinutesAgo.getMinutes())}:${p(tenMinutesAgo.getSeconds())}`;

    expect(fmtAgo(iso, Date.now())).toBe("10 min ago");
  });

  it("never produces NaN in a countdown subtraction", () => {
    const withEstimate = toMs("2026-10-16T10:11:10");
    const placed = toMs("2026-10-16T10:06:10");

    expect(withEstimate! - placed!).toBe(5 * 60_000);
  });
});
