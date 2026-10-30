import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Mic, MonitorSpeaker, Play, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/host/AppShell";
import { Panel } from "@/components/host/Panel";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { SystemPanel } from "@/components/host/panels";
import { startDemo } from "@/lib/agent/demo";
import { connectAgent, getAgentConfig, reloadDisplay, saveAgentConfig, setListening } from "@/lib/agent/service";
import { useAgent } from "@/lib/agent/store";
import type { ListeningMode } from "@/lib/agent/types";
import { C } from "@/lib/booth/constants";
import { cn } from "@/lib/utils";
import {
  listDevices,
  loadDeviceChoice,
  loadGateLevel,
  missingDeviceNotes,
  saveDeviceChoice,
  saveGateLevel,
  SYSTEM_DEFAULT,
  type DeviceChoice,
  type DeviceLists,
} from "@/lib/booth/devices";

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

/**
 * 16 §2u item 5: the camera and microphone the TV uses, chosen on the laptop.
 *
 * The drop-downs used to sit on the Start screen, on the TV, facing guests. They
 * live here now: the dashboard is the same browser origin, so what is saved here
 * is exactly what `/display` reads. A device that has gone missing is reported
 * here as well -- the display itself says nothing and falls back to the system
 * default, because a warning on a guest-facing screen would be worse than the
 * wrong microphone.
 */
