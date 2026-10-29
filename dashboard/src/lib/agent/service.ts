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
import { SOCKET_BACKOFF_MS } from "@/lib/booth/constants";
import type { Activity, AgentEvent, Analytics, BoothTime, Earnings, FeedbackPayload, Health, MenuItem, Metrics, OperationalMode, Order, OrderStatus, PaymentMethod, Visitor } from "./types";

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

export const getHealth = () => request<Health>("/health", undefined, false);
export const getMenu = () => request<{ menu: MenuItem[] }>("/api/menu", undefined, false);
// 16 §2ze item 5: public, like the menu — the display has no operator token.
// This amends §2o item 6: /display now calls /api/menu, /health and this.
export const getPosters = () => request<{ posters: string[] }>("/api/posters", undefined, false);

/**
 * The full URL of a poster the backend serves (16 §2ze item 5).
 *
 * `/api/posters` returns backend paths ("/posters/01-burgers.jpg"), and the TV
 * is a different origin from the backend, so the agent link is put back in
 * front of them before they reach an `<img src>`.
 */
export function posterSrc(path: string): string {
  return `${getAgentConfig().agentUrl.replace(/\/$/, "")}${path}`;
}
export const getOrders = (status: "active" | "completed" | "all" = "all") =>
  request<{ orders: Order[]; counts: Record<string, number> }>(`/api/orders?status=${status}&limit=20`);
export const getVisitors = () => request<{ visitors: Visitor[] }>("/api/visitors?limit=20");
export const getActivity = () => request<{ activity: { kind: Activity["kind"]; label: string; detail?: string; timestamp: BoothTime }[] }>("/api/activity?limit=30");
export const getAnalytics = () => request<Analytics>("/api/analytics");
export const getMetrics = () => request<Metrics>("/api/metrics");
// 16 §2z item 4: operator only, like the metrics.
export const getEarnings = () => request<Earnings>("/api/earnings");
/**
 * 16 §2zi item 4(c)/(d) — the guests' forms and the feedback spoken to THE
 * HOST. Operator only: the Feedback page calls it, and the public display
 * never does.
 */
export const getFeedback = () => request<FeedbackPayload>("/api/feedback");

/** Order ids are integers (20 §4 item 1). */
export async function setOrderStatus(id: number, status: OrderStatus, reason?: string, paymentMethod?: PaymentMethod): Promise<boolean> {
  try {
    // 16 §2z item 2, as §2zf item 3(d) extends it: payment_method travels
    // with the payment (CONFIRMED on an order that was waiting for it) and
    // with the old COLLECTED path; the backend refuses it anywhere else, so
    // it is sent only when given.
    const body: { status: OrderStatus; reason?: string; payment_method?: PaymentMethod } = { status };
    if (reason) body.reason = reason;
    if (paymentMethod) body.payment_method = paymentMethod;
    await request(`/api/orders/${id}/status`, { method: "POST", body: JSON.stringify(body) });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

/* ------------------------- operator controls -------------------------
 * 20 §4 item 4. Every call carries X-Operator-Token (added by `request`).
 * On 400/404 the backend's own "detail" text is shown; on 401 the fixed
 * "Operator token missing or wrong". The screen is never changed before the
 * backend's response or its event arrives — each helper only reports, and
 * the store is updated by the operational_mode_changed / order_updated event.
 */

type ModeResponse = { operational_mode: OperationalMode };

async function operator<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(`/api/operator/${path}`, { method: "POST" });
  } catch (err) {
    report(err);
    return null;
  }
}

export const pauseHost = () => operator<ModeResponse>("pause");
export const resumeHost = () => operator<ModeResponse>("resume");
export const startTakeover = () => operator<ModeResponse>("takeover");
export const endTakeover = () => operator<ModeResponse>("takeover/end");
export const endSession = () => operator<{ ended: boolean }>("end-session");
export const retryConnection = () => operator<{ operational_mode: OperationalMode; reachable: boolean }>("retry-connection");

