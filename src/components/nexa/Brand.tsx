import { cn } from "@/lib/utils";

function Leaf({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 16" className={className} aria-hidden>
      <path d="M12 15C11 9 6 5 1 5c3 4 6 7 11 10Z" fill="currentColor" opacity="0.8" />
      <path d="M12 15c1-7 5-12 11-14-2 6-5 11-11 14Z" fill="currentColor" />
    </svg>
  );
}

export function BrandMark({ size = "md", tagline = false, className }: { size?: "sm" | "md" | "lg" | "xl"; tagline?: boolean; className?: string }) {
  const s = {
    sm: { mono: "text-2xl", word: "text-[0.55rem] tracking-[0.42em]", leaf: "h-2.5" },
    md: { mono: "text-4xl", word: "text-[0.62rem] tracking-[0.5em]", leaf: "h-3" },
    lg: { mono: "text-6xl", word: "text-sm tracking-[0.55em]", leaf: "h-5" },
    xl: { mono: "text-8xl", word: "text-lg tracking-[0.6em]", leaf: "h-7" },
  }[size];
  return (
    <div className={cn("flex flex-col items-center text-center", className)}>
      <Leaf className={cn("text-gold", s.leaf)} />
      <span className={cn("font-display font-semibold leading-none text-gold-gradient", s.mono)}>B&amp;P</span>
      <span className={cn("mt-1.5 pl-[0.5em] font-display font-semibold uppercase text-gold", s.word)}>Bite &amp; Pour</span>
      {tagline && <span className="mt-2 text-[0.55rem] font-medium uppercase tracking-[0.3em] text-muted-foreground">For moments worth tasting.</span>}
    </div>
  );
}