function DisplayDevicesPanel({ className }: { className?: string | undefined }) {
  const [choice, setChoice] = useState<DeviceChoice>(() => loadDeviceChoice());
  const [lists, setLists] = useState<DeviceLists>({ cameras: [], mics: [] });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void listDevices().then(setLists);
  }, []);

  const notes = missingDeviceNotes(choice, lists);
  // 16 §2zf item 8(c): the Reload display screen button's own two bits.
  const [reloading, setReloading] = useState(false);
  const [reloadNote, setReloadNote] = useState("");
  const field =
    "mt-1.5 w-full rounded-md border border-line bg-input px-3 py-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-gold";

  function choose(next: DeviceChoice) {
    setChoice(next);
    saveDeviceChoice(next);
    setSaved(true);
  }

  return (
    // PanelBoundary gives the panel its grid class, so it has to arrive here.
    <Panel title="Display screen devices" icon={<MonitorSpeaker className="h-4 w-4" />} className={className}>
      <div className="max-w-xl space-y-4">
        <p className="text-sm text-muted-foreground">
          The camera and microphone THE HOST uses on the display screen. Saved in this browser, and read by /display on the
          same machine — the TV itself has no controls on it.
        </p>
        <label className="block">
          <span className="label-caps">Camera</span>
          <select className={field} value={choice.cameraId} onChange={(e) => choose({ ...choice, cameraId: e.target.value })} aria-label="Camera">
            <option value={SYSTEM_DEFAULT}>System default</option>
            {lists.cameras.map((device) => (
              <option key={device.id} value={device.id}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label-caps">Microphone</span>
          <select className={field} value={choice.micId} onChange={(e) => choose({ ...choice, micId: e.target.value })} aria-label="Microphone">
            <option value={SYSTEM_DEFAULT}>System default</option>
            {lists.mics.map((device) => (
              <option key={device.id} value={device.id}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        {notes.map((note) => (
          <p key={note} className="rounded-sm border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
            {note} — the display is using the system default.
          </p>
        ))}
        {saved && notes.length === 0 && (
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Saved · reload the display screen to use it
          </p>
        )}
        {/* 16 §2zf item 8(c): and here is the button that does it. The TV is
            across the stall on a kiosk browser with no keyboard, so a device
            change -- or anything that looks wrong on it -- needed somebody to
            walk over with a mouse until now. */}
        <div className="border-t border-line pt-4">
          <button
            disabled={reloading}
            onClick={() => {
              setReloading(true);
              void reloadDisplay()
                .then((ok) => setReloadNote(ok ? "Display screen asked to reload" : ""))
                .finally(() => setReloading(false));
            }}
            className="h-9 rounded-md border border-line px-3 text-xs font-semibold uppercase transition-colors hover:border-gold hover:text-gold disabled:opacity-50"
          >
            Reload display screen
          </button>
          {reloadNote && <p className="mt-2 text-xs text-champagne">{reloadNote}</p>}
        </div>
      </div>
    </Panel>
  );
}

/**
 * 16 §2zk item 3 — who decides when THE HOST is listening.
 *
 * Operator is the default and the one Rehman demos on: he presses Start
 * listening when a guest steps up. Automatic is kept as an option for a quiet
 * room, and it is the only mode where the level number means anything, so the
 * number is shown only then.
 */
function ListeningModePanel({ className }: { className?: string | undefined }) {
  const mode = useAgent((s) => s.listeningMode);
  const [busy, setBusy] = useState(false);
  const [level, setLevel] = useState(() => String(loadGateLevel()));

  const choose = (next: ListeningMode) => {
    if (next === mode || busy) return;
    setBusy(true);
    void setListening({ mode: next }).finally(() => setBusy(false));
  };

  const option = (value: ListeningMode, title: string, detail: string) => (
    <button
      key={value}
      type="button"
      data-testid={`listening-mode-${value}`}
      disabled={busy}
      onClick={() => choose(value)}
      aria-pressed={mode === value}
      className={cn(
        "rounded-md border p-3 text-left transition-colors disabled:opacity-60",
        mode === value ? "border-gold bg-gold/10" : "border-line hover:border-gold/60",
      )}
    >
      <p className={cn("text-sm font-semibold", mode === value && "text-gold")}>{title}</p>
      <p className="mt-1 text-[0.68rem] text-muted-foreground">{detail}</p>
    </button>
  );

  return (
    <Panel title="Listening mode" icon={<Mic className="h-4 w-4" />} className={className}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {option(
          "operator",
          "Operator (default)",
          "You press Start listening when a guest steps up, and Stop listening when they are done. F2 does the same. Use this at a demo and in a busy hall.",
        )}
        {option(
          "automatic",
          "Automatic",
          "THE HOST listens by itself while a guest is close to the camera and facing it. Quiet rooms only.",
        )}
      </div>
      {mode === "automatic" && (
        <div className="mt-4 border-t border-line pt-4">
          <label className="block">
            <span className="label-caps">Noise gate level</span>
            <input
              type="number"
              data-testid="gate-level"
              min={C.UPLINK_GATE_LEVEL_MIN}
              max={C.UPLINK_GATE_LEVEL_MAX}
              step={0.01}
              value={level}
              onChange={(event) => {
                setLevel(event.target.value);
                const next = Number(event.target.value);
                if (
                  Number.isFinite(next) &&
                  next >= C.UPLINK_GATE_LEVEL_MIN &&
                  next <= C.UPLINK_GATE_LEVEL_MAX
                ) {
                  saveGateLevel(next);
                }
              }}
              className="mt-1 h-9 w-28 rounded-md border border-line bg-background/60 px-2 font-mono text-sm"
            />
          </label>
          <p className="mt-2 text-[0.68rem] text-muted-foreground">
            Between {C.UPLINK_GATE_LEVEL_MIN} and {C.UPLINK_GATE_LEVEL_MAX}; the default is {C.UPLINK_GATE_LEVEL_DEFAULT}. Anything
            quieter than this is treated as room noise and never reaches THE HOST. Open the display with ?debug=mic to see how many
            frames the gate is holding before changing it.
          </p>
        </div>
      )}
    </Panel>
  );
}

export function SettingsPage() {
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

        {/* 16 §2u item 5: the TV has no controls on it any more, so the display's
            camera and microphone are chosen here, on the laptop. */}
        <PanelBoundary name="Display screen devices" className="xl:col-span-4">
          <DisplayDevicesPanel />
        </PanelBoundary>

        {/* 16 §2zk item 3: who holds the microphone. Beside the devices panel,
            because at a demo the handheld mic and Operator mode are chosen
            together. */}
        <PanelBoundary name="Listening mode" className="xl:col-span-4">
          <ListeningModePanel />
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
