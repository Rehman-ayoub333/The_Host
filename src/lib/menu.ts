/**
 * Bite & Pour menu — owned by the FRONTEND, served by the real backend.
 *
 * The SMD display's idle carousel loads GET /api/menu (no token) once on
 * start and on every reconnect, shows only available items, and hides
 * items the moment a menu_updated event marks them unavailable.
 * If the backend cannot be reached the display shows its calm brand
 * screen — never a stale or sample menu.
 */
export type { MenuItem } from "./agent/types";
