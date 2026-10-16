/**
 * Contract between the THE HOST frontend and the real backend.
 * The backend emits AgentEvents over /ws/events; the frontend never
 * reasons on its own and never invents data the backend did not send.
 */

/** States the backend reports (uppercase, as sent). */
export type BackendState =
  | "IDLE"
  | "GREETING"
  | "SEEING"
  | "LISTENING"
  | "THINKING"
  | "SPEAKING"
  | "RECOMMENDING"
  | "TAKING_ORDER"
  | "ANNOUNCING"
  | "REMEMBERING"
  | "NEEDS_HELP";

/** The nine visual states the UI renders (plus offline). */
export type AgentStateName =
  | "idle"
  | "seeing"
  | "listening"
  | "thinking"
  | "speaking"
  | "taking_order"
  | "order_ready"
  | "remembering"
  | "needs_help"
  | "offline";

export type OperationalMode = "ONLINE" | "DEGRADED" | "RECOVERING" | "OFFLINE" | "PAUSED" | "OPERATOR_TAKEOVER";

export type ConnectionStatus = "unconfigured" | "connecting" | "live" | "reconnecting" | "token_error";
export type DataMode = "live" | "demo";

export type BackendComponent = "backend" | "ai_agent" | "database" | "web_search";
export type BrowserComponent = "camera" | "microphone" | "speaker" | "internet";
export type SystemComponent = BackendComponent | BrowserComponent;
export type ComponentStatus = "online" | "degraded" | "offline" | "unknown";

export interface DetectedObject {
  label: string;
  confidence: number; // 0..1
}

/**
 * A booth-local ISO 8601 string WITHOUT a timezone, for example
 * "2026-10-10T10:06:10". Never a number: parse it with `toMs()` (which uses
 * `new Date(value).getTime()`, reading it as local time) before any countdown,
 * progress bar or "2 days ago" text. `null` means no value exists, so the UI
 * shows no countdown and no "ago" text rather than inventing one.
 */
export type BoothTime = string;

export interface OrderItem {
  name: string;
  quantity: number;
  /** Already formatted by the backend, e.g. "Rs. 650". Shown exactly as sent. */
  price?: string | undefined;
}

export type OrderStatus =
  | "PENDING_CONFIRMATION"
  | "CONFIRMED"
  | "PREPARING"
  | "READY"
  | "COLLECTED"
  | "CANCELLED"
  | "FAILED"
  | "REQUIRES_ATTENTION";

export interface Order {
  /** An integer, e.g. 27 — never a string. */
  id: number;
  items: OrderItem[];
  status: OrderStatus;
  guest_name?: string | null | undefined;
  /** Already formatted, e.g. "Rs. 1,300". null means show nothing. */
  total?: string | null | undefined;
  timestamp?: BoothTime | undefined;
  estimated_ready_at?: BoothTime | null | undefined;
  ready_at?: BoothTime | null | undefined;
  /** 16 §2m item 5. Missing means false. */
  complimentary?: boolean | undefined;
}

export interface Visitor {
  name_key?: string | undefined;
  name: string;
  visits: number;
  favorite_item?: string | null | undefined;
  last_order?: string | null | undefined;
  first_seen?: BoothTime | undefined;
  last_seen?: BoothTime | undefined;
  returning: boolean;
}

export interface MemoryEntry {
  id: string;
  name: string;
  visits: number;
  favorite_item?: string | null | undefined;
  last_order?: string | null | undefined;
  last_seen?: BoothTime | null | undefined;
  returning: boolean;
}

export interface TranscriptLine {
  id: string;
  speaker: "visitor" | "host";
  text: string;
  final: boolean;
  /** The event's own booth-local time. */
  timestamp?: BoothTime | null | undefined;
  /** Arrival time in this browser (ms), used only for ordering and display. */
  ts: number;
  /** The conversation this line belongs to, for the session divider. */
  session_id?: string | null | undefined;
}

export type ActivityKind = "speech" | "order" | "memory" | "visitor" | "vision" | "system" | "operator";

export interface Activity {
  id: string;
  kind: ActivityKind;
  label: string;
  detail?: string | undefined;
  /** Booth-local ISO string, exactly as the backend sends it. */
  timestamp?: BoothTime | null | undefined;
}

/**
 * One queued "order ready" announcement for the public display (16 §2o item 6).
 * Several are shown one after another, 15 s each, and none is ever dropped.
 */
export interface ReadyAnnouncement {
  order_id: number;
  customer_name?: string | null | undefined;
}

/** GET /api/metrics (20 §4 item 4). Every value is an integer. */
export interface Metrics {
  date: string;
  sessions_today: number;
  orders_today: number;
  failed_tool_calls_today: number;
  connection_failures_today: number;
}

/** GET /health (no token). */
export interface Health {
  status?: string;
  operational_mode?: OperationalMode;
  components?: Partial<Record<BackendComponent, ComponentStatus | string>>;
}

