import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
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
        <AnalyticsPanel className="xl:col-span-5" />
        <OrdersPanel limit={6} className="xl:col-span-4" />
        <VisitorsPanel className="xl:col-span-3" />
      </div>
    </AppShell>
  ),
});
