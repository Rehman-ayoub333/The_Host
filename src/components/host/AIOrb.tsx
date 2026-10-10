import { STATE_META } from "@/lib/agent/ui";
import type { AgentStateName } from "@/lib/agent/types";
import { cn } from "@/lib/utils";

const BARS = 64;

/** THE HOST's core. Every ring and motion maps to a meaning in the agent state. */
export function AIOrb({ state, className }: { state: AgentStateName; className?: string }) {
  const meta = STATE_META[state];
  const rings = meta.rings;

  return (
    <div className={cn("host-orb relative aspect-square", className)} data-tone={meta.tone} aria-label={`THE HOST is ${meta.label}`} role="img">
      <svg viewBox="0 0 400 400" className="absolute inset-0 h-full w-full overflow-visible">
        <defs>
          <radialGradient id="orb-core" cx="50%" cy="45%" r="55%">
            <stop offset="0%" stopColor="var(--c2)" stopOpacity="0.6" />
            <stop offset="35%" stopColor="var(--c)" stopOpacity="0.19" />
            <stop offset="75%" stopColor="var(--c)" stopOpacity="0.035" />
            <stop offset="100%" stopColor="var(--c)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="orb-halo" cx="50%" cy="50%" r="50%">
            <stop offset="55%" stopColor="var(--c)" stopOpacity="0" />
            <stop offset="72%" stopColor="var(--c)" stopOpacity="0.055" />
            <stop offset="100%" stopColor="var(--c)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="orb-arc" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--c2)" />
            <stop offset="100%" stopColor="var(--c)" stopOpacity="0" />
          </linearGradient>
          <filter id="orb-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <circle cx="200" cy="200" r="200" fill="url(#orb-halo)" />

        {/* outer gold bezel — brand */}
        <g className="spin-slow">
          <circle cx="200" cy="200" r="192" fill="none" stroke="var(--gold)" strokeOpacity="0.23" strokeWidth="1" strokeDasharray="1 10" />
        </g>
        <circle cx="200" cy="200" r="182" fill="none" stroke="var(--gold)" strokeOpacity="0.18" strokeWidth="1" />

        {/* segmented intelligence ring */}
        <g className="spin-rev">
          <circle cx="200" cy="200" r="166" fill="none" stroke="var(--c)" strokeOpacity="0.42" strokeWidth="1" strokeDasharray="72 55 8 55" />
        </g>

        {/* sweeping arc */}
        <g className="spin" filter="url(#orb-glow)">
          <circle
            cx="200"
            cy="200"
            r="148"
            fill="none"
            stroke="url(#orb-arc)"
            strokeWidth={rings === "think" ? 2.5 : 1.5}
            strokeLinecap="round"
            strokeDasharray={rings === "think" ? "260 670" : "120 810"}
          />
        </g>

        {/* pulse — detection / confirmation */}
        {rings === "pulse" && (
          <>
            <circle className="pulse-ring" cx="200" cy="200" r="130" fill="none" stroke="var(--c)" strokeWidth="1.5" />
            <circle className="pulse-ring" style={{ animationDelay: "1.2s" }} cx="200" cy="200" r="130" fill="none" stroke="var(--c)" strokeWidth="1" />
          </>
        )}

        {/* voice — listening & speaking */}
        <g opacity={rings === "wave" ? 1 : 0}>
          {Array.from({ length: BARS }).map((_, i) => {
            const h = 14 + ((i * 37) % 22);
            return (
              <g key={i} transform={`rotate(${(360 / BARS) * i} 200 200)`}>
                <rect
                  className="bar"
                  x="199"
                  y={200 - 104 - h}
                  width="2"
                  height={h}
                  rx="1"
                  fill="var(--c)"
                  style={{ animationDelay: `${((i * 53) % 900) / 1000}s`, animationDuration: `${0.6 + ((i * 17) % 50) / 100}s` }}
                />
              </g>
            );
          })}
        </g>

        {/* memory particles */}
        {rings === "particles" && (
          <g className="orbit">
            {Array.from({ length: 10 }).map((_, i) => {
              const a = (i / 10) * Math.PI * 2;
              const r = 120 + (i % 3) * 14;
              return (
                <circle key={i} cx={200 + Math.cos(a) * r} cy={200 + Math.sin(a) * r} r={i % 3 === 0 ? 3 : 1.8} fill="var(--gold-bright)" opacity={0.5 + (i % 4) * 0.12} />
              );
            })}
          </g>
        )}

        {/* core */}
        <g className="breath">
          <circle cx="200" cy="200" r="96" fill="url(#orb-core)" />
          <circle cx="200" cy="200" r="70" fill="none" stroke="var(--c)" strokeOpacity="0.35" strokeWidth="1" />
          <circle cx="200" cy="200" r="46" fill="none" stroke="var(--c2)" strokeOpacity="0.35" strokeWidth="0.75" strokeDasharray="2 4" />
          <circle cx="200" cy="200" r="16" fill="none" stroke="var(--c2)" strokeWidth="2" filter="url(#orb-glow)" />
          <circle cx="200" cy="200" r="5" fill="var(--c2)" filter="url(#orb-glow)" />
        </g>
        {state === "order_ready" && <circle cx="252" cy="252" r="5" fill="var(--success)" />}
      </svg>
    </div>
  );
}