export interface Analytics {
  date: string;
  orders: number;
  interactions: number;
  named_visitors: number;
  returning_visitors: number;
  popular_items: { name: string; percent: number }[];
  average_order_to_ready_seconds?: number | null;
}

export interface MenuItem {
  name: string;
  category: string;
  /** Already formatted, e.g. "Rs. 650". Shown exactly as sent. */
  price: string;
  description?: string | undefined;
  image_url?: string | null | undefined;
  available: boolean;
  prep_seconds?: number | null | undefined;
}

/**
 * Every event carries the same envelope (03 §3): `timestamp` is booth-local
 * ISO without a timezone, `session_id` is the 8-hex conversation id or null.
 */
interface Envelope {
  event_id?: number;
  timestamp?: BoothTime;
  session_id?: string | null;
}

/** Events the backend sends over /ws/events (exact shapes, 03 §4). */
export type AgentEvent =
  | (Envelope & { type: "state_snapshot"; boot_id: string; operational_mode: OperationalMode; conversation_state: BackendState; present: boolean; active_orders: Order[] })
  | (Envelope & { type: "agent_state_changed"; state: BackendState })
  | (Envelope & { type: "order_ready"; order_id: number; customer_name?: string | null })
  | (Envelope & { type: "operational_mode_changed"; mode: OperationalMode; reason?: string })
  | (Envelope & { type: "speech_transcript"; role: "visitor" | "agent"; text: string; final?: boolean })
  | (Envelope & { type: "order_created"; order: Order })
  | (Envelope & { type: "order_updated"; order: Order })
  | (Envelope & { type: "visitor_identified"; name: string; returning: boolean; visits?: number; favorite_item?: string | null; last_order?: string | null })
  | (Envelope & { type: "memory_updated"; name: string; visits: number; favorite_item?: string | null; last_order?: string | null; last_seen?: BoothTime | null; returning: boolean })
  | (Envelope & { type: "recommendation"; item: string; reason: string })
  | (Envelope & { type: "menu_updated"; item: string; available: boolean })
  | (Envelope & { type: "person_detected"; person_id: string })
  | (Envelope & { type: "person_left"; person_id: string })
  | (Envelope & { type: "vision_update"; present: boolean; people: number; objects: DetectedObject[] })
  | (Envelope & { type: "system_status_changed"; component: BackendComponent; status: "online" | "degraded" | "offline"; detail?: string | null })
  | (Envelope & { type: "agent_activity"; kind: ActivityKind; label: string; detail?: string })
  | (Envelope & { type: "capture_request" })
  | (Envelope & { type: "interrupted" })
  | (Envelope & { type: "error"; message: string; recoverable?: boolean })
  | { type: "heartbeat"; timestamp?: BoothTime };

/** Internal (frontend-only) actions */
export type LocalAction =
  | { type: "@connection"; connection: ConnectionStatus }
  | { type: "@mode"; mode: DataMode }
  | { type: "@demo_step"; step: number | null }
  | { type: "@hydrate"; snapshot: Partial<AgentSnapshot> }
  | { type: "@menu"; menu: MenuItem[] }
  | { type: "@menu_error"; failed: boolean }
  | { type: "@analytics"; analytics: Analytics | null }
  | { type: "@metrics"; metrics: Metrics | null }
  | { type: "@token_error"; message: string | null }
  | { type: "@ready_done" }
  | { type: "@reset" };

export interface AgentSnapshot {
  mode: DataMode;
  connection: ConnectionStatus;
  state: AgentStateName;
  /** Last raw agent_state_changed, shown uppercase as sent by the Live panel. */
  lastAgentState: BackendState | null;
  /** When that state began (ms), from the event's own timestamp. */
  stateSince: number | null;
  /** The conversation the latest events belong to. */
  sessionId: string | null;
  opMode: { mode: OperationalMode; reason?: string | undefined } | null;
  caption: { speaker: "visitor" | "host"; text: string } | null;
  transcript: TranscriptLine[];
  present: boolean;
  people: number;
  objects: DetectedObject[];
  focus: { name: string; returning: boolean; visits?: number | undefined; favorite_item?: string | null | undefined; last_order?: string | null | undefined } | null;
  visitors: Visitor[];
  orders: Order[];
  memory: MemoryEntry[];
  activity: Activity[];
  analytics: Analytics | null;
  metrics: Metrics | null;
  menu: MenuItem[];
  /** True while GET /api/menu is failing, so the display shows "Menu loading…". */
  menuFailed: boolean;
  recommendation: { item: string; reason: string; until: number } | null;
  orderReady: { order_id: number; customer_name?: string | null | undefined; until: number } | null;
  /** FIFO of announcements still to show on the display; never dropped. */
  readyQueue: ReadyAnnouncement[];
  system: Record<SystemComponent, ComponentStatus>;
  lastError: string | null;
  tokenError: string | null;
  demoStep: number | null;
  updatedAt: number;
}
