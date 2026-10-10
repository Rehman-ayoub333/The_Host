# Roadmap

- [x] Restyle the shared palette and state visuals in black, champagne gold, and ivory.
- [x] Rework dashboard hierarchy, navigation, and public display while retaining agent/demo behavior.
- [x] Verify all screens, demo sync, and responsive presentation; complete page metadata.
- [x] Frontend-owned idle menu carousel on the SMD display (IDLE → MENU → MENU → MENU), never AI-generated.
- [x] Rename NEXA → THE HOST everywhere (folder, keys, channel, speaker value, docs).
- [x] Connect to the real THE HOST backend: one agent link + operator token, /ws/events sockets (dashboard/smd), new event set, REST endpoints, operator order controls, menu sold-out toggles.
- [x] Remove sample data from live mode; demo-only data with DEMO DATA badges; demo order step requires guest confirmation.
- [x] Public display: own role=smd socket, resting screen when not ONLINE, order-ready voice announcement, menu from GET /api/menu only.
- [ ] Verify against the real backend once it is running (token, events, order controls).
