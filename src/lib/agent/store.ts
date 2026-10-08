import { useSyncExternalStore } from "react";
import type { Activity, ActivityKind, AgentEvent, AgentSnapshot, AgentStateName, BackendState, LocalAction } from "./types";

export const initialSnapshot: AgentSnapshot = {
  mode: "live",
  connection: "unconfigured",
  state: "offline",
  lastAgentState: null,
  opMode: null,
  caption: null,
  transcript: [],
  present: false,
  people: 0,
  objects: [],
  focus: null,
  visitors: [],
  orders: [],
  memory: [],
  activity: [],
  analytics: null,
  menu: [],
  recommendation: null,
  orderReady: null,
  system: {
    backend: "unknown",
    ai_agent: "unknown",
    database: "unknown",
    web_search: "unknown",
    camera: "unknown",
    microphone: "unknown",
    speaker: "unknown",
    internet: "unknown",
  },
  lastError: null,
  tokenError: null,
  demoStep: null,
  updatedAt: 0,
};

let seq = 0;
const uid = () => `${Date.now().toString(36)}-${(seq++).toString(36)}`;

function log(s: AgentSnapshot, kind: ActivityKind, label: string, detail?: string): Activity[] {
  return [{ id: uid(), kind, label, detail, ts: Date.now() }, ...s.activity].slice(0, 80);
}

/** Map a backend state to one of the nine visual states. */
export function mapState(state: BackendState): AgentStateName {
  switch (state) {
    case "IDLE":
      return "idle";
    case "SEEING":
      return "seeing";
    case "LISTENING":
      return "listening";
    case "THINKING":
      return "thinking";
    case "SPEAKING":
    case "GREETING":
    case "RECOMMENDING":
      return "speaking";
    case "TAKING_ORDER":
      return "taking_order";
    case "ANNOUNCING":
      return "order_ready";
    case "REMEMBERING":
      return "remembering";
    case "NEEDS_HELP":
      return "needs_help";
  }
}

const ACTIVE_ORDER: Order["status"][] = ["CONFIRMED", "PREPARING", "READY", "REQUIRES_ATTENTION"];

