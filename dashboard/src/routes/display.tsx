import { useEffect, useRef } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Maximize, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AIOrb } from "@/components/host/AIOrb";
import { BrandMark } from "@/components/host/Brand";
import { VoiceWaveform } from "@/components/host/VoiceWaveform";
import { MenuCarousel } from "@/components/host/MenuCarousel";
import { useAgent } from "@/lib/agent/store";
import { connectAgent } from "@/lib/agent/service";
import { STATE_META, fmtCountdown, useNow } from "@/lib/agent/ui";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/display")({
  head: () => ({
    meta: [
      { title: "THE HOST — Live Display · Bite & Pour" },
      { name: "description", content: "The public face of THE HOST, the AI host at the Bite & Pour booth." },
      { property: "og:title", content: "THE HOST Live Display — Bite & Pour" },
      { property: "og:description", content: "Meet THE HOST: the AI host that sees, hears, thinks, speaks and remembers." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SMDDisplay,
});

/** Speaks an order-ready sentence once per order (public display only). */
function useOrderReadyVoice() {
  const orderReady = useAgent((s) => s.orderReady);
  const lastAgentState = useAgent((s) => s.lastAgentState);
  const spoken = useRef(new Set<string>());

  useEffect(() => {
    if (!orderReady || spoken.current.has(orderReady.order_id)) return;
    // Only when no conversation is running (last agent state was IDLE).
    if (lastAgentState !== "IDLE") return;
    spoken.current.add(orderReady.order_id);
    const sentence = orderReady.customer_name
      ? `${orderReady.customer_name}, your order is ready`
      : `Order ${orderReady.order_id} is ready`;
    try {
      const u = new SpeechSynthesisUtterance(sentence);
      window.speechSynthesis?.speak(u);
    } catch {
      /* speech is best-effort */
    }
  }, [orderReady, lastAgentState]);
}

function SMDDisplay() {
  const state = useAgent((s) => s.state);
  const caption = useAgent((s) => s.caption);
  const orders = useAgent((s) => s.orders);
  const focus = useAgent((s) => s.focus);
  const mode = useAgent((s) => s.mode);
  const opMode = useAgent((s) => s.opMode);
  const recommendation = useAgent((s) => s.recommendation);
  const orderReady = useAgent((s) => s.orderReady);
  const transcript = useAgent((s) => s.transcript);
  const now = useNow(1000);
  const meta = STATE_META[state];

  // The public display connects with its own role=smd socket — never the
  // dashboard's data, never the operator token.
  useEffect(() => {
    connectAgent("smd");
  }, []);
  useOrderReadyVoice();

  const resting = opMode && opMode.mode !== "ONLINE" && mode !== "demo";
  const idle = state === "idle" && !resting;
  const orderStates = ["taking_order", "order_ready"].includes(state);
  const memoryStates = state === "remembering";
  const voice = state === "listening" || state === "speaking";
  const order = orders.find((o) => ["CONFIRMED", "PREPARING", "READY"].includes(o.status));
  const readyActive = orderReady && now && orderReady.until > now;
  const recActive = recommendation && now && recommendation.until > now;
  const showSide = !resting && ((orderStates && !!order) || (memoryStates && !!focus) || !!recActive);

  // Public display: final transcript lines only, latest one or two, short.
  const finalLines = transcript.filter((l) => l.final).slice(-2);

  let headline: string = meta.verb;
  if (memoryStates && focus) headline = focus.returning ? `Welcome back, ${focus.name}!` : `Nice to meet you, ${focus.name}!`;
  if (idle) headline = "Ready when you are.";
  if (readyActive) headline = orderReady.customer_name ? `${orderReady.customer_name}, your order is ready` : `Order #${orderReady.order_id} is ready`;

  const toneText = meta.tone === "warn" ? "text-destructive" : meta.tone === "off" ? "text-muted-foreground" : "text-foreground";

  return (
    <div className="relative flex min-h-screen w-full flex-col overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-3 border border-line sm:inset-6" />

      <Button
        variant="ghost"
        size="icon"
        onClick={() => document.documentElement.requestFullscreen?.().catch(() => undefined)}
        className="absolute right-7 top-7 z-10 text-muted-foreground transition-colors hover:text-gold sm:right-10 sm:top-10"
        aria-label="Enter full screen"
      >
        <Maximize className="h-5 w-5" />
      </Button>
      {mode === "demo" && <span className="absolute left-7 top-7 font-mono text-xs uppercase text-warning sm:left-10 sm:top-10">Demo data</span>}

      <header className="relative pt-12 sm:pt-14">
        <BrandMark size="md" tagline />
      </header>

      {resting ? (
        <main className="relative flex flex-1 flex-col items-center justify-center px-7 text-center">
          <div className="w-[min(22vh,40vw)]">
            <AIOrb state="offline" />
          </div>
          <p className="mt-6 font-display text-4xl font-semibold text-foreground sm:text-5xl">THE HOST will be right back</p>
          <p className="mt-3 text-[clamp(1rem,1.6vw,1.3rem)] text-muted-foreground">Please speak with a host if you need anything.</p>
        </main>
      ) : (
        <main className={cn("relative flex flex-1 items-center justify-center gap-4 px-7 py-6 transition-all duration-700 sm:gap-10 sm:px-12 lg:gap-[6vw]", showSide ? "flex-col lg:flex-row" : "flex-col")}>
          <div className="flex min-w-0 flex-col items-center">
            <div className={cn("transition-all duration-700", idle ? "w-[min(22vh,40vw)]" : showSide ? "w-[min(34vh,55vw)] lg:w-[min(38vh,30vw)]" : "w-[min(42vh,68vw)]")}>
              <AIOrb state={state} />
            </div>
            <p className="font-mono text-xs uppercase text-champagne">THE HOST · Your AI host</p>
            {idle ? (
              <MenuCarousel className="mt-4" />
            ) : (
              <>
                <p key={headline} className={cn("animate-rise mt-3 text-center font-display text-4xl font-semibold leading-tight sm:text-6xl lg:text-7xl", toneText)}>
                  {headline}
                </p>
                {state === "offline" && <p className="mt-2 text-center text-[clamp(1rem,1.8vw,1.6rem)] text-muted-foreground">Please speak with a host</p>}
              </>
            )}
            {voice && caption && (
              <p key={caption.text} className="animate-rise mt-6 max-w-[60vw] text-center text-[clamp(1.25rem,2.6vw,2.4rem)] font-medium leading-snug text-foreground">
                “{caption.text}”
              </p>
            )}
            {!voice && finalLines.length > 0 && !idle && (
              <div className="mt-6 space-y-2 text-center">
                {finalLines.map((l) => (
                  <p key={l.id} className="max-w-[60vw] text-[clamp(1rem,2vw,1.8rem)] leading-snug text-foreground/80">“{l.text}”</p>
                ))}
              </div>
            )}
            <VoiceWaveform active={voice} tone={state === "speaking" ? "ivory" : "gold"} bars={56} className={cn("mt-6 h-14 w-[min(70vw,520px)] transition-opacity", voice ? "opacity-100" : "opacity-30")} />
          </div>

          {orderStates && order && (
            <div key={order.id} className="animate-rise w-full max-w-[460px] border-t border-line-strong pt-5 text-center lg:w-[min(32vw,460px)] lg:border-l lg:border-t-0 lg:pl-8">
              <div className="p-4 text-center sm:p-7">
                <p className="font-mono text-sm uppercase tracking-[0.3em] text-muted-foreground">Order #{order.id}</p>
                <p className="mt-2 text-[clamp(1.2rem,2vw,2rem)] font-semibold text-gold">{order.items.map((i) => i.name).join(" + ")}</p>
                {order.status === "READY" ? (
                  <p className="mt-4 flex items-center justify-center gap-2 text-2xl font-semibold text-success">
                    <Check className="h-7 w-7" /> Ready for pickup
                  </p>
                ) : order.status === "PREPARING" ? (
                  <>
                    {order.estimated_ready_at && now ? (
                      <>
                        <p className="mt-4 font-mono text-5xl text-foreground">{fmtCountdown(Math.max(0, order.estimated_ready_at - now))}</p>
                        <p className="mt-1 text-sm uppercase tracking-widest text-muted-foreground">Preparing · remaining</p>
                      </>
                    ) : (
                      <p className="mt-4 text-xl text-champagne">Preparing…</p>
                    )}
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
              {focus.returning && <p className="mt-2 text-lg text-gold">Welcome back</p>}
            </div>
          )}

          {recActive && !orderStates && !memoryStates && (
            <div className="animate-rise w-full max-w-[420px] border-t border-line-strong p-5 text-center lg:w-[min(30vw,420px)] lg:border-l lg:border-t-0 lg:p-10">
              <p className="label-caps !text-gold/80">You might also like</p>
              <p className="mt-3 font-display text-4xl font-semibold text-foreground">{recommendation.item}</p>
              <div className="mx-auto my-4 w-24 hairline-gold" />
              <p className="text-base text-muted-foreground">{recommendation.reason}</p>
            </div>
          )}
        </main>
      )}

      <footer className="relative pb-12 text-center">
        <p className="font-display text-2xl font-semibold text-foreground">THE HOST</p>
        <p className="mt-1 text-xs uppercase text-gold/80">See · Hear · Think · Speak · Remember</p>
      </footer>
    </div>
  );
}
