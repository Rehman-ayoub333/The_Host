/**
 * DEMO MODE — scripted events pushed through the exact same event pipeline
 * the real agent uses. All data here is clearly labelled as demo data.
 */
import visionDemo from "@/assets/vision-demo.jpg";
import { agentStore } from "./store";
import type { AgentEvent, Detection, LocalAction, Visitor } from "./types";

export const DEMO_STEPS = ["See", "Hear", "Think", "Speak", "Take Order", "Remember", "Personalize", "Track Order"] as const;

const min = 60_000;

const detections: Detection[] = [
  { id: "d1", label: "Person", confidence: 0.97, box: [0.46, 0.5, 0.12, 0.42], visitorId: "v-ahmed" },
  { id: "d2", label: "Person", confidence: 0.94, box: [0.65, 0.46, 0.1, 0.4] },
  { id: "d3", label: "Table", confidence: 0.88, box: [0.4, 0.82, 0.14, 0.16] },
  { id: "d4", label: "Food stall", confidence: 0.81, box: [0.02, 0.28, 0.3, 0.45] },
];

const ahmed = (): Visitor => ({
  id: "v-ahmed",
  name: "Ahmed",
  visits: 3,
  lastVisit: Date.now() - 2 * 24 * 60 * min,
  returning: true,
  favorite: "Blue Lemonade",
  lastOrder: "Chicken Burger",
});

type Step = { at: number; step?: number; ev: () => AgentEvent | LocalAction };

const script = (): Step[] => [
  { at: 0, step: 0, ev: () => ({ type: "agent_state_changed", state: "seeing", detail: "Scanning booth" }) },
  { at: 400, ev: () => ({ type: "vision_update", frameUrl: visionDemo, detections }) },
  { at: 2600, ev: () => ({ type: "person_detected", detection: detections[0] }) },

  { at: 5200, step: 1, ev: () => ({ type: "speech_started" }) },
  { at: 6400, ev: () => ({ type: "speech_transcript", text: "I want a chicken burger…" }) },
  { at: 7800, ev: () => ({ type: "speech_transcript", text: "I want a chicken burger and a blue lemonade.", final: true }) },

  { at: 9000, step: 2, ev: () => ({ type: "agent_thinking", detail: "Matching menu items" }) },
  { at: 10600, ev: () => ({ type: "agent_thinking", detail: "Checking the kitchen queue" }) },

  { at: 12400, step: 3, ev: () => ({ type: "agent_speaking", text: "Great choice! One Chicken Burger and a Blue Lemonade, coming right up." }) },
  { at: 16000, ev: () => ({ type: "agent_speech_finished" }) },

  { at: 16400, step: 4, ev: () => ({ type: "agent_state_changed", state: "taking_order", detail: "Chicken Burger · Blue Lemonade" }) },
  {
    at: 18600,
    ev: () => ({
      type: "order_created",
      order: {
        id: "o-027",
        number: "027",
        customerName: "Ahmed",
        visitorId: "v-ahmed",
        items: [
          { name: "Chicken Burger", qty: 1 },
          { name: "Blue Lemonade", qty: 1 },
        ],
        status: "confirming",
        createdAt: Date.now(),
      },
    }),
  },
  { at: 20600, ev: () => ({ type: "order_updated", order: { id: "o-027", status: "preparing", readyAt: Date.now() + 36_000, prepSeconds: 36 } }) },

  { at: 22800, step: 5, ev: () => ({ type: "person_recognized", visitor: ahmed() }) },
  {
    at: 24400,
    ev: () => ({
      type: "memory_updated",
      entry: { id: "m-ahmed-2", visitorId: "v-ahmed", visitorName: "Ahmed", text: "Ordered Blue Lemonade again — likely favourite", ts: Date.now() },
    }),
  },

  { at: 26500, step: 6, ev: () => ({ type: "agent_state_changed", state: "welcoming" }) },
  { at: 28000, ev: () => ({ type: "agent_speaking", text: "Welcome back, Ahmed! That Blue Lemonade is one of your favourites." }) },
  { at: 32000, ev: () => ({ type: "agent_speech_finished" }) },

  { at: 32400, step: 7, ev: () => ({ type: "agent_state_changed", state: "order_preparing", detail: "Order #027" }) },
  { at: 56800, ev: () => ({ type: "order_ready", id: "o-027" }) },
  { at: 57600, ev: () => ({ type: "agent_speaking", text: "Ahmed, your order #027 is ready. Enjoy!" }) },
  { at: 61500, ev: () => ({ type: "agent_speech_finished" }) },
  { at: 62000, ev: () => ({ type: "@demo_step", step: DEMO_STEPS.length }) },
];

let timers: ReturnType<typeof setTimeout>[] = [];

function seed() {
  const now = Date.now();
  agentStore.dispatch({
    type: "@hydrate",
    snapshot: {
      mode: "demo",
      state: "idle",
      detail: null,
      caption: null,
      transcript: [],
      frameUrl: null,
      detections: [],
      focusVisitorId: null,
      lastError: null,
      system: { camera: "online", microphone: "online", speaker: "online", agent: "online", internet: "online" },
      visitors: [
        { id: "v-ayesha", name: "Ayesha", visits: 1, lastVisit: now - 6 * min, returning: false, lastOrder: "Club Sandwich" },
        { id: "v-usman", name: "Usman", visits: 2, lastVisit: now - 13 * min, returning: true, lastOrder: "Chicken Burger" },
        { id: "v-sara", name: "Sara", visits: 1, lastVisit: now - 24 * min, returning: false, lastOrder: "Blue Lemonade" },
      ],
      orders: [
        {
          id: "o-026",
          number: "026",
          customerName: "Ayesha",
          items: [
            { name: "Club Sandwich", qty: 1 },
            { name: "Strawberry Milkshake", qty: 1 },
          ],
          status: "preparing",
          createdAt: now - 5 * min,
          readyAt: now + 3 * min,
          prepSeconds: 8 * 60,
        },
        {
          id: "o-025",
          number: "025",
          customerName: "Usman",
          items: [{ name: "Chicken Burger", qty: 1 }],
          status: "completed",
          createdAt: now - 14 * min,
        },
        {
          id: "o-024",
          number: "024",
          customerName: "Sara",
          items: [{ name: "Blue Lemonade", qty: 2 }],
          status: "completed",
          createdAt: now - 25 * min,
        },
      ],
      memory: [
        { id: "m-ahmed-1", visitorId: "v-ahmed", visitorName: "Ahmed", text: "Loves the Chicken Burger", ts: now - 2 * 24 * 60 * min },
        { id: "m-usman-1", visitorId: "v-usman", visitorName: "Usman", text: "Prefers no onions", ts: now - 13 * min },
      ],
      activity: [],
    },
  });
}

export function startDemo() {
  stopDemo(false);
  seed();
  agentStore.dispatch({ type: "@demo_step", step: 0 });
  for (const s of script()) {
    timers.push(
      setTimeout(() => {
        if (s.step !== undefined) agentStore.dispatch({ type: "@demo_step", step: s.step });
        agentStore.dispatch(s.ev());
      }, s.at),
    );
  }
}

export function stopDemo(resetToLive = true) {
  timers.forEach(clearTimeout);
  timers = [];
  if (resetToLive) agentStore.dispatch({ type: "@reset" });
}
