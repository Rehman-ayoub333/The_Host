import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { ActivityPanel, CorePanel, TranscriptPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/activity")({
  head: () => ({
    meta: [
      { title: "AI Activity — NEXA · Bite & Pour" },
      { name: "description", content: "A real-time log of everything NEXA perceives, decides and does." },
      { property: "og:title", content: "AI Activity — NEXA" },
      { property: "og:description", content: "NEXA's live event timeline." },
    ],
  }),
  component: () => (
    <AppShell title="AI Activity" subtitle="Every event received from the agent, newest first.">
      <div className="grid gap-4 xl:grid-cols-12">
        <ActivityPanel limit={80} className="xl:col-span-7" />
        <div className="grid content-start gap-4 xl:col-span-5">
          <CorePanel />
          <TranscriptPanel />
        </div>
      </div>
    </AppShell>
  ),
});
