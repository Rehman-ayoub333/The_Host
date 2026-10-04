/**
 * Bite & Pour menu — owned by the FRONTEND, not the AI.
 *
 * The SMD display cycles these items while NEXA is idle
 * (IDLE → MENU → MENU → MENU). The agent never generates or
 * narrates the menu; it only references items when taking orders.
 *
 * Placeholder items/prices — replace with the real menu.
 */
export interface MenuItem {
  name: string;
  category: string;
  description: string;
  price: string;
  signature?: boolean;
}

export const MENU_ITEMS: MenuItem[] = [
  {
    name: "Chicken Burger",
    category: "Burgers",
    description: "Crispy · Juicy · Signature",
    price: "Rs 350",
    signature: true,
  },
  {
    name: "Blue Lemonade",
    category: "Drinks",
    description: "Cold, bright and house-made",
    price: "Rs 150",
  },
  {
    name: "Loaded Fries",
    category: "Snacks",
    description: "Golden fries, signature sauce",
    price: "Rs 250",
  },
  {
    name: "Pasta Bowl",
    category: "Mains",
    description: "Creamy, warm, made to order",
    price: "Rs 450",
  },
  {
    name: "Chocolate Shake",
    category: "Shakes",
    description: "Thick, rich, ice-cold",
    price: "Rs 300",
  },
];
