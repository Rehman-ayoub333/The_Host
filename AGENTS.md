<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

## THE HOST architecture
- All agent data flows through `src/lib/agent/store.ts` (event reducer) fed by `src/lib/agent/service.ts` (WebSocket/REST); components never fetch directly — keeps the external agent swappable.
- Demo mode (`src/lib/agent/demo.ts`) pushes scripted events through the same reducer and is always visibly labelled — the UI must never invent live data.
- The public display (`/display`) connects with its own role=smd socket and GET /api/menu; BroadcastChannel ("thehost-demo") carries Demo Mode snapshots only — never live data.
- Brand-state presentation uses shared semantic CSS tokens and `STATE_META` tones; preserve a black/champagne-gold/ivory visual language so UI state never implies a separate neon AI identity.
