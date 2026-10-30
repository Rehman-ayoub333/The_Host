"""Phase 7o, 16 section 2zk item 4(b): the language guard, in code.

`21` Part A had forbidden Hindi by name since 24 Oct. On 30 Oct, in front of
the CS faculty, THE HOST answered in Hindi anyway -- in Devanagari -- and in
Spanish and Italian for most of one session. A prompt rule the model does not
follow is not a control, so the backend now reads THE HOST's own output
transcription and stops a turn that is not in English or Urdu.

The lines in these tests are real: the foreign ones are what THE HOST actually
said on 30 Oct (from the STEP 2 diagnosis), and the Roman Urdu ones are from
`21` Part C. Nothing here is written to a log or a file -- the guard logs a
reason and no more (12 section 1), and that is asserted.
"""

import asyncio
import logging

import pytest

import doubles
import language_guard
import prompts


# What THE HOST really said on 30 Oct, from the system_events rows.
SPANISH = "Hola, ¿qué le gustaría ordenar hoy?"
ITALIAN = "Sono l'host di Bite & Pour e posso aiutarla a ordinare cibo e bevande dal nostro menu."
HINDI = "जी, आप क्या ऑर्डर करना चाहेंगे?"

# `21` Part C's own Roman Urdu, and THE HOST's English.
ROMAN_URDU = [
    "VC sahab ko ek Blue Lemonade",
    "Mujhe kuch thanda chahiye.",
    "Ek Blue Lemonade total Rs. 250 mein -- shall I place it, cash ya QR?",
    "Aap kya order karna chahenge?",
    "Humari stall par khush aamdeed! Kya aap menu se kuch try karna chahenge?",
]
ENGLISH = [
    "We have a crispy Chicken Burger, a classic Club Sandwich, and juicy Patty Burgers.",
    "Done — your order number is 1, and the total is Rs. 900.",
    "I don't have that detail — the team at the counter can tell you.",
    "Welcome, Dr. Rauf-i-Azam.",
    "Sorry, I missed that — could you say it again?",
    "It's a butterfly-pea lemonade, lightly sweet and refreshing.",
]
# Urdu in its own script: the Arabic block, which the guard must never flag.
URDU_SCRIPT = "سعد سلیم نے میری بزنس لاجک تخلیق کی ہے۔"


# -------------------------------------------------- the script test, by block


@pytest.mark.parametrize(
    "block,sample",
    [
        ("Devanagari", "आप क्या"),
        ("Gurmukhi", "ਸਤ ਸ੍ਰੀ ਅਕਾਲ"),
        ("Bengali", "আপনি কি"),
        ("Cyrillic", "Здравствуйте"),
        ("Greek and Coptic", "Καλημέρα"),
        ("CJK Unified Ideographs", "你好，请问"),
        ("Hangul Syllables", "안녕하세요"),
        ("Thai", "สวัสดีครับ"),
    ],
)
def test_every_forbidden_script_is_a_violation(block, sample):
    print(f"{block}: {language_guard.describe(sample)}")
    assert language_guard.forbidden_script(sample) == block
    assert language_guard.violation(sample) == "script"


def test_the_two_scripts_the_host_is_for_are_never_flagged():
    """English is Latin and Urdu is Arabic; flagging either breaks the stall."""
    for line in ENGLISH + ROMAN_URDU + [URDU_SCRIPT]:
        assert language_guard.forbidden_script(line) is None, line
        assert language_guard.violation(line) is None, line
    print(f"clean: {len(ENGLISH + ROMAN_URDU) + 1} English, Roman Urdu and Urdu lines")


def test_the_real_30_october_lines_are_caught():
    assert language_guard.violation(HINDI) == "script"
    assert language_guard.violation(SPANISH) == "words"
    assert language_guard.violation(ITALIAN) == "words"
    for line in (HINDI, SPANISH, ITALIAN):
        print(language_guard.describe(line))


# ---------------------------------------------- the word test: 1 hit vs 2 hits


def test_one_foreign_word_is_not_enough():
    """"que" and "bien" turn up by accident; two together do not."""
    one = "Our Chicken Burger, que the guests like."
    print(f"one hit: {language_guard.describe(one)}")
    assert language_guard.foreign_words(one) == ["que"]
    assert language_guard.violation(one) is None


def test_two_foreign_words_are_a_violation():
    two = "Hola, que would you like?"
    print(f"two hits: {language_guard.describe(two)}")
    assert language_guard.foreign_words(two) == ["hola", "que"]
    assert language_guard.violation(two) == "words"


def test_the_same_word_twice_counts_twice():
    """"que ... que" is as Spanish as "que ... bien"."""
    twice = "Que the burger, que the drink."
    assert language_guard.foreign_words(twice) == ["que", "que"]
    assert language_guard.violation(twice) == "words"


def test_only_the_first_fifteen_words_are_examined():
    """A long correct answer that happens to reach a listed word later is left
    alone: the guard is for a reply that starts in the wrong language."""
    tail = " ".join(["word"] * 15) + " hola que"
    print(f"beyond the window: {language_guard.describe(tail)}")
    assert language_guard.foreign_words(tail) == []
    assert language_guard.violation(tail) is None

    inside = "hola que " + " ".join(["word"] * 15)
    assert language_guard.violation(inside) == "words"


def test_the_word_test_ignores_case_and_punctuation():
    assert language_guard.violation("HOLA! QUE?") == "words"
    assert language_guard.violation("¿Qué, gustaría...?") == "words"


def test_an_empty_line_is_never_a_violation():
    assert language_guard.violation("") is None
    assert language_guard.violation("   ") is None


