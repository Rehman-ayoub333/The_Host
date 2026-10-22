import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { ActivityPanel, VisionPanel } from "@/components/host/panels";

export const Route = createFileRoute("/vision")({
  head: () => ({
    meta: [
      { title: "Live Vision — THE HOST · Bite & Pour" },
      { name: "description", content: "THE HOST's camera feed with detections and the visitor currently in focus." },
      { property: "og:title", content: "Live Vision — THE HOST" },
      { property: "og:description", content: "See the booth through THE HOST's eyes." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell title="Live Vision" subtitle="Camera feed, detections and current focus as reported by the agent.">
      <div className="grid gap-4 xl:grid-cols-12">
        <PanelBoundary name="Live Vision" className="xl:col-span-9">
          <VisionPanel tall />
        </PanelBoundary>
        <PanelBoundary name="Activity" className="xl:col-span-3">
          <ActivityPanel limit={10} />
        </PanelBoundary>
      </div>
    </AppShell>
  ),
});
