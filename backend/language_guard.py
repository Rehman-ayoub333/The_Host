"""16 section 2zk item 4(b): a language guard in code, not only in the prompt.

On 30 Oct, in front of the CS faculty, THE HOST answered guests in Spanish and
Italian and twice in Hindi written in Devanagari -- and `21` Part A had already
forbidden Hindi by name. A prompt rule that the model does not follow is not a
control, so this is the second layer: the backend reads THE HOST's own output
transcription as it arrives and stops a turn that is not in English or Urdu.

Two tests, both from the section:

  * a script test -- any character from a writing system THE HOST has no business
    using. Urdu is written in the Arabic block and English in Latin, so neither
    can trip this: the blocks below are the ones that can only be another
    language.
  * a word test -- two or more whole words from the section's list inside the
    first fifteen words. One is not enough on purpose: "que" and "bien" turn up
    by accident, two together do not. The limit to the opening words keeps a
    long correct answer that happens to quote a menu name out of it.

Everything here is a pure function over a string. Nothing logs, and nothing in
this module ever keeps or returns the text it was given -- the caller logs a
reason and no more (12 section 1).
"""

import re
import unicodedata


# The section's list, verbatim, lower-cased for comparison. Spanish, Italian,
# French, German and Portuguese: the languages the 30 Oct transcript actually
# produced, plus their nearest neighbours.
FOREIGN_WORDS = frozenset(
    {
        "hola",
        "qué",
        "que",
        "gustaría",
        "usted",
        "ustedes",
        "estoy",
        "gracias",
        "bien",
        "menú",
        "disculpe",
        "podría",
        "ordenar",
        "sono",
        "posso",
        "nostro",
        "nostra",
        "buongiorno",
        "grazie",
        "vorrebbe",
        "cosa",
        "bonjour",
        "merci",
        "vous",
        "avec",
        "voulez",
        "nous",
        "danke",
        "bitte",
        "ich",
        "und",
        "sie",
        "obrigado",
        "você",
        "olá",
    }
)

# How many of the opening words are examined, and how many hits are a violation.
WORD_WINDOW = 15
WORD_HITS_NEEDED = 2

# The script test. Each entry is an inclusive code-point range, and the name is
# what the section calls it.
#
# Deliberately absent: Arabic (U+0600-U+06FF), which is how Urdu is written, and
# Latin, which is English and Roman Urdu. Flagging either would break the two
# languages THE HOST is for.
FORBIDDEN_BLOCKS: tuple[tuple[str, int, int], ...] = (
    ("Devanagari", 0x0900, 0x097F),
    ("Devanagari Extended", 0xA8E0, 0xA8FF),
    ("Bengali", 0x0980, 0x09FF),
    ("Gurmukhi", 0x0A00, 0x0A7F),
    ("Thai", 0x0E00, 0x0E7F),
    ("Greek and Coptic", 0x0370, 0x03FF),
    ("Greek Extended", 0x1F00, 0x1FFF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("Cyrillic Supplement", 0x0500, 0x052F),
    ("Hangul Jamo", 0x1100, 0x11FF),
    ("Hangul Syllables", 0xAC00, 0xD7AF),
    ("Hangul Compatibility Jamo", 0x3130, 0x318F),
    # CJK: the ideographs themselves, the common extension, and the Japanese
    # syllabaries, which are a different language in the same breath.
    ("CJK Unified Ideographs", 0x4E00, 0x9FFF),
    ("CJK Extension A", 0x3400, 0x4DBF),
    ("Hiragana", 0x3040, 0x309F),
    ("Katakana", 0x30A0, 0x30FF),
)

# Letters only: digits, spaces and punctuation are not words, and an accent is
# part of the word it sits on ("gustaría" is one word, not two).
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def forbidden_script(text: str) -> str | None:
    """The name of the first forbidden block `text` uses, or None.

    The name is for a test to read; the caller logs only "script".
    """
    for character in text:
        point = ord(character)
        for name, low, high in FORBIDDEN_BLOCKS:
            if low <= point <= high:
                return name
    return None


def foreign_words(text: str) -> list[str]:
    """Which of the section's words appear in the first WORD_WINDOW words.

    Returned in the order they were found, with repeats kept: two of the same
    word is two hits, because "que ... que" is as Spanish as "que ... bien".
    """
    words = _WORD.findall(text.lower())[:WORD_WINDOW]
    return [word for word in words if word in FOREIGN_WORDS]


def violation(text: str) -> str | None:
    """"script", "words", or None -- the reason the caller logs.

    The script test runs first: it is the certain one. A string that fails
    neither is treated as English or Urdu, which is the safe way round -- the
    guard interrupts THE HOST mid-sentence, so a false positive costs a guest
    their answer.
    """
    if not text:
        return None
    if forbidden_script(text) is not None:
        return "script"
    if len(foreign_words(text)) >= WORD_HITS_NEEDED:
        return "words"
    return None


def describe(text: str) -> str:
    """A reason with its evidence, for a test's own output only.

    Never pass this to a log: `foreign_words` returns words the guest's or THE
    HOST's line really contained, and 12 section 1 keeps conversation text out
    of every log and file.
    """
    script = forbidden_script(text)
    if script is not None:
        sample = next(
            (
                character
                for character in text
                if any(low <= ord(character) <= high for _, low, high in FORBIDDEN_BLOCKS)
            ),
            "",
        )
        return f"script={script} first={unicodedata.name(sample, 'unknown')}"
    hits = foreign_words(text)
    return f"words={hits}" if hits else "clean"
