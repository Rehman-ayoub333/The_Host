import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { ActivityPanel, AnalyticsPanel, CorePanel, OrdersPanel, StateStrip, SystemPanel, TranscriptPanel, VisionPanel, VisitorsPanel } from "@/components/host/panels";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Command Center — THE HOST · Bite & Pour" },
      { name: "description", content: "Monitor THE HOST live: vision, voice, orders, visitors and system health at the Bite & Pour booth." },
      { property: "og:title", content: "THE HOST Command Center — Bite & Pour" },
      { property: "og:description", content: "The operator view of THE HOST, the AI host that sees, hears, thinks, speaks and remembers." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: CommandCenter,
});

function CommandCenter() {
  return (
    <AppShell title="Command Center" subtitle="Monitor everything THE HOST sees, hears and does — in real time.">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <CorePanel className="xl:col-span-5" />
        <VisionPanel className="xl:col-span-7" />
        <div className="xl:col-span-12">
          <StateStrip />
        </div>
        <OrdersPanel className="xl:col-span-5" />
        <ActivityPanel className="xl:col-span-4" />
        <VisitorsPanel className="xl:col-span-3" />
        <TranscriptPanel className="xl:col-span-5" />
        <AnalyticsPanel className="xl:col-span-4" />
        <SystemPanel className="xl:col-span-3" />
      </div>
    </AppShell>
  );
}