export function reduce(s: AgentSnapshot, e: AgentEvent | LocalAction): AgentSnapshot {
  const now = Date.now();
  const n = (patch: Partial<AgentSnapshot>): AgentSnapshot => ({ ...s, ...patch, updatedAt: now });

  switch (e.type) {
    case "@connection":
      return n({ connection: e.connection, state: e.connection === "live" ? (s.state === "offline" ? "idle" : s.state) : s.mode === "demo" ? s.state : "offline" });
    case "@mode":
      return n({ mode: e.mode });
    case "@demo_step":
      return n({ demoStep: e.step });
    case "@hydrate":
      return n(e.snapshot);
    case "@menu":
      return n({ menu: e.menu });
    case "@analytics":
      return n({ analytics: e.analytics });
    case "@token_error":
      return n({ tokenError: e.message });
    case "@reset":
      return { ...initialSnapshot, connection: s.connection, state: s.connection === "live" ? "idle" : "offline", updatedAt: now };

    case "state_snapshot":
      return n({
        state: mapState(e.conversation_state),
        lastAgentState: e.conversation_state,
        opMode: { mode: e.operational_mode },
        present: e.present,
        orders: e.active_orders ?? [],
      });
    case "agent_state_changed":
      return n({ state: mapState(e.state), lastAgentState: e.state });
    case "order_ready":
      return n({
        orderReady: { order_id: e.order_id, customer_name: e.customer_name, until: now + 8000 },
        activity: log(s, "order", `Order #${e.order_id} ready`, e.customer_name ?? undefined),
      });
    case "operational_mode_changed":
      return n({ opMode: { mode: e.mode, reason: e.reason }, activity: log(s, "system", `Mode: ${e.mode}`, e.reason) });
    case "speech_transcript": {
      const speaker = e.role === "agent" ? ("host" as const) : ("visitor" as const);
      const caption = { speaker, text: e.text };
      const last = s.transcript[s.transcript.length - 1];
      let transcript: AgentSnapshot["transcript"];
      if (last && last.speaker === speaker && !last.final) {
        transcript = [...s.transcript.slice(0, -1), { ...last, text: e.text, final: !!e.final, ts: now }];
      } else {
        transcript = [...s.transcript, { id: uid(), speaker, text: e.text, final: !!e.final, ts: now }];
      }
      return n({ caption, transcript: transcript.slice(-40) });
    }
    case "order_created": {
      const faint = e.order.status === "PENDING_CONFIRMATION";
      return n({
        orders: [e.order, ...s.orders.filter((o) => o.id !== e.order.id)],
        activity: faint ? s.activity : log(s, "order", `Order #${e.order.id} created`, e.order.items.map((i) => i.name).join(" · ")),
      });
    }
    case "order_updated": {
      const orders = s.orders.map((o) => (o.id === e.order.id ? { ...o, ...e.order } : o));
      const o = orders.find((x) => x.id === e.order.id);
      return n({ orders, activity: log(s, "order", `Order #${e.order.id} updated`, o?.status) });
    }
    case "visitor_identified":
      return n({
        focus: { name: e.name, returning: e.returning, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order },
        activity: log(s, "visitor", "Visitor identified", e.name),
      });
    case "memory_updated": {
      const entry = { id: `m-${e.name}`, name: e.name, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order, last_seen: e.last_seen, returning: e.returning };
      const visitors = [
        { name_key: e.name.toLowerCase(), name: e.name, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order, last_seen: e.last_seen, returning: e.returning },
        ...s.visitors.filter((v) => v.name !== e.name),
      ];
      return n({
        memory: [entry, ...s.memory.filter((m) => m.name !== e.name)].slice(0, 100),
        visitors,
        activity: log(s, "memory", "Memory updated", e.name),
      });
    }
    case "recommendation":
      return n({ recommendation: { item: e.item, reason: e.reason, until: now + 10_000 }, activity: log(s, "speech", "Recommendation", `${e.item} — ${e.reason}`) });
    case "menu_updated":
      return n({ menu: s.menu.map((m) => (m.name === e.item ? { ...m, available: e.available } : m)) });
    case "person_detected":
      return n({ present: true, activity: log(s, "visitor", "Visitor detected") });
    case "person_left":
      return n({ present: false, focus: null, activity: log(s, "visitor", "Visitor left") });
    case "vision_update":
      return n({ present: e.present, people: e.people, objects: e.objects });
    case "system_status_changed":
      return n({ system: { ...s.system, [e.component]: e.status }, activity: log(s, "system", `${e.component} ${e.status}`, e.detail) });
    case "agent_activity":
      return n({ activity: log(s, e.kind, e.label, e.detail) });
    case "interrupted":
      return s;
    case "error":
      return n({ lastError: e.message, activity: log(s, "system", "Error", e.message) });
    case "heartbeat":
      return s;
  }
}

/* ---------------- store + demo-only cross-window sync ---------------- */

let snap = initialSnapshot;
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;

const emit = () => listeners.forEach((l) => l());

export const agentStore = {
  get: () => snap,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
  dispatch(e: AgentEvent | LocalAction) {
    snap = reduce(snap, e);
    emit();
    // BroadcastChannel carries Demo Mode only — never live data.
    if (snap.mode === "demo") channel?.postMessage({ kind: "snapshot", snap });
  },
};

/** Demo Mode sync between the operator window and the SMD display window. */
export function initDemoSync() {
  if (typeof window === "undefined" || channel || !("BroadcastChannel" in window)) return;
  channel = new BroadcastChannel("thehost-demo");
  channel.onmessage = (ev: MessageEvent) => {
    const msg = ev.data as { kind: string; snap?: AgentSnapshot };
    if (msg.kind === "snapshot" && msg.snap && msg.snap.mode === "demo" && msg.snap.updatedAt > snap.updatedAt) {
      snap = msg.snap;
      emit();
    } else if (msg.kind === "hello" && snap.mode === "demo" && snap.updatedAt > 0) {
      channel?.postMessage({ kind: "snapshot", snap });
    }
  };
  channel.postMessage({ kind: "hello" });
}

export function useAgent<T>(selector: (s: AgentSnapshot) => T): T {
  return useSyncExternalStore(
    agentStore.subscribe,
    () => selector(snap),
    () => selector(initialSnapshot),
  );
}

export { ACTIVE_ORDER };
