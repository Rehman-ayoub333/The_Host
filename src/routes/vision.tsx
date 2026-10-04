import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/nexa/AppShell";
import { ActivityPanel, VisionPanel } from "@/components/nexa/panels";

export const Route = createFileRoute("/vision")({
  head: () => ({
    meta: [
      { title: "Live Vision — NEXA · Bite & Pour" },
      { name: "description", content: "NEXA's camera feed with detections and the visitor currently in focus." },
      { property: "og:title", content: "Live Vision — NEXA" },
      { property: "og:description", content: "See the booth through NEXA's eyes." },
    ],
  }),
  component: () => (
    <AppShell title="Live Vision" subtitle="Camera feed, detections and current focus as reported by the agent.">
      <div className="grid gap-4 xl:grid-cols-12">
        <VisionPanel tall className="xl:col-span-9" />
        <ActivityPanel limit={10} className="xl:col-span-3" />
      </div>
    </AppShell>
  ),
});
