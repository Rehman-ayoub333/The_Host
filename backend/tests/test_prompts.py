from datetime import datetime

import config
import prompts


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
    # 21 Part A spells out what a clear yes sounds like, in both languages.
    assert (
        'Only call confirm_order after a clear yes ("yes", "haan", "ji", "confirm", '
        '"go ahead").' in text
    )
    # A confirmed order is final: a later request is a new, separate order
    # (09 section 15, reworded by 21 Part A).
    assert (
        "Once confirmed, an order is final. Anything more is a new, separate order "
        'with only the new items; call it "a new order", never "adding to" the '
        "confirmed one." in text
    )
    assert (
        "To change a confirmed order, offer to cancel it and build a new one." in text
    )
    assert "You do not recognise anyone by their face." in text
    for tool_name in (
        "check_item_availability",
        "recommend_item",
        "build_order",
        "confirm_order",
        "cancel_order",
        "get_order_status",
        "report_feedback",
        "remember_visitor",
        "signal_confirmation_request",
        "get_business_info",
        "request_operator_help",
        "web_search",
    ):
        assert tool_name in text


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
