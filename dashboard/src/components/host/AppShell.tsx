import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  Bookmark,
  ChartNoAxesColumn,
  Eye,
  Home,
  Menu,
  MonitorPlay,
  Play,
  Settings,
  ShoppingBag,
  Users,
  UtensilsCrossed,
  X,
} from "lucide-react";
import { useAgent } from "@/lib/agent/store";
import { Button } from "@/components/ui/button";
import { STATE_META } from "@/lib/agent/ui";
import { cn } from "@/lib/utils";
import { BrandMark } from "./Brand";
import { StatusDot } from "./Panel";
import { DemoIntro, DemoStepper } from "./DemoMode";

const NAV = [
  { label: "Core", items: [{ to: "/", label: "Command Center", icon: Home }, { to: "/vision", label: "Live Vision", icon: Eye }] },
  { label: "Experience", items: [{ to: "/orders", label: "Orders", icon: ShoppingBag }, { to: "/menu", label: "Menu", icon: UtensilsCrossed }, { to: "/visitors", label: "Visitors", icon: Users }, { to: "/memory", label: "Memory", icon: Bookmark }] },
  { label: "Insight", items: [{ to: "/activity", label: "AI Activity", icon: Activity }, { to: "/analytics", label: "Analytics", icon: ChartNoAxesColumn }] },
  { label: "System", items: [{ to: "/settings", label: "Settings", icon: Settings }] },
] as const;

function Sidebar({ onDemo, onNavigate }: { onDemo: () => void; onNavigate?: () => void }) {
  const connection = useAgent((s) => s.connection);
  const mode = useAgent((s) => s.mode);
  const live = mode === "demo" || connection === "live";
  return (
    <div className="flex h-full flex-col">
      <div className="px-6 pb-6 pt-8">
        <BrandMark size="md" tagline />
      </div>
      <div className="mx-6 hairline-gold" />
      <nav className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-5">
        {NAV.map((group) => (
          <div key={group.label}>
            <p className="label-caps px-3 pb-2">{group.label}</p>
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon }) => (
                <Link
                  key={to}
                  to={to}
                  onClick={onNavigate}
                  activeOptions={{ exact: to === "/" }}
                  className="group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-surface-2/60 hover:text-foreground"
                  activeProps={{ className: "!text-gold bg-gold/10 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:rounded-full before:bg-gold" }}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="space-y-2 px-4 pb-4">
        <Button
          onClick={onDemo}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-gold px-4 py-3 text-xs font-bold uppercase tracking-[0.22em] text-primary-foreground shadow-[var(--glow-gold)] transition-colors hover:bg-gold-bright"
        >
          <Play className="h-3.5 w-3.5 fill-current" /> Demo Mode
        </Button>
        <a
          href="/display"
          target="_blank"
          rel="noreferrer"
          className="flex w-full items-center justify-center gap-2 rounded-md border border-line-strong px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.18em] text-gold transition-colors hover:bg-gold/10"
        >
          <MonitorPlay className="h-3.5 w-3.5" /> Open Display Screen
        </a>
      </div>
      <div className="border-t border-line px-6 py-4">
        <p className="flex items-center gap-2 text-xs font-semibold">
          <StatusDot status={live ? "live" : "unknown"} />
          <span className={live ? "text-success" : "text-muted-foreground"}>{mode === "demo" ? "Demo running" : live ? "Online" : "Agent not connected"}</span>
        </p>
        <p className="mt-2 text-sm font-semibold tracking-wide">THE HOST</p>
        {mode === "demo" && <p className="text-[0.68rem] text-muted-foreground">Demo scenario · Booth #4</p>}
      </div>
    </div>
  );
}

export function AppShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const [demoOpen, setDemoOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const state = useAgent((s) => s.state);
  const meta = STATE_META[state];

  return (
    <div className="flex min-h-screen w-full">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line bg-background/60 backdrop-blur lg:block">
        <Sidebar onDemo={() => setDemoOpen(true)} />
      </aside>

      {navOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-background/80 backdrop-blur-sm" onClick={() => setNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-line bg-background animate-in slide-in-from-left">
             <Button variant="ghost" size="icon" className="absolute right-3 top-3 text-muted-foreground" onClick={() => setNavOpen(false)} aria-label="Close menu">
              <X className="h-5 w-5" />
             </Button>
            <Sidebar
              onDemo={() => {
                setNavOpen(false);
                setDemoOpen(true);
              }}
              onNavigate={() => setNavOpen(false)}
            />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-line bg-background/75 px-4 py-3 backdrop-blur-md sm:px-6">
          <Button variant="ghost" size="icon" className="text-muted-foreground lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="min-w-0 flex-1">
            <p className="hidden text-[0.6rem] font-semibold uppercase text-gold sm:block">Bite &amp; Pour · AI Control Center</p>
            <h1 className="truncate text-lg font-semibold">{title}</h1>
            {subtitle && <p className="hidden truncate text-xs text-muted-foreground sm:block">{subtitle}</p>}
          </div>
          <div className="hidden items-center gap-2 rounded-md border border-line bg-surface/60 px-3 py-1.5 md:flex">
            <span className={cn("h-1.5 w-1.5 rounded-full", meta.tone === "off" ? "bg-muted-foreground" : meta.tone === "brand" ? "bg-gold" : meta.tone === "warn" ? "bg-destructive" : "bg-champagne", meta.tone !== "off" && "animate-blink")} />
            <span className="label-caps !text-[0.6rem]">THE HOST</span>
            <span className="text-xs font-semibold">{meta.label}</span>
          </div>
          <Button onClick={() => setDemoOpen(true)} className="rounded-md bg-gold px-3 py-2 text-[0.65rem] font-bold uppercase text-primary-foreground transition-colors hover:bg-gold-bright lg:hidden">
            Demo
          </Button>
        </header>
        <main className="flex-1 p-4 pb-28 sm:p-6 sm:pb-28">{children}</main>
      </div>

      <DemoIntro open={demoOpen} onClose={() => setDemoOpen(false)} />
      <DemoStepper />
    </div>
  );
}
