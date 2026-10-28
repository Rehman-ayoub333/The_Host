import { useEffect, useRef, useState } from "react";
import {
  Activity as ActivityIcon,
  AudioLines,
  Bookmark,
  Brain,
  Camera,
  CameraOff,
  ChartNoAxesColumn,
  ChefHat,
  Coins,
  Cpu,
  Database,
  Eye,
  Globe,
  Mic,
  MoreHorizontal,
  Radio,
  ScanFace,
  Download,
  Search,
  ShoppingBag,
  Sparkles,
  TriangleAlert,
  UserRound,
  Users,
  Volume2,
} from "lucide-react";
import { agentStore, useAgent } from "@/lib/agent/store";
import { STATE_META, fmtAgo, fmtClock, fmtCountdown, toMs, useNow } from "@/lib/agent/ui";
import type { ActivityKind, AgentStateName, ComponentStatus, Earnings, Order, OrderStatus, PaymentMethod, SystemComponent, Visitor } from "@/lib/agent/types";
import {
  announceAgain,
  downloadEarningsCsv,
  endSession,
  endTakeover,
  forgetVisitor,
  pauseHost,
  reloadVisitors,
  resumeHost,
  retryConnection,
  setOrderStatus,
  startTakeover,
  updateVisitor,
} from "@/lib/agent/service";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AIOrb } from "./AIOrb";
import { VoiceWaveform } from "./VoiceWaveform";
import { DemoTag, EmptyState, Panel, StatusDot } from "./Panel";

const useIsDemo = () => useAgent((s) => s.mode === "demo");
const TagFor = ({ demo }: { demo: boolean }) => (demo ? <DemoTag /> : null);

/* ------------------------------------------------------------------ */
/* THE HOST core                                                       */
/* ------------------------------------------------------------------ */

