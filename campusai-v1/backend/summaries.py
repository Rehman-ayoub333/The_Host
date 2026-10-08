"""Activity feed labels: the only way tool and system activity reaches a frontend.

`activity_for_tool` maps a finished tool call onto the fixed label table in
03 section 4. `emit_activity` is the single helper that both logs the row to
`system_events` and publishes the `agent_activity` event (16 section 2b item 7).
"""

import data
import event_bus


MAX_DETAIL_REASON = 80
MAX_DETAIL_SPEECH = 120


def _order_id(args, result):
    for source in (result, args):
        if isinstance(source, dict) and source.get("order_id") is not None:
            return source["order_id"]
    return None


def _item_names(items) -> str | None:
    names = [
        str((entry or {}).get("name"))
        for entry in items or []
        if (entry or {}).get("name")
    ]
    return ", ".join(names) or None


def activity_for_tool(name: str, args: dict, result: dict) -> dict | None:
    """The 03 section 4 table. None when the table defines no row."""
    args = args or {}
    result = result or {}
    failed = "error" in result

    if name == "signal_confirmation_request":
        return None

    if name == "check_item_availability":
        return None if failed else {"kind": "order", "label": "Checked menu", "detail": None}

    if name == "build_order":
        if failed:
            return {"kind": "order", "label": "Order could not be prepared", "detail": None}
        return {
            "kind": "order",
            "label": f"Order draft #{_order_id(args, result)} prepared",
            "detail": None,
        }

    if name == "confirm_order":
        if failed:
            return {"kind": "order", "label": "Order could not be confirmed", "detail": None}
        return {
            "kind": "order",
            "label": f"Order #{_order_id(args, result)} created",
            "detail": _item_names(result.get("items")),
        }

    if name == "cancel_order":
        return (
            None
            if failed
            else {
                "kind": "order",
                "label": f"Order #{_order_id(args, result)} cancelled",
                "detail": None,
            }
        )

    if name == "get_order_status":
        if failed:
            return None
        orders = result.get("orders") or []
        label = (
            f"Order #{orders[0]['order_id']} checked"
            if len(orders) == 1
            else "Order status checked"
        )
        return {"kind": "order", "label": label, "detail": None}

    if name == "report_feedback":
        return (
            None
            if failed
            else {"kind": "order", "label": "Feedback logged", "detail": result.get("subject")}
        )

    if name == "remember_visitor":
        if failed:
            return None
        if result.get("returning"):
            return {
                "kind": "visitor",
                "label": "Visitor identified",
                "detail": f"{result.get('name')} · visit {result.get('visits')}",
            }
        return {"kind": "visitor", "label": "New visitor noted", "detail": result.get("name")}

    if name == "get_business_info":
        return (
            None
            if failed
            else {"kind": "system", "label": "Checked stall information", "detail": None}
        )

    if name == "web_search":
        return (
            None
            if failed
            else {"kind": "system", "label": "Looked something up online", "detail": None}
        )

    if name == "recommend_item":
        if "error" in result:
            return None
        return {
            "kind": "speech",
            "label": f"Recommended: {result.get('item')}",
            "detail": None,
        }

    if name == "request_operator_help":
        if failed:
            return None
        reason = str(result.get("reason") or args.get("reason") or "")[:MAX_DETAIL_REASON]
        return {"kind": "operator", "label": "Operator help requested", "detail": reason or None}

    return None


def emit_activity(kind: str, label: str, detail=None, session_id=None) -> None:
    """Write the system_events row and publish the agent_activity event."""
    data.log_system_event(
        "agent_activity", "system", {"kind": kind, "label": label, "detail": detail}
    )
    event_bus.publish_threadsafe(
        {
            "type": "agent_activity",
            "kind": kind,
            "label": label,
            "detail": detail,
            "session_id": session_id,
        }
    )


def emit_tool_activity(name: str, args: dict, result: dict, session_id=None) -> dict | None:
    entry = activity_for_tool(name, args, result)
    if entry is not None:
        emit_activity(entry["kind"], entry["label"], entry["detail"], session_id)
    return entry
