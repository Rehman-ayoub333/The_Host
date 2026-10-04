import { createFileRoute } from "@tanstack/react-router";
import { Maximize, Check } from "lucide-react";
import comboImg from "@/assets/order-combo.jpg";
import { AIOrb } from "@/components/nexa/AIOrb";
import { BrandMark } from "@/components/nexa/Brand";
import { VoiceWaveform } from "@/components/nexa/VoiceWaveform";
import { useAgent } from "@/lib/agent/store";
import { STATE_META, fmtAgo, fmtCountdown, useNow } from "@/lib/agent/ui";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/display")({
  head: () => ({
    meta: [
      { title: "NEXA — Live Display · Bite & Pour" },
      { name: "description", content: "The public face of NEXA, the AI host at the Bite & Pour booth." },
      { property: "og:title", content: "NEXA Live Display — Bite & Pour" },
      { property: "og:description", content: "Meet NEXA: the AI host that sees, hears, thinks, speaks and remembers." },
    ],
  }),
  component: SMDDisplay,
});

function SMDDisplay() {
  const state = useAgent((s) => s.state);
  const caption = useAgent((s) => s.caption);
  const detail = useAgent((s) => s.detail);
  const orders = useAgent((s) => s.orders);
  const visitors = useAgent((s) => s.visitors);
  const focusId = useAgent((s) => s.focusVisitorId);
  const mode = useAgent((s) => s.mode);
  const now = useNow(1000);
  const meta = STATE_META[state];
  const focus = visitors.find((v) => v.id === focusId);
  const order = orders.find((o) => ["confirming", "preparing", "ready"].includes(o.status) && (!focusId || o.visitorId === focusId)) ?? orders[0];

  const orderStates = ["taking_order", "order_confirmed", "order_preparing", "order_ready"].includes(state);
  const memoryStates = state === "remembering" || state === "welcoming";
  const voice = state === "listening" || state === "speaking";
  const showSide = (orderStates && order) || (memoryStates && focus);

  let headline: string = meta.verb;
  if (memoryStates && focus) headline = state === "welcoming" ? `Welcome back, ${focus.name}!` : `I remember you, ${focus.name}`;
  if (state === "idle") headline = "Hello! I'm NEXA";
  if (state === "order_ready" && order) headline = `Order #${order.number} is ready`;

  const toneText = meta.tone === "brand" ? "text-gold glow-gold" : meta.tone === "warn" ? "text-destructive" : meta.tone === "off" ? "text-muted-foreground" : "text-nexa glow-nexa";

  return (
    <div className="relative flex h-screen w-full flex-col overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_45%,oklch(0.83_0.12_205/0.08),transparent_70%)]" />
      <div className="pointer-events-none absolute inset-6 rounded-xl border border-line" />
      <div className="pointer-events-none absolute inset-6 panel-corners rounded-xl" />

      <button
        onClick={() => document.documentElement.requestFullscreen?.().catch(() => undefined)}
        className="absolute right-10 top-10 z-10 rounded-md p-2 text-muted-foreground/40 transition-colors hover:text-gold"
        aria-label="Enter full screen"
      >
        <Maximize className="h-5 w-5" />
      </button>
      {mode === "demo" && <span className="absolute left-10 top-10 font-mono text-xs uppercase tracking-widest text-warning/70">Demo</span>}

      <header className="relative pt-12">
        <BrandMark size="lg" />
      </header>

      <main className={cn("relative flex flex-1 items-center justify-center gap-[6vw] px-12 transition-all duration-700", showSide ? "flex-row" : "flex-col")}>
        <div className="flex flex-col items-center">
          <div className={cn("transition-all duration-700", showSide ? "w-[min(38vh,30vw)]" : "w-[min(46vh,60vw)]")}>
            <AIOrb state={state} />
          </div>
          <p key={state} className={cn("animate-rise mt-6 text-center text-[clamp(2rem,4.6vw,4.5rem)] font-semibold leading-tight tracking-tight", toneText)}>
            {headline}
          </p>
          <p className="mt-2 min-h-8 text-center text-[clamp(1rem,1.8vw,1.6rem)] text-muted-foreground">
            {state === "idle" ? "Your AI host · How can I help you?" : state === "offline" ? "Back in a moment" : detail && !memoryStates ? detail : ""}
          </p>
          {voice && caption && (
            <p key={caption.text} className="animate-rise mt-6 max-w-[60vw] text-center text-[clamp(1.25rem,2.6vw,2.4rem)] font-medium leading-snug text-foreground">
              “{caption.text}”
            </p>
          )}
          <VoiceWaveform active={voice} bars={56} className={cn("mt-6 h-14 w-[min(40vw,520px)] transition-opacity", voice ? "opacity-100" : "opacity-30")} />
        </div>

        {orderStates && order && (
          <div key={order.id} className="panel panel-corners animate-rise w-[min(32vw,460px)] overflow-hidden">
            <img src={comboImg} alt="" width={1024} height={768} className="aspect-[4/3] w-full object-cover" />
            <div className="p-7 text-center">
              <p className="font-mono text-sm uppercase tracking-[0.3em] text-muted-foreground">Order #{order.number}</p>
              <p className="mt-2 text-[clamp(1.2rem,2vw,2rem)] font-semibold text-gold">{order.items.map((i) => i.name).join(" + ")}</p>
              {order.status === "ready" ? (
                <p className="mt-4 flex items-center justify-center gap-2 text-2xl font-semibold text-success">
                  <Check className="h-7 w-7" /> Ready for pickup
                </p>
              ) : order.status === "preparing" ? (
                <>
                  <p className="mt-4 font-mono text-5xl text-foreground">{order.readyAt && now ? fmtCountdown(order.readyAt - now) : "--:--"}</p>
                  <p className="mt-1 text-sm uppercase tracking-widest text-muted-foreground">Preparing · remaining</p>
                  <div className="mx-auto mt-4 h-1.5 w-3/4 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-nexa-dim to-nexa transition-all duration-1000"
                      style={{ width: `${order.readyAt && order.prepSeconds && now ? Math.min(100, 100 - ((order.readyAt - now) / (order.prepSeconds * 1000)) * 100) : 5}%` }}
                    />
                  </div>
                </>
              ) : (
                <p className="mt-4 text-xl text-nexa">Confirming…</p>
              )}
            </div>
          </div>
        )}

        {memoryStates && focus && !orderStates && (
          <div className="panel panel-corners animate-rise w-[min(30vw,420px)] p-10 text-center">
            <div className="mx-auto grid h-28 w-28 place-items-center rounded-full border-2 border-gold bg-gradient-to-br from-gold/30 to-surface-2 font-display text-6xl font-semibold text-gold shadow-[var(--glow-gold)]">
              {focus.name.slice(0, 1)}
            </div>
            <p className="mt-6 font-display text-5xl font-semibold text-foreground">{focus.name}</p>
            <p className="mt-2 text-lg text-gold">Visit #{focus.visits}</p>
            <div className="mx-auto my-5 w-24 hairline-gold" />
            <p className="text-base text-muted-foreground">Last visit · {fmtAgo(focus.lastVisit, now)}</p>
            {focus.favorite && <p className="mt-1 text-base text-muted-foreground">Favourite · <span className="text-foreground">{focus.favorite}</span></p>}
          </div>
        )}
      </main>

      <footer className="relative pb-12 text-center">
        <p className="font-display text-2xl font-semibold tracking-[0.35em] text-foreground">NEXA</p>
        <p className="mt-1 text-xs uppercase tracking-[0.5em] text-gold/80">See · Hear · Think · Speak · Remember</p>
      </footer>
    </div>
  );
}
