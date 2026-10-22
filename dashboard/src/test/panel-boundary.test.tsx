/**
 * 16 §2s item 4(b) — a panel that throws costs that panel and nothing else.
 *
 * The root route's errorComponent is the whole page, so before this every
 * render throw anywhere below it replaced the entire Command Center with
 * "This page didn't load — Try again / Go home". These tests pin the three
 * things item 4(b) asks for: the fallback text and its button, the neighbours
 * carrying on, and "Reload panel" really re-mounting the panel.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PANEL_FAILED_TEXT, PANEL_RELOAD_TEXT, PanelBoundary } from "@/components/host/PanelBoundary";

/** Throws until `failUntil` says otherwise, counting its own mounts. */
function makeFlaky() {
  const state = { mounts: 0, shouldThrow: true };
  function Flaky({ className }: { className?: string }) {
    state.mounts += 1;
    if (state.shouldThrow) throw new TypeError("Cannot read properties of undefined (reading 'mode')");
    return <section className={className}>Panel is working again</section>;
  }
  return { state, Flaky };
}

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  // React also prints its own notice for a caught error; the assertions below
  // look for the boundary's one line specifically.
  consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  consoleError.mockRestore();
  cleanup();
});

describe("a panel that throws", () => {
  it("shows the fallback and its Reload panel button", () => {
    const { Flaky } = makeFlaky();

    render(
      <PanelBoundary name="Orders">
        <Flaky />
      </PanelBoundary>,
    );

    expect(screen.getByText(PANEL_FAILED_TEXT)).toBeInTheDocument();
    expect(screen.getByText("This panel hit a problem.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: PANEL_RELOAD_TEXT })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload panel" })).toBeInTheDocument();
  });

  it("leaves its neighbours rendering", () => {
    const { Flaky } = makeFlaky();

    render(
      <div>
        <PanelBoundary name="Activity">
          <section>Activity panel content</section>
        </PanelBoundary>
        <PanelBoundary name="Orders">
          <Flaky />
        </PanelBoundary>
        <PanelBoundary name="Visitors">
          <section>Visitors panel content</section>
        </PanelBoundary>
      </div>,
    );

    expect(screen.getByText(PANEL_FAILED_TEXT)).toBeInTheDocument();
    expect(screen.getByText("Activity panel content")).toBeInTheDocument();
    expect(screen.getByText("Visitors panel content")).toBeInTheDocument();
    // Exactly one panel is in the fallback: the one that threw.
    expect(screen.getAllByText(PANEL_FAILED_TEXT)).toHaveLength(1);
  });

  it("never shows the router's error page", () => {
    const { Flaky } = makeFlaky();

    render(
      <PanelBoundary name="Orders">
        <Flaky />
      </PanelBoundary>,
    );

    expect(screen.queryByText("This page didn't load")).not.toBeInTheDocument();
    expect(screen.queryByText("Try again")).not.toBeInTheDocument();
    expect(screen.queryByText("Go home")).not.toBeInTheDocument();
  });

  it("writes one line of its own to the console, naming the panel", () => {
    const { Flaky } = makeFlaky();

    render(
      <PanelBoundary name="Orders">
        <Flaky />
      </PanelBoundary>,
    );

    const ours = (consoleError.mock.calls as unknown[][]).filter(
      (args) => typeof args[0] === "string" && args[0].startsWith("[panel] "),
    );
    expect(ours).toHaveLength(1);
    expect(ours[0]![0]).toBe("[panel] Orders hit a problem");
  });

  it("keeps the panel's place in the grid", () => {
    const { Flaky } = makeFlaky();

    const { container } = render(
      <PanelBoundary name="Orders" className="xl:col-span-5">
        <Flaky />
      </PanelBoundary>,
    );

    const fallback = container.querySelector("section");
    expect(fallback).not.toBeNull();
    expect(fallback!.className).toContain("xl:col-span-5");
  });
});

describe("Reload panel", () => {
  it("re-mounts the panel rather than re-rendering the one that threw", async () => {
    const { state, Flaky } = makeFlaky();

    render(
      <PanelBoundary name="Orders">
        <Flaky />
      </PanelBoundary>,
    );
    expect(screen.getByText(PANEL_FAILED_TEXT)).toBeInTheDocument();
    const mountsWhenItFailed = state.mounts;

    // Whatever was wrong has passed -- a reconnect finished, an event arrived.
    state.shouldThrow = false;
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByRole("button", { name: PANEL_RELOAD_TEXT }));

    expect(state.mounts).toBeGreaterThan(mountsWhenItFailed);
    expect(screen.getByText("Panel is working again")).toBeInTheDocument();
    expect(screen.queryByText(PANEL_FAILED_TEXT)).not.toBeInTheDocument();
  });

  it("shows the fallback again if the panel is still broken", async () => {
    const { Flaky } = makeFlaky();

    render(
      <PanelBoundary name="Orders">
        <Flaky />
      </PanelBoundary>,
    );
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByRole("button", { name: PANEL_RELOAD_TEXT }));

    expect(screen.getByText(PANEL_FAILED_TEXT)).toBeInTheDocument();
  });
});

describe("a healthy panel", () => {
  it("renders exactly what the page would have rendered, with no extra wrapper", () => {
    const { container } = render(
      <PanelBoundary name="Orders" className="xl:col-span-5">
        <section>Orders panel content</section>
      </PanelBoundary>,
    );

    expect(screen.getByText("Orders panel content")).toBeInTheDocument();
    // The panel itself is the first element: the boundary adds no DOM of its own.
    expect(container.firstElementChild?.tagName).toBe("SECTION");
    expect(container.firstElementChild?.className).toContain("xl:col-span-5");
    expect(screen.queryByText(PANEL_FAILED_TEXT)).not.toBeInTheDocument();
  });

  it("keeps a class the page put on the panel when the boundary has none", () => {
    const { container } = render(
      <PanelBoundary name="Transcript">
        <section className="kept-by-the-page">Transcript panel content</section>
      </PanelBoundary>,
    );

    expect(container.firstElementChild?.className).toBe("kept-by-the-page");
  });
});
