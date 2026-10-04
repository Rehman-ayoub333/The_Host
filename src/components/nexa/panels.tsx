import { useEffect, useRef, useState } from "react";
import {
  Activity as ActivityIcon,
  AudioLines,
  Brain,
  Camera,
  CameraOff,
  ChefHat,
  Cpu,
  Eye,
  Globe,
  Mic,
  ScanFace,
  ShoppingBag,
  Sparkles,
  TriangleAlert,
  UserRound,
  Users,
  Volume2,
  Bookmark,
  ChartNoAxesColumn,
  Radio,
} from "lucide-react";
import { useAgent } from "@/lib/agent/store";
import { STATE_META, fmtAgo, fmtClock, fmtCountdown, useNow } from "@/lib/agent/ui";
import type { ActivityKind, AgentStateName, Order, SystemComponent } from "@/lib/agent/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AIOrb } from "./AIOrb";
import { VoiceWaveform } from "./VoiceWaveform";
import { DemoTag, EmptyState, Panel, StatusDot } from "./Panel";

const useIsDemo = () => useAgent((s) => s.mode === "demo");

/* ------------------------------------------------------------------ */
/* NEXA core                                                           */
/* ------------------------------------------------------------------ */

export function CorePanel({ className }: { className?: string }) {
  const state = useAgent((s) => s.state);
  const detail = useAgent((s) => s.detail);
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
          <h2 className="font-display text-3xl font-semibold tracking-wide text-foreground">NEXA</h2>
        </div>
        <div className="flex items-center gap-2">
          {isDemo && <DemoTag />}
          <span className="flex items-center gap-2 rounded-sm border border-line bg-background/40 px-2 py-1 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">
            <StatusDot status={isDemo || connection === "connected" ? "live" : connection === "connecting" ? "degraded" : "unknown"} />
            {isDemo ? "Demo" : connection}
          </span>
        </div>
      </header>

      <div className="relative mx-auto w-[min(100%,400px)] py-2">
        <AIOrb state={state} />
      </div>

      <div className="relative px-5 pb-5 text-center">
        <p className={cn("label-caps", meta.tone === "brand" ? "text-gold" : meta.tone === "warn" ? "text-destructive" : "text-champagne")}>
          Current state
        </p>
        <p key={state} className={cn("animate-rise mt-1 font-display text-4xl font-semibold", meta.tone === "off" ? "text-muted-foreground" : "text-champagne")}>
          {meta.label}
        </p>
        <p className="mt-1 min-h-5 text-sm text-muted-foreground">{detail ?? (state === "offline" ? "Waiting for the agent to connect" : meta.verb)}</p>

        <div className="mt-4 rounded-md border border-line bg-background/40 px-4 py-3">
          <VoiceWaveform active={voice} tone={state === "speaking" ? "ivory" : "gold"} bars={48} className="h-8" />
          <p className="mt-2 min-h-10 text-sm leading-snug">
            {caption ? (
              <>
                <span className={cn("mr-2 font-mono text-[0.6rem] uppercase tracking-widest", caption.speaker === "nexa" ? "text-champagne" : "text-gold")}>
                  {caption.speaker === "nexa" ? "NEXA" : "Visitor"}
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
/* Live vision                                                         */
/* ------------------------------------------------------------------ */

export function VisionPanel({ className, tall }: { className?: string; tall?: boolean }) {
  const frameUrl = useAgent((s) => s.frameUrl);
  const detections = useAgent((s) => s.detections);
  const camera = useAgent((s) => s.system.camera);
  const focusId = useAgent((s) => s.focusVisitorId);
  const visitors = useAgent((s) => s.visitors);
  const isDemo = useIsDemo();
  const focus = visitors.find((v) => v.id === focusId);
  const now = useNow(1000);

  const videoRef = useRef<HTMLVideoElement>(null);
  const [localCam, setLocalCam] = useState<MediaStream | null>(null);
  const [camErr, setCamErr] = useState<string | null>(null);

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = localCam;
    return () => undefined;
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
      setCamErr("Camera permission was denied.");
    }
  };

  const hasFeed = !!frameUrl || !!localCam;

  return (
    <Panel
      title="Live Vision"
      icon={<Eye className="h-4 w-4" />}
      className={className}
      bodyClassName="p-0"
      action={
        <div className="flex items-center gap-3">
          {isDemo && <DemoTag />}
          <span className="flex items-center gap-1.5 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">
            <StatusDot status={frameUrl ? "live" : camera} /> Camera {frameUrl ? "on" : camera}
          </span>
          {!frameUrl && (
             <Button variant="outline" size="sm" onClick={toggleLocal} className="h-7 rounded-sm border-line px-2 text-[0.65rem] font-semibold uppercase text-gold transition-colors hover:border-gold hover:bg-gold/10">
              {localCam ? "Stop preview" : "Local preview"}
             </Button>
          )}
        </div>
      }
    >
      <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_200px]">
        <div className={cn("relative overflow-hidden bg-background", tall ? "aspect-video lg:aspect-auto lg:min-h-[520px]" : "aspect-video lg:aspect-auto lg:min-h-[380px]")}>
          {frameUrl && <img src={frameUrl} alt="Booth camera feed" className="absolute inset-0 h-full w-full object-cover" />}
          {localCam && !frameUrl && <video ref={videoRef} autoPlay muted playsInline className="absolute inset-0 h-full w-full -scale-x-100 object-cover" />}
          {!hasFeed && (
            <div className="absolute inset-0 grid place-items-center scan-grid">
              <EmptyState icon={<CameraOff className="h-7 w-7" />} title="No vision feed" hint={camErr ?? "Frames appear here once the agent streams its camera. Use Local preview to check framing."} />
            </div>
          )}
           {frameUrl && (
            <>
              <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_60%,var(--background))] opacity-70" />
              <div className="pointer-events-none absolute inset-x-0 h-1/3 animate-scan bg-gradient-to-b from-transparent via-champagne/10 to-transparent" />
            </>
          )}
          {frameUrl &&
            detections.map((d) => {
              const isPerson = d.label.toLowerCase() === "person";
              return (
                <div
                  key={d.id}
                  className={cn("absolute border transition-all duration-700", isPerson ? "border-champagne shadow-[var(--glow-gold)]" : "border-gold/60 border-dashed")}
                  style={{ left: `${d.box[0] * 100}%`, top: `${d.box[1] * 100}%`, width: `${d.box[2] * 100}%`, height: `${d.box[3] * 100}%` }}
                >
                  <span className={cn("absolute -top-5 left-[-1px] whitespace-nowrap px-1.5 py-0.5 font-mono text-[0.6rem] font-semibold", isPerson ? "bg-champagne text-background" : "bg-gold/80 text-background")}>
                    {d.label} {Math.round(d.confidence * 100)}%
                  </span>
                </div>
              );
            })}
          {localCam && !frameUrl && (
            <span className="absolute bottom-3 left-3 rounded-sm bg-background/80 px-2 py-1 font-mono text-[0.6rem] uppercase tracking-widest text-muted-foreground">
              Local preview · no AI detections
            </span>
          )}
           {frameUrl && (
            <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-sm bg-background/70 px-2 py-1 font-mono text-[0.6rem] uppercase tracking-widest text-foreground">
               <span className="h-1.5 w-1.5 rounded-full bg-destructive animate-blink" /> Live · {fmtClock(now)}
            </span>
          )}
        </div>

        <div className="flex flex-col gap-4 border-t border-line p-4 lg:border-l lg:border-t-0">
          <div>
            <p className="label-caps mb-2">Detections</p>
            {detections.length === 0 ? (
              <p className="text-xs text-muted-foreground">None reported</p>
            ) : (
              <ul className="space-y-1.5">
                {detections.map((d) => (
                  <li key={d.id} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2 text-foreground/90">
                      {d.label === "Person" ? <UserRound className="h-3.5 w-3.5 text-champagne" /> : <ScanFace className="h-3.5 w-3.5 text-gold-dim" />}
                      {d.label}
                    </span>
                    <span className="font-mono text-muted-foreground">{Math.round(d.confidence * 100)}%</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="mt-auto rounded-md border border-line bg-background/40 p-3">
            <p className="label-caps mb-2">Current focus</p>
            {focus ? (
              <div className="animate-rise">
                <div className="flex items-center gap-2">
                  <Avatar name={focus.name} />
                  <div>
                    <p className="text-sm font-semibold">{focus.name}</p>
                    <p className="text-[0.68rem] text-gold">{focus.returning ? "Returning visitor" : "New visitor"}</p>
                  </div>
                </div>
                <p className="mt-2 text-[0.68rem] text-muted-foreground">
                  {focus.visits} visits · last {fmtAgo(focus.lastVisit, now)}
                </p>
                {focus.lastOrder && <p className="text-[0.68rem] text-muted-foreground">Last order: {focus.lastOrder}</p>}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No one recognized</p>
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
/* Orders                                                              */
/* ------------------------------------------------------------------ */

const STATUS_STYLE: Record<Order["status"], string> = {
  confirming: "text-champagne",
  preparing: "text-warning",
  ready: "text-success",
  completed: "text-muted-foreground",
  cancelled: "text-destructive",
};

export function OrderCard({ order, now }: { order: Order; now: number }) {
  const remaining = order.readyAt && now ? order.readyAt - now : null;
  const total = (order.prepSeconds ?? 0) * 1000;
  const pct = order.status === "ready" || order.status === "completed" ? 100 : remaining !== null && total ? Math.min(100, Math.max(4, 100 - (remaining / total) * 100)) : order.status === "confirming" ? 8 : 0;

  return (
    <div className="animate-rise rounded-md border border-line bg-background/40 p-3 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">Order #{order.number}</p>
          <p className="truncate text-sm font-semibold">{order.customerName ?? "Guest"}</p>
        </div>
        <div className="text-right">
          <p className={cn("text-xs font-semibold capitalize", STATUS_STYLE[order.status])}>● {order.status}</p>
          {order.status === "preparing" && (
            <p className="font-mono text-sm text-foreground">{remaining !== null ? `${fmtCountdown(remaining)} left` : "ETA pending"}</p>
          )}
        </div>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">{order.items.map((i) => `${i.qty > 1 ? `${i.qty}× ` : ""}${i.name}`).join(" · ")}</p>
      {order.status !== "completed" && order.status !== "cancelled" && (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-2">
          <div className={cn("h-full rounded-full transition-all duration-1000", order.status === "ready" ? "bg-success" : "bg-gradient-to-r from-gold-dim to-champagne")} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

export function OrdersPanel({ className, limit = 3 }: { className?: string; limit?: number }) {
  const orders = useAgent((s) => s.orders);
  const isDemo = useIsDemo();
  const now = useNow(1000);
  const [tab, setTab] = useState<"active" | "completed" | "all">("active");
  const active = orders.filter((o) => ["confirming", "preparing", "ready"].includes(o.status));
  const completed = orders.filter((o) => o.status === "completed");
  const list = (tab === "active" ? active : tab === "completed" ? completed : orders).slice(0, limit);

  return (
    <Panel title="Orders" icon={<ShoppingBag className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
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
        <EmptyState icon={<ChefHat className="h-6 w-6" />} title="No orders yet" hint="Orders appear the moment NEXA confirms one." />
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
  audio: Mic,
  reasoning: Brain,
  voice: Volume2,
  order: ShoppingBag,
  memory: Bookmark,
  system: Cpu,
  error: TriangleAlert,
};

export function ActivityPanel({ className, limit = 7 }: { className?: string; limit?: number }) {
  const activity = useAgent((s) => s.activity);
  const isDemo = useIsDemo();
  return (
    <Panel title="AI Activity" icon={<ActivityIcon className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
      {activity.length === 0 ? (
        <EmptyState icon={<Radio className="h-6 w-6" />} title="Quiet for now" hint="Every event NEXA reports is logged here in real time." />
      ) : (
        <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[15px] before:top-2 before:w-px before:bg-line">
          {activity.slice(0, limit).map((a) => {
            const Icon = KIND_ICON[a.kind];
            return (
              <li key={a.id} className="animate-rise relative flex gap-3">
                <span className={cn("relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border bg-surface", a.kind === "error" ? "border-destructive/50 text-destructive" : a.kind === "memory" || a.kind === "order" ? "border-gold/40 text-gold" : "border-champagne/40 text-champagne")}>
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-medium">{a.title}</p>
                    <span className="font-mono text-[0.62rem] text-muted-foreground">{fmtClock(a.ts)}</span>
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

export function VisitorsPanel({ className, limit = 4 }: { className?: string; limit?: number }) {
  const visitors = useAgent((s) => s.visitors);
  const isDemo = useIsDemo();
  const now = useNow(30000);
  return (
    <Panel title="Visitors" icon={<Users className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
      {visitors.length === 0 ? (
        <EmptyState icon={<Users className="h-6 w-6" />} title="No visitors yet" hint="Visitors are listed when the agent's memory reports them." />
      ) : (
        <ul className="divide-y divide-line">
          {visitors.slice(0, limit).map((v) => (
            <li key={v.id} className="animate-rise flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <Avatar name={v.name} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{v.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {v.lastOrder ?? "No orders"} · {fmtAgo(v.lastVisit, now)}
                </p>
              </div>
              <span className={cn("rounded-sm border px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider", v.returning ? "border-gold/40 text-gold" : "border-champagne/40 text-champagne")}>
                {v.returning ? "Returning" : "New"}
              </span>
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
    <Panel title="Memory" icon={<Bookmark className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
      {memory.length === 0 ? (
        <EmptyState icon={<Sparkles className="h-6 w-6" />} title="No memories stored" hint="NEXA only shows what its memory system has actually saved." />
      ) : (
        <ul className="space-y-2">
          {memory.slice(0, limit).map((m) => (
            <li key={m.id} className="animate-rise rounded-md border border-line bg-background/40 p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-gold">{m.visitorName}</p>
                <span className="text-[0.62rem] text-muted-foreground">{fmtAgo(m.ts, now)}</span>
              </div>
              <p className="mt-0.5 text-xs text-foreground/80">{m.text}</p>
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
    <Panel title="Voice Interaction" icon={<AudioLines className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
      {transcript.length === 0 ? (
        <EmptyState icon={<Mic className="h-6 w-6" />} title="No conversation yet" hint="Transcripts stream in from the agent's speech pipeline." />
      ) : (
        <div className="space-y-2.5">
          {transcript.slice(-4).map((l) => (
            <div key={l.id} className={cn("animate-rise flex gap-2", l.speaker === "nexa" && "flex-row-reverse text-right")}>
              <span className={cn("mt-0.5 font-mono text-[0.58rem] uppercase tracking-widest", l.speaker === "nexa" ? "text-champagne" : "text-gold")}>{l.speaker === "nexa" ? "NEXA" : "Guest"}</span>
              <p className={cn("max-w-[85%] rounded-md border px-3 py-2 text-sm", l.speaker === "nexa" ? "border-champagne/25 bg-champagne/5" : "border-line bg-background/40")}>{l.text}</p>
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

const SYSTEM_ROWS: [SystemComponent, string, typeof Eye][] = [
  ["camera", "Camera", Camera],
  ["microphone", "Microphone", Mic],
  ["speaker", "Speaker", Volume2],
  ["agent", "AI Agent", Cpu],
  ["internet", "Internet", Globe],
];

export function SystemPanel({ className }: { className?: string }) {
  const system = useAgent((s) => s.system);
  const connection = useAgent((s) => s.connection);
  return (
    <Panel title="System" icon={<Cpu className="h-4 w-4" />} className={className}>
      <ul className="space-y-2.5">
        {SYSTEM_ROWS.map(([k, label, Icon]) => (
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
      <p className="mt-3 font-mono text-[0.62rem] uppercase tracking-widest text-muted-foreground">Agent link · {connection}</p>
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* Analytics (derived purely from reported orders/visitors)            */
/* ------------------------------------------------------------------ */

export function AnalyticsPanel({ className }: { className?: string }) {
  const orders = useAgent((s) => s.orders);
  const visitors = useAgent((s) => s.visitors);
  const isDemo = useIsDemo();
  const counts = new Map<string, number>();
  orders.forEach((o) => o.items.forEach((i) => counts.set(i.name, (counts.get(i.name) ?? 0) + i.qty)));
  const total = [...counts.values()].reduce((a, b) => a + b, 0);
  const popular = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
  const returning = visitors.filter((v) => v.returning).length;

  return (
    <Panel title="Analytics" icon={<ChartNoAxesColumn className="h-4 w-4" />} className={className} action={isDemo ? <DemoTag /> : undefined}>
      <div className="grid grid-cols-3 gap-2">
        {[
          ["Orders", orders.length],
          ["Visitors", visitors.length],
          ["Returning", returning],
        ].map(([l, v]) => (
          <div key={l} className="rounded-md border border-line bg-background/40 p-2.5">
            <p className="label-caps !text-[0.56rem]">{l}</p>
            <p className="mt-1 font-mono text-2xl text-foreground">{v}</p>
          </div>
        ))}
      </div>
      <p className="label-caps mb-2 mt-4">Popular items</p>
      {popular.length === 0 ? (
        <p className="text-xs text-muted-foreground">No order data yet</p>
      ) : (
        <ul className="space-y-2">
          {popular.map(([name, n]) => (
            <li key={name}>
              <div className="flex justify-between text-xs">
                <span className="text-foreground/90">{name}</span>
                <span className="font-mono text-muted-foreground">{Math.round((n / total) * 100)}%</span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-gradient-to-r from-gold-dim to-gold transition-all duration-700" style={{ width: `${(n / total) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
/* State strip — what the SMD screen is showing                        */
/* ------------------------------------------------------------------ */

const STRIP: AgentStateName[] = ["idle", "seeing", "listening", "thinking", "speaking", "remembering", "taking_order", "order_ready", "error"];

export function StateStrip({ className }: { className?: string }) {
  const state = useAgent((s) => s.state);
  const group: Partial<Record<AgentStateName, AgentStateName>> = {
    person_detected: "seeing",
    order_confirmed: "taking_order",
    order_preparing: "taking_order",
    welcoming: "remembering",
    engaging: "speaking",
    multitasking: "thinking",
  };
  const current = group[state] ?? state;
  return (
    <section className={cn("panel overflow-hidden", className)}>
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <p className="text-sm font-semibold">
          NEXA visual states <span className="ml-2 text-xs font-normal text-muted-foreground">— mirrored live on the SMD screen</span>
        </p>
      </header>
      <div className="grid grid-cols-3 gap-px bg-line sm:grid-cols-5 lg:grid-cols-9">
        {STRIP.map((s) => {
          const on = s === current;
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
