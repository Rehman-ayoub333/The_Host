/**
 * 16 §2zi item 4(d) — the Feedback page.
 *
 * Two things that are never mixed: what guests filled in on Rehman's Netlify
 * form, and what a guest asked THE HOST to pass on at the stall. Summary tiles
 * above, two tabs below, newest first, and a CSV of the form rows.
 *
 * Operator only. It fetches here rather than through the event store, so the
 * public display has no path to it at all: the `smd` role never calls
 * /api/feedback because nothing on /display renders this.
 */

import { useCallback, useEffect, useState } from "react";
import { Download, MessageSquareQuote, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState, Panel } from "./Panel";
import { downloadFeedbackCsv, getFeedback } from "@/lib/agent/service";
import type { FeedbackPayload, FormFeedback, SpokenFeedback } from "@/lib/agent/types";
import { cn } from "@/lib/utils";

/** 16 §2zi item 4(d) — refreshed every 60 s, like the import itself. */
export const FEEDBACK_REFRESH_MS = 60_000;

type Tab = "form" | "spoken";

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg text-foreground">{value}</p>
    </div>
  );
}

/** A rating as stars, or an em dash when the guest did not answer. */
function Stars({ value }: { value?: number | null | undefined }) {
  if (typeof value !== "number") return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-0.5 text-gold" aria-label={`${value} of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} className={cn("h-3 w-3", n <= value ? "fill-current" : "opacity-25")} />
      ))}
    </span>
  );
}

function FormRow({ row }: { row: FormFeedback }) {
  return (
    <li className="animate-rise rounded-md border border-line bg-background/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate text-sm font-semibold">{row.item || "No item named"}</p>
        {row.created_at && (
          <p className="shrink-0 font-mono text-[0.62rem] text-muted-foreground">
            {row.created_at}
          </p>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.68rem] text-muted-foreground">
        <span className="flex items-center gap-1">Overall <Stars value={row.overall_rating} /></span>
        <span className="flex items-center gap-1">Taste <Stars value={row.taste_rating} /></span>
        <span className="flex items-center gap-1">Presentation <Stars value={row.presentation_rating} /></span>
        {row.value_rating && <span>Value: {row.value_rating}</span>}
        {row.buy_again && <span>Buy again: {row.buy_again}</span>}
      </div>
      {row.liked_most && <p className="mt-1.5 text-xs text-foreground">Liked: {row.liked_most}</p>}
      {row.improvement && (
        <p className="mt-1 text-xs text-muted-foreground">To improve: {row.improvement}</p>
      )}
      {row.one_word && <p className="mt-1 text-xs italic text-champagne">“{row.one_word}”</p>}
    </li>
  );
}

function SpokenRow({ row }: { row: SpokenFeedback }) {
  return (
    <li className="animate-rise rounded-md border border-line bg-background/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate text-sm font-semibold">{row.subject}</p>
        {row.timestamp && (
          <p className="shrink-0 font-mono text-[0.62rem] text-muted-foreground">{row.timestamp}</p>
        )}
      </div>
      <p className="mt-1 text-xs text-foreground">{row.comment}</p>
      <div className="mt-1.5 flex items-center gap-4 text-[0.68rem] text-muted-foreground">
        <span className="flex items-center gap-1">Rating <Stars value={row.rating} /></span>
        {row.guest_name && <span>{row.guest_name}</span>}
      </div>
    </li>
  );
}

export function FeedbackPanel({ className }: { className?: string }) {
  const [payload, setPayload] = useState<FeedbackPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<Tab>("form");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getFeedback()
      .then((next) => {
        setPayload(next);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, FEEDBACK_REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const summary = payload?.summary;
  const rows = tab === "form" ? payload?.form ?? [] : payload?.spoken ?? [];
  const off = payload?.import_status?.state === "off";

  return (
    <Panel
      title="Feedback"
      icon={<MessageSquareQuote className="h-4 w-4" />}
      className={className}
      action={
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !payload?.form.length}
          onClick={() => {
            setBusy(true);
            void downloadFeedbackCsv().finally(() => setBusy(false));
          }}
          className="h-7 rounded-sm border-line px-2 text-[0.65rem] font-semibold uppercase text-gold transition-colors hover:border-gold hover:bg-gold/10"
        >
          <Download className="mr-1 h-3 w-3" /> Download guest forms (CSV)
        </Button>
      }
    >
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Tile label="Forms received" value={summary ? String(summary.count) : "—"} />
        <Tile
          label="Average overall"
          value={summary?.avg_overall != null ? summary.avg_overall.toFixed(1) : "—"}
        />
        <Tile
          label="Average taste"
          value={summary?.avg_taste != null ? summary.avg_taste.toFixed(1) : "—"}
        />
        <Tile
          label="Would buy again"
          value={summary?.buy_again_yes_pct != null ? `${summary.buy_again_yes_pct}%` : "—"}
        />
      </div>

      <div className="mt-4 flex gap-1 border-b border-line">
        {(
          [
            ["form", "Guest forms"],
            ["spoken", "Spoken to THE HOST"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-1.5 text-[0.68rem] font-semibold uppercase tracking-wide transition-colors",
              tab === key
                ? "border-gold text-gold"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-3">
        {failed ? (
          <EmptyState
            icon={<MessageSquareQuote className="h-6 w-6" />}
            title="Feedback could not be read"
            hint="The backend did not answer. It is tried again every minute."
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<MessageSquareQuote className="h-6 w-6" />}
            title={tab === "form" ? "No guest forms yet" : "Nothing spoken to THE HOST yet"}
            hint={
              tab === "form" && off
                ? "The import is off: NETLIFY_TOKEN and NETLIFY_SITE_ID are not set."
                : tab === "form"
                  ? "Forms appear within a minute of a guest sending one."
                  : "Feedback a guest asks THE HOST to pass on appears here."
            }
          />
        ) : (
          <ul className="space-y-2">
            {tab === "form"
              ? (rows as FormFeedback[]).map((row) => <FormRow key={row.id} row={row} />)
              : (rows as SpokenFeedback[]).map((row) => <SpokenRow key={row.id} row={row} />)}
          </ul>
        )}
      </div>
    </Panel>
  );
}
