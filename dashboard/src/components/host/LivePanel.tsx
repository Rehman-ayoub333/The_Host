/**
 * The Live panel (16 §2o item 5) — the operator's one view of the conversation
 * as it happens. Everything here comes from real events only: nothing is
 * polled, inferred or invented.
 *
 * Privacy: the spoken lines are held in memory for the life of the page and
 * nowhere else. They are never written to localStorage, sessionStorage, a
 * cookie, a file, the console or any log, and the backend never sends them to
 * the public display at all (16 §2o item 2).
 */
import { useEffect, useRef } from "react";
import { Radio } from "lucide-react";
import { useAgent } from "@/lib/agent/store";
import { fmtClock, fmtElapsed, toMs, useNow } from "@/lib/agent/ui";
import type { OperationalMode, TranscriptLine } from "@/lib/agent/types";
import { cn } from "@/lib/utils";
import { Panel, StatusDot } from "./Panel";

/** 16 §2o item 5(b). ONLINE green, OFFLINE red, everything else amber. */
const MODE_TONE: Record<OperationalMode, string> = {
  ONLINE: "text-success",
  RECOVERING: "text-warning",
  PAUSED: "text-warning",
  OPERATOR_TAKEOVER: "text-warning",
  DEGRADED: "text-warning",
  OFFLINE: "text-destructive",
};

/** RECOVERING carries its own wording; the rest show the mode as sent. */
function modeText(mode: OperationalMode): string {
  return mode === "RECOVERING" ? "Reconnecting…" : mode;
}

function ConversationState() {
  const state = useAgent((s) => s.lastAgentState);
  const since = useAgent((s) => s.stateSince);
  const now = useNow(1000);

  const idle = state === null || state === "IDLE";
  const elapsed = since !== null && now ? now - since : null;

  return (
    <div className="rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps mb-1.5">Conversation</p>
      {idle ? (
        <p className="text-sm text-muted-foreground">No conversation</p>
      ) : (
        <>
          {/* The backend's own state name, uppercase exactly as sent. */}
          <p className="font-display text-2xl font-semibold text-champagne">{state}</p>
          {elapsed !== null && <p className="mt-0.5 font-mono text-[0.68rem] text-muted-foreground">for {fmtElapsed(elapsed)}</p>}
        </>
      )}
    </div>
  );
}

function OperationalMode_() {
  const opMode = useAgent((s) => s.opMode);
  const mode = opMode?.mode;

  return (
    <div className="rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps mb-1.5">Mode</p>
      {!mode ? (
        <p className="text-sm text-muted-foreground">unknown</p>
      ) : (
        <>
          <p className={cn("flex items-center gap-2 text-lg font-semibold", MODE_TONE[mode])}>
            <StatusDot status={mode === "ONLINE" ? "online" : mode === "OFFLINE" ? "offline" : "degraded"} />
            {modeText(mode)}
          </p>
          {opMode.reason && <p className="mt-0.5 text-[0.68rem] text-muted-foreground">{opMode.reason}</p>}
        </>
      )}
    </div>
  );
}

function OpenDraft() {
  const orders = useAgent((s) => s.orders);
  // The latest order still being taken. It disappears by itself the moment
  // its status changes, because it stops matching.
  const draft = orders.find((o) => o.status === "PENDING_CONFIRMATION");

  return (
    <div className="rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps mb-1.5">Open draft</p>
      {!draft ? (
        <p className="text-sm text-muted-foreground">No open order</p>
      ) : (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <p className="font-mono text-sm text-foreground">Order #{draft.id}</p>
            {draft.guest_name && <p className="truncate text-xs text-champagne">{draft.guest_name}</p>}
          </div>
          <ul className="mt-1 space-y-0.5">
            {draft.items.map((i) => (
              <li key={i.name} className="text-xs text-muted-foreground">
                {i.quantity > 1 ? `${i.quantity}× ` : ""}
                {i.name}
              </li>
            ))}
          </ul>
          <div className="mt-1.5 flex items-center gap-2">
            {/* Shown exactly as sent; no arithmetic, no second "Rs". */}
            {draft.total != null && <p className={cn("font-mono text-xs text-gold", draft.complimentary && "line-through opacity-70")}>{draft.total}</p>}
            {draft.complimentary && (
              <span className="rounded-sm border border-gold/40 px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wider text-gold">On the house</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const SPEAKER_LABEL = { visitor: "Guest", host: "THE HOST" } as const;

function LiveTranscript() {
  const lines = useAgent((s) => s.transcript);
  const boxRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // Follow the newest line, unless Rehman has scrolled up to read back.
  const onScroll = () => {
    const el = boxRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  useEffect(() => {
    const el = boxRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div ref={boxRef} onScroll={onScroll} className="h-[260px] overflow-y-auto rounded-md border border-line bg-background/40 p-3">
      {lines.length === 0 ? (
        <p className="text-sm text-muted-foreground">No conversation yet</p>
      ) : (
        <div className="space-y-1.5">
          {lines.map((l, i) => (
            <LineRow key={l.id} line={l} previous={i > 0 ? lines[i - 1] : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}

function LineRow({ line, previous }: { line: TranscriptLine; previous?: TranscriptLine | undefined }) {
  // A new conversation starts a thin divider carrying its time.
  const newSession = previous !== undefined && previous.session_id !== line.session_id;
  return (
    <>
      {newSession && (
        <div className="flex items-center gap-2 py-1.5">
          <span className="h-px flex-1 bg-line" />
          <span className="font-mono text-[0.58rem] uppercase tracking-widest text-muted-foreground">{fmtClock(line.timestamp ?? line.ts)}</span>
          <span className="h-px flex-1 bg-line" />
        </div>
      )}
      <p className="text-sm leading-snug">
        <span className={cn("mr-2 font-mono text-[0.58rem] uppercase tracking-widest", line.speaker === "host" ? "text-champagne" : "text-gold")}>
          {SPEAKER_LABEL[line.speaker]}
        </span>
        {/* A line still being spoken is muted and italic, and the next event
            for the same role REPLACES it — the text is always the whole line. */}
        <span className={cn(line.final ? "text-foreground/90" : "italic text-muted-foreground")}>{line.text}</span>
      </p>
    </>
  );
}

export function LivePanel({ className }: { className?: string }) {
  const sessionId = useAgent((s) => s.sessionId);

  // 16 §2p item 2: arranged for a narrower box — Conversation and Mode side by
  // side, then the open draft, then the transcript. "What THE HOST just did" is
  // gone: the AI Activity panel beside it shows the same agent_activity rows.
  return (
    <Panel
      title="Live conversation"
      icon={<Radio className="h-4 w-4" />}
      className={className}
      action={sessionId ? <span className="font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">Session {sessionId}</span> : null}
    >
      <p className="mb-3 text-[0.68rem] text-muted-foreground">Operator only. Guest speech is never shown on the public display or saved.</p>
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <ConversationState />
          <OperationalMode_ />
        </div>
        <OpenDraft />
        <LiveTranscript />
      </div>
    </Panel>
  );
}
