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

## NEXA architecture
- All agent data flows through `src/lib/agent/store.ts` (event reducer) fed by `src/lib/agent/service.ts` (WebSocket/REST); components never fetch directly — keeps the external agent swappable.
- Demo mode (`src/lib/agent/demo.ts`) pushes scripted events through the same reducer and is always visibly labelled — the UI must never invent live data.
- Dashboard and `/display` (SMD screen) sync across windows via BroadcastChannel — so one operator window drives the public screen.
