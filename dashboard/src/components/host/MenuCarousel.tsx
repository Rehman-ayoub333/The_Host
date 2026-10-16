import { useEffect, useState } from "react";
import { useAgent } from "@/lib/agent/store";
import { cn } from "@/lib/utils";

const ROTATE_MS = 6000;

/**
 * Idle menu carousel for the SMD display.
 * The items come only from GET /api/menu (no token), kept current by
 * `menu_updated` — never sample or hard-coded data (16 §2o item 6). While the
 * request is failing the screen says "Menu loading…" and the service retries
 * every 10 s.
 */
export function MenuCarousel({ className }: { className?: string }) {
  const items = useAgent((s) => s.menu).filter((m) => m.available);
  const menuFailed = useAgent((s) => s.menuFailed);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (items.length < 2) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % items.length), ROTATE_MS);
    return () => clearInterval(t);
  }, [items.length]);

  if (items.length === 0) {
    if (!menuFailed) return null;
    return (
      <div className={cn("flex flex-col items-center text-center", className)}>
        <p className="label-caps !text-gold/80">Our Menu</p>
        <p className="mt-4 text-[clamp(1.1rem,2vw,1.8rem)] text-muted-foreground">Menu loading…</p>
      </div>
    );
  }
  const item = items[index % items.length]!;

  return (
    <div className={cn("flex flex-col items-center text-center", className)}>
      <p className="label-caps !text-gold/80">Our Menu</p>
      <div key={item.name} className="animate-rise mt-4 flex flex-col items-center">
        {item.image_url && (
          <img src={item.image_url} alt={item.name} className="mb-4 h-28 w-28 rounded-full border border-gold/30 object-cover" />
        )}
        <p className="font-display text-5xl font-semibold leading-tight text-foreground sm:text-6xl lg:text-7xl">{item.name}</p>
        {item.description && <p className="mt-3 text-[clamp(1rem,1.6vw,1.4rem)] text-muted-foreground">{item.description}</p>}
        <div className="mx-auto my-5 w-24 hairline-gold" />
        <p className="font-display text-3xl font-semibold text-gold-gradient sm:text-4xl">{item.price}</p>
      </div>
      <div className="mt-8 flex items-center gap-2.5">
        {items.map((m, i) => (
          <button
            key={m.name}
            onClick={() => setIndex(i)}
            aria-label={`Show ${m.name}`}
            className={cn("h-1 rounded-full transition-all duration-500", i === index % items.length ? "w-8 bg-gold" : "w-2 bg-gold/25 hover:bg-gold/50")}
          />
        ))}
      </div>
      <p className="mt-3 font-mono text-xs text-muted-foreground">
        {(index % items.length) + 1} / {items.length}
      </p>
    </div>
  );
}
