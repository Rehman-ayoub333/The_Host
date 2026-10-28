/**
 * 16 §2o item 8 — what each screen actually renders.
 *  - the public display renders no spoken line of any kind;
 *  - the Live panel shows an open draft and hides it once it is placed;
 *  - the Live panel shows an order waiting for payment, with the two presses
 *    that take the money (16 §2zf item 4);
 *  - a complimentary order is badged "On the house".
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Collected by the mocked service below, so the assertions are about exactly
// what the panel asked the backend to send. Nothing is stored anywhere else.
const { notesSent } = vi.hoisted(() => ({ notesSent: [] as string[] }));

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  // 16 §2t item 3: /display reads the agent link to reach /ws/session.
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
  // 16 §2ze item 5: the display asks for the poster list on mount.
  getPosters: () => Promise.resolve({ posters: [] as string[] }),
  posterSrc: (path: string) => path,
  setOrderStatus: () => Promise.resolve(true),
  announceAgain: () => Promise.resolve(true),
  // 16 §2zf item 6: the operator's note into a live conversation.
  sendSessionNote: (text: string) => {
    notesSent.push(text);
    return Promise.resolve(true);
  },
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

import { LivePanel } from "@/components/host/LivePanel";
import { OrderCard } from "@/components/host/panels";
import { SMDDisplay } from "@/routes/display";
import { agentStore } from "@/lib/agent/store";
import type { AgentEvent, Order } from "@/lib/agent/types";

const GUEST_LINE = "I would like a chicken burger";
const HOST_LINE = "One Chicken Burger, coming up";

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

const dispatchAll = (events: AgentEvent[]) => events.forEach((e) => agentStore.dispatch(e));

beforeEach(() => {
  notesSent.length = 0;
  agentStore.dispatch({ type: "@reset" });
});

afterEach(() => {
  cleanup();
  agentStore.dispatch({ type: "@reset" });
});

describe("the public display renders no spoken line from the event stream", () => {
  it("shows neither the guest's words nor THE HOST's, even if events reach the store", () => {
    // The backend never sends these to role=smd; this proves the screen would
    // not render them even so. 16 §2t item 4 adds THE HOST's caption, but it is
    // fed by the page's own /ws/session socket -- never by this event stream,
    // which still carries no transcripts at all.
    dispatchAll([
      { type: "agent_state_changed", state: "LISTENING", timestamp: "2026-10-16T10:06:10", session_id: "a1b2c3d4" },
      { type: "speech_transcript", role: "visitor", text: GUEST_LINE, final: true, session_id: "a1b2c3d4" },
      { type: "speech_transcript", role: "agent", text: HOST_LINE, final: true, session_id: "a1b2c3d4" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.queryByText(new RegExp(GUEST_LINE, "i"))).toBeNull();
    expect(screen.queryByText(new RegExp(HOST_LINE, "i"))).toBeNull();
    expect(document.body.textContent).not.toContain(GUEST_LINE);
    expect(document.body.textContent).not.toContain(HOST_LINE);
  });

  it("shows no partial line either", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "SPEAKING", timestamp: "2026-10-16T10:06:10" },
      { type: "speech_transcript", role: "agent", text: HOST_LINE, final: false },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(document.body.textContent).not.toContain(HOST_LINE);
  });

  it("announces a ready order with the name, in the spec's words", () => {
    dispatchAll([{ type: "order_ready", order_id: 27, customer_name: "Ahmed" }] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.getByText("Order #27 for Ahmed is ready!")).toBeInTheDocument();
  });

  it("shows the announcement even when THE HOST has gone back to IDLE", () => {
    // An order becomes ready long after its conversation ended, so the idle
    // menu carousel must give way to the announcement.
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-16T19:47:30" },
      { type: "order_ready", order_id: 34, customer_name: "Ahmed" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.getByText("Order #34 for Ahmed is ready!")).toBeInTheDocument();
    expect(screen.queryByText("Our Menu")).toBeNull();
  });

  it("returns to the idle menu once the queue is empty again", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-16T19:47:30" },
      { type: "order_ready", order_id: 34, customer_name: "Ahmed" },
    ] as AgentEvent[]);
    agentStore.dispatch({ type: "@ready_done" });

    render(<SMDDisplay />);

    expect(screen.queryByText("Order #34 for Ahmed is ready!")).toBeNull();
  });

  it("announces a ready order without a name when there is none", () => {
    dispatchAll([{ type: "order_ready", order_id: 28, customer_name: null }] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.getByText("Order #28 is ready!")).toBeInTheDocument();
  });

  it("shows no price and no On the house badge for a complimentary order", () => {
    dispatchAll([
      { type: "agent_state_changed", state: "TAKING_ORDER", timestamp: "2026-10-16T10:06:10" },
      { type: "order_updated", order: { ...draft, status: "PREPARING", complimentary: true } },
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(document.body.textContent).not.toContain("On the house");
    expect(document.body.textContent).not.toContain("Rs. 950");
  });
});

describe("the Live panel's open draft", () => {
  it("shows the order number, the items with quantities, the total as sent and the name", () => {
    dispatchAll([{ type: "order_created", order: draft }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Order #27")).toBeInTheDocument();
    expect(screen.getByText("Chicken Burger")).toBeInTheDocument();
    expect(screen.getByText("2× Blue Lemonade")).toBeInTheDocument();
    expect(screen.getByText("Rs. 950")).toBeInTheDocument();
    expect(screen.getByText("Ahmed")).toBeInTheDocument();
  });

  it("shows the name as soon as an order_updated adds it to the open draft", () => {
    // 16 §2o item 10(a): THE HOST builds the draft before it has the name and
    // rebuilds it afterwards. The later event replaces the stored order, so
    // the name must appear without any REST reload.
    dispatchAll([
      { type: "order_created", order: { ...draft, guest_name: null } },
      { type: "order_updated", order: { ...draft, guest_name: "Ahmed" } },
    ] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Order #27")).toBeInTheDocument();
    expect(screen.getByText("Ahmed")).toBeInTheDocument();
  });

  it("hides it once that order is CONFIRMED", () => {
    dispatchAll([
      { type: "order_created", order: draft },
      { type: "order_updated", order: { ...draft, status: "CONFIRMED" } },
    ] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("No open order")).toBeInTheDocument();
    expect(screen.queryByText("Order #27")).toBeNull();
  });

  it("says No open order when none is being taken", () => {
    render(<LivePanel />);

    expect(screen.getByText("No open order")).toBeInTheDocument();
  });

  it("badges a complimentary draft On the house", () => {
    dispatchAll([{ type: "order_created", order: { ...draft, complimentary: true } }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("On the house")).toBeInTheDocument();
  });
});

describe("the Live panel's Waiting for payment card (16 §2zf item 4)", () => {
  const unpaid: Order = {
    ...draft,
    status: "AWAITING_PAYMENT",
    payment_method: "CASH",
  };

  it("shows nothing at all when no order is waiting for payment", () => {
    dispatchAll([{ type: "order_created", order: draft }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.queryByText("Waiting for payment")).toBeNull();
    expect(screen.queryByRole("button", { name: /Paid · Cash/ })).toBeNull();
  });

  it("shows the order, the total large and the method the guest named", () => {
    dispatchAll([{ type: "order_updated", order: unpaid }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Waiting for payment")).toBeInTheDocument();
    expect(screen.getByText("Order #27")).toBeInTheDocument();
    expect(screen.getByText("Chicken Burger")).toBeInTheDocument();
    expect(screen.getByText("2× Blue Lemonade")).toBeInTheDocument();
    expect(screen.getByText("Rs. 950")).toBeInTheDocument();
    expect(screen.getByText("Guest said cash")).toBeInTheDocument();
  });

  it("offers Paid · Cash, Paid · QR and Cancel", () => {
    dispatchAll([{ type: "order_updated", order: unpaid }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByRole("button", { name: /Paid · Cash/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Paid · QR/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("says so plainly when the guest was never asked how they would pay", () => {
    dispatchAll([
      { type: "order_updated", order: { ...unpaid, payment_method: null } },
    ] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("No method given")).toBeInTheDocument();
  });

  it("disappears the moment the payment is marked", () => {
    dispatchAll([
      { type: "order_updated", order: unpaid },
      {
        type: "order_updated",
        order: { ...unpaid, status: "CONFIRMED", paid_at: "2026-10-28T19:06:10" },
      },
    ] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.queryByText("Waiting for payment")).toBeNull();
  });
});

describe("the Live panel's note box (16 §2zf item 6)", () => {
  const listening = [
    {
      type: "agent_state_changed",
      state: "LISTENING",
      timestamp: "2026-10-28T19:06:10",
      session_id: "a1b2c3d4",
    },
  ] as AgentEvent[];

  it("offers the box, Send and the three quick notes", () => {
    dispatchAll(listening);

    render(<LivePanel />);

    expect(screen.getByPlaceholderText("Tell THE HOST…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "This is the Vice Chancellor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask them to pay at the counter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wrap up politely" })).toBeInTheDocument();
  });

  it("disables Send and every quick note with no live conversation", () => {
    render(<LivePanel />);

    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Wrap up politely" })).toHaveProperty("disabled", true);
    expect(screen.getByText("No conversation is running.")).toBeInTheDocument();
  });

  it("disables Send while the box is empty, even with a conversation running", () => {
    dispatchAll(listening);

    render(<LivePanel />);

    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", true);
    // A quick note needs no typing, so it is live.
    expect(screen.getByRole("button", { name: "Wrap up politely" })).toHaveProperty("disabled", false);
  });

  it("sends what was typed and clears the box", async () => {
    dispatchAll(listening);
    render(<LivePanel />);
    const box = screen.getByPlaceholderText("Tell THE HOST…") as HTMLInputElement;

    // A controlled input: React only sees the change through its own handler.
    fireEvent.change(box, { target: { value: "  They are in a hurry  " } });
    await act(async () => {
      screen.getByRole("button", { name: "Send" }).click();
    });

    expect(notesSent.at(-1)).toBe("They are in a hurry");
    expect(box.value).toBe("");
  });

  it("sends a quick note word for word", async () => {
    dispatchAll(listening);
    render(<LivePanel />);

    await act(async () => {
      screen.getByRole("button", { name: "This is the Vice Chancellor" }).click();
    });

    expect(notesSent.at(-1)).toBe("This is the Vice Chancellor");
  });

  it("says plainly that THE HOST never reads it out, and that nothing is saved", () => {
    dispatchAll(listening);

    render(<LivePanel />);

    expect(
      screen.getByText("THE HOST acts on this at once and never reads it out. Nothing typed here is saved."),
    ).toBeInTheDocument();
  });

  it("will not take more than 300 characters", () => {
    dispatchAll(listening);

    render(<LivePanel />);

    expect(screen.getByPlaceholderText("Tell THE HOST…")).toHaveProperty("maxLength", 300);
  });
});

describe("the Live panel's conversation state and mode", () => {
  it("shows the backend's state uppercase, exactly as sent", () => {
    dispatchAll([{ type: "agent_state_changed", state: "LISTENING", timestamp: "2026-10-16T10:06:10", session_id: "a1b2c3d4" }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("LISTENING")).toBeInTheDocument();
  });

  it("says No conversation when the state is IDLE", () => {
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-16T10:06:10" }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("No conversation")).toBeInTheDocument();
  });

  it("shows RECOVERING as Reconnecting…", () => {
    dispatchAll([{ type: "operational_mode_changed", mode: "RECOVERING", reason: "the AI service dropped" }] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Reconnecting…")).toBeInTheDocument();
    expect(screen.getByText("the AI service dropped")).toBeInTheDocument();
  });

  it("shows the operator-only notice", () => {
    render(<LivePanel />);

    expect(screen.getByText("Operator only. Guest speech is never shown on the public display or saved.")).toBeInTheDocument();
  });

  it("labels the two speakers Guest and THE HOST, and marks an open line as not final", () => {
    dispatchAll([
      { type: "speech_transcript", role: "visitor", text: GUEST_LINE, final: true, session_id: "a1b2c3d4", timestamp: "2026-10-16T10:06:10" },
      { type: "speech_transcript", role: "agent", text: HOST_LINE, final: false, session_id: "a1b2c3d4", timestamp: "2026-10-16T10:06:12" },
    ] as AgentEvent[]);

    render(<LivePanel />);

    expect(screen.getByText("Guest")).toBeInTheDocument();
    expect(screen.getByText("THE HOST")).toBeInTheDocument();
    expect(screen.getByText(GUEST_LINE)).toBeInTheDocument();
    // The open line is rendered muted and italic.
    expect(screen.getByText(HOST_LINE).className).toContain("italic");
  });
});

describe("an order card shows money exactly as the backend formatted it", () => {
  it("prints the total with no second Rs prefix", () => {
    render(<OrderCard order={{ ...draft, status: "CONFIRMED", total: "Rs. 1,300" }} now={Date.now()} />);

    expect(screen.getByText("Rs. 1,300")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Rs Rs");
    expect(document.body.textContent).not.toContain("Rs Rs. 1,300");
  });

  it("prints nothing where a null total would go", () => {
    render(<OrderCard order={{ ...draft, status: "CONFIRMED", total: null }} now={Date.now()} />);

    expect(document.body.textContent).not.toContain("Rs");
    expect(document.body.textContent).not.toContain("NaN");
  });

  it("shows On the house and strikes the total through", () => {
    render(<OrderCard order={{ ...draft, status: "CONFIRMED", complimentary: true }} now={Date.now()} />);

    expect(screen.getByText("On the house")).toBeInTheDocument();
    expect(screen.getByText("Rs. 950").className).toContain("line-through");
  });

  it("shows no countdown and no NaN when there is no estimate", () => {
    render(<OrderCard order={{ ...draft, status: "PREPARING", estimated_ready_at: null }} now={Date.now()} />);

    expect(document.body.textContent).not.toContain("NaN");
    expect(document.body.textContent).not.toContain("left");
  });

  it("shows a real countdown when an estimate exists", () => {
    const soon = new Date(Date.now() + 5 * 60_000);
    const p = (n: number) => String(n).padStart(2, "0");
    const iso = `${soon.getFullYear()}-${p(soon.getMonth() + 1)}-${p(soon.getDate())}T${p(soon.getHours())}:${p(soon.getMinutes())}:${p(soon.getSeconds())}`;

    render(<OrderCard order={{ ...draft, status: "PREPARING", estimated_ready_at: iso }} now={Date.now()} />);

    expect(screen.getByText(/0[45]:\d\d left/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("NaN");
  });
});
