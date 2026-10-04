import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { MemoryPanel, VisitorsPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/memory")({
  head: () => ({
    meta: [
      { title: "Memory — NEXA · Bite & Pour" },
      { name: "description", content: "Preferences and notes NEXA remembers about returning guests." },
      { property: "og:title", content: "Memory — NEXA" },
      { property: "og:description", content: "What NEXA remembers, so every visit feels personal." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Memory" subtitle="Only what the agent's memory system has actually stored.">
      <div className="grid gap-4 xl:grid-cols-12">
        <MemoryPanel limit={100} className="xl:col-span-8" />
        <VisitorsPanel className="xl:col-span-4" />
      </div>
    </AppShell>
  ),
});
