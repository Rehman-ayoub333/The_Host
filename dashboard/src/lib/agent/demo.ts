/**
 * DEMO MODE — scripted events pushed through the exact same event pipeline
 * the real backend uses. All data here is clearly labelled as demo data.
 * While the demo runs, live events and REST data are ignored; on exit all
 * demo content is cleared and live data reloads.
 */
import { agentStore } from "./store";
import { pauseLiveForDemo, resumeLiveAfterDemo } from "./service";
import type { AgentEvent, LocalAction } from "./types";

export const DEMO_STEPS = ["See", "Hear", "Think", "Speak", "Confirm Order", "Remember", "Personalize", "Track Order"] as const;

const min = 60_000;

/**
 * A booth-local ISO string without a timezone — the exact shape the backend
 * sends (`datetime.now().isoformat(timespec="seconds")`), so Demo Mode exercises
 * the same parsing path as live data.
 */
const iso = (ms: number): string => {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

type Step = { at: number; step?: number; ev: () => AgentEvent | LocalAction };

const script = (): Step[] => [
  { at: 0, step: 0, ev: () => ({ type: "agent_state_changed", state: "SEEING" }) },
  { at: 400, ev: () => ({ type: "vision_update", present: true, people: 2, objects: [{ label: "Cup", confidence: 0.88 }, { label: "Chair", confidence: 0.81 }] }) },
  { at: 2600, ev: () => ({ type: "person_detected", person_id: "p-1" }) },

  { at: 5200, step: 1, ev: () => ({ type: "agent_state_changed", state: "LISTENING" }) },
  { at: 6400, ev: () => ({ type: "speech_transcript", role: "visitor", text: "I want a chicken burger…" }) },
  { at: 7800, ev: () => ({ type: "speech_transcript", role: "visitor", text: "I want a chicken burger and a blue lemonade.", final: true }) },

  { at: 9000, step: 2, ev: () => ({ type: "agent_state_changed", state: "THINKING" }) },
  { at: 10600, ev: () => ({ type: "agent_activity", kind: "system", label: "Checking the kitchen queue" }) },

  // Read-back + confirmation — the live system never places an order without it.
  { at: 12400, step: 3, ev: () => ({ type: "agent_state_changed", state: "SPEAKING" }) },
  { at: 12600, ev: () => ({ type: "speech_transcript", role: "agent", text: "That's one Chicken Burger and one Blue Lemonade — Rs 500 in total. Shall I confirm that?", final: true }) },
  { at: 17000, ev: () => ({ type: "agent_state_changed", state: "LISTENING" }) },
  { at: 18000, ev: () => ({ type: "speech_transcript", role: "visitor", text: "Yes.", final: true }) },

  { at: 19000, step: 4, ev: () => ({ type: "agent_state_changed", state: "TAKING_ORDER" }) },
  {
    at: 20600,
    ev: () => ({
      type: "order_created",
      order: {
        id: 27,
        items: [
          { name: "Chicken Burger", quantity: 1, price: "Rs. 350" },
          { name: "Blue Lemonade", quantity: 1, price: "Rs. 150" },
        ],
        status: "CONFIRMED",
        guest_name: "Ahmed",
        total: "Rs. 500",
        timestamp: iso(Date.now()),
      },
    }),
  },
  { at: 20800, ev: () => ({ type: "agent_activity", kind: "order", label: "Order #27 created", detail: "Chicken Burger, Blue Lemonade", timestamp: iso(Date.now()) }) },
  { at: 22600, ev: () => ({ type: "order_updated", order: { id: 27, items: [{ name: "Chicken Burger", quantity: 1 }, { name: "Blue Lemonade", quantity: 1 }], status: "PREPARING", guest_name: "Ahmed", total: "Rs. 500", estimated_ready_at: iso(Date.now() + 36_000) } }) },
  { at: 22800, ev: () => ({ type: "agent_activity", kind: "order", label: "Order #27 updated", detail: "preparing", timestamp: iso(Date.now()) }) },

  { at: 24800, step: 5, ev: () => ({ type: "visitor_identified", name: "Ahmed", returning: true, visits: 3, favorite_item: "Blue Lemonade", last_order: "Chicken Burger" }) },
  { at: 25000, ev: () => ({ type: "agent_activity", kind: "visitor", label: "Visitor identified", detail: "Ahmed · visit 3", timestamp: iso(Date.now()) }) },
  { at: 26400, ev: () => ({ type: "memory_updated", name: "Ahmed", visits: 3, favorite_item: "Blue Lemonade", last_order: "Chicken Burger", last_seen: iso(Date.now()), returning: true }) },
  { at: 26600, ev: () => ({ type: "agent_activity", kind: "memory", label: "Memory updated", detail: "Ahmed: new favourite, Blue Lemonade", timestamp: iso(Date.now()) }) },

  { at: 28500, step: 6, ev: () => ({ type: "agent_state_changed", state: "GREETING" }) },
  { at: 28700, ev: () => ({ type: "speech_transcript", role: "agent", text: "Welcome back, Ahmed! That Blue Lemonade is one of your favourites.", final: true }) },
  { at: 33000, ev: () => ({ type: "recommendation", item: "Loaded Fries", reason: "Guests often pair them with the Chicken Burger" }) },
  { at: 33200, ev: () => ({ type: "agent_activity", kind: "speech", label: "Recommended: Loaded Fries", timestamp: iso(Date.now()) }) },

  { at: 35000, step: 7, ev: () => ({ type: "agent_state_changed", state: "IDLE" }) },
  { at: 59000, ev: () => ({ type: "order_ready", order_id: 27, customer_name: "Ahmed" }) },
  { at: 59200, ev: () => ({ type: "agent_activity", kind: "order", label: "Order #27 ready", detail: "ready", timestamp: iso(Date.now()) }) },
  { at: 59800, ev: () => ({ type: "agent_state_changed", state: "ANNOUNCING" }) },
  { at: 60000, ev: () => ({ type: "speech_transcript", role: "agent", text: "Ahmed, your order #27 is ready. Enjoy!", final: true }) },
  { at: 64000, ev: () => ({ type: "@demo_step", step: DEMO_STEPS.length }) },
  // Visitor walks away — THE HOST returns to idle so the menu carousel resumes.
  { at: 66000, ev: () => ({ type: "person_left", person_id: "p-1" }) },
  { at: 66200, ev: () => ({ type: "vision_update", present: false, people: 0, objects: [] }) },
  { at: 66500, ev: () => ({ type: "agent_state_changed", state: "IDLE" }) },
];

let timers: ReturnType<typeof setTimeout>[] = [];

function seed() {
  const now = Date.now();
  agentStore.dispatch({
    type: "@hydrate",
    snapshot: {
      mode: "demo",
      state: "idle",
      lastAgentState: "IDLE",
      opMode: { mode: "ONLINE" },
      caption: null,
      transcript: [],
      present: false,
      people: 0,
      objects: [],
      focus: null,
      lastError: null,
      tokenError: null,
      recommendation: null,
      orderReady: null,
      system: { backend: "online", ai_agent: "online", database: "online", web_search: "online", camera: "online", microphone: "online", speaker: "online", internet: "online" },
      visitors: [
        { name: "Ayesha", visits: 1, last_seen: iso(now - 6 * min), returning: false, last_order: "Club Sandwich" },
        { name: "Usman", visits: 2, last_seen: iso(now - 13 * min), returning: true, last_order: "Chicken Burger" },
        { name: "Sara", visits: 1, last_seen: iso(now - 24 * min), returning: false, last_order: "Blue Lemonade" },
      ],
      orders: [
        {
          id: 26,
          items: [
            { name: "Club Sandwich", quantity: 1 },
            { name: "Strawberry Milkshake", quantity: 1 },
          ],
          status: "PREPARING",
          guest_name: "Ayesha",
          total: "Rs. 900",
          timestamp: iso(now - 5 * min),
          estimated_ready_at: iso(now + 3 * min),
        },
        { id: 25, items: [{ name: "Chicken Burger", quantity: 1 }], status: "COLLECTED", guest_name: "Usman", total: "Rs. 650", timestamp: iso(now - 14 * min) },
        { id: 24, items: [{ name: "Blue Lemonade", quantity: 2 }], status: "COLLECTED", guest_name: "Sara", total: "Rs. 300", timestamp: iso(now - 25 * min) },
      ],
      memory: [
        { id: "m-ahmed", name: "Ahmed", visits: 3, favorite_item: "Chicken Burger", last_order: "Chicken Burger", last_seen: iso(now - 2 * 24 * 60 * min), returning: true },
        { id: "m-usman", name: "Usman", visits: 2, favorite_item: null, last_order: "Chicken Burger", last_seen: iso(now - 13 * min), returning: true },
      ],
      activity: [],
      analytics: null,
      menu: [],
    },
  });
}

export function startDemo() {
  stopDemo(false);
  pauseLiveForDemo();
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

export function stopDemo(resume = true) {
  timers.forEach(clearTimeout);
  timers = [];
  if (resume) {
    // Clear all demo content and reload live data.
    agentStore.dispatch({ type: "@reset" });
    agentStore.dispatch({ type: "@mode", mode: "live" });
    resumeLiveAfterDemo();
  }
}
