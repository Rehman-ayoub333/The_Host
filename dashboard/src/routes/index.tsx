import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { LivePanel } from "@/components/host/LivePanel";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { ActivityPanel, AnalyticsPanel, CorePanel, EarningsPanel, OrdersPanel, StateStrip, SystemPanel, VisionPanel, VisitorsPanel } from "@/components/host/panels";

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
      {/* 16 §2p item 2: the original design's order — the AI Host and Live
          Vision on top, then the nine states, then the working panels, with
          Live conversation where the old voice panel stood. */}
      {/* 16 §2s item 4b: one boundary each, so a panel that throws costs that
          panel and nothing else. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <PanelBoundary name="AI Host" className="xl:col-span-5">
          <CorePanel />
        </PanelBoundary>
        <PanelBoundary name="Live Vision" className="xl:col-span-7">
          <VisionPanel />
        </PanelBoundary>
        <div className="xl:col-span-12">
          <PanelBoundary name="States">
            <StateStrip />
          </PanelBoundary>
        </div>
        <PanelBoundary name="Orders" className="xl:col-span-5">
          <OrdersPanel />
        </PanelBoundary>
        <PanelBoundary name="Activity" className="xl:col-span-4">
          <ActivityPanel />
        </PanelBoundary>
        <PanelBoundary name="Visitors" className="xl:col-span-3">
          <VisitorsPanel />
        </PanelBoundary>
        <PanelBoundary name="Live conversation" className="xl:col-span-5">
          <LivePanel />
        </PanelBoundary>
        <PanelBoundary name="Analytics" className="xl:col-span-4">
          <AnalyticsPanel />
        </PanelBoundary>
        <PanelBoundary name="System" className="xl:col-span-3">
          <SystemPanel />
        </PanelBoundary>
        {/* 16 §2z item 5: the money, full width, as the last row. */}
        <PanelBoundary name="Earnings" className="xl:col-span-12">
          <EarningsPanel />
        </PanelBoundary>
      </div>
    </AppShell>
  );
}
