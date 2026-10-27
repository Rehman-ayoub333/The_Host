/**
 * 16 §2ze item 5 — the TV's idle screen is Rehman's full-screen pictures.
 *
 * Rehman's rule 2(d): the idle menu shows only pictures, no text, because each
 * picture already carries all its information. So the old text carousel is gone
 * from `/display`, the posters fill the screen with nothing over them, and a
 * ready-order banner still shows over them as it did over the menu.
 */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  posters: [] as string[],
  fails: false,
  calls: 0,
}));

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
  getPosters: () => {
    backend.calls += 1;
    return backend.fails
      ? Promise.reject(new Error("Backend unavailable"))
      : Promise.resolve({ posters: backend.posters });
  },
  posterSrc: (path: string) => `http://localhost:8000${path}`,
}));

import { PosterScreen, POSTER_FADE_MS, POSTER_MS } from "@/components/host/PosterScreen";
import { POSTER_REFETCH_MS, SMDDisplay } from "@/routes/display";
import { agentStore } from "@/lib/agent/store";
import type { AgentEvent } from "@/lib/agent/types";

const THREE = ["/posters/01-burgers.jpg", "/posters/02-shakes.png", "/posters/03-drinks.webp"];
const dispatchAll = (events: AgentEvent[]) => events.forEach((e) => agentStore.dispatch(e));

const posters = () => screen.queryAllByTestId("poster");
const current = () => posters().filter((img) => img.getAttribute("data-current") === "true");

