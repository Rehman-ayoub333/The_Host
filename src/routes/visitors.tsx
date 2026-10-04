import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { MemoryPanel, VisitorsPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/visitors")({
  head: () => ({
    meta: [
      { title: "Visitors — NEXA · Bite & Pour" },
      { name: "description", content: "New and returning visitors recognized by NEXA's memory system." },
      { property: "og:title", content: "Visitors — NEXA" },
      { property: "og:description", content: "Who NEXA has met at the Bite & Pour booth." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Visitors" subtitle="New and returning guests reported by the visitor-memory system.">
      <div className="grid gap-4 xl:grid-cols-12">
        <VisitorsPanel limit={100} className="xl:col-span-7" />
        <MemoryPanel limit={8} className="xl:col-span-5" />
      </div>
    </AppShell>
  ),
});
