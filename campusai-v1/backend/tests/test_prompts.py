from datetime import datetime

import config
import prompts


def test_system_instruction_names_the_host_and_the_stall_with_no_braces_left():
    text = prompts.build_system_instruction(datetime(2026, 10, 10, 18, 42))

    assert text.startswith("You are THE HOST, the AI host for Bite & Pour, a food and drink stall.")
    assert "Current date and time at the stall: Saturday 10 October 2026, 18:42." in text
    assert "{" not in text and "}" not in text
    assert config.AGENT_NAME == "THE HOST"
    assert config.STALL_NAME == "Bite & Pour"


def test_the_system_instruction_covers_the_two_step_order_rule():
    text = prompts.build_system_instruction(datetime(2026, 10, 10, 18, 42))

    assert "ORDERS: TWO STEPS" in text
    assert "Only call confirm_order after a clear yes." in text
    # A confirmed order is final: a later request is a new, separate order (09 section 15).
    assert (
        "Once an order is confirmed it is final: anything the guest asks for after "
        'that is a new, separate order (call it a new order, never "adding to" the '
        "confirmed one), so call build_order with only the new items, never items "
        "from an order that is already confirmed." in text
    )
    assert (
        "If they want to change a confirmed order, offer to cancel it (cancel_order) "
        "and put together a new one." in text
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


def test_the_three_prompt_constants_are_plain_formatted_strings():
    for constant in (prompts.opening_instruction("presence"), prompts.VISION_PROMPT):
        assert isinstance(constant, str)
        assert "{" not in constant and "}" not in constant

    assert "Bite & Pour" in prompts.opening_instruction("presence")
    # 2m item 4: the lines are formatted strings too, with nothing left to fill.
    for line in prompts.GREETING_LINES:
        assert "{" not in line and "}" not in line
    assert "Do not comment on any person's appearance." in prompts.VISION_PROMPT
