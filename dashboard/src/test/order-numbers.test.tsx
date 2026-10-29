/**
 * Phase 7n: the guest's order number on the screens (16 §2zi item 3(b), (d)).
 *
 * Orders are numbered 1, 2, 3 as they are placed. The internal id stays in the
 * URLs the operator API is called with (item 3(d)) and is never shown, because
 * every draft consumes one and no guest was ever told it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// The panels reach the backend through the service; nothing here needs it.
vi.mock("@/lib/agent/service", () => ({
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
  getPosters: () => Promise.resolve({ posters: [] as string[] }),
  posterSrc: (path: string) => path,
  setOrderStatus: () => Promise.resolve(true),
  announceAgain: () => Promise.resolve(true),
  sendSessionNote: () => Promise.resolve(true),
  updateVisitor: () => Promise.resolve(true),
  forgetVisitor: () => Promise.resolve(true),
  reloadVisitors: () => Promise.resolve(),
  pauseHost: () => Promise.resolve(null),
  resumeHost: () => Promise.resolve(null),
  startTakeover: () => Promise.resolve(null),
  endTakeover: () => Promise.resolve(null),
  endSession: () => Promise.resolve(null),
  retryConnection: () => Promise.resolve(null),
}));

import { agentStore } from "@/lib/agent/store";
import { readyHeadline } from "@/routes/display";
import { LivePanel } from "@/components/host/LivePanel";
import { OrderCard, OrdersPanel } from "@/components/host/panels";
import type { AgentEvent, Order } from "@/lib/agent/types";

const placed: Order = {
  id: 27,
  number: 3,
  items: [{ name: "Chicken Burger", quantity: 1, price: "Rs. 650" }],
  status: "AWAITING_PAYMENT",
  guest_name: "Ahmed",
  total: "Rs. 650",
  timestamp: "2026-10-29T10:06:10",
  payment_method: "CASH",
};

const dispatchAll = (events: AgentEvent[]) =>
  events.forEach((e) => agentStore.dispatch(e));

beforeEach(() => {
  agentStore.dispatch({ type: "@reset" });
});

afterEach(() => {
  cleanup();
  agentStore.dispatch({ type: "@reset" });
});

describe("the ready banner on /display", () => {
  it("calls out the number the guest was given, not the internal id", () => {
    expect(readyHeadline({ order_id: 27, order_number: 3, customer_name: "Ahmed" })).toBe(
      "Order #3 for Ahmed is ready!",
    );
    expect(readyHeadline({ order_id: 27, order_number: 3 })).toBe("Order #3 is ready!");
  });

  it("falls back to the id for an order placed before the column existed", () => {
    // Those rows carry no number, and their id is the only one anyone knew.
    expect(readyHeadline({ order_id: 27 })).toBe("Order #27 is ready!");
    expect(readyHeadline({ order_id: 27, order_number: null })).toBe("Order #27 is ready!");
  });

  it("carries the number from the event into the queue", () => {
    dispatchAll([
      { type: "order_ready", order_id: 27, order_number: 3, customer_name: "Ahmed" },
    ] as AgentEvent[]);

    const state = agentStore.get();
    expect(state.orderReady?.order_number).toBe(3);
    expect(state.readyQueue[0]?.order_number).toBe(3);
    // The id is still there, so two announcements can be told apart.
    expect(state.readyQueue[0]?.order_id).toBe(27);
  });
});

describe("the orders panel", () => {
  it("shows a placed order by its number", () => {
    dispatchAll([{ type: "order_created", order: placed }] as AgentEvent[]);

    render(<OrdersPanel />);

    expect(screen.getByText("Order #3")).toBeInTheDocument();
    expect(screen.queryByText("Order #27")).toBeNull();
  });

  it("shows a card with no number yet as a draft", () => {
    // The panel itself lists active orders only, so the card is rendered
    // directly: this is about what the card says, not what the panel selects.
    render(
      <OrderCard
        order={{ ...placed, number: null, status: "PENDING_CONFIRMATION" }}
        now={Date.now()}
      />,
    );

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByText("Order #27")).toBeNull();
  });
});

describe("the Live panel", () => {
  it("shows the waiting-for-payment card by its number", () => {
    dispatchAll([{ type: "order_updated", order: placed }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Waiting for payment")).toBeInTheDocument();
    expect(screen.getByText("Order #3")).toBeInTheDocument();
    expect(screen.queryByText("Order #27")).toBeNull();
  });
});