def test_the_word_list_is_the_one_the_section_gives():
    # 16 section 2zk item 4(b) lists 35 words; a word quietly dropped from the
    # list is a language that stops being caught.
    assert len(language_guard.FOREIGN_WORDS) == 35
    for word in ("hola", "qué", "que", "sono", "bonjour", "danke", "obrigado", "olá"):
        assert word in language_guard.FOREIGN_WORDS
    assert language_guard.WORD_WINDOW == 15
    assert language_guard.WORD_HITS_NEEDED == 2


# --------------------------------------------- the session's side of the guard


def agent_turn(session, line, audio=b"\x01\x02"):
    """One output-transcription fragment, with audio, as the API sends it."""
    asyncio.run(
        session._handle_message(doubles.message(doubles.content(agent=line, audio=audio)))
    )


def test_a_foreign_turn_is_interrupted_and_asked_for_again(caplog):
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, SPANISH)

    sent = [event.get("type") for event in ws.sent]
    print("to the page:", sent)
    print("to Gemini:", session.session.inputs)
    # The page is interrupted, so the audio it has queued is dropped at once.
    assert "interrupted" in sent
    # And THE HOST is told to say it again in English, in the section's words.
    assert session.session.inputs == [{"text": prompts.LANGUAGE_GUARD_PROMPT}]
    assert session.language_guard_fired is True
    assert session.drop_turn_audio is True
    doubles.validate(ws)


def test_the_log_carries_a_reason_and_never_a_word_of_the_line(caplog):
    session, _ = doubles.new_session()
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, SPANISH)

    messages = [record.getMessage() for record in caplog.records]
    for line in messages:
        print("log:", line)
    assert f"language guard session {session_id} reason=words" in messages
    # 12 section 1: not one word of what was said reaches the log.
    joined = "\n".join(messages)
    for word in ("Hola", "hola", "gustaría", "ordenar", "qué"):
        assert word not in joined


def test_a_script_violation_logs_script_not_words(caplog):
    session, _ = doubles.new_session()
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, HINDI)

    messages = [record.getMessage() for record in caplog.records]
    assert f"language guard session {session_id} reason=script" in messages
    assert HINDI not in "\n".join(messages)


def test_the_rest_of_the_turn_s_audio_is_dropped():
    """The guest must not hear the end of a Spanish sentence after its start
    has already been cut off."""
    session, ws = doubles.new_session()
    agent_turn(session, SPANISH, audio=b"\x01")
    before = len(ws.binary)

    # More audio for the same turn arrives and goes nowhere.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x02\x03"))))
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x04"))))

    print("binary frames before/after:", before, len(ws.binary))
    assert len(ws.binary) == before


def test_the_guard_fires_at_most_once_per_turn(caplog):
    """A second violation in the same turn is dropped in silence: telling the
    model again mid-turn is what would turn one bad answer into a loop."""
    session, ws = doubles.new_session()

    with caplog.at_level(logging.INFO, logger="live_session"):
        agent_turn(session, SPANISH)
        asked_once = list(session.session.inputs)
        interrupts_once = [e for e in ws.sent if e.get("type") == "interrupted"]
        # Still the same turn, still foreign.
        agent_turn(session, ITALIAN)

    interrupts_after = [e for e in ws.sent if e.get("type") == "interrupted"]
    guard_lines = [
        record.getMessage()
        for record in caplog.records
        if "language guard" in record.getMessage()
    ]
    print("asked:", session.session.inputs)
    print("interrupts:", len(interrupts_once), "->", len(interrupts_after))
    print("guard log lines:", guard_lines)
    assert session.session.inputs == asked_once
    assert len(interrupts_after) == len(interrupts_once)
    assert len(guard_lines) == 1


def test_a_clean_turn_is_left_completely_alone():
    session, ws = doubles.new_session()

    for line in ENGLISH[:3] + ROMAN_URDU[:3]:
        agent_turn(session, line)

    print("to Gemini:", session.session.inputs)
    print("interrupts:", [e for e in ws.sent if e.get("type") == "interrupted"])
    assert session.session.inputs == []
    assert [e for e in ws.sent if e.get("type") == "interrupted"] == []
    assert session.language_guard_fired is False
    assert session.drop_turn_audio is False
    # The audio of a correct answer still reaches the guest.
    assert len(ws.binary) == 6


def test_the_next_turn_may_speak_and_is_judged_again():
    """The flags are per turn, so one bad answer does not mute the rest of the
    conversation."""
    session, ws = doubles.new_session()
    agent_turn(session, SPANISH)
    assert session.drop_turn_audio is True

    # The turn ends.
    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("after turn_complete:", session.language_guard_fired, session.drop_turn_audio)
    assert session.language_guard_fired is False
    assert session.drop_turn_audio is False

    # A correct answer now gets through, audio and all.
    before = len(ws.binary)
    agent_turn(session, "Our Chicken Burger is the crispy one.")
    assert len(ws.binary) > before
    assert session.session.inputs == [{"text": prompts.LANGUAGE_GUARD_PROMPT}]


def test_the_wrong_words_do_not_stay_on_the_screen():
    """The TV shows THE HOST's caption, so an interrupted foreign line is
    cleared rather than left under the orb."""
    session, _ = doubles.new_session()
    agent_turn(session, SPANISH)
    print("agent transcript after the guard:", repr(session.transcripts["agent"]))
    assert session.transcripts["agent"] == ""


def test_the_prompt_is_the_section_s_exact_words():
    assert prompts.LANGUAGE_GUARD_PROMPT == (
        "Your last reply was not in English or Urdu. Say it again now in "
        "English, or in Urdu if the guest spoke Urdu."
    )
