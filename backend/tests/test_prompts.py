from datetime import datetime

import config
import prompts
import tools


def test_system_instruction_names_the_host_and_the_stall_with_no_braces_left():
    text = prompts.build_system_instruction(datetime(2026, 10, 10, 18, 42))

    assert text.startswith(
        "You are THE HOST, the AI host of Bite & Pour, a food and drink stall at "
        "the GCUF Business Gala."
    )
    assert "Current date and time at the stall: Saturday 10 October 2026, 18:42." in text
    assert "{" not in text and "}" not in text
    assert config.AGENT_NAME == "THE HOST"
    assert config.STALL_NAME == "Bite & Pour"


def test_the_system_instruction_covers_the_two_step_order_rule():
    text = prompts.build_system_instruction(datetime(2026, 10, 10, 18, 42))

    assert "ORDERS: TWO STEPS" in text
    # 21 Part A spells out what a clear yes sounds like, in both languages, and
    # 16 section 2zb item 10 adds the wait and the same-turn ban.
    assert (
        "Then ask if you should confirm it, and stop talking: wait for the guest's "
        "answer." in text
    )
    assert "Never call confirm_order in the same turn as the question." in text
    assert (
        'Only call confirm_order after the guest\'s own clear yes ("yes", "haan", '
        '"ji", "confirm", "go ahead").' in text
    )
    # A confirmed order is final: adding is a new, separate order
    # (09 section 15, reworded again by 16 section 2zc item 2(d)).
    assert (
        "Once confirmed, an order is final. To add something, take a new, separate "
        'order with only the new items; call it "a new order", never "adding to" '
        "the confirmed one." in text
    )
    # 16 section 2zc: removing, changing or cancelling is allowed by voice only
    # while the kitchen has not started, the guest's yes comes first, and a
    # change is new-first so the guest is never left with nothing.
    assert (
        "To remove an item from a confirmed order, change it, or cancel it: first "
        "call get_order_status for that order. You may change or cancel it only "
        "while it is confirmed and queued (the kitchen has not started)." in text
    )
    assert (
        'To cancel it: ask "Shall I cancel order number" and the number, then wait '
        "for the guest's yes, and only then call cancel_order." in text
    )
    assert (
        "After the guest's yes, call confirm_order for the new order first, then "
        "cancel_order for the old one, and give the new order number." in text
    )
    assert (
        "If the order is being prepared, is ready or has been collected, do not "
        "cancel or change it: say the kitchen has already started on it, and call "
        "request_operator_help with the order number and what the guest wants." in text
    )
    assert "You do not recognise anyone by their face." in text
    # Every tool the prompt asks for by name. 16 section 2za item 2 took
    # signal_confirmation_request out of the order tool list and the ORDERS and
    # FEEDBACK rules, so the prompt no longer names it: it stays declared in
    # tools.py (thirteen tools) and is asserted absent here and in
    # test_always_ready.test_the_order_and_feedback_rules_no_longer_ask_for_the_signal.
    for tool_name in (
        "check_item_availability",
        "recommend_item",
        "build_order",
        "confirm_order",
        "cancel_order",
        "get_order_status",
        "report_feedback",
        "remember_visitor",
        "get_business_info",
        "request_operator_help",
        "web_search",
        "look_at_camera",
    ):
        assert tool_name in text
    assert "signal_confirmation_request" not in text
    assert len(tools.TOOL_FUNCTIONS) == 13
    assert "signal_confirmation_request" in tools.TOOL_FUNCTIONS


def test_the_speak_first_rule_is_not_in_the_prompt():
    """16 section 2s item 3's gate, measured against the real API on 22 Oct 2026.

    The rule was added, compared old against new over the six turns item 3
    lists, and removed because the gate it sets was not met: 3 of 6 new-prompt
    turns spoke before the tool, and the gate needs at least 5 of 6. (Order
    outcomes were correct in both passes, which is the gate's other half.) The
    rule is gone; the banned-filler list it sat beside stays, as item 3 says.
    """
    text = prompts.build_system_instruction(datetime(2026, 10, 10, 18, 42))

    assert "first say a very short natural acknowledgement" not in text
    assert "Sure, one moment." not in text
    assert "Let me check that." not in text
    # What item 3 said must survive either outcome.
    assert (
        "Never use filler such as 'Great question', 'Absolutely!', 'I can "
        "definitely help with that', 'How can I assist you today?', 'As an AI' "
        "or 'I'm just an AI'." in text
    )
    # The instruction that was already there to cover the wait is untouched:
    # it asks for a short "I am checking" rather than a scripted filler.
    assert (
        "Never state a result before the tool has returned it; while you wait, "
        "say briefly that you are checking." in text
    )


def test_the_three_prompt_constants_are_plain_formatted_strings():
    for constant in (prompts.opening_instruction("presence"), prompts.VISION_PROMPT):
        assert isinstance(constant, str)
        assert "{" not in constant and "}" not in constant

    assert "Bite & Pour" in prompts.opening_instruction("presence")
    # 2m item 4: the lines are formatted strings too, with nothing left to fill.
    for line in prompts.GREETING_LINES:
        assert "{" not in line and "}" not in line
    assert "Do not comment on any person's appearance." in prompts.VISION_PROMPT
