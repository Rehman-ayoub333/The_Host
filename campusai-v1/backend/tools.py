import contextvars
import json
import logging

import httpx

import config
import data
import event_bus


log = logging.getLogger(__name__)

# 09 section 1: the per-session context. live_session calls SESSION_CTX.set(self.ctx)
# immediately before every asyncio.to_thread(...) so the worker thread sees the same
# dict object. Tests must set their own dict first; the empty default is shared and
# must never be mutated.
SESSION_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("session_ctx", default={})


def _ctx() -> dict:
    return SESSION_CTX.get()


def _pub(event: dict) -> None:
    event["session_id"] = _ctx().get("session_id")
    event_bus.publish_threadsafe(event)


def _owns_order(order) -> bool:
    c = _ctx()
    if order.get("session_id") and order["session_id"] == c.get("session_id"):
        return True
    name = (c.get("visitor_name") or "").strip().lower()
    return bool(name and (order.get("guest_name") or "").strip().lower() == name)


def _finish(tool: str, args: dict, result: dict) -> dict:
    data.log_action(tool, args, result)
    return result


def check_item_availability(item=None, category=None) -> dict:
    args = {"item": item, "category": category}
    try:
        rows = data.get_menu(
            item=str(item).strip() if item else None,
            category=str(category).strip() if category else None,
        )
        items = [
            {
                "name": row["name"],
                "category": row["category"],
                "price": row["price"],
                "description": row["description"],
                "available": bool(row["available"]),
            }
            for row in rows[:20]
        ]
        return _finish(
            "check_item_availability",
            args,
            {"source": "menu", "total": len(rows), "items": items},
        )
    except Exception:
        log.exception("check_item_availability failed")
        return _finish(
            "check_item_availability",
            args,
            {"source": "menu", "error": "I couldn't check the menu right now."},
        )


def recommend_item(item, reason) -> dict:
    try:
        row = data.get_menu_item(str(item or "").strip())
        if row is None:
            return {"error": "That item isn't on the menu."}
        if not row["available"]:
            return {"error": "That item isn't available right now."}
        reason = " ".join(str(reason or "").split())[:200]
        _pub({"type": "recommendation", "item": row["name"], "reason": reason})
        return {"item": row["name"], "price": row["price"], "reason": reason}
    except Exception:
        log.exception("recommend_item failed")
        return {"error": "I couldn't do that right now."}


def build_order(items, guest_name=None) -> dict:
    args = {"items": items, "guest_name": guest_name}
    try:
        c = _ctx()
        validated = []
        for entry in (items or []):
            name = str((entry or {}).get("name", "")).strip()
            try:
                quantity = max(1, min(20, int((entry or {}).get("quantity", 1))))
            except (TypeError, ValueError):
                quantity = 1
            row = data.get_menu_item(name)
            if row is None:
                return _finish(
                    "build_order",
                    args,
                    {"source": "order", "error": f"'{name}' isn't on the menu."},
                )
            if not row["available"]:
                return _finish(
                    "build_order",
                    args,
                    {"source": "order", "error": f"'{row['name']}' isn't available right now."},
                )
            validated.append(
                {"name": row["name"], "quantity": quantity, "price": row["price"]}
            )
        if not validated:
            return _finish(
                "build_order",
                args,
                {"source": "order", "error": "I didn't catch any items."},
            )
        who = (str(guest_name).strip()[:60] if guest_name else None) or c.get("visitor_name")
        result = data.create_order_draft(validated, who, c.get("session_id"))
        c["pending_order_id"] = result["order_id"]
        order = data.get_order(result["order_id"])
        if result["action"] == "created":
            _pub({"type": "order_created", "order": data.order_view(order)})
        elif result["action"] == "updated":
            _pub({"type": "order_updated", "order": data.order_view(order)})
        return _finish(
            "build_order",
            args,
            {
                "source": "order",
                "order_id": result["order_id"],
                "items": validated,
                "total": data.compute_total(validated),
                "status": "PENDING_CONFIRMATION",
            },
        )
    except Exception:
        log.exception("build_order failed")
        return _finish(
            "build_order",
            args,
            {"source": "order", "error": "I couldn't put that order together."},
        )


