/**
 * Contract between the NEXA frontend and the external agent.
 * The backend emits AgentEvents; the frontend never reasons on its own.
 */

export type AgentStateName =
  | "idle"
  | "seeing"
  | "person_detected"
  | "listening"
  | "thinking"
  | "speaking"
  | "taking_order"
  | "order_confirmed"
  | "order_preparing"
  | "order_ready"
  | "remembering"
  | "welcoming"
  | "engaging"
  | "multitasking"
  | "error"
  | "offline";

export type ConnectionStatus = "unconfigured" | "connecting" | "connected" | "disconnected";
export type DataMode = "live" | "demo";

export type SystemComponent = "camera" | "microphone" | "speaker" | "agent" | "internet";
export type ComponentStatus = "online" | "degraded" | "offline" | "unknown";

export interface Detection {
  id: string;
  label: string;
  confidence: number; // 0..1
  /** normalised [x, y, w, h] in 0..1 */
  box: [number, number, number, number];
  visitorId?: string;
}

export interface Visitor {
  id: string;
  name: string;
  visits: number;
  lastVisit: number; // epoch ms
  returning: boolean;
  favorite?: string;
  lastOrder?: string;
}

export interface OrderItem {
  name: string;
  qty: number;
}

export type OrderStatus = "confirming" | "preparing" | "ready" | "completed" | "cancelled";

export interface Order {
  id: string;
  number: string;
  customerName?: string;
  visitorId?: string;
  items: OrderItem[];
  status: OrderStatus;
  createdAt: number;
  /** epoch ms supplied by backend — never invented by the UI */
  readyAt?: number;
  prepSeconds?: number;
}

export interface MemoryEntry {
  id: string;
  visitorId: string;
  visitorName: string;
  text: string;
  ts: number;
}

export interface TranscriptLine {
  id: string;
  speaker: "visitor" | "nexa";
  text: string;
  ts: number;
}

export type ActivityKind = "vision" | "audio" | "reasoning" | "voice" | "order" | "memory" | "system" | "error";

export interface Activity {
  id: string;
  kind: ActivityKind;
  title: string;
  detail?: string | undefined;
  ts: number;
}

export type AgentEvent =
  | { type: "agent_state_changed"; state: AgentStateName; detail?: string }
  | { type: "vision_update"; frameUrl?: string | null; detections: Detection[] }
  | { type: "person_detected"; detection?: Detection }
  | { type: "person_recognized"; visitor: Visitor }
  | { type: "speech_started" }
  | { type: "speech_transcript"; text: string; final?: boolean }
  | { type: "agent_thinking"; detail?: string }
  | { type: "agent_speaking"; text: string }
  | { type: "agent_speech_finished" }
  | { type: "order_created"; order: Order }
  | { type: "order_updated"; order: Partial<Order> & { id: string } }
  | { type: "order_ready"; id: string }
  | { type: "memory_updated"; entry: MemoryEntry }
  | { type: "system_status_changed"; component: SystemComponent; status: ComponentStatus }
  | { type: "error"; message: string };

/** Internal (frontend-only) actions */
export type LocalAction =
  | { type: "@connection"; connection: ConnectionStatus }
  | { type: "@mode"; mode: DataMode }
  | { type: "@demo_step"; step: number | null }
  | { type: "@hydrate"; snapshot: Partial<AgentSnapshot> }
  | { type: "@reset" };

export interface AgentSnapshot {
  mode: DataMode;
  connection: ConnectionStatus;
  state: AgentStateName;
  detail: string | null;
  caption: { speaker: "visitor" | "nexa"; text: string } | null;
  transcript: TranscriptLine[];
  frameUrl: string | null;
  detections: Detection[];
  focusVisitorId: string | null;
  visitors: Visitor[];
  orders: Order[];
  memory: MemoryEntry[];
  activity: Activity[];
  system: Record<SystemComponent, ComponentStatus>;
  lastError: string | null;
  demoStep: number | null;
  updatedAt: number;
}