export function CorePanel({ className }: { className?: string }) {
  const state = useAgent((s) => s.state);
  const caption = useAgent((s) => s.caption);
  const connection = useAgent((s) => s.connection);
  const isDemo = useIsDemo();
  const meta = STATE_META[state];
  const voice = state === "listening" || state === "speaking";

  return (
    <section className={cn("panel panel-corners relative flex flex-col overflow-hidden border-line-strong bg-surface", className)}>
      <div className="pointer-events-none absolute inset-0 scan-grid opacity-20 [mask-image:radial-gradient(circle_at_50%_45%,black,transparent_70%)]" />
      <header className="relative flex items-center justify-between px-5 pt-4">
        <div>
          <p className="label-caps">AI Host</p>
          <h2 className="font-display text-3xl font-semibold tracking-wide text-foreground">THE HOST</h2>
        </div>
        <div className="flex items-center gap-2">
          <TagFor demo={isDemo} />
          <span className="flex items-center gap-2 rounded-sm border border-line bg-background/40 px-2 py-1 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">
            <StatusDot status={isDemo || connection === "live" ? "live" : connection === "connecting" || connection === "reconnecting" ? "degraded" : "unknown"} />
            {isDemo ? "Demo" : connection === "token_error" ? "Token error" : connection}
          </span>
        </div>
      </header>

      <div className="relative mx-auto w-[min(100%,400px)] py-2">
        <AIOrb state={state} />
      </div>

      <div className="relative px-5 pb-5 text-center">
        <p className={cn("label-caps", meta.tone === "brand" ? "text-gold" : meta.tone === "warn" ? "text-destructive" : "text-champagne")}>Current state</p>
        <p key={state} className={cn("animate-rise mt-1 font-display text-4xl font-semibold", meta.tone === "off" ? "text-muted-foreground" : "text-champagne")}>
          {meta.label}
        </p>
        <p className="mt-1 min-h-5 text-sm text-muted-foreground">{state === "offline" ? "Waiting for the agent to connect" : meta.verb}</p>

        <div className="mt-4 rounded-md border border-line bg-background/40 px-4 py-3">
          <VoiceWaveform active={voice} tone={state === "speaking" ? "ivory" : "gold"} bars={48} className="h-8" />
          <p className="mt-2 min-h-10 text-sm leading-snug">
            {caption ? (
              <>
                <span className={cn("mr-2 font-mono text-[0.6rem] uppercase tracking-widest", caption.speaker === "host" ? "text-champagne" : "text-gold")}>
                  {caption.speaker === "host" ? "THE HOST" : "Guest"}
                </span>
                <span className="text-foreground/90">“{caption.text}”</span>
              </>
            ) : (
              <span className="text-muted-foreground">No voice activity</span>
            )}
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Live vision — local camera preview + backend detections             */
/* ------------------------------------------------------------------ */

export function VisionPanel({ className, tall }: { className?: string; tall?: boolean }) {
  const people = useAgent((s) => s.people);
  const objects = useAgent((s) => s.objects);
  const present = useAgent((s) => s.present);
  const focus = useAgent((s) => s.focus);
  const isDemo = useIsDemo();
  const now = useNow(30000);

  const videoRef = useRef<HTMLVideoElement>(null);
  const [localCam, setLocalCam] = useState<MediaStream | null>(null);
  const [camErr, setCamErr] = useState<string | null>(null);

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = localCam;
  }, [localCam]);
  useEffect(() => () => localCam?.getTracks().forEach((t) => t.stop()), [localCam]);

  const toggleLocal = async () => {
    if (localCam) {
      localCam.getTracks().forEach((t) => t.stop());
      setLocalCam(null);
      return;
    }
    try {
      setCamErr(null);
      setLocalCam(await navigator.mediaDevices.getUserMedia({ video: true }));
    } catch {
      setCamErr("Preview unavailable");
    }
  };

  return (
    <Panel
      title="Live Vision"
      icon={<Eye className="h-4 w-4" />}
      className={className}
      bodyClassName="p-0"
      action={
        <div className="flex items-center gap-3">
          <TagFor demo={isDemo} />
          <span className="flex items-center gap-1.5 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">
            <StatusDot status={present ? "live" : "unknown"} /> {present ? "Visitor present" : "No one present"}
          </span>
          <Button variant="outline" size="sm" onClick={toggleLocal} className="h-7 rounded-sm border-line px-2 text-[0.65rem] font-semibold uppercase text-gold transition-colors hover:border-gold hover:bg-gold/10">
            {localCam ? "Stop preview" : "Local preview"}
          </Button>
        </div>
      }
    >
      <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_200px]">
        <div className={cn("relative overflow-hidden bg-background", tall ? "aspect-video lg:aspect-auto lg:min-h-[520px]" : "aspect-video lg:aspect-auto lg:min-h-[380px]")}>
          {localCam ? (
            <>
              <video ref={videoRef} autoPlay muted playsInline className="absolute inset-0 h-full w-full -scale-x-100 object-cover" />
              <span className="absolute bottom-3 left-3 rounded-sm bg-background/80 px-2 py-1 font-mono text-[0.6rem] uppercase tracking-widest text-muted-foreground">
                Local preview · never uploaded
              </span>
            </>
          ) : (
            <div className="absolute inset-0 grid place-items-center scan-grid">
              <EmptyState icon={<CameraOff className="h-7 w-7" />} title={camErr ?? "No preview running"} hint="The camera preview is opened locally by this dashboard and never sent anywhere." />
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4 border-t border-line p-4 lg:border-l lg:border-t-0">
          <div>
            <p className="label-caps mb-2">Detections</p>
            <ul className="space-y-1.5">
              <li className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 text-foreground/90">
                  <UserRound className="h-3.5 w-3.5 text-champagne" /> People
                </span>
                <span className="font-mono text-muted-foreground">{people}</span>
              </li>
              {objects.map((o) => (
                <li key={o.label} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-foreground/90">
                    <ScanFace className="h-3.5 w-3.5 text-gold-dim" /> {o.label}
                  </span>
                  <span className="font-mono text-muted-foreground">{Math.round(o.confidence * 100)}%</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-auto rounded-md border border-line bg-background/40 p-3">
            <p className="label-caps mb-2">Current focus</p>
            {focus ? (
              <div className="animate-rise">
                <div className="flex items-center gap-2">
                  <Avatar name={focus.name} />
                  <div>
                    <p className="text-sm font-semibold">Identified by name: {focus.name}</p>
                    <p className="text-[0.68rem] text-gold">{focus.returning ? "Returning visitor" : "New visitor"}</p>
                  </div>
                </div>
                {focus.visits !== undefined && <p className="mt-2 text-[0.68rem] text-muted-foreground">{focus.visits} visits</p>}
                {focus.favorite_item && <p className="text-[0.68rem] text-muted-foreground">Favourite: {focus.favorite_item}</p>}
                {focus.last_order && <p className="text-[0.68rem] text-muted-foreground">Last order: {focus.last_order}</p>}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No one identified</p>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function Avatar({ name, size = "sm" }: { name: string; size?: "sm" | "lg" }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full border border-gold/50 bg-gradient-to-br from-gold/25 to-surface-2 font-display font-semibold text-gold",
        size === "sm" ? "h-8 w-8 text-sm" : "h-16 w-16 text-2xl",
      )}
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Orders + operator controls                                          */
/* ------------------------------------------------------------------ */

const STATUS_STYLE: Record<OrderStatus, string> = {
  PENDING_CONFIRMATION: "text-champagne",
  // 16 §2zf item 4: money is owed, so it reads as something to act on.
  AWAITING_PAYMENT: "text-warning",
  CONFIRMED: "text-champagne",
  PREPARING: "text-warning",
  READY: "text-success",
  COLLECTED: "text-muted-foreground",
  CANCELLED: "text-destructive",
  FAILED: "text-destructive",
  REQUIRES_ATTENTION: "text-destructive",
};

const STATUS_LABEL: Record<OrderStatus, string> = {
  PENDING_CONFIRMATION: "Being taken",
  AWAITING_PAYMENT: "Waiting for payment",
  CONFIRMED: "Confirmed",
  PREPARING: "Preparing",
  READY: "Ready",
  COLLECTED: "Collected",
  CANCELLED: "Cancelled",
  FAILED: "Failed",
  REQUIRES_ATTENTION: "Needs attention",
};

/** 16 §2zf item 3(a): every status an order reaches once the money is taken. */
const PAID_STATUSES: OrderStatus[] = ["CONFIRMED", "PREPARING", "READY", "COLLECTED"];

function OrderActions({ order }: { order: Order }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmFail, setConfirmFail] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const act = async (status: OrderStatus, r?: string, payment?: PaymentMethod) => {
    setBusy(true);
    await setOrderStatus(order.id, status, r, payment);
    setBusy(false);
    setMenuOpen(false);
    setConfirmFail(false);
    setCancelOpen(false);
    setReason("");
  };

  const btn = "h-7 rounded-sm border border-line px-2 text-[0.65rem] font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50";

  if (confirmFail) {
    return (
      <div className="mt-2.5 flex items-center gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2">
        <p className="flex-1 text-[0.68rem] text-destructive">Mark order #{order.id} as failed?</p>
        <button disabled={busy} onClick={() => void act("FAILED")} className="text-[0.65rem] font-semibold uppercase text-destructive hover:underline">Yes</button>
        <button onClick={() => setConfirmFail(false)} className="text-[0.65rem] font-semibold uppercase text-muted-foreground hover:underline">No</button>
      </div>
    );
  }
  if (cancelOpen) {
    return (
      <div className="mt-2.5 space-y-2 rounded-sm border border-line bg-background/60 p-2">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (optional)"
          className="w-full rounded-sm border border-line bg-input px-2 py-1 text-xs text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-gold"
        />
        <div className="flex gap-2">
          <button disabled={busy} onClick={() => void act("CANCELLED", reason || undefined)} className="text-[0.65rem] font-semibold uppercase text-destructive hover:underline">Cancel order</button>
          <button onClick={() => setCancelOpen(false)} className="text-[0.65rem] font-semibold uppercase text-muted-foreground hover:underline">Back</button>
        </div>
      </div>
    );
  }

  // 16 §2zf item 4: the two presses that take the money. The method the guest
  // named is highlighted, because it is what the team expects at the counter —
  // but either press is allowed, since what was really handed over wins.
  const paidBtn = (method: PaymentMethod, label: string) => (
    <button
      disabled={busy}
      onClick={() => void act("CONFIRMED", undefined, method)}
      className={cn(
        btn,
        order.payment_method === method && "border-gold bg-gold/10 text-gold",
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="relative mt-2.5 flex flex-wrap items-center gap-1.5">
      {/* 16 §2zf item 4: an order waiting for payment is not the kitchen's
          yet. The only things to do with it are take the money or cancel it. */}
      {order.status === "AWAITING_PAYMENT" && (
        <>
          {paidBtn("CASH", "Paid · Cash")}
          {paidBtn("QR", "Paid · QR")}
        </>
      )}
      {(order.status === "CONFIRMED" || order.status === "REQUIRES_ATTENTION") && (
        <button disabled={busy} onClick={() => void act("PREPARING")} className={btn}>Preparing</button>
      )}
      {(order.status === "PREPARING" || order.status === "REQUIRES_ATTENTION") && (
        <button disabled={busy} onClick={() => void act("READY")} className={btn}>Ready</button>
      )}
      {/* 16 §2zf item 4, replacing §2z item 3's two buttons: under pay-first
          the method is already on the order by the time the food goes out, so
          collection is one press again, for every order. */}
      {(order.status === "READY" || order.status === "REQUIRES_ATTENTION") && (
        <button disabled={busy} onClick={() => void act("COLLECTED")} className={btn}>Collected</button>
      )}
      {/* A deliberate repeat of the announcement (20 §4 item 4). */}
      {order.status === "READY" && (
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void announceAgain(order.id).finally(() => setBusy(false));
          }}
          className={btn}
        >
          Announce again
        </button>
      )}
      {(order.status === "AWAITING_PAYMENT" || order.status === "CONFIRMED" || order.status === "PREPARING" || order.status === "REQUIRES_ATTENTION") && (
        <button disabled={busy} onClick={() => setCancelOpen(true)} className={cn(btn, "hover:border-destructive hover:text-destructive")}>Cancel</button>
      )}
      {(order.status === "CONFIRMED" || order.status === "PREPARING" || order.status === "READY") && (
        <button disabled={busy} onClick={() => setMenuOpen((v) => !v)} className={cn(btn, "px-1.5")} aria-label="More actions">
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      )}
      {menuOpen && (
        <div className="absolute bottom-8 right-0 z-10 w-44 rounded-md border border-line bg-surface p-1 shadow-xl">
          <button onClick={() => void act("REQUIRES_ATTENTION")} className="block w-full rounded-sm px-2.5 py-1.5 text-left text-xs text-foreground hover:bg-surface-2">Flag for attention</button>
          <button onClick={() => { setMenuOpen(false); setConfirmFail(true); }} className="block w-full rounded-sm px-2.5 py-1.5 text-left text-xs text-destructive hover:bg-surface-2">Mark failed</button>
        </div>
      )}
    </div>
  );
}

export function OrderCard({ order, now }: { order: Order; now: number }) {
  // Every time field is a booth-local ISO string: parsed once, here.
  // A null or missing estimate means no countdown and no progress bar —
  // never an invented figure (20 §4 item 1).
  const readyAtMs = toMs(order.estimated_ready_at);
  const placedAtMs = toMs(order.timestamp);
  const remaining = readyAtMs !== null && now ? readyAtMs - now : null;
  const pct =
    order.status === "READY" || order.status === "COLLECTED"
      ? 100
      : remaining !== null && placedAtMs !== null && readyAtMs !== null && readyAtMs > placedAtMs
        ? Math.min(100, Math.max(4, 100 - (remaining / (readyAtMs - placedAtMs)) * 100))
        : order.status === "PENDING_CONFIRMATION" || order.status === "CONFIRMED"
          ? 8
          : 0;
  const done = order.status === "COLLECTED" || order.status === "CANCELLED" || order.status === "FAILED";

  return (
    <div className="animate-rise rounded-md border border-line bg-background/40 p-3 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">Order #{order.id}</p>
          <p className="truncate text-sm font-semibold">{order.guest_name ?? "Guest"}</p>
        </div>
        <div className="text-right">
          <p className={cn("text-xs font-semibold", STATUS_STYLE[order.status])}>● {STATUS_LABEL[order.status]}</p>
          {order.status === "PREPARING" && remaining !== null && <p className="font-mono text-sm text-foreground">{fmtCountdown(remaining)} left</p>}
        </div>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">{order.items.map((i) => `${i.quantity > 1 ? `${i.quantity}× ` : ""}${i.name}`).join(" · ")}</p>
      {/* 16 §2m item 5 / §2o item 4: a complimentary order carries a badge and
          its total is struck through. The public display never shows either. */}
      <div className="mt-0.5 flex items-center gap-2">
        {/* The total is already formatted ("Rs. 1,300"): shown exactly as sent,
            with no second "Rs" prefix and no arithmetic. null shows nothing. */}
        {order.total != null && (
          <p className={cn("font-mono text-xs text-gold", order.complimentary && "line-through opacity-70")}>{order.total}</p>
        )}
        {order.complimentary && (
          <span className="rounded-sm border border-gold/40 px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider text-gold">On the house</span>
        )}
        {/* 16 §2z item 3, as §2zf item 4 extends it: from the payment on, a
            card says how it was paid. An order waiting for payment is handled
            on its own below, and an old row that recorded nothing says exactly
            that instead of guessing. */}
        {PAID_STATUSES.includes(order.status) && !order.complimentary && (
          <span className="rounded-sm border border-line px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider text-muted-foreground">
            {order.payment_method === "CASH" ? "Paid · Cash" : order.payment_method === "QR" ? "Paid · QR" : "Paid · not recorded"}
          </span>
        )}
      </div>
      {/* 16 §2zf item 4: the total large, and the method the guest named, so
          the team at the counter knows what to expect before they take it. */}
      {order.status === "AWAITING_PAYMENT" && (
        <div className="mt-2 flex items-baseline justify-between gap-2 rounded-sm border border-warning/30 bg-warning/5 px-2.5 py-2">
          <p className="text-[0.68rem] font-semibold uppercase tracking-wider text-warning">
            Waiting for payment
            {order.payment_method === "CASH" ? " · Cash" : order.payment_method === "QR" ? " · QR" : ""}
          </p>
          {order.total != null && <p className="font-mono text-2xl text-gold">{order.total}</p>}
        </div>
      )}
      {!done && (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-2">
          <div className={cn("h-full rounded-full transition-all duration-1000", order.status === "READY" ? "bg-success" : "bg-gradient-to-r from-gold-dim to-champagne")} style={{ width: `${pct}%` }} />
        </div>
      )}
      {!done && order.status !== "PENDING_CONFIRMATION" && <OrderActions order={order} />}
    </div>
  );
}

export function OrdersPanel({ className, limit = 3 }: { className?: string; limit?: number }) {
  const orders = useAgent((s) => s.orders);
  const isDemo = useIsDemo();
  const now = useNow(1000);
  const [tab, setTab] = useState<"active" | "completed" | "all">("active");
  const taking = orders.filter((o) => o.status === "PENDING_CONFIRMATION");
  // 16 §2zf item 4: an order waiting for payment is active, and it is shown
  // at the top of whatever is on screen — it is the one thing holding a guest
  // at the counter, so it must never scroll out of sight behind the kitchen.
  const unpaid = orders.filter((o) => o.status === "AWAITING_PAYMENT");
  const active = orders.filter((o) => ["AWAITING_PAYMENT", "CONFIRMED", "PREPARING", "READY", "REQUIRES_ATTENTION"].includes(o.status));
  const completed = orders.filter((o) => ["COLLECTED", "CANCELLED", "FAILED"].includes(o.status));
  const chosen = tab === "active" ? active : tab === "completed" ? completed : orders.filter((o) => o.status !== "PENDING_CONFIRMATION");
  const list = [
    ...chosen.filter((o) => o.status === "AWAITING_PAYMENT"),
    ...chosen.filter((o) => o.status !== "AWAITING_PAYMENT"),
  ].slice(0, limit);

  return (
    <Panel title="Orders" icon={<ShoppingBag className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {taking.length > 0 && (
        <p className="mb-2 animate-pulse rounded-sm border border-champagne/20 bg-champagne/5 px-2.5 py-1.5 text-[0.68rem] text-champagne/80">Order being taken…</p>
      )}
      {unpaid.length > 0 && (
        <p className="mb-2 rounded-sm border border-warning/30 bg-warning/5 px-2.5 py-1.5 text-[0.68rem] font-semibold text-warning">
          {unpaid.length === 1 ? "1 order waiting for payment" : `${unpaid.length} orders waiting for payment`}
        </p>
      )}
      <div className="mb-3 flex gap-1 rounded-md bg-background/50 p-1">
        {(
          [
            ["active", `Active ${active.length}`],
            ["completed", `Completed ${completed.length}`],
            ["all", "All"],
          ] as const
        ).map(([k, l]) => (
          <Button key={k} variant="ghost" size="sm" onClick={() => setTab(k)} className={cn("h-7 flex-1 rounded-sm px-2 text-xs font-medium transition-colors", tab === k ? "bg-gold/15 text-gold" : "text-muted-foreground hover:text-foreground")}>
            {l}
          </Button>
        ))}
      </div>
      {list.length === 0 ? (
        <EmptyState icon={<ChefHat className="h-6 w-6" />} title="No orders yet" hint="Orders appear the moment THE HOST confirms one." />
      ) : (
        <div className="space-y-2">
          {list.map((o) => (
            <OrderCard key={o.id} order={o} now={now} />
          ))}
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Activity                                                            */
/* ------------------------------------------------------------------ */

const KIND_ICON: Record<ActivityKind, typeof Eye> = {
  vision: Eye,
  speech: Mic,
  order: ShoppingBag,
  memory: Bookmark,
  visitor: UserRound,
  system: Cpu,
  operator: Sparkles,
};

export function ActivityPanel({ className, limit = 7 }: { className?: string; limit?: number }) {
  const activity = useAgent((s) => s.activity);
  const isDemo = useIsDemo();
  return (
    <Panel title="AI Activity" icon={<ActivityIcon className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {activity.length === 0 ? (
        <EmptyState icon={<Radio className="h-6 w-6" />} title="Quiet for now" hint="Every event THE HOST reports is logged here in real time." />
      ) : (
        <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[15px] before:top-2 before:w-px before:bg-line">
          {activity.slice(0, limit).map((a) => {
            const Icon = KIND_ICON[a.kind] ?? Radio;
            return (
              <li key={a.id} className="animate-rise relative flex gap-3">
                <span className={cn("relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border bg-surface", a.kind === "memory" || a.kind === "order" ? "border-gold/40 text-gold" : "border-champagne/40 text-champagne")}>
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-medium">{a.label}</p>
                    <span className="font-mono text-[0.62rem] text-muted-foreground">{fmtClock(a.timestamp)}</span>
                  </div>
                  {a.detail && <p className="truncate text-xs text-muted-foreground">{a.detail}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Visitors & memory                                                   */
/* ------------------------------------------------------------------ */

/**
 * Edit and Forget for one visitor (20 §4 item 4). The PATCH sends only the
 * fields that actually changed; an emptied favourite sends null. Forget asks
 * first. Both reload GET /api/visitors afterwards.
 */
function VisitorActions({ visitor }: { visitor: Visitor }) {
  const [editing, setEditing] = useState(false);
  const [confirmForget, setConfirmForget] = useState(false);
  const [name, setName] = useState(visitor.name);
  const [favorite, setFavorite] = useState(visitor.favorite_item ?? "");
  const [busy, setBusy] = useState(false);
  const nameKey = visitor.name_key;

  const field = "w-full rounded-sm border border-line bg-input px-2 py-1 text-xs text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-gold";

  if (!nameKey) return null;

  const save = async () => {
    const patch: { display_name?: string; favorite_item?: string | null } = {};
    const trimmedName = name.trim();
    if (trimmedName && trimmedName !== visitor.name) patch.display_name = trimmedName;
    const trimmedFav = favorite.trim();
    const currentFav = visitor.favorite_item ?? "";
    if (trimmedFav !== currentFav) patch.favorite_item = trimmedFav === "" ? null : trimmedFav;
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    setBusy(true);
    const ok = await updateVisitor(nameKey, patch);
    setBusy(false);
    if (ok) {
      setEditing(false);
      await reloadVisitors();
    }
  };

  if (confirmForget) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-sm border border-destructive/40 bg-destructive/5 p-2">
        <p className="flex-1 text-[0.68rem] text-destructive">Forget {visitor.name}?</p>
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void forgetVisitor(nameKey).then(async (ok) => {
              setBusy(false);
              setConfirmForget(false);
              if (ok) await reloadVisitors();
            });
          }}
          className="text-[0.65rem] font-semibold uppercase text-destructive hover:underline"
        >
          Yes
        </button>
        <button onClick={() => setConfirmForget(false)} className="text-[0.65rem] font-semibold uppercase text-muted-foreground hover:underline">No</button>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="mt-2 space-y-2 rounded-sm border border-line bg-background/60 p-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Name" className={field} />
        <input value={favorite} onChange={(e) => setFavorite(e.target.value)} placeholder="Favourite item" aria-label="Favourite item" className={field} />
        <div className="flex gap-2">
          <button disabled={busy} onClick={() => void save()} className="text-[0.65rem] font-semibold uppercase text-gold hover:underline">Save</button>
          <button onClick={() => setEditing(false)} className="text-[0.65rem] font-semibold uppercase text-muted-foreground hover:underline">Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2 flex gap-1.5">
      <button onClick={() => setEditing(true)} className={OP_BTN}>Edit</button>
      <button onClick={() => setConfirmForget(true)} className={cn(OP_BTN, "hover:border-destructive hover:text-destructive")}>Forget</button>
    </div>
  );
}

export function VisitorsPanel({ className, limit = 4 }: { className?: string; limit?: number }) {
  const visitors = useAgent((s) => s.visitors);
  const isDemo = useIsDemo();
  const now = useNow(30000);
  return (
    <Panel title="Visitors" icon={<Users className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {visitors.length === 0 ? (
        <EmptyState icon={<Users className="h-6 w-6" />} title="No visitors yet" hint="Visitors are listed when the agent's memory reports them." />
      ) : (
        <ul className="divide-y divide-line">
          {visitors.slice(0, limit).map((v) => (
            <li key={v.name_key ?? v.name} className="animate-rise py-2.5 first:pt-0 last:pb-0">
              <div className="flex items-center gap-3">
                <Avatar name={v.name} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{v.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {v.last_order ?? "No orders"}{fmtAgo(v.last_seen, now) ? ` · ${fmtAgo(v.last_seen, now)}` : ""}
                  </p>
                </div>
                <span className={cn("rounded-sm border px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider", v.returning ? "border-gold/40 text-gold" : "border-champagne/40 text-champagne")}>
                  {v.returning ? "Returning" : "New"}
                </span>
              </div>
              {!isDemo && <VisitorActions visitor={v} />}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function MemoryPanel({ className, limit = 4 }: { className?: string; limit?: number }) {
  const memory = useAgent((s) => s.memory);
  const isDemo = useIsDemo();
  const now = useNow(30000);
  return (
    <Panel title="Memory" icon={<Bookmark className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {memory.length === 0 ? (
        <EmptyState icon={<Sparkles className="h-6 w-6" />} title="No memories stored" hint="THE HOST only shows what its memory system has actually saved." />
      ) : (
        <ul className="space-y-2">
          {memory.slice(0, limit).map((m) => (
            <li key={m.id} className="animate-rise rounded-md border border-line bg-background/40 p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-gold">{m.name}</p>
                {m.last_seen && <span className="text-[0.62rem] text-muted-foreground">{fmtAgo(m.last_seen, now)}</span>}
              </div>
              <p className="mt-0.5 text-xs text-foreground/80">
                {m.visits} visits{m.favorite_item ? ` · favourite: ${m.favorite_item}` : ""}{m.last_order ? ` · last: ${m.last_order}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Transcript                                                          */
/* ------------------------------------------------------------------ */

export function TranscriptPanel({ className }: { className?: string }) {
  const transcript = useAgent((s) => s.transcript);
  const state = useAgent((s) => s.state);
  const isDemo = useIsDemo();
  return (
    <Panel title="Voice Interaction" icon={<AudioLines className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {transcript.length === 0 ? (
        <EmptyState icon={<Mic className="h-6 w-6" />} title="No conversation yet" hint="Transcripts stream in from the agent's speech pipeline." />
      ) : (
        <div className="space-y-2.5">
          {transcript.slice(-4).map((l) => (
            <div key={l.id} className={cn("animate-rise flex gap-2", l.speaker === "host" && "flex-row-reverse text-right")}>
              <span className={cn("mt-0.5 font-mono text-[0.58rem] uppercase tracking-widest", l.speaker === "host" ? "text-champagne" : "text-gold")}>{l.speaker === "host" ? "THE HOST" : "Guest"}</span>
              <p className={cn("max-w-[85%] rounded-md border px-3 py-2 text-sm", l.speaker === "host" ? "border-champagne/25 bg-champagne/5" : "border-line bg-background/40", !l.final && "opacity-60")}>{l.text}</p>
            </div>
          ))}
        </div>
      )}
      <VoiceWaveform active={state === "listening" || state === "speaking"} bars={60} className="mt-3 h-6" />
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* System                                                              */
/* ------------------------------------------------------------------ */

const BACKEND_ROWS: [SystemComponent, string, typeof Eye][] = [
  ["backend", "Backend", Cpu],
  ["ai_agent", "AI Agent", Brain],
  ["database", "Database", Database],
  ["web_search", "Web Search", Search],
];

const BROWSER_ROWS: [SystemComponent, string, typeof Eye][] = [
  ["camera", "Camera", Camera],
  ["microphone", "Microphone", Mic],
  ["speaker", "Speaker", Volume2],
  ["internet", "Internet", Globe],
];

/** A small uppercase operator button, matching the order-card buttons. */
const OP_BTN = "h-7 rounded-sm border border-line px-2 text-[0.65rem] font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50";

/**
 * The operator controls (20 §4 item 4). Pause, Take over and End conversation
 * ask for confirmation first. Nothing on screen changes until the backend's
 * response or its event arrives: each handler only awaits the call and reports
 * the result, while `operational_mode_changed` updates the mode.
 */
function OperatorControls() {
  const opMode = useAgent((s) => s.opMode);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<null | "pause" | "takeover" | "end-session">(null);
  const [note, setNote] = useState<string | null>(null);

  const mode = opMode?.mode;
  const paused = mode === "PAUSED";
  const takenOver = mode === "OPERATOR_TAKEOVER";

  const run = async (fn: () => Promise<unknown>, after?: (r: unknown) => void) => {
    setBusy(true);
    setNote(null);
    const result = await fn();
    setBusy(false);
    setConfirming(null);
    if (result !== null && after) after(result);
  };

  const CONFIRM_TEXT: Record<"pause" | "takeover" | "end-session", string> = {
    pause: "Pause THE HOST? The current conversation ends.",
    takeover: "Take over? The current conversation ends.",
    "end-session": "End the conversation now?",
  };

  const doConfirmed = () => {
    if (confirming === "pause") return void run(pauseHost);
    if (confirming === "takeover") return void run(startTakeover);
    if (confirming === "end-session")
      return void run(endSession, (r) => setNote((r as { ended: boolean }).ended ? "Conversation ended" : "No conversation running"));
  };

  return (
    <div className="mb-3 rounded-md border border-line bg-background/40 p-3">
      <p className="label-caps mb-2">Operator</p>
      <p className="mb-2.5 text-[0.68rem] text-muted-foreground">
        Mode: <span className="font-semibold text-foreground/90">{mode ?? "unknown"}</span>
        {opMode?.reason ? ` — ${opMode.reason}` : ""}
      </p>

      {confirming ? (
        <div className="flex items-center gap-2 rounded-sm border border-warning/40 bg-warning/5 p-2">
          <p className="flex-1 text-[0.68rem] text-warning">{CONFIRM_TEXT[confirming]}</p>
          <button disabled={busy} onClick={doConfirmed} className="text-[0.65rem] font-semibold uppercase text-warning hover:underline">Yes</button>
          <button onClick={() => setConfirming(null)} className="text-[0.65rem] font-semibold uppercase text-muted-foreground hover:underline">No</button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {paused ? (
            <button disabled={busy} onClick={() => void run(resumeHost)} className={OP_BTN}>Resume THE HOST</button>
          ) : (
            <button disabled={busy} onClick={() => setConfirming("pause")} className={OP_BTN}>Pause THE HOST</button>
          )}
          {takenOver ? (
            <button disabled={busy} onClick={() => void run(endTakeover)} className={OP_BTN}>End takeover</button>
          ) : (
            <button disabled={busy} onClick={() => setConfirming("takeover")} className={OP_BTN}>Take over</button>
          )}
          <button disabled={busy} onClick={() => setConfirming("end-session")} className={OP_BTN}>End conversation</button>
          <button
            disabled={busy}
            onClick={() => void run(retryConnection, (r) => setNote((r as { reachable: boolean }).reachable ? "AI service reachable" : "AI service unreachable"))}
            className={OP_BTN}
          >
            Retry connection
          </button>
        </div>
      )}
      {note && <p className="mt-2 text-[0.68rem] text-champagne">{note}</p>}
    </div>
  );
}

export function SystemPanel({ className }: { className?: string }) {
  const system = useAgent((s) => s.system);
  const connection = useAgent((s) => s.connection);
  const opMode = useAgent((s) => s.opMode);
  const tokenError = useAgent((s) => s.tokenError);

  // Browser-side checks: camera/mic permission state, navigator.onLine.
  useEffect(() => {
    const setSys = (patch: Partial<Record<SystemComponent, ComponentStatus>>) => {
      const s = agentStore.get();
      agentStore.dispatch({ type: "@hydrate", snapshot: { system: { ...s.system, ...patch } } });
    };
    setSys({ internet: navigator.onLine ? "online" : "offline" });
    const on = () => setSys({ internet: "online" });
    const off = () => setSys({ internet: "offline" });
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    navigator.permissions?.query({ name: "camera" as PermissionName }).then((p) => setSys({ camera: p.state === "granted" ? "online" : "unknown" })).catch(() => undefined);
    navigator.permissions?.query({ name: "microphone" as PermissionName }).then((p) => setSys({ microphone: p.state === "granted" ? "online" : "unknown" })).catch(() => undefined);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  return (
    <Panel title="System" icon={<Cpu className="h-4 w-4" />} className={className}>
      <OperatorControls />
      {opMode && opMode.mode !== "ONLINE" && (
        <p className="mb-3 rounded-sm border border-warning/40 bg-warning/10 px-2.5 py-1.5 text-[0.68rem] text-warning">
          Mode: {opMode.mode}{opMode.reason ? ` — ${opMode.reason}` : ""}
        </p>
      )}
      {tokenError && (
        <p className="mb-3 rounded-sm border border-destructive/40 bg-destructive/10 px-2.5 py-1.5 text-[0.68rem] text-destructive">{tokenError}</p>
      )}
      <ul className="space-y-2.5">
        {[...BACKEND_ROWS, ...BROWSER_ROWS].map(([k, label, Icon]) => (
          <li key={k} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2.5 text-foreground/90">
              <Icon className="h-4 w-4 text-muted-foreground" />
              {label}
            </span>
            <span className="flex items-center gap-2 text-xs capitalize text-muted-foreground">
              <StatusDot status={system[k]} />
              {system[k]}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 hairline-gold" />
      <p className="mt-3 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">
        Agent link · {connection === "live" ? "live" : connection === "token_error" ? "token error" : connection === "reconnecting" ? "reconnecting" : connection}
      </p>
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Analytics (from GET /api/analytics only)                            */
/* ------------------------------------------------------------------ */

/** The "Today" row from GET /api/metrics, reloaded every 30 s (20 §4 item 4). */
export function MetricsToday({ className }: { className?: string }) {
  const metrics = useAgent((s) => s.metrics);
  if (!metrics) return null;
  const rows: [string, number][] = [
    ["Sessions today", metrics.sessions_today],
    ["Orders today", metrics.orders_today],
    ["Failed tool calls today", metrics.failed_tool_calls_today],
    ["Connection failures today", metrics.connection_failures_today],
  ];
  return (
    <div className={cn("mb-4 rounded-md border border-line bg-background/40 p-2.5", className)}>
      <p className="label-caps mb-2">Today · {metrics.date}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label}>
            <p className="label-caps !text-[0.56rem]">{label}</p>
            <p className="mt-0.5 font-mono text-xl text-foreground">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AnalyticsPanel({ className }: { className?: string }) {
  const analytics = useAgent((s) => s.analytics);
  const isDemo = useIsDemo();

  return (
    <Panel title="Analytics" icon={<ChartNoAxesColumn className="h-4 w-4" />} className={className} action={<TagFor demo={isDemo} />}>
      {!isDemo && <MetricsToday />}
      {!analytics ? (
        <EmptyState icon={<ChartNoAxesColumn className="h-6 w-6" />} title="No analytics yet" hint="Daily figures arrive from the backend every 30 seconds." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            {(
              [
                ["Orders", analytics.orders],
                ["Interactions", analytics.interactions],
                ["Named visitors", analytics.named_visitors],
                ["Returning", analytics.returning_visitors],
              ] as const
            ).map(([l, v]) => (
              <div key={l} className="rounded-md border border-line bg-background/40 p-2.5">
                <p className="label-caps !text-[0.56rem]">{l}</p>
                <p className="mt-1 font-mono text-2xl text-foreground">{v}</p>
              </div>
            ))}
          </div>
          <p className="label-caps mb-2 mt-4">Popular items</p>
          {analytics.popular_items.length === 0 ? (
            <p className="text-xs text-muted-foreground">No order data yet</p>
          ) : (
            <ul className="space-y-2">
              {analytics.popular_items.map((p) => (
                <li key={p.name}>
                  <div className="flex justify-between text-xs">
                    <span className="text-foreground/90">{p.name}</span>
                    <span className="font-mono text-muted-foreground">{p.percent}%</span>
                  </div>
                  <div className="mt-1 h-1 rounded-full bg-surface-2">
                    <div className="h-full rounded-full bg-gradient-to-r from-gold-dim to-gold transition-all duration-700" style={{ width: `${p.percent}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Earnings — 16 §2z. Operator only: never on /display.                */
/* ------------------------------------------------------------------ */

/** Rupees as the gala reads them: "Rs. 12,450", never a bare number. */
export const fmtRs = (amount: number) => `Rs. ${Math.round(amount).toLocaleString("en-US")}`;

/**
 * Demo Mode's own figures (16 §2z item 5). They are invented on purpose and
 * carry the DEMO DATA tag, so a demonstration never shows the real takings
 * and never hides them either.
 */
const DEMO_EARNINGS: Earnings = {
  date: "demo",
  earned: 12450,
  earned_cash: 7200,
  earned_qr: 5250,
  earned_unrecorded: 0,
  awaiting_payment: 1850,
  on_the_house: 600,
  on_the_house_orders: 2,
  paid_orders: 24,
  cancelled_orders: 1,
  refunded: 250,
  refunded_orders: 1,
  by_item: [
    { name: "Chicken Burger", quantity: 9, amount: 5850 },
    { name: "Club Sandwich", quantity: 6, amount: 3300 },
    { name: "Mixed Fruit Shake", quantity: 5, amount: 1750 },
    { name: "Blue Lemonade", quantity: 6, amount: 1500 },
  ],
  unpriced_orders: 0,
};

function Figure({ label, value, tone }: { label: string; value: string; tone?: "gold" | "plain" }) {
  return (
    <div className="rounded-md border border-line bg-background/40 p-2.5">
      <p className="label-caps !text-[0.56rem]">{label}</p>
      <p className={cn("mt-1 font-mono text-2xl", tone === "gold" ? "text-gold" : "text-foreground")}>{value}</p>
    </div>
  );
}

export function EarningsPanel({ className }: { className?: string }) {
  const live = useAgent((s) => s.earnings);
  const isDemo = useIsDemo();
  const [busy, setBusy] = useState(false);
  const earnings = isDemo ? DEMO_EARNINGS : live;

  return (
    <Panel
      title="Earnings"
      icon={<Coins className="h-4 w-4" />}
      className={className}
      action={
        <div className="flex items-center gap-3">
          <TagFor demo={isDemo} />
          <Button
            variant="outline"
            size="sm"
            disabled={busy || isDemo}
            onClick={() => {
              setBusy(true);
              void downloadEarningsCsv().finally(() => setBusy(false));
            }}
            className="h-7 rounded-sm border-line px-2 text-[0.65rem] font-semibold uppercase text-gold transition-colors hover:border-gold hover:bg-gold/10"
          >
            <Download className="mr-1 h-3 w-3" /> Download today's sales (CSV)
          </Button>
        </div>
      }
    >
      {!earnings ? (
        <EmptyState icon={<Coins className="h-6 w-6" />} title="No figures yet" hint="The takings arrive from the backend on connect and every 30 seconds." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Figure label="Earned today" value={fmtRs(earnings.earned)} tone="gold" />
            <Figure label="Cash" value={fmtRs(earnings.earned_cash)} />
            <Figure label="QR" value={fmtRs(earnings.earned_qr)} />
            {/* 16 §2zf item 4: what is still at the counter, not what is
                still in the kitchen — under pay-first they are not the same. */}
            <Figure label="Waiting for payment" value={fmtRs(earnings.awaiting_payment)} />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
            <span>
              On the house <span className="font-mono text-foreground/90">{fmtRs(earnings.on_the_house)}</span> ({earnings.on_the_house_orders})
            </span>
            <span>
              Paid orders <span className="font-mono text-foreground/90">{earnings.paid_orders}</span>
            </span>
            <span>
              Cancelled <span className="font-mono text-foreground/90">{earnings.cancelled_orders}</span>
            </span>
            {/* 16 §2zf item 3(i): money taken and then given back. */}
            <span>
              Refunded <span className="font-mono text-foreground/90">{fmtRs(earnings.refunded)}</span> ({earnings.refunded_orders})
            </span>
          </div>

          {/* 16 §2z item 5: both warnings, in plain words, only when they apply. */}
          {earnings.earned_unrecorded > 0 && (
            <p className="mt-2 text-xs text-warning">{fmtRs(earnings.earned_unrecorded)} collected without a payment type</p>
          )}
          {earnings.unpriced_orders > 0 && (
            <p className="mt-1 flex items-center gap-1.5 text-xs text-destructive">
              <TriangleAlert className="h-3.5 w-3.5" />
              {earnings.unpriced_orders} order{earnings.unpriced_orders === 1 ? "" : "s"} had no price and are in none of these figures
            </p>
          )}

          <p className="label-caps mb-2 mt-4">By item</p>
          {earnings.by_item.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nothing collected yet</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="pb-1 text-left font-normal">Item</th>
                  <th className="pb-1 text-right font-normal">Sold</th>
                  <th className="pb-1 text-right font-normal">Amount</th>
                </tr>
              </thead>
              <tbody>
                {earnings.by_item.map((row) => (
                  <tr key={row.name} className="border-t border-line/60">
                    <td className="py-1 text-foreground/90">{row.name}</td>
                    <td className="py-1 text-right font-mono text-muted-foreground">{row.quantity}</td>
                    <td className="py-1 text-right font-mono text-gold">{fmtRs(row.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* State strip — what the SMD screen is showing                        */
/* ------------------------------------------------------------------ */

const STRIP: AgentStateName[] = ["idle", "seeing", "listening", "thinking", "speaking", "remembering", "taking_order", "order_ready", "needs_help"];

export function StateStrip({ className }: { className?: string }) {
  const state = useAgent((s) => s.state);
  return (
    <section className={cn("panel overflow-hidden", className)}>
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <p className="text-sm font-semibold">
          THE HOST visual states <span className="ml-2 text-xs font-normal text-muted-foreground">— the nine states of the display screen</span>
        </p>
      </header>
      <div className="grid grid-cols-3 gap-px bg-line sm:grid-cols-5 lg:grid-cols-9">
        {STRIP.map((s) => {
          const on = s === state;
          return (
            <div key={s} className={cn("flex flex-col items-center gap-2 bg-surface px-2 py-3 transition-colors", on && "bg-surface-2")}>
              <div className={cn("w-14 transition-all duration-500", on ? "scale-110 opacity-100" : "opacity-40 grayscale-[0.4]")}>
                <AIOrb state={s} />
              </div>
              <span className={cn("text-[0.65rem] font-semibold uppercase tracking-wider", on ? "text-gold" : "text-muted-foreground")}>{STATE_META[s].label}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
