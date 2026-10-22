import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Play, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/host/AppShell";
import { Panel } from "@/components/host/Panel";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { SystemPanel } from "@/components/host/panels";
import { startDemo } from "@/lib/agent/demo";
import { connectAgent, getAgentConfig, saveAgentConfig } from "@/lib/agent/service";
import { useAgent } from "@/lib/agent/store";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — THE HOST · Bite & Pour" },
      { name: "description", content: "Connect the THE HOST control center to the backend." },
      { property: "og:title", content: "Settings — THE HOST" },
      { property: "og:description", content: "Agent connection settings for the THE HOST control center." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const connection = useAgent((s) => s.connection);
  const tokenError = useAgent((s) => s.tokenError);
  const navigate = useNavigate();
  const [agentUrl, setAgentUrl] = useState("");
  const [token, setToken] = useState("");
  useEffect(() => {
    const c = getAgentConfig();
    setAgentUrl(c.agentUrl);
    setToken(c.token);
  }, []);

  const field = "mt-1.5 w-full rounded-md border border-line bg-input px-3 py-2.5 font-mono text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-gold";

  return (
    <AppShell title="Settings" subtitle="Point the control center at the THE HOST backend.">
      <div className="grid gap-4 xl:grid-cols-12">
        {/* 16 §2s item 4b: a boundary each, here too. */}
        <PanelBoundary name="Agent connection" className="xl:col-span-8">
          <Panel title="Agent connection" icon={<Plug className="h-4 w-4" />}>
            <form
              className="max-w-xl space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                saveAgentConfig({ agentUrl: agentUrl.trim() || "http://localhost:8000", token: token.trim() });
                connectAgent("dashboard");
              }}
            >
              <label className="block">
                <span className="label-caps">Agent link (backend base URL)</span>
                <input className={field} value={agentUrl} onChange={(e) => setAgentUrl(e.target.value)} placeholder="http://localhost:8000" />
              </label>
              <label className="block">
                <span className="label-caps">Operator token</span>
                <input className={field} type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Operator token" />
              </label>
              <div className="flex items-center gap-4">
                <Button type="submit" className="rounded-md bg-gold px-5 py-2.5 text-xs font-bold uppercase text-primary-foreground transition-colors hover:bg-gold-bright">
                  Save &amp; connect
                </Button>
                <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                  Agent link · {connection === "live" ? "live" : connection === "reconnecting" ? "reconnecting" : connection}
                </span>
              </div>
              {tokenError && <p className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">{tokenError}</p>}
              <p className="text-xs text-muted-foreground">
                The dashboard opens its event stream at /ws/events?role=dashboard with this token; the public display uses role=smd and never sees the token.
              </p>
            </form>
          </Panel>
        </PanelBoundary>
        <PanelBoundary name="System" className="xl:col-span-4">
          <SystemPanel />
        </PanelBoundary>

        {/* 16 §2p item 4: Demo Mode lives here, out of the way, so the main
            screen never suggests the system is staged. The demo itself is
            unchanged. */}
        <PanelBoundary name="Demo Mode (backup)" className="xl:col-span-8">
          <Panel title="Demo Mode (backup)" icon={<Play className="h-4 w-4" />}>
            <p className="text-sm text-muted-foreground">
              Plays a scripted conversation with DEMO DATA badges. Use only if the live system cannot run.
            </p>
            <Button
              onClick={() => {
                startDemo();
                void navigate({ to: "/" });
              }}
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-gold px-5 py-2.5 text-xs font-bold uppercase tracking-[0.22em] text-primary-foreground transition-colors hover:bg-gold-bright"
            >
              <Play className="h-3.5 w-3.5 fill-current" /> Start Demo Mode
            </Button>
          </Panel>
        </PanelBoundary>
      </div>
    </AppShell>
  );
}
