import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Panel({
  title,
  icon,
  action,
  children,
  className,
  bodyClassName,
  corners,
}: {
  title?: string | undefined;
  icon?: ReactNode | undefined;
  action?: ReactNode | undefined;
  children: ReactNode;
  className?: string | undefined;
  bodyClassName?: string | undefined;
  corners?: boolean | undefined;
}) {
  return (
    <section className={cn("panel flex min-w-0 flex-col", corners && "panel-corners", className)}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold tracking-wide text-foreground">
            {icon && <span className="text-gold">{icon}</span>}
            {title}
          </div>
          {action}
        </header>
      )}
      <div className={cn("min-h-0 flex-1 p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function EmptyState({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex h-full min-h-28 flex-col items-center justify-center gap-2 py-6 text-center">
      {icon && <div className="text-gold-dim">{icon}</div>}
      <p className="text-sm font-medium text-foreground/80">{title}</p>
      {hint && <p className="max-w-60 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function StatusDot({ status }: { status: "online" | "degraded" | "offline" | "unknown" | "live" }) {
  const c = {
    online: "bg-success",
    live: "bg-success",
    degraded: "bg-warning",
    offline: "bg-destructive",
    unknown: "bg-muted-foreground/50",
  }[status];
  return (
    <span className="relative inline-flex h-2 w-2">
      {(status === "online" || status === "live") && <span className={cn("absolute inset-0 rounded-full opacity-60 animate-ping", c)} />}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", c)} />
    </span>
  );
}

export function DemoTag() {
  return (
    <span className="rounded-sm border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono text-[0.58rem] font-semibold uppercase tracking-widest text-warning">
      Demo data
    </span>
  );
}

export function SampleTag() {
  return (
    <span className="rounded-sm border border-gold/30 bg-gold/5 px-1.5 py-0.5 font-mono text-[0.58rem] font-semibold uppercase tracking-widest text-gold/80">
      Sample data
    </span>
  );
}
