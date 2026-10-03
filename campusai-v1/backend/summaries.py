DEFAULT_SOURCE = {
    "query_timetable": "real",
    "check_room_availability": "real",
    "create_complaint": "demo",
    "get_complaint_status": "demo",
    "list_recent_complaints": "demo",
    "web_search": "web",
}


def default_source(tool) -> str:
    return DEFAULT_SOURCE.get(tool, "demo")


def summarize_running(tool, args) -> str:
    if tool == "query_timetable":
        return "Searching the timetable…"
    if tool == "check_room_availability":
        parts = []
        if args.get("room"):
            parts.append(str(args["room"]))
        if args.get("day"):
            parts.append(f"on {args['day']}" if parts else str(args["day"]))
        if args.get("time"):
            parts.append(f"at {args['time']}")
        return f"Checking {' '.join(parts)}…"
    if tool == "create_complaint":
        return "Logging your complaint…"
    if tool == "get_complaint_status":
        return f"Looking up ticket #{args.get('ticket_number')}…"
    if tool == "list_recent_complaints":
        return "Fetching recent complaints…"
    if tool == "web_search":
        return "Looking that up online…"
    return "Working…"


def summarize_done(tool, args, result) -> str:
    if result.get("error"):
        failures = {
            "query_timetable": "Timetable search failed",
            "check_room_availability": "Couldn't check that room",
            "create_complaint": "Couldn't log the complaint",
            "get_complaint_status": "Couldn't look up that ticket",
            "list_recent_complaints": "Couldn't fetch complaints",
            "web_search": "Web lookup failed",
        }
        return failures.get(tool, "Failed")

    if tool == "query_timetable":
        total = result.get("total", 0)
        if total == 0:
            return "No matching classes"
        if total == 1:
            return "1 matching class"
        return f"{total} matching classes"
    if tool == "check_room_availability":
        room = result.get("room", args.get("room"))
        if not result.get("known_room"):
            return f"{room} isn't in the timetable"
        day = result.get("day", args.get("day"))
        time = result.get("time", args.get("time"))
        if result.get("available"):
            return f"{room} is free — {day} {time}"
        summary = f"{room} is booked — {day} {time}"
        class_entry = result.get("class")
        if class_entry and class_entry.get("course"):
            return f"{summary} ({class_entry['course']})"
        if result.get("source") == "demo" and result.get("reason"):
            return f"{summary} (demo: {result['reason']})"
        return summary
    if tool == "create_complaint":
        return f"Ticket #{result.get('ticket_number')} logged — {result.get('issue')} ({result.get('room')})"
    if tool == "get_complaint_status":
        number = result.get("ticket_number", args.get("ticket_number"))
        if result.get("found"):
            record = result.get("record") or {}
            return f"Ticket #{number}: {record.get('status')} — {record.get('issue')}"
        return f"Ticket #{number} not found"
    if tool == "list_recent_complaints":
        total = result.get("total", 0)
        if total == 0:
            return "No complaints logged yet"
        noun = "complaint" if total == 1 else "complaints"
        return f"{total} recent {noun}"
    if tool == "web_search":
        return "Found an answer online" if result.get("found") else "Nothing found online"
    return "Done"