beforeEach(() => {
  backend.posters = [];
  backend.fails = false;
  backend.calls = 0;
  agentStore.dispatch({ type: "@reset" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  agentStore.dispatch({ type: "@reset" });
});

/* ------------------------------ the rotation ------------------------------ */

describe("the poster rotation (16 §2ze item 5)", () => {
  it("shows one poster at a time, in the order it is given, and wraps", () => {
    vi.useFakeTimers();
    render(<PosterScreen posters={THREE} />);

    // The endpoint sorts by file name; the screen must not reorder them.
    expect(posters().map((img) => img.getAttribute("src"))).toEqual(THREE);

    expect(current()).toHaveLength(1);
    expect(current()[0]!.getAttribute("src")).toBe(THREE[0]);

    act(() => void vi.advanceTimersByTime(POSTER_MS));
    expect(current()[0]!.getAttribute("src")).toBe(THREE[1]);

    act(() => void vi.advanceTimersByTime(POSTER_MS));
    expect(current()[0]!.getAttribute("src")).toBe(THREE[2]);

    act(() => void vi.advanceTimersByTime(POSTER_MS));
    expect(current()[0]!.getAttribute("src")).toBe(THREE[0]);
  });

  it("holds each poster for eight seconds", () => {
    vi.useFakeTimers();
    render(<PosterScreen posters={THREE} />);

    act(() => void vi.advanceTimersByTime(POSTER_MS - 1));
    expect(current()[0]!.getAttribute("src")).toBe(THREE[0]);

    act(() => void vi.advanceTimersByTime(1));
    expect(current()[0]!.getAttribute("src")).toBe(THREE[1]);
  });

  it("cross-fades over 0.6 s, with the others held at nothing", () => {
    render(<PosterScreen posters={THREE} />);

    expect(POSTER_MS).toBe(8000);
    expect(POSTER_FADE_MS).toBe(600);
    for (const img of posters()) {
      expect(img.style.transitionDuration).toBe("600ms");
      expect(img.className).toContain("transition-opacity");
      expect(img.style.opacity).toBe(img.getAttribute("data-current") === "true" ? "1" : "0");
    }
  });

  it("letterboxes a picture on the display's own background colour", () => {
    render(<PosterScreen posters={THREE} />);

    for (const img of posters()) {
      expect(img.className).toContain("object-contain");
      expect(img.className).toContain("inset-0");
    }
    expect(screen.getByTestId("poster-screen").className).toContain("bg-background");
    expect(screen.getByTestId("poster-screen").className).toContain("inset-0");
  });

  it("renders no text, caption or control of its own", () => {
    render(<PosterScreen posters={THREE} />);

    const layer = screen.getByTestId("poster-screen");
    expect(layer.textContent).toBe("");
    expect(layer.querySelector("button")).toBeNull();
    expect(layer.getAttribute("aria-hidden")).toBe("true");
    for (const img of posters()) expect(img.getAttribute("alt")).toBe("");
  });

  it("renders nothing at all when there are no posters", () => {
    const { container } = render(<PosterScreen posters={[]} />);

    expect(container.firstChild).toBeNull();
  });
});

/* ------------------------------- the display ------------------------------ */

/** The chrome that must not be drawn over a poster (16 §2ze item 5). */
const CHROME = ["Ready when you are.", "THE HOST · Your AI host", "See · Hear · Think · Speak · Remember"];

describe("/display in poster mode (16 §2ze item 5)", () => {
  it("shows the posters with nothing over them when nobody is talking", async () => {
    backend.posters = THREE;
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" }] as AgentEvent[]);

    render(<SMDDisplay />);
    await screen.findByTestId("poster-screen");

    expect(posters().map((img) => img.getAttribute("src"))).toEqual(
      THREE.map((path) => `http://localhost:8000${path}`),
    );
    for (const text of CHROME) expect(screen.queryByText(text)).toBeNull();
    expect(screen.queryByLabelText("Enter full screen")).toBeNull();
    expect(screen.queryByTestId("host-caption")).toBeNull();
    // The old text menu carousel is gone from this screen for good.
    expect(screen.queryByText("Our Menu")).toBeNull();
    expect(document.body.textContent).not.toContain("Our Menu");
  });

  it("shows a ready-order banner over a poster", async () => {
    backend.posters = THREE;
    dispatchAll([
      { type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" },
      { type: "order_ready", order_id: 34, customer_name: "Ahmed" },
    ] as AgentEvent[]);

    render(<SMDDisplay />);
    await screen.findByTestId("poster-screen");

    // Both at once: the poster underneath, the announcement on top.
    expect(screen.getByText("Order #34 for Ahmed is ready!")).toBeInTheDocument();
    expect(posters().length).toBe(THREE.length);
  });

  it("shows the brand screen only when there are no posters", async () => {
    backend.posters = [];
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" }] as AgentEvent[]);

    render(<SMDDisplay />);
    await waitFor(() => expect(backend.calls).toBe(1));

    expect(screen.queryByTestId("poster-screen")).toBeNull();
    expect(screen.getByText("Ready when you are.")).toBeInTheDocument();
    // §2ze item 5: the brand screen, and never a text menu in its place.
    expect(screen.queryByText("Our Menu")).toBeNull();
    expect(document.body.textContent).not.toContain("Rs. ");
  });

  it("shows the brand screen only when the list cannot be loaded", async () => {
    backend.fails = true;
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" }] as AgentEvent[]);

    render(<SMDDisplay />);
    await waitFor(() => expect(backend.calls).toBe(1));

    expect(screen.queryByTestId("poster-screen")).toBeNull();
    expect(screen.getByText("Ready when you are.")).toBeInTheDocument();
  });

  it("gives the screen back to THE HOST during a conversation", async () => {
    backend.posters = THREE;
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" }] as AgentEvent[]);

    render(<SMDDisplay />);
    await screen.findByTestId("poster-screen");

    act(() => {
      agentStore.dispatch({
        type: "agent_state_changed",
        state: "LISTENING",
        timestamp: "2026-10-27T19:48:00",
      } as AgentEvent);
    });

    expect(screen.queryByTestId("poster-screen")).toBeNull();
    expect(screen.getByText("THE HOST · Your AI host")).toBeInTheDocument();
  });

  it("reads the list again every 60 s, so a new poster needs no restart", async () => {
    vi.useFakeTimers();
    backend.posters = [];
    dispatchAll([{ type: "agent_state_changed", state: "IDLE", timestamp: "2026-10-27T19:47:30" }] as AgentEvent[]);

    render(<SMDDisplay />);
    await act(async () => undefined);
    expect(backend.calls).toBe(1);

    // Rehman drops a picture into backend/data/posters/ during the gala.
    backend.posters = THREE;
    await act(async () => {
      vi.advanceTimersByTime(POSTER_REFETCH_MS);
    });

    expect(backend.calls).toBe(2);
    expect(POSTER_REFETCH_MS).toBe(60_000);
    expect(screen.getAllByTestId("poster").length).toBe(THREE.length);
  });
});
