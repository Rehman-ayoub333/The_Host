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
import { useEffect, useRef, useState } from "react";
import { Radio } from "lucide-react";
import { useAgent } from "@/lib/agent/store";
import { sendSessionNote, setOrderStatus } from "@/lib/agent/service";
import { fmtClock, fmtElapsed, toMs, useNow } from "@/lib/agent/ui";
import type { OperationalMode, OrderStatus, PaymentMethod, TranscriptLine } from "@/lib/agent/types";
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
            {/* 16 §2zi item 3(b): numbers are given out at placing, so a draft is
                shown as a draft rather than by an id no guest was told. */}
            <p className="font-mono text-sm text-foreground">Draft</p>
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

/**
 * 16 §2zf item 4 — the order this guest has just placed and not yet paid for.
 *
 * It sits in the Live panel as well as the Orders panel because this is the
 * screen Rehman is watching while the guest is still standing there: the total
 * is large, the method the guest named is highlighted, and the two presses
 * that take the money are right under it.
 */
function AwaitingPayment() {
  const orders = useAgent((s) => s.orders);
  const [busy, setBusy] = useState(false);
  // The newest one still waiting. It disappears by itself the moment the
  // payment is marked, because it stops matching.
  const order = orders.find((o) => o.status === "AWAITING_PAYMENT");

  if (!order) return null;

  const act = async (status: OrderStatus, method?: PaymentMethod) => {
    setBusy(true);
    await setOrderStatus(order.id, status, undefined, method);
    setBusy(false);
  };

  const btn =
    "h-8 rounded-sm border border-line px-2.5 text-[0.65rem] font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50";

  return (
    <div className="rounded-md border border-warning/40 bg-warning/5 p-3">
      <p className="label-caps mb-1.5 text-warning">Waiting for payment</p>
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-mono text-sm text-foreground">Order #{order.number ?? "—"}</p>
        {order.guest_name && <p className="truncate text-xs text-champagne">{order.guest_name}</p>}
      </div>
      <ul className="mt-1 space-y-0.5">
        {order.items.map((i) => (
          <li key={i.name} className="text-xs text-muted-foreground">
            {i.quantity > 1 ? `${i.quantity}× ` : ""}
            {i.name}
          </li>
        ))}
      </ul>
      <div className="mt-1.5 flex items-baseline justify-between gap-2">
        {/* Shown exactly as sent; no arithmetic, no second "Rs". */}
        {order.total != null && <p className="font-mono text-3xl text-gold">{order.total}</p>}
        <p className="text-[0.68rem] uppercase tracking-wider text-muted-foreground">
          {order.payment_method === "CASH" ? "Guest said cash" : order.payment_method === "QR" ? "Guest said QR" : "No method given"}
        </p>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <button
          disabled={busy}
          onClick={() => void act("CONFIRMED", "CASH")}
          className={cn(btn, order.payment_method === "CASH" && "border-gold bg-gold/10 text-gold")}
        >
          Paid · Cash
        </button>
        <button
          disabled={busy}
          onClick={() => void act("CONFIRMED", "QR")}
          className={cn(btn, order.payment_method === "QR" && "border-gold bg-gold/10 text-gold")}
        >
          Paid · QR
        </button>
        <button
          disabled={busy}
          onClick={() => void act("CANCELLED")}
          className={cn(btn, "hover:border-destructive hover:text-destructive")}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/**
 * 16 §2zf item 6 — the box Rehman types into to steer a live conversation.
 *
 * THE HOST acts on the note at once and never says a word about it (`21`
 * Part A, OPERATOR NOTES). Nothing typed here is kept: the text leaves the
 * box, goes to the backend, and the box is cleared.
 */
const QUICK_NOTES = [
  "This is the Vice Chancellor",
  "Ask them to pay at the counter",
  "Wrap up politely",
] as const;

const NOTE_MAX_CHARS = 300;

function OperatorNote() {
  const state = useAgent((s) => s.lastAgentState);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // The same test the Conversation box uses: a conversation is running when
  // THE HOST has reported any state other than IDLE.
  const live = state !== null && state !== "IDLE";

  const send = async (note: string) => {
    const clean = note.trim();
    if (!clean || !live) return;
    setBusy(true);
    const ok = await sendSessionNote(clean.slice(0, NOTE_MAX_CHARS));
    setBusy(false);
    if (ok) setText("");
  };

  const quickBtn =
    "h-7 rounded-sm border border-line px-2 text-[0.62rem] font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50";

  return (
    <div className="rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps mb-1.5">Tell THE HOST</p>
      <div className="flex gap-2">
        <input
          value={text}
          maxLength={NOTE_MAX_CHARS}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void send(text);
          }}
          placeholder="Tell THE HOST…"
          aria-label="Tell THE HOST"
          className="flex-1 rounded-sm border border-line bg-input px-2 py-1.5 text-xs text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-gold"
        />
        <button
          disabled={busy || !live || text.trim().length === 0}
          onClick={() => void send(text)}
          className="h-8 rounded-sm border border-line px-3 text-[0.65rem] font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50"
        >
          Send
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK_NOTES.map((note) => (
          <button key={note} disabled={busy || !live} onClick={() => void send(note)} className={quickBtn}>
            {note}
          </button>
        ))}
      </div>
      {!live && <p className="mt-2 text-[0.68rem] text-muted-foreground">No conversation is running.</p>}
      <p className="mt-1 text-[0.62rem] text-muted-foreground">
        THE HOST acts on this at once and never reads it out. Nothing typed here is saved.
      </p>
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
        {/* 16 §2zf item 4: nothing at all when no order is waiting. */}
        <AwaitingPayment />
        {/* 16 §2zf item 6: Rehman's own line into the conversation. */}
        <OperatorNote />
        <LiveTranscript />
      </div>
    </Panel>
  );
}
