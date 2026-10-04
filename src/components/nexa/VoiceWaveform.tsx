import { cn } from "@/lib/utils";

export function VoiceWaveform({
  active,
  bars = 40,
  tone = "gold",
  className,
}: {
  active: boolean;
  bars?: number;
  tone?: "ivory" | "gold";
  className?: string;
}) {
  return (
    <div className={cn("flex h-10 items-center justify-center gap-[3px]", !active && "wave-idle", className)} aria-hidden>
      {Array.from({ length: bars }).map((_, i) => {
        const center = 1 - Math.abs(i - bars / 2) / (bars / 2);
        return (
          <span
            key={i}
            className={cn("wave-bar w-[2px] rounded-full", tone === "ivory" ? "bg-ivory" : "bg-champagne")}
            style={{
              height: `${30 + center * 70}%`,
              opacity: 0.35 + center * 0.65,
              animationDelay: `${((i * 71) % 1000) / 1000}s`,
              animationDuration: `${0.7 + ((i * 13) % 60) / 100}s`,
            }}
          />
        );
      })}
    </div>
  );
}
