/**
 * Bite & Pour menu — owned by the FRONTEND, not the AI.
 *
 * The SMD display cycles these items while THE HOST is idle
 * (IDLE → MENU → MENU → MENU). The agent never generates or
 * narrates the menu; it only references items when taking orders.
 *
 * TEMPORARY placeholder items/prices — replace with the real menu.
 */
export interface MenuItem {
  name: string;
  category: string;
  description: string;
  price: string;
  signature?: boolean;
}

export const MENU_ITEMS: MenuItem[] = [
  { name: "Chicken Burger", category: "Burgers", description: "Crispy · Juicy · Signature", price: "Rs 350", signature: true },
  { name: "Zinger Burger", category: "Burgers", description: "Crunchy fillet, spicy mayo", price: "Rs 400" },
  { name: "Beef Burger", category: "Burgers", description: "Flame-grilled, smoky glaze", price: "Rs 450" },
  { name: "Club Sandwich", category: "Mains", description: "Triple-layered, toasted golden", price: "Rs 380" },
  { name: "Pasta Bowl", category: "Mains", description: "Creamy, warm, made to order", price: "Rs 450" },
  { name: "Loaded Fries", category: "Snacks", description: "Golden fries, signature sauce", price: "Rs 250" },
  { name: "Chicken Wings", category: "Snacks", description: "Tossed in our house glaze", price: "Rs 320" },
  { name: "Blue Lemonade", category: "Drinks", description: "Cold, bright and house-made", price: "Rs 150" },
  { name: "Mint Margarita", category: "Drinks", description: "Fresh mint over crushed ice", price: "Rs 180" },
  { name: "Chocolate Shake", category: "Shakes", description: "Rich cocoa, whipped top", price: "Rs 280" },
  { name: "Strawberry Milkshake", category: "Shakes", description: "Thick, rich, ice-cold", price: "Rs 300" },
];
