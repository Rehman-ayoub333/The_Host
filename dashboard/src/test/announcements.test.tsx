/**
 * 16 §2zs item 4 — the operator's announcement, on both screens.
 *
 * Rehman types one line. The dashboard sends it to a different endpoint from a
 * private note, the public display shows it in the ready-order queue in amber
 * for 20 s, and THE HOST says it. Nothing of a private note ever gets there.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { notesSent, announced, toasts } = vi.hoisted(() => ({
  notesSent: [] as string[],
  announced: [] as string[],
  toasts: [] as string[],
}));

vi.mock("sonner", () => ({
  toast: {
    success: (message: string) => toasts.push(message),
    error: (message: string) => toasts.push(message),
    info: (message: string) => toasts.push(message),
  },
}));

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
  getPosters: () => Promise.resolve({ posters: [] as string[] }),
  posterSrc: (path: string) => path,
  setOrderStatus: () => Promise.resolve(true),
  announceAgain: () => Promise.resolve(true),
  sendSessionNote: (text: string) => {
    notesSent.push(text);
    return Promise.resolve(true);
  },
  sendAnnouncement: (text: string) => {
    announced.push(text);
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
import { readyHeadline, SMDDisplay } from "@/routes/display";
import { agentStore } from "@/lib/agent/store";
import type { AgentEvent } from "@/lib/agent/types";

// 21 Part C row E65, word for word.
const E65 = "Only 5 Fire Burgers left today!";

function stamp(event: Partial<AgentEvent> & { type: string }, id: number): AgentEvent {
  return { event_id: id, timestamp: new Date().toISOString(), session_id: null, ...event } as AgentEvent;
}

const LIVE = [
  stamp({ type: "agent_state_changed", state: "LISTENING" }, 1),
] as AgentEvent[];

function dispatchAll(events: AgentEvent[]) {
  act(() => {
    for (const event of events) agentStore.dispatch(event);
  });
}

beforeEach(() => {
  agentStore.dispatch({ type: "@reset" });
  notesSent.length = 0;
  announced.length = 0;
  toasts.length = 0;
});

afterEach(cleanup);

// ------------------------------------------------- the two buttons

describe("the dashboard's two buttons", () => {
  it("offers a private note and an announcement, clearly different", () => {
    dispatchAll(LIVE);

    render(<LivePanel />);

    expect(screen.getByRole("button", { name: "Send private note" })).toBeInTheDocument();
    const announce = screen.getByRole("button", { name: "Announce on screen" });
    expect(announce).toBeInTheDocument();
    // 16 §2zs item 4(a): the announcement button is the amber one.
    expect(announce.className).toContain("amber");
    expect(screen.getByRole("button", { name: "Send private note" }).className).not.toContain("amber");
  });

  it("sends each button's text to its own endpoint", async () => {
    dispatchAll(LIVE);
    render(<LivePanel />);
    const box = screen.getByPlaceholderText("Tell THE HOST…") as HTMLInputElement;

    fireEvent.change(box, { target: { value: "  This is the VC  " } });
    await act(async () => {
      screen.getByRole("button", { name: "Send private note" }).click();
    });
    fireEvent.change(box, { target: { value: `  ${E65}  ` } });
    await act(async () => {
      screen.getByRole("button", { name: "Announce on screen" }).click();
    });

    expect(notesSent).toEqual(["This is the VC"]);
    expect(announced).toEqual([E65]);
  });

  it("announces with no conversation running, where a note cannot", () => {
    // Nothing dispatched: `lastAgentState` is null, as between guests.
    render(<LivePanel />);
    const box = screen.getByPlaceholderText("Tell THE HOST…") as HTMLInputElement;
    fireEvent.change(box, { target: { value: E65 } });

    expect(screen.getByRole("button", { name: "Send private note" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Announce on screen" })).toHaveProperty("disabled", false);
    expect(
      screen.getByText("No conversation is running — a note needs one, an announcement starts one."),
    ).toBeInTheDocument();
  });

  it("toasts once it is on the screen", async () => {
    render(<LivePanel />);
    fireEvent.change(screen.getByPlaceholderText("Tell THE HOST…"), { target: { value: E65 } });

    await act(async () => {
      screen.getByRole("button", { name: "Announce on screen" }).click();
    });

    expect(toasts).toContain("Announced on the screen");
  });

  it("refuses more than 140 characters", () => {
    render(<LivePanel />);
    fireEvent.change(screen.getByPlaceholderText("Tell THE HOST…"), { target: { value: "x".repeat(141) } });

    expect(screen.getByRole("button", { name: "Announce on screen" })).toHaveProperty("disabled", true);
    expect(screen.getByText("An announcement is at most 140 characters.")).toBeInTheDocument();
  });

  it("allows exactly 140", () => {
    render(<LivePanel />);
    fireEvent.change(screen.getByPlaceholderText("Tell THE HOST…"), { target: { value: "x".repeat(140) } });

    expect(screen.getByRole("button", { name: "Announce on screen" })).toHaveProperty("disabled", false);
  });
});

// ------------------------------------------------- the last five, and "Again"

describe("the last five announcements", () => {
  it("lists them newest first and keeps only five", () => {
    dispatchAll(
      Array.from({ length: 6 }, (_, i) =>
        stamp({ type: "display_announcement", text: `line ${i + 1}`, seconds: 20 }, i + 1),
      ) as AgentEvent[],
    );

    render(<LivePanel />);

    const items = screen.getAllByRole("button", { name: "Again" });
    expect(items).toHaveLength(5);
    // "line 1" fell off the end; "line 6" is at the top.
    expect(screen.queryByText("line 1")).toBeNull();
    expect(screen.getByText("line 6")).toBeInTheDocument();
  });

  it("sends the same words again on Again", async () => {
    dispatchAll([stamp({ type: "display_announcement", text: E65, seconds: 20 }, 1)] as AgentEvent[]);
    render(<LivePanel />);

    await act(async () => {
      screen.getByRole("button", { name: "Again" }).click();
    });

    expect(announced).toEqual([E65]);
  });

  it("shows no list before anything has been announced", () => {
    render(<LivePanel />);

    expect(screen.queryByRole("button", { name: "Again" })).toBeNull();
  });
});

// ------------------------------------------------- the public screen

describe("the public display", () => {
  it("puts the announcement in the ready-order queue with its own 20 s", () => {
    dispatchAll([stamp({ type: "display_announcement", text: E65, seconds: 20 }, 1)] as AgentEvent[]);

    const queue = agentStore.get().readyQueue;
    expect(queue).toHaveLength(1);
    expect(queue[0]!.announcement).toBe(E65);
    expect(queue[0]!.ms).toBe(20_000);
    // Not an order: the chime's "one per order" set is never touched by it.
    expect(queue[0]!.order_id).toBe(0);
  });

  it("shows exactly the operator's text, with nothing added", () => {
    expect(readyHeadline({ order_id: 0, announcement: E65 })).toBe(E65);
    // A ready order is unchanged.
    expect(readyHeadline({ order_id: 3, order_number: 3, customer_name: "Ahmed" })).toBe(
      "Order #3 for Ahmed is ready!",
    );
  });

  it("renders the banner in amber", () => {
    dispatchAll([stamp({ type: "display_announcement", text: E65, seconds: 20 }, 1)] as AgentEvent[]);

    render(<SMDDisplay />);

    const banner = screen.getByTestId("display-announcement");
    expect(banner.textContent).toBe(E65);
    expect(banner.className).toContain("amber");
  });

  it("gives a ready order a banner that is not the announcement's", () => {
    dispatchAll([
      stamp({ type: "order_ready", order_id: 3, order_number: 3, customer_name: "Ahmed" }, 1),
    ] as AgentEvent[]);

    render(<SMDDisplay />);

    expect(screen.queryByTestId("display-announcement")).toBeNull();
    expect(screen.getByText("Order #3 for Ahmed is ready!")).toBeInTheDocument();
  });

  it("never shows a private note", () => {
    dispatchAll(LIVE);

    render(<SMDDisplay />);

    expect(screen.queryByTestId("display-announcement")).toBeNull();
    expect(agentStore.get().readyQueue).toEqual([]);
  });
});
