import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { AnalyticsPanel, OrdersPanel, VisitorsPanel } from "@/components/host/panels";

export const Route = createFileRoute("/analytics")({
  head: () => ({
    meta: [
      { title: "Analytics — THE HOST · Bite & Pour" },
      { name: "description", content: "Orders, visitors and popular items, calculated from live booth data." },
      { property: "og:title", content: "Analytics — THE HOST" },
      { property: "og:description", content: "How the Bite & Pour booth is performing today." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Analytics" subtitle="Calculated only from orders and visitors the agent has reported.">
      <div className="grid gap-4 xl:grid-cols-12">
        <PanelBoundary name="Analytics" className="xl:col-span-5">
          <AnalyticsPanel />
        </PanelBoundary>
        <PanelBoundary name="Orders" className="xl:col-span-4">
          <OrdersPanel limit={6} />
        </PanelBoundary>
        <PanelBoundary name="Visitors" className="xl:col-span-3">
          <VisitorsPanel />
        </PanelBoundary>
      </div>
    </AppShell>
  ),
});
