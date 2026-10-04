/**
 * Integration layer for the external NEXA agent.
 * Components never call the network directly — everything goes through here.
 *
 * Configure with env vars (public, no secrets):
 *   VITE_AGENT_API_URL  e.g. https://agent.example.com
 *   VITE_AGENT_WS_URL   e.g. wss://agent.example.com/events
 * Operators can override both at runtime from Settings (stored locally).
 */
import { agentStore } from "./store";
import type { AgentEvent, AgentSnapshot, MemoryEntry, Order, SystemComponent, ComponentStatus, Visitor } from "./types";

const LS_KEY = "nexa.agent.config";

export interface AgentConfig {
  apiUrl: string;
  wsUrl: string;
}

export function getAgentConfig(): AgentConfig {
  const env = {
    apiUrl: (import.meta.env.VITE_AGENT_API_URL as string | undefined) ?? "",
    wsUrl: (import.meta.env.VITE_AGENT_WS_URL as string | undefined) ?? "",
  };
  if (typeof window === "undefined") return env;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) return { ...env, ...(JSON.parse(raw) as Partial<AgentConfig>) };
  } catch {
    /* ignore */
  }
  return env;
}

export function saveAgentConfig(cfg: AgentConfig) {
  window.localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { apiUrl } = getAgentConfig();
  if (!apiUrl) throw new Error("Agent API URL is not configured");
  const res = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`Agent request failed (${res.status})`);
  return (await res.json()) as T;
}

export const getAgentState = () => request<Partial<AgentSnapshot>>("/state");
export const getOrders = () => request<Order[]>("/orders");
export const getVisitors = () => request<Visitor[]>("/visitors");
export const getMemory = () => request<MemoryEntry[]>("/memory");
export const getSystemStatus = () => request<Record<SystemComponent, ComponentStatus>>("/system");
export const getVisionState = () => request<Pick<AgentSnapshot, "frameUrl" | "detections">>("/vision");
export const sendAgentMessage = (text: string) =>
  request<{ ok: boolean }>("/message", { method: "POST", body: JSON.stringify({ text }) });

/** Subscribes to the agent's realtime stream with exponential reconnect. */
export function subscribeToAgentEvents(
  onEvent: (e: AgentEvent) => void,
  onStatus: (s: "connecting" | "connected" | "disconnected") => void,
): () => void {
  const { wsUrl } = getAgentConfig();
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const open = () => {
    onStatus("connecting");
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      onStatus("disconnected");
      return;
    }
    ws.onopen = () => {
      attempt = 0;
      onStatus("connected");
    };
    ws.onmessage = (m) => {
      try {
        const data = JSON.parse(String(m.data)) as AgentEvent;
        if (data && typeof data.type === "string") onEvent(data);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      onStatus("disconnected");
      if (closed) return;
      const delay = Math.min(15000, 1000 * 2 ** attempt++);
      timer = setTimeout(open, delay);
    };
  };

  open();
  return () => {
    closed = true;
    clearTimeout(timer);
    ws?.close();
  };
}

let unsubscribe: (() => void) | null = null;

/** Connects the global store to the live agent if configured. */
export async function connectAgent() {
  unsubscribe?.();
  unsubscribe = null;
  const { wsUrl, apiUrl } = getAgentConfig();
  if (!wsUrl) {
    agentStore.dispatch({ type: "@connection", connection: "unconfigured" });
    return;
  }
  if (apiUrl) {
    getAgentState()
      .then((snapshot) => agentStore.dispatch({ type: "@hydrate", snapshot }))
      .catch(() => undefined);
  }
  unsubscribe = subscribeToAgentEvents(
    (e) => {
      if (agentStore.get().mode === "live") agentStore.dispatch(e);
    },
    (connection) => agentStore.dispatch({ type: "@connection", connection }),
  );
}
