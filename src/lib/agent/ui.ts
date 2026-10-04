import { useEffect, useState } from "react";
import type { AgentStateName } from "./types";

export type OrbTone = "brand" | "ai" | "think" | "warn" | "off";

export interface StateMeta {
  label: string;
  verb: string;
  tone: OrbTone;
  rings: "wave" | "think" | "pulse" | "particles" | "none";
}

export const STATE_META: Record<AgentStateName, StateMeta> = {
  idle: { label: "Idle", verb: "Ready to welcome you", tone: "brand", rings: "none" },
  seeing: { label: "Seeing", verb: "Seeing…", tone: "ai", rings: "pulse" },
  person_detected: { label: "Person Detected", verb: "Welcome!", tone: "ai", rings: "pulse" },
  listening: { label: "Listening", verb: "Listening…", tone: "ai", rings: "wave" },
  thinking: { label: "Thinking", verb: "Thinking…", tone: "think", rings: "think" },
  speaking: { label: "Speaking", verb: "Speaking", tone: "ai", rings: "wave" },
  taking_order: { label: "Taking Order", verb: "Taking your order", tone: "ai", rings: "pulse" },
  order_confirmed: { label: "Order Confirmed", verb: "Order confirmed", tone: "brand", rings: "pulse" },
  order_preparing: { label: "Preparing", verb: "Preparing your order", tone: "brand", rings: "none" },
  order_ready: { label: "Order Ready", verb: "Your order is ready", tone: "brand", rings: "pulse" },
  remembering: { label: "Remembering", verb: "I remember you", tone: "brand", rings: "particles" },
  welcoming: { label: "Welcoming", verb: "Welcome back", tone: "brand", rings: "particles" },
  engaging: { label: "Engaging", verb: "Here for you", tone: "ai", rings: "none" },
  multitasking: { label: "Multi-tasking", verb: "Handling several things", tone: "think", rings: "think" },
  error: { label: "Needs Help", verb: "One moment — calling a host", tone: "warn", rings: "pulse" },
  offline: { label: "Offline", verb: "NEXA is resting", tone: "off", rings: "none" },
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

export function fmtCountdown(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtClock(ts: number) {
  if (!ts) return "--:--:--";
  return new Date(ts).toLocaleTimeString([], { hour12: false });
}

export function fmtAgo(ts: number, now: number) {
  if (!now) return "";
  const m = Math.round((now - ts) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