def confirm_order(order_id) -> dict:
    args = {"order_id": order_id}
    try:
        try:
            oid = int(float(order_id))
        except (TypeError, ValueError):
            return _finish(
                "confirm_order",
                args,
                {"source": "order", "error": "I couldn't understand that order number."},
            )
        order = data.get_order(oid)
        if order is None or not _owns_order(order):
            return _finish(
                "confirm_order",
                args,
                {"source": "order", "error": "I don't have an order to confirm."},
            )
        if order["status"] == "CANCELLED" and order.get("cancel_reason") == "expired":
            return _finish(
                "confirm_order",
                args,
                {
                    "source": "order",
                    "error": "That order expired before it was confirmed. "
                             "Shall I put it together again?",
                },
            )
        if order["status"] != "PENDING_CONFIRMATION":
            return _finish(
                "confirm_order",
                args,
                {"source": "order", "error": "That order isn't waiting on confirmation."},
            )
        result = data.update_order_status(oid, "CONFIRMED")
        if not result["ok"]:
            return _finish(
                "confirm_order",
                args,
                {"source": "order", "error": "I couldn't confirm that."},
            )
        order = result["order"]
        c = _ctx()
        if c.get("pending_order_id") == oid:
            c["pending_order_id"] = None
        _pub({"type": "order_updated", "order": data.order_view(order)})
        if order.get("guest_name"):
            profile = data.refresh_visitor_after_order(order)
            if profile:
                _pub(data.memory_event(profile))
        return _finish(
            "confirm_order",
            args,
            {
                "source": "order",
                "order_id": oid,
                "status": "CONFIRMED",
                "items": order["items"],
                "total": data.compute_total(order["items"]),
            },
        )
    except Exception:
        log.exception("confirm_order failed")
        return _finish(
            "confirm_order",
            args,
            {"source": "order", "error": "I couldn't confirm that."},
        )


def cancel_order(order_id, reason=None) -> dict:
    args = {"order_id": order_id, "reason": reason}
    try:
        try:
            oid = int(float(order_id))
        except (TypeError, ValueError):
            return _finish(
                "cancel_order",
                args,
                {"source": "order", "error": "I couldn't understand that order number."},
            )
        order = data.get_order(oid)
        if order is None or not _owns_order(order):
            return _finish(
                "cancel_order",
                args,
                {"source": "order", "error": "I couldn't find that order."},
            )
        if order["status"] not in ("PENDING_CONFIRMATION", "CONFIRMED", "PREPARING"):
            return _finish(
                "cancel_order",
                args,
                {"source": "order", "error": "That order can't be cancelled here any more."},
            )
        result = data.update_order_status(
            oid, "CANCELLED", reason=" ".join(str(reason or "").split())[:120]
        )
        if not result["ok"]:
            return _finish(
                "cancel_order",
                args,
                {"source": "order", "error": "I couldn't cancel that."},
            )
        c = _ctx()
        if c.get("pending_order_id") == oid:
            c["pending_order_id"] = None
        _pub({"type": "order_updated", "order": data.order_view(result["order"])})
        return _finish(
            "cancel_order",
            args,
            {"source": "order", "order_id": oid, "status": "CANCELLED"},
        )
    except Exception:
        log.exception("cancel_order failed")
        return _finish(
            "cancel_order",
            args,
            {"source": "order", "error": "I couldn't cancel that."},
        )


def get_order_status(order_id=None) -> dict:
    args = {"order_id": order_id}
    try:
        c = _ctx()
        if order_id in (None, ""):
            found = data.find_orders_for(c.get("session_id"), c.get("visitor_name"))[:3]
        else:
            try:
                oid = int(float(order_id))
            except (TypeError, ValueError):
                return _finish(
                    "get_order_status",
                    args,
                    {"source": "order", "error": "I couldn't understand that order number."},
                )
            order = data.get_order(oid)
            found = [order] if (order is not None and _owns_order(order)) else []
        orders = [
            {
                "order_id": order["id"],
                "status": order["status"],
                "items": order["items"],
                "estimated_minutes_left": data.minutes_left(order),
            }
            for order in found
        ]
        return _finish(
            "get_order_status",
            args,
            {"source": "order", "found": bool(orders), "orders": orders},
        )
    except Exception:
        log.exception("get_order_status failed")
        return _finish(
            "get_order_status",
            args,
            {"source": "order", "error": "I couldn't look that up."},
        )


def report_feedback(subject, comment, rating=None) -> dict:
    args = {"subject": subject, "comment": comment, "rating": rating}
    try:
        clean_subject = " ".join(str(subject or "").split())[:80]
        clean_comment = " ".join(str(comment or "").split())[:500]
        if not clean_subject or not clean_comment:
            return _finish(
                "report_feedback",
                args,
                {
                    "source": "order",
                    "error": "I need to know what it's about and what you'd like to say.",
                },
            )
        try:
            score = int(rating)
        except (TypeError, ValueError):
            score = None
        score = score if score is not None and 1 <= score <= 5 else None
        feedback_id = data.create_feedback(
            clean_subject, clean_comment, score, _ctx().get("visitor_name")
        )
        return _finish(
            "report_feedback",
            args,
            {
                "source": "order",
                "feedback_id": feedback_id,
                "subject": clean_subject,
                "rating": score,
            },
        )
    except Exception:
        log.exception("report_feedback failed")
        return _finish(
            "report_feedback",
            args,
            {"source": "order", "error": "I couldn't log that feedback."},
        )


