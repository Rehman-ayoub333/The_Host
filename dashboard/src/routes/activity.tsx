import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { ActivityPanel, CorePanel, TranscriptPanel } from "@/components/host/panels";

export const Route = createFileRoute("/activity")({
  head: () => ({
    meta: [
      { title: "AI Activity — THE HOST · Bite & Pour" },
      { name: "description", content: "A real-time log of everything THE HOST perceives, decides and does." },
      { property: "og:title", content: "AI Activity — THE HOST" },
      { property: "og:description", content: "THE HOST's live event timeline." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="AI Activity" subtitle="Every event received from the agent, newest first.">
      <div className="grid gap-4 xl:grid-cols-12">
        <PanelBoundary name="Activity" className="xl:col-span-7">
          <ActivityPanel limit={80} />
        </PanelBoundary>
        <div className="grid content-start gap-4 xl:col-span-5">
          <PanelBoundary name="AI Host">
            <CorePanel />
          </PanelBoundary>
          <PanelBoundary name="Transcript">
            <TranscriptPanel />
          </PanelBoundary>
        </div>
      </div>
    </AppShell>
  ),
});
