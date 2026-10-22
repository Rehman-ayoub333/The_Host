import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { AnalyticsPanel, OrdersPanel } from "@/components/host/panels";

export const Route = createFileRoute("/orders")({
  head: () => ({
    meta: [
      { title: "Orders — THE HOST · Bite & Pour" },
      { name: "description", content: "Every order THE HOST has taken, with live preparation countdowns." },
      { property: "og:title", content: "Orders — THE HOST" },
      { property: "og:description", content: "Live order tracking at the Bite & Pour booth." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Orders" subtitle="Orders created by THE HOST, with times supplied by the kitchen system.">
      <div className="grid gap-4 xl:grid-cols-12">
        <PanelBoundary name="Orders" className="xl:col-span-8">
          <OrdersPanel limit={50} />
        </PanelBoundary>
        <PanelBoundary name="Analytics" className="xl:col-span-4">
          <AnalyticsPanel />
        </PanelBoundary>
      </div>
    </AppShell>
  ),
});
