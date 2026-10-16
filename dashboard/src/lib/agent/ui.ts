import { useEffect, useState } from "react";
import type { AgentStateName, BoothTime } from "./types";

export type OrbTone = "brand" | "scan" | "voice" | "think" | "memory" | "order" | "ready" | "warn" | "off";

export interface StateMeta {
  label: string;
  verb: string;
  tone: OrbTone;
  rings: "wave" | "think" | "pulse" | "particles" | "none";
}

export const STATE_META: Record<AgentStateName, StateMeta> = {
  idle: { label: "Idle", verb: "Ready to welcome you", tone: "brand", rings: "none" },
  seeing: { label: "Seeing", verb: "Seeing…", tone: "scan", rings: "pulse" },
  listening: { label: "Listening", verb: "Listening…", tone: "voice", rings: "wave" },
  thinking: { label: "Thinking", verb: "Thinking…", tone: "think", rings: "think" },
  speaking: { label: "Speaking", verb: "Speaking", tone: "voice", rings: "wave" },
  taking_order: { label: "Taking Order", verb: "Taking your order", tone: "order", rings: "pulse" },
  order_ready: { label: "Order Ready", verb: "Your order is ready", tone: "ready", rings: "pulse" },
  remembering: { label: "Remembering", verb: "I remember you", tone: "memory", rings: "particles" },
  needs_help: { label: "Needs Help", verb: "One moment — calling a host", tone: "warn", rings: "pulse" },
  offline: { label: "Offline", verb: "THE HOST is unavailable", tone: "off", rings: "none" },
};

/** Ticking clock that is SSR-safe (0 until hydrated). */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/**
 * The one place a backend time string becomes a number (20 §4 item 1).
 * Every `timestamp`, `estimated_ready_at`, `ready_at`, `last_seen`, `first_seen`
 * and activity-row time is a booth-local ISO string without a timezone;
 * `new Date(value).getTime()` reads it as local time. A null, missing or
 * unparseable value yields null, which every caller renders as "nothing" —
 * never NaN, and never an invented figure.
 */
export function toMs(value: BoothTime | null | undefined): number | null {
  if (typeof value !== "string" || value === "") return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

export function fmtCountdown(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Seconds, as "4s" / "1m 12s". Used for "in this state for …". */
export function fmtElapsed(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Clock for a backend time string, or for a browser ms value. */
export function fmtClock(value: BoothTime | number | null | undefined) {
  const ms = typeof value === "number" ? value : toMs(value);
  if (!ms) return "--:--:--";
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

export function fmtAgo(value: BoothTime | null | undefined, now: number) {
  const ts = toMs(value);
  if (!now || ts === null) return "";
  const m = Math.round((now - ts) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