def remember_visitor(name) -> dict:
    args = {"name": name}
    try:
        clean = " ".join(str(name or "").split())[:60]
        if not clean:
            return _finish(
                "remember_visitor",
                args,
                {"source": "order", "error": "I didn't catch a name."},
            )
        c, key = _ctx(), clean.lower()
        # The same name again in this session: do not count another visit.
        already = (c.get("visitor_name") or "").lower() == key
        profile = data.get_visitor(key)
        if profile is None:
            data.create_visitor(key, clean)
            returning = False
        else:
            if not already:
                data.record_visit(key)
            returning = True
        profile = data.get_visitor(key)
        c["visitor_name"] = profile["display_name"]
        # Orders placed this session before a name was given.
        for order in data.attach_guest_name(c.get("session_id"), profile["display_name"]):
            _pub({"type": "order_updated", "order": data.order_view(order)})
            if order["status"] in ("CONFIRMED", "PREPARING", "READY", "COLLECTED"):
                linked = data.refresh_visitor_after_order(order)
                if linked:
                    _pub(data.memory_event(linked))
        # Re-read: favourite and last order may have changed.
        profile = data.get_visitor(key)
        _pub(
            {
                "type": "visitor_identified",
                "name": profile["display_name"],
                "returning": returning,
                "visits": profile["visits"],
                "favorite_item": profile["favorite_item"],
                "last_order": profile["last_order"],
            }
        )
        _pub(data.memory_event(profile))
        return _finish(
            "remember_visitor",
            args,
            {
                "source": "order",
                "returning": returning,
                "name": profile["display_name"],
                "visits": profile["visits"],
                "favorite_item": profile["favorite_item"],
                "last_order": profile["last_order"],
            },
        )
    except Exception:
        log.exception("remember_visitor failed")
        return _finish(
            "remember_visitor",
            args,
            {"source": "order", "error": "I couldn't note that."},
        )


def signal_confirmation_request(summary) -> dict:
    return {"acknowledged": True}


def get_business_info(topic=None) -> dict:
    args = {"topic": topic}
    try:
        rows = data.get_business_info(str(topic).strip() if topic else None)
        return _finish(
            "get_business_info",
            args,
            {
                "source": "menu",
                "found": bool(rows),
                "answers": [
                    {"topic": row["topic"], "answer": row["answer"]} for row in rows[:5]
                ],
            },
        )
    except Exception:
        log.exception("get_business_info failed")
        return _finish(
            "get_business_info",
            args,
            {"source": "menu", "error": "I couldn't look that up."},
        )


def request_operator_help(reason) -> dict:
    args = {"reason": reason}
    try:
        clean = " ".join(str(reason or "").split())[:120] or "Help requested"
        return _finish(
            "request_operator_help",
            args,
            {"source": "order", "acknowledged": True, "reason": clean},
        )
    except Exception:
        log.exception("request_operator_help failed")
        return _finish(
            "request_operator_help",
            args,
            {"source": "order", "error": "I couldn't flag that."},
        )


def web_search(query) -> dict:
    clean_query = " ".join(str(query or "").split())[:200]
    args = {"query": clean_query}
    if not clean_query:
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": clean_query,
                "found": False,
                "summary": "",
                "error": "What should I look up?",
            },
        )
    try:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": clean_query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": "THE-HOST-Stall/1.0"},
            timeout=config.WEB_SEARCH_TIMEOUT_S,
            follow_redirects=True,
        )
        payload = json.loads(response.text)
        summary = (
            payload.get("AbstractText")
            or payload.get("Answer")
            or payload.get("Definition")
            or ""
        ).strip()
        if not summary:
            for item in payload.get("RelatedTopics", []):
                if isinstance(item, dict) and item.get("Text"):
                    summary = item["Text"].strip()
                    break
                for subtopic in (item.get("Topics", []) if isinstance(item, dict) else []):
                    if subtopic.get("Text"):
                        summary = subtopic["Text"].strip()
                        break
                if summary:
                    break
        summary = summary[:500]
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": clean_query,
                "found": bool(summary),
                "summary": summary,
                "url": payload.get("AbstractURL", ""),
            },
        )
    except Exception:
        log.exception("web_search failed")
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": clean_query,
                "found": False,
                "summary": "",
                "error": "Web lookup is unavailable right now.",
            },
        )


