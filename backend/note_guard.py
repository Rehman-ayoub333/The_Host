"""16 section 2zt item 3(b): an acknowledgement guard in code, not only in the prompt.

On 4 Nov Rehman sent the private note "Wrap up politely." and THE HOST answered
it out loud -- "Okay, I will wrap up" -- in front of the guest. The note reaches
Gemini as a full user turn, so the model's next turn is a reply *to the note*,
and `21` Part A's "never mention that you received a note" was not strong enough
to stop it. The prompt bullet is now much firmer (item 3(a)), but a prompt rule
the model does not follow is not a control: this is the second layer, built on
exactly the mechanism the language guard already proved (2zk item 4(b)).

Two windows, both from the section:

  * an **opener** test over the first four words -- the acknowledgement always
    comes first ("Okay, …", "Sure, …"). Four words is deliberately short: "right
    away" is an acknowledgement at the front of a reply and an ordinary phrase
    in the middle of one ("your order will be right away" is not what this is
    looking for).
  * a **mention** test over the first fifteen words -- the words that name the
    note or announce what THE HOST is about to do ("noted", "I will now…",
    "as instructed"). These are wrong anywhere near the start of the turn, so
    the window is the whole opening sentence or two.

Everything here is a pure function over a string. Nothing logs, and nothing in
this module ever keeps or returns the text it was given: the caller logs a
session id and no more (12 section 1).
"""

import re


# The section's lists, verbatim, lower-cased for comparison.

# First four words. "right away" is in OPENER_PHRASES below.
OPENERS = frozenset({"okay", "ok", "sure", "certainly", "alright"})

OPENER_PHRASES = ("right away",)

# First fifteen words.
MENTIONS = frozenset(
    {
        "note",
        "notes",
        "instruction",
        "instructions",
        "operator",
        "dashboard",
        "understood",
        "noted",
    }
)

MENTION_PHRASES = ("got it", "will do", "i will now", "i'll now", "as instructed")

OPENER_WINDOW = 4
MENTION_WINDOW = 15

# Letters, keeping an apostrophe inside the word it belongs to, so "i'll" is one
# word and not "i" followed by "ll". Digits and punctuation are not words.
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)

# The model writes both apostrophes; the lists above use the straight one.
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'"})


def words(text: str, window: int) -> list[str]:
    """The first `window` words of `text`, lower-cased and apostrophe-normalised."""
    return _WORD.findall(text.translate(_APOSTROPHES).lower())[:window]


def _phrase_in(window_words: list[str], phrases) -> str | None:
    """The first phrase of `phrases` that appears whole inside `window_words`."""
    joined = f" {' '.join(window_words)} "
    for phrase in phrases:
        if f" {phrase} " in joined:
            return phrase
    return None


def opener(text: str) -> str | None:
    """The acknowledgement word or phrase opening `text`, or None.

    The word is for a test to read; the caller logs neither it nor the line.
    """
    opening = words(text, OPENER_WINDOW)
    for word in opening:
        if word in OPENERS:
            return word
    return _phrase_in(opening, OPENER_PHRASES)


def mention(text: str) -> str | None:
    """The word or phrase naming the note inside the opening of `text`, or None."""
    opening = words(text, MENTION_WINDOW)
    for word in opening:
        if word in MENTIONS:
            return word
    return _phrase_in(opening, MENTION_PHRASES)


def violation(text: str) -> str | None:
    """"opener", "mention", or None -- the reason, for a test and never a log.

    A string that trips neither test is treated as a clean reply to the guest,
    which is the safe way round: the guard interrupts THE HOST mid-sentence, so
    a false positive costs a guest their answer.
    """
    if not text:
        return None
    if opener(text) is not None:
        return "opener"
    if mention(text) is not None:
        return "mention"
    return None


def describe(text: str) -> str:
    """A reason with its evidence, for a test's own output only.

    Never pass this to a log: it returns words THE HOST's line really contained,
    and 12 section 1 keeps conversation text out of every log and file.
    """
    hit = opener(text)
    if hit is not None:
        return f"opener={hit}"
    hit = mention(text)
    return f"mention={hit}" if hit is not None else "clean"
