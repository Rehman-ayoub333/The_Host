"""Phase 7t: an operator's note is never acknowledged aloud (16 §2zt item 3(b)).

Rehman sent "Wrap up politely." and THE HOST told the guest "Okay, I will wrap
up". The note goes to Gemini as a user turn, so the model answers the turn it
was handed. `21` Part A is firmer about it now; this is the layer that does not
depend on the model reading it.

Nothing here is a real conversation: every line is written in the test and the
double keeps it in memory.
"""

import asyncio
import logging

import pytest

import doubles
import note_guard
import prompts


ACK = "Okay, I will wrap up and send them on their way."
CLEAN = "Your Zinger Burger will be about six minutes, Rehman."


# ------------------------------------------------- the words, as a pure function


@pytest.mark.parametrize(
    "line",
    [
        "Okay, I will wrap up.",
        "Ok — one moment.",
        "Sure, anything else?",
        "Certainly, Sir.",
        "Alright, let me do that.",
        "Right away, Sir.",
    ],
)
def test_an_acknowledgement_in_the_first_four_words_is_a_violation(line):
    print(line, "->", note_guard.describe(line))
    assert note_guard.violation(line) == "opener"


@pytest.mark.parametrize(
    "line",
    [
        "I have noted that for you.",
        "Understood, Sir.",
        "Got it, Rehman.",
        "Will do.",
        "I will now take your order properly.",
        "I'll now be quicker about it.",
        "As instructed, let me wrap this up.",
        "The team's note says to wrap up.",
        "Following the operator's instruction now.",
        "That came from the dashboard just now.",
    ],
)
def test_naming_the_note_in_the_first_fifteen_words_is_a_violation(line):
    print(line, "->", note_guard.describe(line))
    assert note_guard.violation(line) in ("opener", "mention")


@pytest.mark.parametrize(
    "line",
    [
        CLEAN,
        "Welcome, Dr. Rauf-i-Azam.",
        "That's our crispy one — would you like a drink with it?",
        "Thank you for visiting Bite & Pour.",
        # The window is why these pass: an ordinary reply that happens to use
        # one of the words well past the opening is not an acknowledgement.
        "Your two Fire Burgers and one Blue Citrus Lemonade come to 1,150 "
        "rupees, and the kitchen will have it ready in about eight minutes, noted "
        "under your name.",
    ],
)
def test_an_ordinary_reply_is_not_a_violation(line):
    print(line, "->", note_guard.describe(line))
    assert note_guard.violation(line) is None


def test_an_empty_line_is_never_a_violation():
    assert note_guard.violation("") is None


def test_the_word_lists_are_the_ones_the_section_gives():
    assert note_guard.OPENERS == {"okay", "ok", "sure", "certainly", "alright"}
    assert note_guard.OPENER_PHRASES == ("right away",)
    assert note_guard.MENTIONS == {
        "note",
        "notes",
        "instruction",
        "instructions",
        "operator",
        "dashboard",
        "understood",
        "noted",
    }
    assert note_guard.MENTION_PHRASES == (
        "got it",
        "will do",
        "i will now",
        "i'll now",
        "as instructed",
    )
    assert note_guard.OPENER_WINDOW == 4
    assert note_guard.MENTION_WINDOW == 15


def test_a_curly_apostrophe_reads_the_same_as_a_straight_one():
    """The model writes both, and "I'll now" is on the list once."""
    assert note_guard.violation("I’ll now get that for you.") == "mention"


# --------------------------------------------- the session's side of the guard


def agent_turn(session, line, audio=b"\x01\x02"):
    """One output-transcription fragment, with audio, as the API sends it."""
    asyncio.run(
        session._handle_message(doubles.message(doubles.content(agent=line, audio=audio)))
    )


def send_note(session, text="Wrap up politely."):
    """The note, through the path main.py uses, which is what arms the guard."""
    asyncio.run(
        session._send_injection("note", prompts.OPERATOR_NOTE_TEMPLATE.format(text=text))
    )


