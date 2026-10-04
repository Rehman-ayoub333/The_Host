import { useEffect, useState } from "react";
import { MENU_ITEMS } from "@/lib/menu";
import { cn } from "@/lib/utils";

const ROTATE_MS = 6000;

/**
 * Idle menu carousel for the SMD display.
 * Purely frontend-owned: cycles MENU_ITEMS on a timer,
 * independent of the agent. Rendered only while NEXA is idle.
 */
export function MenuCarousel({ className }: { className?: string }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setIndex((i) => (i + 1) % MENU_ITEMS.length), ROTATE_MS);
    return () => clearInterval(t);
  }, []);

  const item = MENU_ITEMS[index];

  return (
    <div className={cn("flex flex-col items-center text-center", className)}>
      <p className="label-caps !text-gold/80">Our Menu</p>
      <div key={index} className="animate-rise mt-4 flex flex-col items-center">
        {item.signature && (
          <p className="mb-2 font-mono text-[0.65rem] uppercase tracking-[0.3em] text-champagne">Signature</p>
        )}
        <p className="font-display text-5xl font-semibold leading-tight text-foreground sm:text-6xl lg:text-7xl">
          {item.name}
        </p>
        <p className="mt-3 text-[clamp(1rem,1.6vw,1.4rem)] text-muted-foreground">{item.description}</p>
        <div className="mx-auto my-5 w-24 hairline-gold" />
        <p className="font-display text-3xl font-semibold text-gold-gradient sm:text-4xl">{item.price}</p>
      </div>
      <div className="mt-8 flex items-center gap-2.5">
        {MENU_ITEMS.map((m, i) => (
          <button
            key={m.name}
            onClick={() => setIndex(i)}
            aria-label={`Show ${m.name}`}
            className={cn(
              "h-1 rounded-full transition-all duration-500",
              i === index ? "w-8 bg-gold" : "w-2 bg-gold/25 hover:bg-gold/50",
            )}
          />
        ))}
      </div>
      <p className="mt-3 font-mono text-xs text-muted-foreground">
        {index + 1} / {MENU_ITEMS.length}
      </p>
    </div>
  );
}
