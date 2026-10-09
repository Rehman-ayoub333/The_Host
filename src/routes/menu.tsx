import { createFileRoute } from "@tanstack/react-router";
import { UtensilsCrossed } from "lucide-react";
import { AppShell } from "@/components/host/AppShell";
import { Panel, EmptyState, DemoTag } from "@/components/host/Panel";
import { useAgent } from "@/lib/agent/store";
import { setMenuAvailability } from "@/lib/agent/service";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/menu")({
  head: () => ({
    meta: [
      { title: "Menu — THE HOST · Bite & Pour" },
      { name: "description", content: "The Bite & Pour menu as served by the backend, with sold-out control." },
      { property: "og:title", content: "Menu — THE HOST" },
      { property: "og:description", content: "Menu availability at the Bite & Pour booth." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MenuPage,
});

function MenuPage() {
  const menu = useAgent((s) => s.menu);
  const isDemo = useAgent((s) => s.mode === "demo");

  return (
    <AppShell title="Menu" subtitle="The menu exactly as the backend serves it — mark items sold out here.">
      <Panel title="Menu" icon={<UtensilsCrossed className="h-4 w-4" />} action={isDemo ? <DemoTag /> : undefined}>
        {menu.length === 0 ? (
          <EmptyState icon={<UtensilsCrossed className="h-6 w-6" />} title="No menu loaded" hint="The menu arrives from the backend once the agent link is connected." />
        ) : (
          <ul className="divide-y divide-line">
            {menu.map((m) => (
              <li key={m.name} className="flex items-center gap-4 py-3 first:pt-0 last:pb-0">
                {m.image_url && <img src={m.image_url} alt="" className="h-10 w-10 rounded-md border border-line object-cover" />}
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm font-semibold", !m.available && "text-muted-foreground line-through")}>{m.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {m.category} · {m.price}{m.description ? ` · ${m.description}` : ""}
                  </p>
                </div>
                <button
                  onClick={() => void setMenuAvailability(m.name, !m.available)}
                  className={cn(
                    "rounded-sm border px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-wider transition-colors",
                    m.available ? "border-line text-muted-foreground hover:border-destructive hover:text-destructive" : "border-destructive/50 text-destructive hover:border-gold hover:text-gold",
                  )}
                >
                  {m.available ? "Mark sold out" : "Sold out — restore"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </AppShell>
  );
}
