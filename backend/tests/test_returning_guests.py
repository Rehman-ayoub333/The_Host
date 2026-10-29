"""Phase 7l: build_order remembers the guest too (16 section 2zf item 5).

Rehman's request, in his own words: "when Rehman returns it should appreciate
him." THE HOST only ever learnt a name through `remember_visitor`, and once it
had the name for the order it usually did not bother calling it -- so a guest
who came back twice was greeted as a stranger.

So the name passed to `build_order` goes through the same helper
`remember_visitor` uses, and the draft comes back carrying whether this guest
is returning. A title is a role rather than a guest, and never becomes a
visitor profile.
"""

import pytest

import data
import event_bus
import tools


BURGER = [{"name": "Chicken Burger", "quantity": 1}]
LEMONADE = [{"name": "Blue Lemonade", "quantity": 1}]


def in_session(session_id="second-session"):
    """A second conversation, with no memory of its own."""
    own = {
        "session_id": session_id,
        "visitor_name": None,
        "pending_order_id": None,
        "awaiting_confirmation": False,
    }
    return own, tools.SESSION_CTX.set(own)


def published(kind):
    return [event for event in event_bus.PUBLISHED if event["type"] == kind]


# ---------------------------------------- the draft says who the guest is


def test_a_new_name_is_remembered_and_is_not_returning(ctx):
    result = tools.build_order(BURGER, guest_name="Rehman")

    assert result["visitor"] == {
        "returning": False,
        "visits": 1,
        "favorite_item": None,
    }
    assert data.get_visitor("rehman")["display_name"] == "Rehman"
    assert ctx["visitor_name"] == "Rehman"


def test_a_second_session_with_the_same_name_is_welcomed_back(ctx):
    """E45: the order is placed and paid, then Rehman comes back."""
    first = tools.build_order(BURGER, guest_name="Rehman")
    tools.confirm_order(first["order_id"], payment_method="CASH")

    later, token = in_session()
    try:
        again = tools.build_order(LEMONADE, guest_name="Rehman")
    finally:
        tools.SESSION_CTX.reset(token)

    print("the second visit:", again["visitor"])
    assert again["visitor"]["returning"] is True
    assert again["visitor"]["visits"] == 2
    # Only from what the tool returned: his favourite is the order he placed.
    assert again["visitor"]["favorite_item"] == "Chicken Burger"
    assert later["visitor_name"] == "Rehman"


def test_the_same_name_twice_in_one_conversation_counts_one_visit(ctx):
    """THE HOST rebuilds a draft freely; the guest only walked up once."""
    tools.build_order(BURGER, guest_name="Rehman")
    again = tools.build_order(BURGER + LEMONADE, guest_name="Rehman")
    third = tools.build_order(LEMONADE, guest_name="rehman")

    assert again["visitor"]["visits"] == 1
    assert third["visitor"]["visits"] == 1
    assert data.get_visitor("rehman")["visits"] == 1


def test_remember_visitor_and_build_order_agree_about_the_same_guest(ctx):
    """One helper, so the two can never drift apart.

    `returning` has always meant "a profile already existed", so the second
    time a name is given in one conversation it reads true while the visit
    count stays at one. That is `remember_visitor`'s own behaviour, unchanged
    by 2zf item 5, and `21` Part A's "Welcome a guest only once per
    conversation" is what stops it being said twice.
    """
    noted = tools.remember_visitor("Rehman")
    assert noted["returning"] is False

    drafted = tools.build_order(BURGER, guest_name="Rehman")

    # The same conversation, the same name: still one visit.
    assert noted["visits"] == 1
    assert drafted["visitor"]["visits"] == 1
    assert drafted["visitor"]["returning"] is True
    assert tools.remember_visitor("Rehman")["returning"] is True


def test_a_build_with_no_name_says_nothing_about_a_visitor(ctx):
    result = tools.build_order(BURGER)

    assert "visitor" not in result
    assert ctx["visitor_name"] is None


# -------------------------------------------------- titles are not guests


@pytest.mark.parametrize(
    "title",
    ["Vice Chancellor", "Chief Guest", "Dr. Rauf-i-Azam", "rauf e azam", "chief guest"],
)
def test_a_title_never_becomes_a_visitor(ctx, title):
    result = tools.build_order(BURGER, guest_name=title)

    assert "visitor" not in result
    assert data.get_visitor(title.lower()) is None
    assert ctx["visitor_name"] is None
    # And the name still goes on the order itself.
    assert data.get_order(result["order_id"])["guest_name"] == title


def test_a_title_publishes_no_visitor_event(ctx):
    event_bus.PUBLISHED.clear()

    tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)

    assert published("visitor_identified") == []
    assert published("memory_updated") == []


