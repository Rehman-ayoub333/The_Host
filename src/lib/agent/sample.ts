/**
 * SAMPLE DATA — temporary placeholder dataset shown while no live agent
 * is connected. Every panel that shows it is labelled "Sample data".
 * Nothing here is real: names, orders and memories are placeholders
 * until the real agent connects (or real data is provided), at which
 * point the sample is cleared automatically.
 *
 * Kept in one file so the real menu/visitors/orders can replace it in
 * a single edit later.
 */
import visionDemo from "@/assets/vision-demo.jpg";
import type { AgentSnapshot, Detection } from "./types";

const min = 60_000;

const SAMPLE_DETECTIONS: Detection[] = [
  { id: "s-d1", label: "Person", confidence: 0.95, box: [0.44, 0.48, 0.13, 0.44], visitorId: "s-ahmed" },
  { id: "s-d2", label: "Person", confidence: 0.91, box: [0.68, 0.44, 0.1, 0.42] },
  { id: "s-d3", label: "Table", confidence: 0.86, box: [0.38, 0.8, 0.16, 0.18] },
  { id: "s-d4", label: "Food stall", confidence: 0.82, box: [0.02, 0.26, 0.3, 0.46] },
];

export function sampleData(now = Date.now()): Partial<AgentSnapshot> {
  return {
    frameUrl: visionDemo,
    detections: SAMPLE_DETECTIONS,
    visitors: [
      { id: "s-ahmed", name: "Ahmed", visits: 5, lastVisit: now - 2 * min, returning: true, favorite: "Chicken Burger", lastOrder: "Chicken Burger" },
      { id: "s-usman", name: "Usman", visits: 3, lastVisit: now - 9 * min, returning: true, lastOrder: "Loaded Fries" },
      { id: "s-ayesha", name: "Ayesha", visits: 1, lastVisit: now - 14 * min, returning: false, lastOrder: "Club Sandwich" },
      { id: "s-sara", name: "Sara", visits: 2, lastVisit: now - 21 * min, returning: true, favorite: "Blue Lemonade", lastOrder: "Blue Lemonade" },
      { id: "s-bilal", name: "Bilal", visits: 1, lastVisit: now - 33 * min, returning: false, lastOrder: "Zinger Burger" },
      { id: "s-hira", name: "Hira", visits: 4, lastVisit: now - 48 * min, returning: true, favorite: "Pasta Bowl", lastOrder: "Pasta Bowl" },
    ],
    orders: [
      {
        id: "s-o-031",
        number: "031",
        customerName: "Hira",
        visitorId: "s-hira",
        items: [
          { name: "Pasta Bowl", qty: 1 },
          { name: "Mint Margarita", qty: 1 },
        ],
        status: "preparing",
        createdAt: now - 2 * min,
        readyAt: now + 6 * min,
        prepSeconds: 8 * 60,
      },
      {
        id: "s-o-030",
        number: "030",
        customerName: "Usman",
        visitorId: "s-usman",
        items: [{ name: "Loaded Fries", qty: 1 }],
        status: "ready",
        createdAt: now - 9 * min,
      },
      {
        id: "s-o-029",
        number: "029",
        customerName: "Sara",
        visitorId: "s-sara",
        items: [{ name: "Blue Lemonade", qty: 2 }],
        status: "completed",
        createdAt: now - 21 * min,
      },
      {
        id: "s-o-028",
        number: "028",
        customerName: "Ayesha",
        visitorId: "s-ayesha",
        items: [
          { name: "Club Sandwich", qty: 1 },
          { name: "Blue Lemonade", qty: 1 },
        ],
        status: "completed",
        createdAt: now - 26 * min,
      },
      {
        id: "s-o-027",
        number: "027",
        customerName: "Ahmed",
        visitorId: "s-ahmed",
        items: [
          { name: "Chicken Burger", qty: 1 },
          { name: "Chocolate Shake", qty: 1 },
        ],
        status: "completed",
        createdAt: now - 40 * min,
      },
    ],
    memory: [
      { id: "s-m-1", visitorId: "s-ahmed", visitorName: "Ahmed", text: "Loves the Chicken Burger — orders it almost every visit", ts: now - 2 * 24 * 60 * min },
      { id: "s-m-2", visitorId: "s-sara", visitorName: "Sara", text: "Always asks for extra lemon in the Blue Lemonade", ts: now - 21 * min },
      { id: "s-m-3", visitorId: "s-hira", visitorName: "Hira", text: "Favourite is the Pasta Bowl — likes it extra spicy", ts: now - 48 * min },
      { id: "s-m-4", visitorId: "s-usman", visitorName: "Usman", text: "Prefers no onions", ts: now - 3 * 24 * 60 * min },
    ],
    transcript: [
      { id: "s-t-1", speaker: "visitor", text: "One Pasta Bowl, please — make it spicy.", ts: now - 3 * min },
      { id: "s-t-2", speaker: "nexa", text: "Of course, Hira. One extra-spicy Pasta Bowl coming right up.", ts: now - 170_000 },
      { id: "s-t-3", speaker: "visitor", text: "And a mint margarita with that.", ts: now - 160_000 },
      { id: "s-t-4", speaker: "nexa", text: "Added. Your order number is 031.", ts: now - 150_000 },
    ],
    activity: [
      { id: "s-a-1", kind: "order", title: "Order #031 created", detail: "Pasta Bowl · Mint Margarita", ts: now - 2 * min },
      { id: "s-a-2", kind: "voice", title: "Responding", detail: "“Of course, Hira. One extra-spicy Pasta Bowl coming right up.”", ts: now - 170_000 },
      { id: "s-a-3", kind: "reasoning", title: "Reasoning", detail: "Matching menu items", ts: now - 3 * min },
      { id: "s-a-4", kind: "audio", title: "Speech detected", ts: now - 180_000 },
      { id: "s-a-5", kind: "vision", title: "Person detected", detail: "95% confidence", ts: now - 210_000 },
      { id: "s-a-6", kind: "order", title: "Order #029 completed", ts: now - 21 * min },
      { id: "s-a-7", kind: "system", title: "camera offline", detail: "No agent connected yet", ts: now - 40 * min },
    ],
    system: { camera: "offline", microphone: "offline", speaker: "offline", agent: "offline", internet: "unknown" },
  };
}
