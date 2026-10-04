import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { ActivityPanel, AnalyticsPanel, CorePanel, OrdersPanel, StateStrip, SystemPanel, TranscriptPanel, VisionPanel, VisitorsPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Command Center — NEXA · Bite & Pour" },
      { name: "description", content: "Monitor NEXA live: vision, voice, orders, visitors and system health at the Bite & Pour booth." },
      { property: "og:title", content: "NEXA Command Center — Bite & Pour" },
      { property: "og:description", content: "The operator view of NEXA, the AI host that sees, hears, thinks, speaks and remembers." },
    ],
  }),
  component: CommandCenter,
});

function CommandCenter() {
  return (
    <AppShell title="Command Center" subtitle="Monitor everything NEXA sees, hears and does — in real time.">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <CorePanel className="xl:col-span-4" />
        <VisionPanel className="xl:col-span-8" />
        <OrdersPanel className="md:col-span-1 xl:col-span-4" />
        <ActivityPanel className="xl:col-span-4" />
        <div className="grid gap-4 xl:col-span-4">
          <VisitorsPanel />
        </div>
        <TranscriptPanel className="xl:col-span-5" />
        <AnalyticsPanel className="xl:col-span-4" />
        <SystemPanel className="xl:col-span-3" />
        <StateStrip className="xl:col-span-12" />
      </div>
    </AppShell>
  );
}
