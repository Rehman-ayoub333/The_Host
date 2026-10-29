/**
 * Phase 7n: the Feedback page (16 §2zi item 4(d), (f)).
 *
 * The summary tiles, the two tabs, newest first, the CSV button, and a refresh
 * every 60 s. Operator only: nothing on /display renders this, so the `smd`
 * role has no path to /api/feedback at all.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { calls } = vi.hoisted(() => ({ calls: { feedback: 0, csv: 0 } }));

vi.mock("@/lib/agent/service", () => ({
  getFeedback: () => {
    calls.feedback += 1;
    return Promise.resolve(payload);
  },
  downloadFeedbackCsv: () => {
    calls.csv += 1;
    return Promise.resolve(true);
  },
}));

import { FEEDBACK_REFRESH_MS, FeedbackPanel } from "@/components/host/FeedbackPanel";
import type { FeedbackPayload } from "@/lib/agent/types";

let payload: FeedbackPayload = emptyPayload();

function emptyPayload(): FeedbackPayload {
  return {
    form: [],
    spoken: [],
    summary: {
      count: 0,
      avg_overall: null,
      avg_taste: null,
      avg_presentation: null,
      buy_again_yes_pct: null,
    },
    import_status: { state: "off", last_ok: null, last_error: null, imported: 0 },
  };
}

function fullPayload(): FeedbackPayload {
  return {
    form: [
      {
        id: 2,
        netlify_id: "sub-2",
        created_at: "2026-10-29T19:00:00",
        item: "Blue Lemonade",
        overall_rating: 4,
        taste_rating: 5,
        presentation_rating: 3,
        value_rating: "Great value",
        liked_most: "So refreshing",
        improvement: "More ice",
        buy_again: "Probably",
        one_word: "Cool",
      },
      {
        id: 1,
        netlify_id: "sub-1",
        created_at: "2026-10-29T18:00:00",
        item: "Chicken Burger",
        overall_rating: 5,
        taste_rating: 5,
        presentation_rating: 5,
        buy_again: "Definitely",
        one_word: "Crispy",
      },
    ],
    spoken: [
      {
        id: 7,
        timestamp: "2026-10-29T18:30:00",
        subject: "chicken burger",
        comment: "Really good, thank you",
        rating: 5,
        guest_name: "Ahmed",
      },
    ],
    summary: {
      count: 2,
      avg_overall: 4.5,
      avg_taste: 5,
      avg_presentation: 4,
      buy_again_yes_pct: 100,
    },
    import_status: { state: "ok", last_ok: "2026-10-29T19:01:00", last_error: null, imported: 2 },
  };
}

beforeEach(() => {
  calls.feedback = 0;
  calls.csv = 0;
  payload = fullPayload();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the Feedback page", () => {
  it("shows the summary tiles from the backend's own figures", async () => {
    render(<FeedbackPanel />);

    expect(await screen.findByText("Forms received")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("4.5")).toBeInTheDocument();
    expect(screen.getByText("5.0")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("has both tabs and opens on the guest forms, newest first", async () => {
    render(<FeedbackPanel />);

    expect(await screen.findByText("Guest forms")).toBeInTheDocument();
    expect(screen.getByText("Spoken to THE HOST")).toBeInTheDocument();
    // The backend sends them newest first and the page keeps that order.
    const items = screen.getAllByText(/Blue Lemonade|Chicken Burger/);
    expect(items[0]).toHaveTextContent("Blue Lemonade");
    expect(screen.getByText("Liked: So refreshing")).toBeInTheDocument();
  });

  it("shows what a guest told THE HOST on the other tab, and only there", async () => {
    render(<FeedbackPanel />);
    await screen.findByText("Guest forms");

    expect(screen.queryByText("Really good, thank you")).toBeNull();

    fireEvent.click(screen.getByText("Spoken to THE HOST"));

    expect(screen.getByText("Really good, thank you")).toBeInTheDocument();
    expect(screen.getByText("Ahmed")).toBeInTheDocument();
    // The two are never mixed: the form rows are gone from this tab.
    expect(screen.queryByText("Liked: So refreshing")).toBeNull();
  });

  it("downloads the form rows as a CSV", async () => {
    render(<FeedbackPanel />);
    const button = await screen.findByRole("button", { name: /Download guest forms/ });

    fireEvent.click(button);

    await waitFor(() => expect(calls.csv).toBe(1));
  });

  it("asks the backend again every sixty seconds", async () => {
    vi.useFakeTimers();
    render(<FeedbackPanel />);
    await vi.waitFor(() => expect(calls.feedback).toBe(1));

    await act(async () => {
      vi.advanceTimersByTime(FEEDBACK_REFRESH_MS);
    });

    expect(calls.feedback).toBe(2);
    expect(FEEDBACK_REFRESH_MS).toBe(60_000);
  });

  it("says the import is off rather than pretending there is no feedback", async () => {
    payload = emptyPayload();

    render(<FeedbackPanel />);

    expect(await screen.findByText("No guest forms yet")).toBeInTheDocument();
    expect(
      screen.getByText(/NETLIFY_TOKEN and NETLIFY_SITE_ID are not set/),
    ).toBeInTheDocument();
  });

  it("shows an em dash for a rating the guest did not give", async () => {
    payload = {
      ...emptyPayload(),
      form: [{ id: 1, netlify_id: "sub-1", item: "Chicken Burger" }],
      summary: { ...emptyPayload().summary, count: 1 },
    };

    render(<FeedbackPanel />);

    expect(await screen.findByText("Chicken Burger")).toBeInTheDocument();
    // Three unanswered ratings, plus the three tiles that have no average.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});
