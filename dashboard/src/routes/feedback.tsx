import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/host/AppShell";
import { PanelBoundary } from "@/components/host/PanelBoundary";
import { FeedbackPanel } from "@/components/host/FeedbackPanel";

export const Route = createFileRoute("/feedback")({
  head: () => ({
    meta: [
      { title: "Feedback — THE HOST · Bite & Pour" },
      { name: "description", content: "What guests said about Bite & Pour, on the form and to THE HOST." },
      { property: "og:title", content: "Feedback — THE HOST" },
      { property: "og:description", content: "Guest feedback collected at the Bite & Pour stall." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => (
    <AppShell
      title="Feedback"
      subtitle="What guests filled in on the form, and what they asked THE HOST to pass on."
    >
      <PanelBoundary name="Feedback">
        <FeedbackPanel />
      </PanelBoundary>
    </AppShell>
  ),
});
