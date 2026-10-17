import { Play, Square, RotateCcw, X, MonitorPlay } from "lucide-react";
import { useAgent } from "@/lib/agent/store";
import { DEMO_STEPS, startDemo, stopDemo } from "@/lib/agent/demo";
import { cn } from "@/lib/utils";
import { AIOrb } from "./AIOrb";
import { Button } from "@/components/ui/button";
import { BrandMark } from "./Brand";

export function DemoIntro({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/85 p-6 backdrop-blur-md animate-in fade-in" role="dialog" aria-modal="true" aria-label="Demo mode">
      <div className="panel panel-corners relative w-full max-w-xl overflow-hidden p-10 text-center">
        <Button variant="ghost" size="icon" onClick={onClose} className="absolute right-4 top-4 text-muted-foreground transition-colors hover:text-foreground" aria-label="Close">
          <X className="h-5 w-5" />
        </Button>
        <BrandMark size="md" />
        <div className="mx-auto my-6 w-44">
          <AIOrb state="idle" />
        </div>
        <p className="label-caps text-champagne">Demo Mode</p>
        <h2 className="mt-2 font-display text-5xl font-semibold tracking-wide text-foreground">THE HOST AI Host</h2>
        <p className="mt-3 text-sm tracking-[0.3em] text-gold">SEE • HEAR • THINK • SPEAK • REMEMBER</p>
        <p className="mx-auto mt-5 max-w-sm text-sm text-muted-foreground">
          A guided one-minute example of a visitor interaction. Every screen shows a <span className="text-warning">Demo data</span> label while it runs.
        </p>
        <Button
          onClick={() => {
            startDemo();
            onClose();
          }}
          className="group mt-8 inline-flex items-center gap-3 rounded-md bg-gold px-8 py-3.5 text-sm font-bold uppercase tracking-[0.25em] text-primary-foreground shadow-[var(--glow-gold)] transition-all hover:bg-gold-bright "
        >
          <Play className="h-4 w-4 fill-current" /> Start Demo
        </Button>
        <p className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <MonitorPlay className="h-3.5 w-3.5" /> Open the display screen in another window — it follows along.
        </p>
      </div>
    </div>
  );
}

export function DemoStepper() {
  const step = useAgent((s) => s.demoStep);
  const mode = useAgent((s) => s.mode);
  if (mode !== "demo" || step === null) return null;
  const done = step >= DEMO_STEPS.length;

  return (
    <div className="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 animate-rise">
      <div className="panel flex max-w-full items-center gap-3 overflow-x-auto px-3 py-2.5 shadow-2xl">
        <span className="hidden shrink-0 pl-1 font-mono text-[0.6rem] uppercase tracking-widest text-warning sm:inline">Demo</span>
        <ol className="flex items-center gap-1">
          {DEMO_STEPS.map((label, i) => (
            <li
              key={label}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-[0.7rem] font-semibold uppercase tracking-wider transition-all duration-500",
                i === step ? "bg-champagne/15 text-champagne" : i < step ? "text-gold" : "text-muted-foreground/60",
              )}
            >
              <span className={cn("grid h-4 w-4 place-items-center rounded-full border font-mono text-[0.55rem]", i === step ? "border-champagne" : i < step ? "border-gold bg-gold text-primary-foreground" : "border-muted-foreground/40")}>
                {i + 1}
              </span>
              {label}
            </li>
          ))}
        </ol>
        <div className="ml-1 flex shrink-0 gap-1 border-l border-line pl-3">
          {done && (
             <Button variant="ghost" size="sm" onClick={startDemo} className="flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-xs font-semibold text-gold hover:bg-gold/10">
              <RotateCcw className="h-3.5 w-3.5" /> Replay
             </Button>
          )}
           <Button variant="ghost" size="sm" onClick={() => stopDemo()} className="flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-xs font-semibold text-muted-foreground hover:bg-surface-2 hover:text-foreground">
            <Square className="h-3 w-3 fill-current" /> Exit demo
           </Button>
        </div>
      </div>
    </div>
  );
}
