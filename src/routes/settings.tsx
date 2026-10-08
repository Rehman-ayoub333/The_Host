import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/host/AppShell";
import { Panel } from "@/components/host/Panel";
import { SystemPanel } from "@/components/host/panels";
import { connectAgent, getAgentConfig, saveAgentConfig } from "@/lib/agent/service";
import { useAgent } from "@/lib/agent/store";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — THE HOST · Bite & Pour" },
      { name: "description", content: "Connect the THE HOST control center to the external AI agent." },
      { property: "og:title", content: "Settings — THE HOST" },
      { property: "og:description", content: "Agent connection settings for the THE HOST control center." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const connection = useAgent((s) => s.connection);
  const [apiUrl, setApiUrl] = useState("");
  const [wsUrl, setWsUrl] = useState("");
  useEffect(() => {
    const c = getAgentConfig();
    setApiUrl(c.apiUrl);
    setWsUrl(c.wsUrl);
  }, []);

  const field = "mt-1.5 w-full rounded-md border border-line bg-input px-3 py-2.5 font-mono text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-gold";

  return (
    <AppShell title="Settings" subtitle="Point the control center at the THE HOST agent.">
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel title="Agent connection" icon={<Plug className="h-4 w-4" />} className="xl:col-span-8">
          <form
            className="max-w-xl space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              saveAgentConfig({ apiUrl: apiUrl.trim(), wsUrl: wsUrl.trim() });
              void connectAgent();
            }}
          >
            <label className="block">
              <span className="label-caps">REST API URL</span>
              <input className={field} value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://agent.example.com" />
            </label>
            <label className="block">
              <span className="label-caps">Realtime events URL (WebSocket)</span>
              <input className={field} value={wsUrl} onChange={(e) => setWsUrl(e.target.value)} placeholder="wss://agent.example.com/events" />
            </label>
            <div className="flex items-center gap-4">
              <Button type="submit" className="rounded-md bg-gold px-5 py-2.5 text-xs font-bold uppercase text-primary-foreground transition-colors hover:bg-gold-bright">
                Save &amp; connect
              </Button>
              <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Status · {connection}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Never paste secret keys here — these addresses are visible in the browser. The agent should stream events such as agent_state_changed, speech_transcript, order_created and memory_updated as JSON.
            </p>
          </form>
        </Panel>
        <SystemPanel className="xl:col-span-4" />
      </div>
    </AppShell>
  );
}