# ------------------------------------------------- the events it publishes


def test_a_remembered_name_publishes_the_same_two_events_as_the_tool(ctx):
    event_bus.PUBLISHED.clear()

    tools.build_order(BURGER, guest_name="Rehman")

    identified = published("visitor_identified")
    assert len(identified) == 1
    assert identified[0]["name"] == "Rehman"
    assert identified[0]["returning"] is False
    assert identified[0]["session_id"] == ctx["session_id"]
    assert len(published("memory_updated")) == 1


def test_a_returning_guest_is_published_as_returning(ctx):
    tools.build_order(BURGER, guest_name="Rehman")

    later, token = in_session()
    try:
        event_bus.PUBLISHED.clear()
        tools.build_order(LEMONADE, guest_name="Rehman")
        identified = published("visitor_identified")
    finally:
        tools.SESSION_CTX.reset(token)

    assert identified[0]["returning"] is True
    assert identified[0]["visits"] == 2


# --------------------- 2zh item 3(d): announced only when the visitor changes


def test_the_same_name_again_in_one_conversation_announces_nothing(ctx):
    """16 §2zh item 3(d). THE HOST rebuilds a draft whenever the guest changes
    their mind, and passes the same name every time. The guest walked up once,
    so the screens are told once: anything else is the dashboard announcing
    "Rehman" three times for one order.
    """
    tools.build_order(BURGER, guest_name="Rehman")
    event_bus.PUBLISHED.clear()

    tools.build_order(BURGER + LEMONADE, guest_name="Rehman")
    tools.build_order(LEMONADE, guest_name="rehman")

    assert published("visitor_identified") == []
    assert published("memory_updated") == []
    # The name is still on the order and still in this session's context.
    assert ctx["visitor_name"] == "Rehman"


def test_the_first_name_of_the_conversation_is_announced(ctx):
    """The visitor changed: from nobody to Rehman."""
    event_bus.PUBLISHED.clear()

    tools.build_order(BURGER, guest_name="Rehman")

    assert len(published("visitor_identified")) == 1
    assert len(published("memory_updated")) == 1


def test_a_different_name_in_the_same_conversation_is_announced(ctx):
    """Two friends at the mic, or a draft renamed: the visitor really changed."""
    tools.build_order(BURGER, guest_name="Rehman")
    event_bus.PUBLISHED.clear()

    tools.build_order(LEMONADE, guest_name="Sara")

    identified = published("visitor_identified")
    assert len(identified) == 1
    assert identified[0]["name"] == "Sara"
    assert len(published("memory_updated")) == 1


def test_remember_visitor_still_announces_every_time(ctx):
    """16 §2zh item 3(d) names `build_order` only.

    `remember_visitor` is the model saying "this is who I am talking to", which
    is always worth telling the screens, and 2zf item 5 left it unchanged.
    """
    tools.remember_visitor("Rehman")
    event_bus.PUBLISHED.clear()

    tools.remember_visitor("Rehman")

    assert len(published("visitor_identified")) == 1
    assert len(published("memory_updated")) == 1


def test_a_build_after_remember_visitor_announces_nothing_new(ctx):
    """The two share one helper, so the session's visitor is already this one."""
    tools.remember_visitor("Rehman")
    event_bus.PUBLISHED.clear()

    drafted = tools.build_order(BURGER, guest_name="Rehman")

    assert published("visitor_identified") == []
    assert published("memory_updated") == []
    # The draft still carries what `21` Part A may be said out loud from.
    assert drafted["visitor"]["returning"] is True


# ----------------------------------- remember_visitor itself is unchanged


def test_remember_visitor_still_returns_exactly_what_it_did(ctx):
    assert tools.remember_visitor("  Ahmed  ") == {
        "source": "order",
        "returning": False,
        "name": "Ahmed",
        "visits": 1,
        "favorite_item": None,
        "last_order": None,
    }
    assert tools.remember_visitor("   ") == {
        "source": "order",
        "error": "I didn't catch a name.",
    }


def test_remember_visitor_still_attaches_the_name_to_an_unnamed_order(ctx):
    order_id = tools.build_order(BURGER)["order_id"]
    assert data.get_order(order_id)["guest_name"] is None

    tools.remember_visitor("Sara")

    assert data.get_order(order_id)["guest_name"] == "Sara"


def test_build_order_attaches_the_name_to_an_earlier_unnamed_order(ctx):
    """The same helper, so the name reaches the same places."""
    first = tools.build_order(BURGER)["order_id"]
    tools.confirm_order(first, payment_method="CASH")

    tools.build_order(LEMONADE, guest_name="Sara")

    assert data.get_order(first)["guest_name"] == "Sara"
