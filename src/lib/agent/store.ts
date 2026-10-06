import { useSyncExternalStore } from "react";
import { sampleData } from "./sample";
import type { Activity, ActivityKind, AgentEvent, AgentSnapshot, LocalAction } from "./types";

export const initialSnapshot: AgentSnapshot = {
  mode: "live",
  connection: "unconfigured",
  state: "offline",
  detail: null,
  caption: null,
  transcript: [],
  frameUrl: null,
  detections: [],
  focusVisitorId: null,
  visitors: [],
  orders: [],
  memory: [],
  activity: [],
  system: { camera: "unknown", microphone: "unknown", speaker: "unknown", agent: "unknown", internet: "unknown" },
  lastError: null,
  demoStep: null,
  sample: false,
  updatedAt: 0,
};

let seq = 0;
const uid = () => `${Date.now().toString(36)}-${(seq++).toString(36)}`;

function log(s: AgentSnapshot, kind: ActivityKind, title: string, detail?: string): Activity[] {
  return [{ id: uid(), kind, title, detail, ts: Date.now() }, ...s.activity].slice(0, 80);
}

export function reduce(s: AgentSnapshot, e: AgentEvent | LocalAction): AgentSnapshot {
  const now = Date.now();
  const n = (patch: Partial<AgentSnapshot>): AgentSnapshot => ({ ...s, ...patch, updatedAt: now });

  switch (e.type) {
    case "@connection": {
      if (e.connection === "connected" && s.sample)
        return { ...initialSnapshot, connection: "connected", state: "idle", sample: false, updatedAt: now };
      const next = n({
        connection: e.connection,
        state: e.connection === "connected" ? (s.state === "offline" ? "idle" : s.state) : s.mode === "demo" ? s.state : "offline",
      });
      if (e.connection !== "connected" && next.mode === "live" && !next.sample) return { ...next, ...sampleData(now), sample: true };
      return next;
    }
    case "@mode":
      if (e.mode === "live" && s.connection !== "connected") return { ...n({ mode: "live" }), ...sampleData(now), sample: true };
      return n({ mode: e.mode, sample: e.mode === "demo" ? false : s.sample });
    case "@demo_step":
      return n({ demoStep: e.step });
    case "@hydrate":
      return n(e.snapshot);
    case "@reset": {
      const base = { ...initialSnapshot, connection: s.connection, state: s.connection === "connected" ? ("idle" as const) : ("offline" as const), updatedAt: now };
      return s.connection === "connected" ? base : { ...base, ...sampleData(now), sample: true };
    }

    case "agent_state_changed":
      return n({ state: e.state, detail: e.detail ?? null });
    case "vision_update":
      return n({ frameUrl: e.frameUrl === undefined ? s.frameUrl : e.frameUrl, detections: e.detections });
    case "person_detected":
      return n({
        state: "person_detected",
        detail: null,
        activity: log(s, "vision", "Person detected", e.detection ? `${Math.round(e.detection.confidence * 100)}% confidence` : undefined),
      });
    case "person_recognized": {
      const others = s.visitors.filter((v) => v.id !== e.visitor.id);
      return n({
        state: "remembering",
        detail: null,
        focusVisitorId: e.visitor.id,
        visitors: [e.visitor, ...others],
        activity: log(s, "memory", "Visitor recognized", `${e.visitor.name} · visit ${e.visitor.visits}`),
      });
    }
    case "speech_started":
      return n({ state: "listening", detail: null, caption: null, activity: log(s, "audio", "Speech detected") });
    case "speech_transcript": {
      const caption = { speaker: "visitor" as const, text: e.text };
      if (!e.final) return n({ caption });
      return n({
        caption,
        transcript: [...s.transcript, { id: uid(), speaker: "visitor" as const, text: e.text, ts: now }].slice(-40),
        activity: log(s, "audio", "Transcript received", `“${e.text}”`),
      });
    }
    case "agent_thinking":
      return n({ state: "thinking", detail: e.detail ?? null, activity: log(s, "reasoning", "Reasoning", e.detail) });
    case "agent_speaking":
      return n({
        state: "speaking",
        detail: null,
        caption: { speaker: "nexa", text: e.text },
        transcript: [...s.transcript, { id: uid(), speaker: "nexa" as const, text: e.text, ts: now }].slice(-40),
        activity: log(s, "voice", "Responding", `“${e.text}”`),
      });
    case "agent_speech_finished":
      return n({ state: s.detections.length ? "engaging" : "idle" });
    case "order_created":
      return n({
        state: "order_confirmed",
        orders: [e.order, ...s.orders.filter((o) => o.id !== e.order.id)],
        activity: log(s, "order", `Order #${e.order.number} created`, e.order.items.map((i) => i.name).join(" · ")),
      });
    case "order_updated": {
      const orders = s.orders.map((o) => (o.id === e.order.id ? { ...o, ...e.order } : o));
      const o = orders.find((x) => x.id === e.order.id);
      return n({ orders, activity: log(s, "order", `Order #${o?.number ?? "?"} updated`, e.order.status) });
    }
    case "order_ready": {
      const orders = s.orders.map((o) => (o.id === e.id ? { ...o, status: "ready" as const } : o));
      const o = orders.find((x) => x.id === e.id);
      return n({ state: "order_ready", orders, activity: log(s, "order", `Order #${o?.number ?? "?"} ready`) });
    }
    case "memory_updated":
      return n({
        memory: [e.entry, ...s.memory.filter((m) => m.id !== e.entry.id)].slice(0, 100),
        activity: log(s, "memory", "Memory updated", `${e.entry.visitorName}: ${e.entry.text}`),
      });
    case "system_status_changed":
      return n({ system: { ...s.system, [e.component]: e.status }, activity: log(s, "system", `${e.component} ${e.status}`) });
    case "error":
      return n({ state: "error", lastError: e.message, activity: log(s, "error", "Error", e.message) });
  }
}

/* ---------------- store + cross-window sync ---------------- */

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
    channel?.postMessage({ kind: "snapshot", snap });
  },
};

/** Keeps the dashboard and the SMD display window in lock-step. */
export function initCrossWindowSync() {
  if (typeof window === "undefined" || channel || !("BroadcastChannel" in window)) return;
  channel = new BroadcastChannel("nexa-agent");
  channel.onmessage = (ev: MessageEvent) => {
    const msg = ev.data as { kind: string; snap?: AgentSnapshot };
    if (msg.kind === "snapshot" && msg.snap && msg.snap.updatedAt > snap.updatedAt) {
      snap = msg.snap;
      emit();
    } else if (msg.kind === "hello" && snap.updatedAt > 0) {
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