TOOL_FUNCTIONS = {
    "check_item_availability": check_item_availability,
    "recommend_item": recommend_item,
    "build_order": build_order,
    "confirm_order": confirm_order,
    "cancel_order": cancel_order,
    "get_order_status": get_order_status,
    "report_feedback": report_feedback,
    "remember_visitor": remember_visitor,
    "signal_confirmation_request": signal_confirmation_request,
    "get_business_info": get_business_info,
    "request_operator_help": request_operator_help,
    "web_search": web_search,
}


def _decl(name, description, props, required=()):
    return {
        "name": name,
        "description": description,
        "behavior": "BLOCKING",
        "parameters": {"type": "object", "properties": props, "required": list(required)},
    }


TOOL_DECLARATIONS = [
    _decl(
        "check_item_availability",
        "Look up the real menu: what is available, prices and descriptions. Provide only what the guest mentioned; omit both fields to list everything.",
        {
            "item": {"type": "string", "description": "Item name or part of it, e.g. 'burger'."},
            "category": {"type": "string", "description": "Category such as 'Mains' or 'Drinks'."},
        },
    ),
    _decl(
        "recommend_item",
        "Call this when you genuinely recommend a specific menu item, with a short real reason. It only highlights the item; it does not place an order.",
        {
            "item": {"type": "string", "description": "The item name exactly as on the menu."},
            "reason": {"type": "string", "description": "One short genuine sentence."},
        },
        ("item", "reason"),
    ),
    _decl(
        "build_order",
        "Put together a draft order as soon as the guest's choice is clear. This does NOT place the order; it must still be confirmed with confirm_order. Calling it again replaces the current draft.",
        {
            "items": {
                "type": "array",
                "description": "Everything in the order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Menu item name."},
                        "quantity": {"type": "integer", "description": "How many, default 1."},
                    },
                    "required": ["name"],
                },
            },
            "guest_name": {
                "type": "string",
                "description": "The guest's name, only if they gave one.",
            },
        },
        ("items",),
    ),
    _decl(
        "confirm_order",
        "Place the draft order for real. Only call this after signal_confirmation_request AND a clear spoken yes from the guest.",
        {
            "order_id": {
                "type": "integer",
                "description": "The order_id returned by build_order.",
            }
        },
        ("order_id",),
    ),
    _decl(
        "cancel_order",
        "Cancel one of this guest's orders (a draft, confirmed, or being prepared). Not possible once it is ready.",
        {
            "order_id": {"type": "integer", "description": "The order number."},
            "reason": {"type": "string", "description": "Short reason, optional."},
        },
        ("order_id",),
    ),
    _decl(
        "get_order_status",
        "Check the status and estimated time of this guest's own orders. Give the order number if the guest knows it; omit it to find their active orders.",
        {"order_id": {"type": "integer", "description": "The order number, if known."}},
    ),
    _decl(
        "report_feedback",
        "Log the guest's feedback about the food, drinks or service. Only call this after signal_confirmation_request and a clear yes.",
        {
            "subject": {
                "type": "string",
                "description": "What it is about, e.g. 'chicken burger' or 'service speed'.",
            },
            "comment": {
                "type": "string",
                "description": "What the guest said, briefly, in their words.",
            },
            "rating": {
                "type": "integer",
                "description": "1 to 5, only if the guest actually gave one.",
            },
        },
        ("subject", "comment"),
    ),
    _decl(
        "remember_visitor",
        "Look up or create a guest profile from the NAME they told you. Never use this on a guess.",
        {"name": {"type": "string", "description": "The name the guest gave."}},
        ("name",),
    ),
    _decl(
        "signal_confirmation_request",
        "Call this immediately before asking the guest to confirm an order or feedback, with a one-sentence summary. It performs no action.",
        {
            "summary": {
                "type": "string",
                "description": "One sentence describing what you are confirming.",
            }
        },
        ("summary",),
    ),
    _decl(
        "get_business_info",
        "Look up facts about the stall itself: opening hours, promotions, what the stall is. Omit topic to list everything.",
        {"topic": {"type": "string", "description": "e.g. 'hours' or 'stall'."}},
    ),
    _decl(
        "request_operator_help",
        "Ask a human on the team to step in, when you genuinely cannot help.",
        {"reason": {"type": "string", "description": "A short reason."}},
        ("reason",),
    ),
    _decl(
        "web_search",
        "Look up general knowledge on the web (definitions, well-known facts). A limited instant-answer lookup that may find nothing. Do not use it for menu, order or stall questions.",
        {"query": {"type": "string", "description": "What to look up."}},
        ("query",),
    ),
]