def test_an_acknowledged_note_is_interrupted_and_asked_for_again(caplog):
    """§2zt item 3(b): the first violation of the turn gets the full treatment."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    send_note(session)
    assert session.note_guard_armed is True
    before = list(session.session.inputs)

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, ACK)

    sent = [event.get("type") for event in ws.sent]
    print("to the page:", sent)
    print("to Gemini:", session.session.inputs[len(before):])
    # The room stops hearing the acknowledgement at once.
    assert "interrupted" in sent
    # And THE HOST is asked for the guest's answer on its own, in the
    # section's exact words.
    assert session.session.inputs[len(before):] == [
        {"text": prompts.NOTE_GUARD_PROMPT}
    ]
    assert session.drop_turn_audio is True
    # The acknowledgement does not stay on the TV either.
    assert session.transcripts["agent"] == ""

    messages = [record.getMessage() for record in caplog.records]
    for line in messages:
        print("log:", line)
    assert f"note guard session {session.ctx['session_id']}" in messages
    # 12 section 1: neither the note nor the line reaches the log.
    joined = "\n".join(messages)
    for word in ("Okay", "wrap up", "politely", "Wrap"):
        assert word not in joined
    doubles.validate(ws)


def test_a_normal_reply_after_a_note_is_left_completely_alone():
    """The guard must not cost a guest an ordinary answer."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    send_note(session)
    before = list(session.session.inputs)

    agent_turn(session, CLEAN)

    sent = [event.get("type") for event in ws.sent]
    print("to the page:", sent)
    assert "interrupted" not in sent
    assert session.session.inputs[len(before):] == []
    assert session.drop_turn_audio is False
    assert session.transcripts["agent"] == CLEAN
    # The audio went out: a clean turn is heard in full.
    assert ws.binary
    doubles.validate(ws)


def test_the_same_words_in_a_turn_that_follows_no_note_are_left_alone(caplog):
    """The guard is armed by a note and by nothing else, so an announcement --
    which is meant to be spoken -- and an ordinary turn both pass."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    assert session.note_guard_armed is False

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, ACK)
        # An announcement arms nothing either (§2zt item 3(b)).
        asyncio.run(
            session._send_injection(
                "announcement",
                prompts.OPERATOR_ANNOUNCEMENT_TEMPLATE.format(text="Only 5 left!"),
            )
        )
        assert session.note_guard_armed is False
        agent_turn(session, ACK)

    sent = [event.get("type") for event in ws.sent]
    print("to the page:", sent)
    assert "interrupted" not in sent
    messages = [record.getMessage() for record in caplog.records]
    assert not [line for line in messages if line.startswith("note guard")]
    assert session.drop_turn_audio is False


def test_a_second_violation_in_the_same_turn_is_silent(caplog):
    """Telling the model again mid-turn is what would turn one bad answer into
    a loop, so the rest of the turn is dropped without a word."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    send_note(session)
    before = len(session.session.inputs)

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, ACK)
        asked_once = list(session.session.inputs)
        interrupts_once = len([e for e in ws.sent if e.get("type") == "interrupted"])
        # Still the same turn, still acknowledging.
        agent_turn(session, "Understood, I will do that now.")

    interrupts_after = len([e for e in ws.sent if e.get("type") == "interrupted"])
    print("interrupts after one / two:", interrupts_once, interrupts_after)
    print("asked:", session.session.inputs[before:])
    assert interrupts_after == interrupts_once
    assert session.session.inputs == asked_once
    assert session.note_guard_hits == 2
    # One log line for the turn, not two.
    guard_lines = [
        line
        for line in (record.getMessage() for record in caplog.records)
        if line.startswith("note guard")
    ]
    assert len(guard_lines) == 1
    # And the audio of the second acknowledgement goes nowhere.
    assert session.drop_turn_audio is True


def test_the_guard_watches_the_first_turn_after_the_note_and_no_further():
    """A note must not cast a shadow over the rest of the conversation."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    send_note(session)

    agent_turn(session, CLEAN)
    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("armed after the turn ended:", session.note_guard_armed)
    assert session.note_guard_armed is False

    before = list(session.session.inputs)
    agent_turn(session, ACK)
    assert session.session.inputs[len(before):] == []
    assert session.drop_turn_audio is False


def test_the_prompt_is_the_section_s_exact_words():
    assert prompts.NOTE_GUARD_PROMPT == (
        "[System note — not from the guest. Do not acknowledge the note or say "
        "what you will do. Say only your next words to the guest, or nothing if "
        "the guest has not spoken.]"
    )
