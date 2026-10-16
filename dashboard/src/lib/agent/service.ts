/**
 * Integration layer for the real THE HOST backend.
 * Components never call the network directly — everything goes through here.
 *
 * One setting: the agent link (backend base URL, default http://localhost:8000)
 * plus an operator token for the dashboard. Both are stored in localStorage.
 * The WebSocket URL is derived from the agent link.
 */
import { toast } from "sonner";
import { agentStore } from "./store";
import type { Activity, AgentEvent, AgentSnapshot, Analytics, MenuItem, Order, OrderStatus, Visitor } from "./types";

const LS_KEY = "thehost.agent.config";
const DEFAULT_AGENT_URL = "http://localhost:8000";

export interface AgentConfig {
  agentUrl: string;
  token: string;
}

export function getAgentConfig(): AgentConfig {
  const fallback = { agentUrl: DEFAULT_AGENT_URL, token: "" };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) return { ...fallback, ...(JSON.parse(raw) as Partial<AgentConfig>) };
  } catch {
    /* ignore */
  }
  return fallback;
}

export function saveAgentConfig(cfg: AgentConfig) {
  window.localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

function wsUrlFor(role: "dashboard" | "smd"): string {
  const { agentUrl, token } = getAgentConfig();
  const base = agentUrl.replace(/\/$/, "");
  const ws = base.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  const q = role === "dashboard" ? `role=dashboard&token=${encodeURIComponent(token)}` : "role=smd";
  return `${ws}/ws/events?${q}`;
}

/* ------------------------------- REST ------------------------------- */

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const { agentUrl, token } = getAgentConfig();
  let res: Response;
  try {
    res = await fetch(`${agentUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(auth ? { "X-Operator-Token": token } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError("Backend unavailable", 0);
  }
  if (res.status === 401) throw new ApiError("Operator token missing or wrong", 401);
  if (!res.ok) {
    let detail = res.status === 503 ? "Backend unavailable" : `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string; message?: string };
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* keep default */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

function report(err: unknown) {
  const msg = err instanceof ApiError ? err.message : "Backend unavailable";
  if (err instanceof ApiError && err.status === 401) agentStore.dispatch({ type: "@token_error", message: msg });
  toast.error(msg);
}

export const getHealth = () => request<{ status?: string }>("/health", undefined, false);
export const getMenu = () => request<{ menu: MenuItem[] }>("/api/menu", undefined, false);
export const getOrders = (status: "active" | "completed" | "all" = "all") =>
  request<{ orders: Order[]; counts: Record<string, number> }>(`/api/orders?status=${status}&limit=20`);
export const getVisitors = () => request<{ visitors: Visitor[] }>("/api/visitors?limit=20");
export const getActivity = () => request<{ activity: { kind: Activity["kind"]; label: string; detail?: string; timestamp: number }[] }>("/api/activity?limit=30");
export const getAnalytics = () => request<Analytics>("/api/analytics");

export async function setOrderStatus(id: string, status: OrderStatus, reason?: string): Promise<boolean> {
  try {
    await request(`/api/orders/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: JSON.stringify(reason ? { status, reason } : { status }),
    });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

export async function setMenuAvailability(name: string, available: boolean): Promise<boolean> {
  try {
    await request(`/api/menu/${encodeURIComponent(name)}/availability`, {
      method: "POST",
      body: JSON.stringify({ available }),
    });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

/* --------------------------- data loading --------------------------- */

let analyticsTimer: ReturnType<typeof setInterval> | null = null;

/** Initial fill + periodic reloads for the dashboard (skipped in demo mode). */
export async function loadDashboardData() {
  if (agentStore.get().mode === "demo") return;
  try {
    const [{ orders }, { visitors }, { activity }] = await Promise.all([getOrders("all"), getVisitors(), getActivity()]);
    agentStore.dispatch({
      type: "@hydrate",
      snapshot: {
        orders,
        visitors,
        activity: activity.map((a) => ({ id: `a-${a.timestamp}-${a.label}`, kind: a.kind, label: a.label, detail: a.detail, ts: a.timestamp })),
      },
    });
  } catch (err) {
    report(err);
  }
  try {
    const analytics = await getAnalytics();
    agentStore.dispatch({ type: "@analytics", analytics });
  } catch (err) {
    report(err);
  }
}

export function startAnalyticsPolling() {
  stopAnalyticsPolling();
  analyticsTimer = setInterval(() => {
    if (agentStore.get().mode === "demo") return;
    getAnalytics()
      .then((analytics) => agentStore.dispatch({ type: "@analytics", analytics }))
      .catch(() => undefined);
  }, 30_000);
}

export function stopAnalyticsPolling() {
  if (analyticsTimer) clearInterval(analyticsTimer);
  analyticsTimer = null;
}

export async function loadMenu() {
  try {
    const { menu } = await getMenu();
    agentStore.dispatch({ type: "@menu", menu });
  } catch {
    /* display shows its calm brand screen; never a stale or sample menu */
  }
}

/* ----------------------------- websocket ----------------------------- */

let ws: WebSocket | null = null;
let closed = true;
let attempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
let watchdog: ReturnType<typeof setTimeout> | undefined;
let lastEventId = 0;
let lastBootId: string | null = null;
let currentRole: "dashboard" | "smd" = "dashboard";

const BACKOFF = [1000, 2000, 4000, 8000, 10_000];

function armWatchdog() {
  clearTimeout(watchdog);
  // Dead after 25 s without any message (heartbeat arrives every 10 s).
  watchdog = setTimeout(() => ws?.close(), 25_000);
}

function scheduleReconnect() {
  if (closed) return;
  agentStore.dispatch({ type: "@connection", connection: "reconnecting" });
  const delay = BACKOFF[Math.min(attempt++, BACKOFF.length - 1)]!;
  reconnectTimer = setTimeout(open, delay);
}

function open() {
  if (closed) return;
  agentStore.dispatch({ type: "@connection", connection: "connecting" });
  try {
    ws = new WebSocket(wsUrlFor(currentRole));
  } catch {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    attempt = 0;
    agentStore.dispatch({ type: "@connection", connection: "live" });
    agentStore.dispatch({ type: "@token_error", message: null });
    armWatchdog();
    if (currentRole === "dashboard") void loadDashboardData();
    void loadMenu();
    startAnalyticsPolling();
  };
  ws.onmessage = (m) => {
    armWatchdog();
    let data: AgentEvent;
    try {
      data = JSON.parse(String(m.data)) as AgentEvent;
    } catch {
      return;
    }
    if (!data || typeof data.type !== "string") return;
    if (data.type === "heartbeat") return;
    // event_id dedup; boot_id change resets the remembered id.
    if (data.type === "state_snapshot") {
      if (data.boot_id !== lastBootId) {
        lastBootId = data.boot_id;
        lastEventId = 0;
      }
    } else if (typeof data.event_id === "number") {
      if (data.event_id <= lastEventId) return;
      lastEventId = data.event_id;
    }
    if (agentStore.get().mode === "demo") return; // demo ignores live events
    agentStore.dispatch(data);
    if (data.type === "order_created" || data.type === "order_updated") {
      // Reload the orders list so tabs/badges stay exact.
      getOrders("all")
        .then(({ orders }) => agentStore.dispatch({ type: "@hydrate", snapshot: { orders } }))
        .catch(() => undefined);
    }
    if (data.type === "error") toast.error(data.message);
  };
  ws.onclose = (ev) => {
    clearTimeout(watchdog);
    if (closed) return;
    if (ev.code === 4401) {
      // Operator token missing or wrong — do not retry until the token changes.
      agentStore.dispatch({ type: "@connection", connection: "token_error" });
      agentStore.dispatch({ type: "@token_error", message: "Operator token missing or wrong" });
      return;
    }
    scheduleReconnect();
  };
  ws.onerror = () => ws?.close();
}

/** Connects the store to the backend. role=smd for the public display. */
export function connectAgent(role: "dashboard" | "smd" = "dashboard") {
  disconnectAgent();
  closed = false;
  currentRole = role;
  attempt = 0;
  open();
}

export function disconnectAgent() {
  closed = true;
  clearTimeout(reconnectTimer);
  clearTimeout(watchdog);
  stopAnalyticsPolling();
  ws?.close();
  ws = null;
}

/** Pauses the live connection while Demo Mode runs; resumes after. */
export function pauseLiveForDemo() {
  disconnectAgent();
}

export function resumeLiveAfterDemo() {
  connectAgent(currentRole);
}
