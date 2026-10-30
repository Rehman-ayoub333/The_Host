"""16 section 2zm item 3: the one place a spoken item name becomes a menu item.

Rehman's warning for the gala was that teachers will try to trick THE HOST, and
guests speak broken English, Roman Urdu or a mix: "zingr burgr", "blue wali
lemonade", "do patty", "shwarma". Matching that by hand in each tool is how two
tools end up disagreeing, so every tool that turns words into an item calls
`resolve_item` here.

The four steps of item 3, in order, stopping at the first that decides:

  (a) normalise -- lowercase, strip punctuation, collapse spaces, drop the
      filler words;
  (b) the exact name, then an exact alias;
  (c) containment -- every query word appears in the name or in one alias. One
      item is a match; several are ambiguous, which is the point of "zinger"
      (Burger or Shawarma) and "lemonade" (four of them);
  (d) difflib, for a misspelling. A clear winner is a match; a near tie is
      ambiguous; nothing close enough is no match, with the three nearest names
      so THE HOST can offer something real.

Ambiguity is never resolved here and never guessed: the caller asks the guest.
"""

import re
from difflib import SequenceMatcher


# Item 3(a). "wala/wali/wale" carry no meaning for matching ("blue wali
# lemonade" is the Blue Citrus Lemonade), and the quantity words are handled by
# the tool's own quantity field, not by the name.
FILLER_WORDS = frozenset(
    {"wala", "wali", "wale", "ek", "one", "a", "an", "the", "please", "plz"}
)

# Item 3(d). The bar a fuzzy match has to clear, and how far ahead of the next
# item it has to be to count as the answer rather than one of two.
FUZZY_FLOOR = 0.80
FUZZY_MARGIN = 0.08
CLOSEST_COUNT = 3

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def normalise(text) -> str:
    """Item 3(a): lowercase, no punctuation, single spaces, no filler words."""
    lowered = _PUNCTUATION.sub(" ", str(text or "").lower())
    words = [word for word in lowered.split() if word not in FILLER_WORDS]
    return " ".join(words)


def _names_for(item: dict) -> list[str]:
    """Every spelling that points at this item: its name and its aliases."""
    spellings = [normalise(item.get("name", ""))]
    for alias in item.get("aliases") or []:
        alias_normalised = normalise(alias)
        if alias_normalised and alias_normalised not in spellings:
            spellings.append(alias_normalised)
    return [spelling for spelling in spellings if spelling]


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _word_score(query_words: list[str], candidate: str) -> float:
    """The mean of each query word's best match among the candidate's words.

    This is what catches "zingr burgr": neither word is right, but each is very
    close to one of "zinger burger", and the whole-string ratio alone is
    dragged down by the two missing letters.
    """
    candidate_words = candidate.split()
    if not query_words or not candidate_words:
        return 0.0
    best_per_word = [
        max(_ratio(word, other) for other in candidate_words) for word in query_words
    ]
    return sum(best_per_word) / len(best_per_word)


def _score(query: str, candidate: str) -> float:
    """Item 3(d): the better of the whole-string ratio and the per-word mean."""
    return max(_ratio(query, candidate), _word_score(query.split(), candidate))


def resolve_item(text, items) -> dict:
    """Item 3(e): `{"match": name}`, `{"ambiguous": [...]}` or `{"no_match": ...}`.

    `items` is the menu as `data.get_menu()` returns it, so every item carries
    its own `aliases` (or none).
    """
    query = normalise(text)
    rows = [item for item in (items or []) if item.get("name")]
    if not query or not rows:
        return {"no_match": True, "closest": [item["name"] for item in rows[:CLOSEST_COUNT]]}

    spellings = {item["name"]: _names_for(item) for item in rows}

    # (b) the exact name, then an exact alias. A name wins over another item's
    # alias, so a real menu name can never be taken for something else.
    for item in rows:
        if query == normalise(item["name"]):
            return {"match": item["name"]}
    alias_hits = [name for name, forms in spellings.items() if query in forms]
    if len(alias_hits) == 1:
        return {"match": alias_hits[0]}
    if len(alias_hits) > 1:
        return {"ambiguous": sorted(alias_hits)}

    # (c) containment: every word the guest said appears in one spelling.
    query_words = query.split()
    contained = [
        name
        for name, forms in spellings.items()
        if any(
            all(word in form.split() for word in query_words) for form in forms
        )
    ]
    if len(contained) == 1:
        return {"match": contained[0]}
    if len(contained) > 1:
        return {"ambiguous": sorted(contained)}

    # (d) fuzzy, against the name and every alias.
    scored = sorted(
        ((max(_score(query, form) for form in forms), name) for name, forms in spellings.items()),
        key=lambda pair: (-pair[0], pair[1]),
    )
    best, best_name = scored[0]
    if best >= FUZZY_FLOOR:
        close = [name for score, name in scored if best - score <= FUZZY_MARGIN]
        if len(close) == 1:
            return {"match": best_name}
        return {"ambiguous": sorted(close)}

    return {
        "no_match": True,
        "closest": [name for _score_value, name in scored[:CLOSEST_COUNT]],
    }