export async function announceAgain(orderId: number): Promise<boolean> {
  try {
    await request("/api/operator/announce", { method: "POST", body: JSON.stringify({ order_id: orderId }) });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

/**
 * 16 §2zf item 8(c) — ask the TV to reload itself.
 *
 * The TV is across the stall on a kiosk browser with no keyboard, so when it
 * looks wrong there is no F5 to press. The backend sends one `display_reload`
 * to the `smd` role; the dashboard never reloads itself.
 */
export async function reloadDisplay(): Promise<boolean> {
  try {
    await request("/api/display/reload", { method: "POST" });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

/**
 * 16 §2zf item 6 — a line for THE HOST, from the team rather than the guest.
 *
 * The backend answers 409 "No conversation is running." when nobody is
 * talking to it, and that text is what the operator reads. The note is never
 * stored on this side: it leaves the box and is gone.
 */
export async function sendSessionNote(text: string): Promise<boolean> {
  try {
    await request("/api/session/note", { method: "POST", body: JSON.stringify({ text }) });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

/** Only the changed fields are sent; an emptied favourite sends null. */
export async function updateVisitor(nameKey: string, patch: { display_name?: string; favorite_item?: string | null }): Promise<boolean> {
  try {
    await request(`/api/visitors/${encodeURIComponent(nameKey)}`, { method: "PATCH", body: JSON.stringify(patch) });
    return true;
  } catch (err) {
    report(err);
    return false;
  }
}

export async function forgetVisitor(nameKey: string): Promise<boolean> {
  const { agentUrl, token } = getAgentConfig();
  try {
    const res = await fetch(`${agentUrl.replace(/\/$/, "")}/api/visitors/${encodeURIComponent(nameKey)}`, {
      method: "DELETE",
      headers: { "X-Operator-Token": token },
    });
    if (res.status === 401) throw new ApiError("Operator token missing or wrong", 401);
    if (res.status !== 204 && !res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        detail = ((await res.json()) as { detail?: string }).detail ?? detail;
      } catch {
        /* keep default */
      }
      throw new ApiError(detail, res.status);
    }
    return true;
  } catch (err) {
    report(err instanceof ApiError ? err : new ApiError("Backend unavailable", 0));
    return false;
  }
}

/** Reloads GET /api/visitors after an edit or a forget (20 §4 item 4). */
export async function reloadVisitors() {
  try {
    const { visitors } = await getVisitors();
    agentStore.dispatch({ type: "@hydrate", snapshot: { visitors } });
  } catch (err) {
    report(err);
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
let healthTimer: ReturnType<typeof setInterval> | null = null;
let menuRetryTimer: ReturnType<typeof setTimeout> | null = null;

const MENU_RETRY_MS = 10_000;

/**
 * The one place GET /api/orders is called: when the /ws/events socket
 * (re)connects (16 §2o item 10a). From then on the order list is kept current
 * by order_created / order_updated / state_snapshot alone.
 * Skipped in demo mode.
 */
export async function loadDashboardData() {
  if (agentStore.get().mode === "demo") return;
  try {
    const [{ orders }, { visitors }, { activity }] = await Promise.all([getOrders("all"), getVisitors(), getActivity()]);
    agentStore.dispatch({
      type: "@hydrate",
      snapshot: {
        orders,
        visitors,
        // Activity rows keep the backend's own time string; the feed parses it.
        activity: activity.map((a) => ({ id: `a-${a.timestamp}-${a.label}`, kind: a.kind, label: a.label, detail: a.detail, timestamp: a.timestamp })),
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
  // 16 §2z item 5: the money is loaded on mount and on every reconnect.
  await loadEarnings();
}

/**
 * 16 §2z item 5 — the Earnings summary. It is a summary, never the order
 * store: this can refetch freely after an order event without any risk to
 * §2o item 10(a), which is about `orders` being event-driven.
 */
export async function loadEarnings() {
  if (agentStore.get().mode === "demo") return;
  try {
    const earnings = await getEarnings();
    agentStore.dispatch({ type: "@earnings", earnings });
  } catch {
    /* the panel keeps the last figures and the toast is left to the caller */
  }
}

let earningsDebounce: ReturnType<typeof setTimeout> | null = null;

/** One refetch 1 s after a burst of order events, not one per event. */
export function scheduleEarningsRefresh() {
  if (earningsDebounce) clearTimeout(earningsDebounce);
  earningsDebounce = setTimeout(() => {
    earningsDebounce = null;
    void loadEarnings();
  }, 1_000);
}

/**
 * 16 §2z item 6 — the end-of-day sheet. The token cannot travel on a plain
 * link, so the CSV is fetched with the header and saved from the blob.
 */
export async function downloadEarningsCsv(): Promise<boolean> {
  const { agentUrl, token } = getAgentConfig();
  try {
    const res = await fetch(`${agentUrl.replace(/\/$/, "")}/api/earnings.csv`, {
      headers: { "X-Operator-Token": token },
    });
    if (res.status === 401) throw new ApiError("Operator token missing or wrong", 401);
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    const text = await res.text();
    const date = agentStore.get().earnings?.date ?? new Date().toISOString().slice(0, 10);
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `bite-and-pour-sales-${date}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch (err) {
    report(err instanceof ApiError ? err : new ApiError("Backend unavailable", 0));
    return false;
  }
}

/** 16 §2zi item 4(d) — the form rows, for Rehman to keep. */
export async function downloadFeedbackCsv(): Promise<boolean> {
  const { agentUrl, token } = getAgentConfig();
  try {
    const res = await fetch(`${agentUrl.replace(/\/$/, "")}/api/feedback.csv`, {
      headers: { "X-Operator-Token": token },
    });
    if (res.status === 401) throw new ApiError("Operator token missing or wrong", 401);
    if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
    const text = await res.text();
    const date = new Date().toISOString().slice(0, 10);
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `bite-and-pour-feedback-${date}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch (err) {
    report(err instanceof ApiError ? err : new ApiError("Backend unavailable", 0));
    return false;
  }
}

/**
 * Dashboard-only polling: analytics and metrics every 30 s (20 §4 item 4),
 * and the earnings on the same tick (16 §2z item 5).
 * All three endpoints need the operator token, so the public display never
 * calls this — see `connectAgent`.
 */
export function startAnalyticsPolling() {
  stopAnalyticsPolling();
  const tick = () => {
    if (agentStore.get().mode === "demo") return;
    getAnalytics()
      .then((analytics) => agentStore.dispatch({ type: "@analytics", analytics }))
      .catch(() => undefined);
    getMetrics()
      .then((metrics) => agentStore.dispatch({ type: "@metrics", metrics }))
      .catch(() => undefined);
    void loadEarnings();
  };
  tick();
  analyticsTimer = setInterval(tick, 30_000);
}

export function stopAnalyticsPolling() {
  if (analyticsTimer) clearInterval(analyticsTimer);
  analyticsTimer = null;
}

/** GET /health every 30 s (no token). Feeds the System panel's three rows. */
export function startHealthPolling() {
  stopHealthPolling();
  const tick = () => {
    if (agentStore.get().mode === "demo") return;
    getHealth()
      .then((h) => {
        const c = h.components ?? {};
        const map = (v: string | undefined) =>
          v === "ok" ? "online" : v === "error" ? "offline" : v === "online" || v === "degraded" || v === "offline" ? v : "unknown";
        const s = agentStore.get();
        agentStore.dispatch({
          type: "@hydrate",
          snapshot: {
            system: {
              ...s.system,
              backend: map(c.backend as string | undefined),
              ai_agent: map(c.ai_agent as string | undefined),
              database: map(c.database as string | undefined),
            },
          },
        });
      })
      .catch(() => undefined);
  };
  tick();
  healthTimer = setInterval(tick, 30_000);
}

export function stopHealthPolling() {
  if (healthTimer) clearInterval(healthTimer);
  healthTimer = null;
}

/**
 * GET /api/menu (no token). On failure the display shows "Menu loading…" and
 * this retries every 10 s until it succeeds (16 §2o item 6). The menu is never
 * sample or hard-coded data.
 */
export async function loadMenu() {
  if (menuRetryTimer) {
    clearTimeout(menuRetryTimer);
    menuRetryTimer = null;
  }
  try {
    const { menu } = await getMenu();
    agentStore.dispatch({ type: "@menu", menu });
    agentStore.dispatch({ type: "@menu_error", failed: false });
  } catch {
    agentStore.dispatch({ type: "@menu_error", failed: true });
    menuRetryTimer = setTimeout(() => void loadMenu(), MENU_RETRY_MS);
  }
}

export function stopMenuRetry() {
  if (menuRetryTimer) clearTimeout(menuRetryTimer);
  menuRetryTimer = null;
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

// 16 §2zf item 8(b): the same backoff the conversation socket now uses, in
// one place so the two can never drift apart.
const BACKOFF = SOCKET_BACKOFF_MS;

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
    // GET /api/menu needs no token, so both roles load it.
    void loadMenu();
    // Everything else is token-protected: the public display must never call
    // it (20 §4 item 3).
    if (currentRole === "dashboard") {
      void loadDashboardData();
      startAnalyticsPolling();
      startHealthPolling();
    }
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
    // capture_request belongs to the display screen; ignored quietly (20 §4 item 5).
    if (data.type === "capture_request") return;
    // 16 §2zf item 8(c): the operator asked this screen to reload itself. Only
    // the `smd` role is ever sent it, and only the TV acts on it.
    if (data.type === "display_reload") {
      if (currentRole === "smd" && typeof window !== "undefined") window.location.reload();
      return;
    }
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
    // Orders come from the events themselves (16 §2o item 10a). GET /api/orders
    // is NOT called here: a reload started by one event could resolve after a
    // newer event and overwrite it with staler data.
    agentStore.dispatch(data);
    // 16 §2z item 5: the Earnings summary follows the orders, debounced by 1 s.
    // It never writes to the order store, so §2o item 10(a) still holds.
    if (data.type === "order_created" || data.type === "order_updated") scheduleEarningsRefresh();
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
  stopHealthPolling();
  stopMenuRetry();
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
