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

export interface OrderItem {
  name: string;
  quantity: number;
  price?: number | undefined;
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
  id: string;
  items: OrderItem[];
  status: OrderStatus;
  guest_name?: string | null | undefined;
  total?: number | null | undefined;
  timestamp?: number | undefined;
  estimated_ready_at?: number | null | undefined;
  ready_at?: number | null | undefined;
}

export interface Visitor {
  name_key?: string | undefined;
  name: string;
  visits: number;
  favorite_item?: string | null | undefined;
  last_order?: string | null | undefined;
  first_seen?: number | undefined;
  last_seen?: number | undefined;
  returning: boolean;
}

export interface MemoryEntry {
  id: string;
  name: string;
  visits: number;
  favorite_item?: string | null | undefined;
  last_order?: string | null | undefined;
  last_seen?: number | undefined;
  returning: boolean;
}

export interface TranscriptLine {
  id: string;
  speaker: "visitor" | "host";
  text: string;
  final: boolean;
  ts: number;
}

export type ActivityKind = "speech" | "order" | "memory" | "visitor" | "vision" | "system" | "operator";

export interface Activity {
  id: string;
  kind: ActivityKind;
  label: string;
  detail?: string | undefined;
  ts: number;
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
  price: string | number;
  description?: string | undefined;
  image_url?: string | null | undefined;
  available: boolean;
  prep_seconds?: number | null | undefined;
}

/** Events the backend sends over /ws/events (exact shapes). */
export type AgentEvent =
  | { type: "state_snapshot"; event_id?: number; boot_id: string; operational_mode: OperationalMode; conversation_state: BackendState; session_id: string; present: boolean; active_orders: Order[] }
  | { type: "agent_state_changed"; event_id?: number; state: BackendState }
  | { type: "order_ready"; event_id?: number; order_id: string; customer_name?: string | null }
  | { type: "operational_mode_changed"; event_id?: number; mode: OperationalMode; reason?: string }
  | { type: "speech_transcript"; event_id?: number; role: "visitor" | "agent"; text: string; final?: boolean }
  | { type: "order_created"; event_id?: number; order: Order }
  | { type: "order_updated"; event_id?: number; order: Order }
  | { type: "visitor_identified"; event_id?: number; name: string; returning: boolean; visits?: number; favorite_item?: string | null; last_order?: string | null }
  | { type: "memory_updated"; event_id?: number; name: string; visits: number; favorite_item?: string | null; last_order?: string | null; last_seen?: number; returning: boolean }
  | { type: "recommendation"; event_id?: number; item: string; reason: string }
  | { type: "menu_updated"; event_id?: number; item: string; available: boolean }
  | { type: "person_detected"; event_id?: number; person_id: string }
  | { type: "person_left"; event_id?: number; person_id: string }
  | { type: "vision_update"; event_id?: number; present: boolean; people: number; objects: DetectedObject[] }
  | { type: "system_status_changed"; event_id?: number; component: BackendComponent; status: "online" | "degraded" | "offline"; detail?: string }
  | { type: "agent_activity"; event_id?: number; kind: ActivityKind; label: string; detail?: string }
  | { type: "interrupted"; event_id?: number }
  | { type: "error"; event_id?: number; message: string; recoverable?: boolean }
  | { type: "heartbeat" };

/** Internal (frontend-only) actions */
export type LocalAction =
  | { type: "@connection"; connection: ConnectionStatus }
  | { type: "@mode"; mode: DataMode }
  | { type: "@demo_step"; step: number | null }
  | { type: "@hydrate"; snapshot: Partial<AgentSnapshot> }
  | { type: "@menu"; menu: MenuItem[] }
  | { type: "@analytics"; analytics: Analytics | null }
  | { type: "@token_error"; message: string | null }
  | { type: "@reset" };

export interface AgentSnapshot {
  mode: DataMode;
  connection: ConnectionStatus;
  state: AgentStateName;
  /** Last raw agent_state_changed (used by the display's order_ready speech rule). */
  lastAgentState: BackendState | null;
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
  menu: MenuItem[];
  recommendation: { item: string; reason: string; until: number } | null;
  orderReady: { order_id: string; customer_name?: string | null | undefined; until: number } | null;
  system: Record<SystemComponent, ComponentStatus>;
  lastError: string | null;
  tokenError: string | null;
  demoStep: number | null;
  updatedAt: number;
}
