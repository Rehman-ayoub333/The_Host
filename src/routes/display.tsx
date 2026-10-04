import { createFileRoute } from "@tanstack/react-router";
import { Maximize, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
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
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
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
  if (state === "idle") headline = "Ready when you are.";
  if (state === "order_ready" && order) headline = `Order #${order.number} is ready`;

  const toneText = meta.tone === "warn" ? "text-destructive" : meta.tone === "off" ? "text-muted-foreground" : "text-foreground";

  return (
    <div className="relative flex min-h-screen w-full flex-col overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-3 border border-line sm:inset-6" />

       <Button variant="ghost" size="icon"
        onClick={() => document.documentElement.requestFullscreen?.().catch(() => undefined)}
         className="absolute right-7 top-7 z-10 text-muted-foreground transition-colors hover:text-gold sm:right-10 sm:top-10"
        aria-label="Enter full screen"
      >
        <Maximize className="h-5 w-5" />
       </Button>
       {mode === "demo" && <span className="absolute left-7 top-7 font-mono text-xs uppercase text-warning sm:left-10 sm:top-10">Demo data</span>}

       <header className="relative pt-12 sm:pt-14">
         <BrandMark size="lg" tagline />
      </header>

       <main className={cn("relative flex flex-1 items-center justify-center gap-4 px-7 py-6 transition-all duration-700 sm:gap-10 sm:px-12 lg:gap-[6vw]", showSide ? "flex-col lg:flex-row" : "flex-col")}>
         <div className="flex min-w-0 flex-col items-center">
           <div className={cn("transition-all duration-700", showSide ? "w-[min(34vh,55vw)] lg:w-[min(38vh,30vw)]" : "w-[min(42vh,68vw)]")}>
            <AIOrb state={state} />
          </div>
           <p className="font-mono text-xs uppercase text-champagne">NEXA · Your AI host</p>
           <p key={state} className={cn("animate-rise mt-3 text-center font-display text-4xl font-semibold leading-tight sm:text-6xl lg:text-7xl", toneText)}>
            {headline}
          </p>
          <p className="mt-2 min-h-8 text-center text-[clamp(1rem,1.8vw,1.6rem)] text-muted-foreground">
             {state === "idle" ? "See · Hear · Speak · Remember" : state === "offline" ? "Back in a moment" : detail && !memoryStates ? detail : ""}
          </p>
          {voice && caption && (
            <p key={caption.text} className="animate-rise mt-6 max-w-[60vw] text-center text-[clamp(1.25rem,2.6vw,2.4rem)] font-medium leading-snug text-foreground">
              “{caption.text}”
            </p>
          )}
           <VoiceWaveform active={voice} tone={state === "speaking" ? "ivory" : "gold"} bars={56} className={cn("mt-6 h-14 w-[min(70vw,520px)] transition-opacity", voice ? "opacity-100" : "opacity-30")} />
        </div>

        {orderStates && order && (
           <div key={order.id} className="animate-rise w-full max-w-[460px] border-t border-line-strong pt-5 text-center lg:w-[min(32vw,460px)] lg:border-l lg:border-t-0 lg:pl-8">
             <div className="p-4 text-center sm:p-7">
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
                      className="h-full rounded-full bg-gradient-to-r from-gold-dim to-champagne transition-all duration-1000"
                      style={{ width: `${order.readyAt && order.prepSeconds && now ? Math.min(100, 100 - ((order.readyAt - now) / (order.prepSeconds * 1000)) * 100) : 5}%` }}
                    />
                  </div>
                </>
              ) : (
                <p className="mt-4 text-xl text-champagne">Confirming…</p>
              )}
            </div>
          </div>
        )}

        {memoryStates && focus && !orderStates && (
           <div className="animate-rise w-full max-w-[420px] border-t border-line-strong p-5 text-center lg:w-[min(30vw,420px)] lg:border-l lg:border-t-0 lg:p-10">
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
