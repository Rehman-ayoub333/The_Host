import { useSyncExternalStore } from "react";
import type { Activity, ActivityKind, AgentEvent, AgentSnapshot, AgentStateName, BackendState, BoothTime, LocalAction, Order } from "./types";
import { toMs } from "./ui";

export const initialSnapshot: AgentSnapshot = {
  mode: "live",
  connection: "unconfigured",
  state: "offline",
  lastAgentState: null,
  stateSince: null,
  sessionId: null,
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
  metrics: null,
  menu: [],
  menuFailed: false,
  recommendation: null,
  orderReady: null,
  readyQueue: [],
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

/**
 * The ONE way a row enters the activity feed (20 §4 item 2): an `agent_activity`
 * event, or a row from GET /api/activity. The reducer never invents a row of
 * its own for order_ready, operational_mode_changed, order_created,
 * order_updated, visitor_identified, memory_updated or any other event — the
 * backend already sends the correct agent_activity row for each, so a second
 * one would be a duplicate.
 */
function logActivity(s: AgentSnapshot, kind: ActivityKind, label: string, detail: string | undefined, timestamp: BoothTime | undefined): Activity[] {
  return [{ id: uid(), kind, label, detail, timestamp }, ...s.activity].slice(0, 80);
}

/** Keeps the last 50 transcript lines, in memory only — never persisted. */
const TRANSCRIPT_LIMIT = 50;

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
    case "@menu_error":
      return n({ menuFailed: e.failed });
    case "@analytics":
      return n({ analytics: e.analytics });
    case "@metrics":
      return n({ metrics: e.metrics });
    case "@token_error":
      return n({ tokenError: e.message });
    case "@ready_done":
      return n({ readyQueue: s.readyQueue.slice(1) });
    case "@reset":
      return { ...initialSnapshot, connection: s.connection, state: s.connection === "live" ? "idle" : "offline", updatedAt: now };

    case "state_snapshot": {
      // 16 §2o item 10(a): the snapshot replaces the ACTIVE set only. Orders
      // that are finished or still being taken are not part of it, so they are
      // kept as they are rather than wiped by a snapshot that never knew them.
      const incoming = e.active_orders ?? [];
      const incomingIds = new Set(incoming.map((o) => o.id));
      const kept = s.orders.filter((o) => !ACTIVE_ORDER.includes(o.status) && !incomingIds.has(o.id));
      return n({
        state: mapState(e.conversation_state),
        lastAgentState: e.conversation_state,
        stateSince: toMs(e.timestamp) ?? now,
        sessionId: e.session_id ?? null,
        opMode: { mode: e.operational_mode },
        present: e.present,
        orders: [...incoming, ...kept],
      });
    }
    case "agent_state_changed":
      return n({
        state: mapState(e.state),
        lastAgentState: e.state,
        // The seconds counter runs from the event's own booth-local timestamp.
        stateSince: toMs(e.timestamp) ?? now,
        sessionId: e.session_id ?? s.sessionId,
      });
    case "order_ready":
      // Appended, never replaced: two orders becoming ready together must both
      // be shown on the display (16 §2o item 6).
      return n({
        orderReady: { order_id: e.order_id, customer_name: e.customer_name, until: now + 8000 },
        readyQueue: [...s.readyQueue, { order_id: e.order_id, customer_name: e.customer_name }],
      });
    case "operational_mode_changed":
      return n({ opMode: { mode: e.mode, reason: e.reason } });
    case "speech_transcript": {
      const speaker = e.role === "agent" ? ("host" as const) : ("visitor" as const);
      const caption = { speaker, text: e.text };
      const last = s.transcript[s.transcript.length - 1];
      // `text` is always the whole line: a still-open line for the same role is
      // REPLACED, never appended to (03 §4).
      let transcript: AgentSnapshot["transcript"];
      if (last && last.speaker === speaker && !last.final) {
        transcript = [...s.transcript.slice(0, -1), { ...last, text: e.text, final: !!e.final, timestamp: e.timestamp, ts: now, session_id: e.session_id ?? null }];
      } else {
        transcript = [...s.transcript, { id: uid(), speaker, text: e.text, final: !!e.final, timestamp: e.timestamp, ts: now, session_id: e.session_id ?? null }];
      }
      return n({ caption, transcript: transcript.slice(-TRANSCRIPT_LIMIT), sessionId: e.session_id ?? s.sessionId });
    }
    // 16 §2o item 10(a): the event's `order` REPLACES the stored order with the
    // same id, or is added if there is none. Never merged with what was there:
    // the event is the newest truth about that order, field for field.
    case "order_created":
    case "order_updated": {
      const known = s.orders.some((o) => o.id === e.order.id);
      const orders = known ? s.orders.map((o) => (o.id === e.order.id ? e.order : o)) : [e.order, ...s.orders];
      return n({ orders });
    }
    case "visitor_identified":
      return n({ focus: { name: e.name, returning: e.returning, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order } });
    case "memory_updated": {
      const entry = { id: `m-${e.name}`, name: e.name, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order, last_seen: e.last_seen, returning: e.returning };
      const visitors = [
        { name_key: e.name.toLowerCase(), name: e.name, visits: e.visits, favorite_item: e.favorite_item, last_order: e.last_order, last_seen: e.last_seen ?? undefined, returning: e.returning },
        ...s.visitors.filter((v) => v.name !== e.name),
      ];
      return n({ memory: [entry, ...s.memory.filter((m) => m.name !== e.name)].slice(0, 100), visitors });
    }
    case "recommendation":
      return n({ recommendation: { item: e.item, reason: e.reason, until: now + 10_000 } });
    case "menu_updated":
      return n({ menu: s.menu.map((m) => (m.name === e.item ? { ...m, available: e.available } : m)) });
    case "person_detected":
      return n({ present: true });
    case "person_left":
      return n({ present: false, focus: null });
    case "vision_update":
      return n({ present: e.present, people: e.people, objects: e.objects });
    case "system_status_changed":
      return n({ system: { ...s.system, [e.component]: e.status } });
    case "agent_activity":
      // The only event that writes to the feed.
      return n({ activity: logActivity(s, e.kind, e.label, e.detail, e.timestamp) });
    case "capture_request":
      return s; // the display screen's business (20 §4 item 5)
    case "interrupted":
      return s;
    // 16 §2k item 3: the display screen holds its clocks on this; the dashboard
    // has no state of its own for it. The connection row it might look like it
    // belongs to is about THIS browser's /ws/events socket, not the backend's
    // Gemini link, so nothing here changes (16 §2s item 4a).
    case "reconnecting":
      return s;
    case "error":
      return n({ lastError: e.message });
    case "heartbeat":
      return s;
  }
  // 16 §2s item 4a: the reducer is total. It used to fall out of the switch and
  // return undefined for any event not listed above, which set the snapshot to
  // undefined and made every useAgent selector throw -- taking the whole
  // Command Center into the router's error page, for the rest of the session.
  // An event this build does not know about now changes nothing instead.
  return s;
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
