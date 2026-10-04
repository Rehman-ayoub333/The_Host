import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { AnalyticsPanel, OrdersPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/orders")({
  head: () => ({
    meta: [
      { title: "Orders — NEXA · Bite & Pour" },
      { name: "description", content: "Every order NEXA has taken, with live preparation countdowns." },
      { property: "og:title", content: "Orders — NEXA" },
      { property: "og:description", content: "Live order tracking at the Bite & Pour booth." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Orders" subtitle="Orders created by NEXA, with times supplied by the kitchen system.">
      <div className="grid gap-4 xl:grid-cols-12">
        <OrdersPanel limit={50} className="xl:col-span-8" />
        <AnalyticsPanel className="xl:col-span-4" />
      </div>
    </AppShell>
  ),
});
