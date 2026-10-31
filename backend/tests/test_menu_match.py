"""Phase 7p, 16 section 2zm item 3: the one name matcher.

Rehman's warning was that teachers will try to trick THE HOST, and guests speak
broken English, Roman Urdu or a mix. The table below is item 3(g)'s, with every
real menu name added, because a matcher that cannot find the menu exactly is
worse than no matcher at all.

The menu here is the real `backend/data/menu.json` loaded through `data`, not a
fixture: the aliases are part of what is being tested.
"""

import pathlib

import pytest

import data
import menu_match
import tools


@pytest.fixture
def items(monkeypatch):
    """The real menu, with aliases, as the tools see it.

    conftest points MENU_JSON_PATH at a fixture seed carrying the old five
    items, and 16 section 2zm item 4 leaves those fixtures alone -- so this
    phase's tests name the real file themselves. The database is still the
    per-test temporary one.
    """
    import config

    real = pathlib.Path(__file__).resolve().parent.parent / "data" / "menu.json"
    monkeypatch.setattr(config, "MENU_JSON_PATH", real)
    data.init_db()
    rows = data.get_menu()
    assert len(rows) == 11, f"the real menu has 11 items, found {len(rows)}"
    return rows


REAL_NAMES = [
    "Patty Burger",
    "Zinger Burger",
    "Fire Burger",
    "Regular Sandwich",
    "Special Sandwich",
    "Classic Lemon Lemonade",
    "Mint Lemonade",
    "Strawberry Lemonade",
    "Blue Citrus Lemonade",
    "Zinger Shawarma",
    "Mix Fruit Cup",
]

# (input, expected name) -- item 3(g)'s single matches, plus the aliases.
MATCHES = [
    # The broken spellings the section names.
    ("zingr burgr", "Zinger Burger"),
    ("shwarma", "Zinger Shawarma"),
    ("blue wali lemonade", "Blue Citrus Lemonade"),
    ("pudina lemonade", "Mint Lemonade"),
    ("fire", "Fire Burger"),
    ("fire burgur", "Fire Burger"),
    ("patty", "Patty Burger"),
    ("special", "Special Sandwich"),
    ("fruit", "Mix Fruit Cup"),
    ("chicken burger", "Zinger Burger"),
    ("strawbery lemonad", "Strawberry Lemonade"),
    # Aliases, exactly as the menu lists them.
    ("patti burger", "Patty Burger"),
    ("pattie burger", "Patty Burger"),
    ("zingar burger", "Zinger Burger"),
    ("fire wala burger", "Fire Burger"),
    ("regular", "Regular Sandwich"),
    ("simple sandwich", "Regular Sandwich"),
    ("normal sandwich", "Regular Sandwich"),
    ("sada sandwich", "Regular Sandwich"),
    ("special wala sandwich", "Special Sandwich"),
    ("classic lemonade", "Classic Lemon Lemonade"),
    ("lemon lemonade", "Classic Lemon Lemonade"),
    ("simple lemonade", "Classic Lemon Lemonade"),
    ("plain lemonade", "Classic Lemon Lemonade"),
    ("nimbu lemonade", "Classic Lemon Lemonade"),
    ("mint", "Mint Lemonade"),
    ("strawberry", "Strawberry Lemonade"),
    ("blue lemonade", "Blue Citrus Lemonade"),
    ("blue citrus", "Blue Citrus Lemonade"),
    ("blue", "Blue Citrus Lemonade"),
    ("shawarma", "Zinger Shawarma"),
    ("chicken shawarma", "Zinger Shawarma"),
    ("fruit cup", "Mix Fruit Cup"),
    ("mixed fruit cup", "Mix Fruit Cup"),
    ("mix fruit", "Mix Fruit Cup"),
    # The filler words of item 3(a), which carry no meaning for matching.
    ("ek blue wali lemonade", "Blue Citrus Lemonade"),
    ("one patty please", "Patty Burger"),
    ("the mint lemonade", "Mint Lemonade"),
    ("a special wale sandwich plz", "Special Sandwich"),
    # Case and punctuation.
    ("ZINGER BURGER", "Zinger Burger"),
    ("mix-fruit cup!", "Mix Fruit Cup"),
    ("  blue   citrus  ", "Blue Citrus Lemonade"),
]

# (input, the names it must come back as) -- item 3(c)'s four ambiguous cases.
AMBIGUOUS = [
    ("zinger", ["Zinger Burger", "Zinger Shawarma"]),
    (
        "lemonade",
        [
            "Blue Citrus Lemonade",
            "Classic Lemon Lemonade",
            "Mint Lemonade",
            "Strawberry Lemonade",
        ],
    ),
    ("sandwich", ["Regular Sandwich", "Special Sandwich"]),
    ("burger", ["Fire Burger", "Patty Burger", "Zinger Burger"]),
]

NO_MATCH = ["pizza", "biryani", "tea", "coffee", "shawaya zinger pizza roll"]


@pytest.mark.parametrize("text,expected", MATCHES)
def test_a_spoken_name_reaches_the_right_item(items, text, expected):
    result = menu_match.resolve_item(text, items)
    print(f"{text!r} -> {result}")
    assert result == {"match": expected}


@pytest.mark.parametrize("name", REAL_NAMES)
def test_every_real_name_matches_itself(items, name):
    assert menu_match.resolve_item(name, items) == {"match": name}


@pytest.mark.parametrize("text,expected", AMBIGUOUS)
def test_a_shared_word_is_a_question_not_a_guess(items, text, expected):
    result = menu_match.resolve_item(text, items)
    print(f"{text!r} -> {result}")
    assert result == {"ambiguous": expected}


@pytest.mark.parametrize("text", NO_MATCH)
def test_something_we_do_not_serve_returns_three_real_names(items, text):
    result = menu_match.resolve_item(text, items)
    print(f"{text!r} -> {result}")
    assert result["no_match"] is True
    assert len(result["closest"]) == 3
    # Every suggestion is a real item: THE HOST must never offer an invention.
    for name in result["closest"]:
        assert name in REAL_NAMES


def test_an_empty_query_is_never_a_match(items):
    for text in ("", "   ", None, "please", "ek"):
        result = menu_match.resolve_item(text, items)
        print(f"{text!r} -> {result}")
        assert "match" not in result


# 16 section 2zn item 4(b): the number words joined the filler list. On 30 Oct
# E54 lost the guest's "do" (two) because "do patty" matched nothing, so the
# model dropped the word rather than passing it on with a quantity of 2.
@pytest.mark.parametrize(
    "text,expected",
    [
        ("do patty", "Patty Burger"),
        ("teen blue wali lemonade", "Blue Citrus Lemonade"),
        pytest.param(
            "de do patty",
            "Patty Burger",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "16 section 2zn item 4(b) asks for this but adds only the "
                    "number words. With 'do' dropped the query is 'de patty'; "
                    "'de' (Urdu: give) is not in the filler list, so "
                    "containment fails and the best fuzzy score is 0.7692 "
                    "against the 0.80 floor section 2zm item 3(d) sets. Passing "
                    "it needs either 'de' added to the list or a lower floor, "
                    "and both are Cowork's to decide."
                ),
            ),
        ),
    ],
)
def test_a_number_word_never_hides_the_item(items, text, expected):
    result = menu_match.resolve_item(text, items)
    print(f"{text!r} -> {result}")
    assert result == {"match": expected}


@pytest.mark.parametrize(
    "number", ["do", "teen", "char", "chaar", "paanch", "two", "three", "four", "five"]
)
def test_every_number_word_the_section_lists_is_filler(number):
    """None of them ever names an item, and the quantity has its own field."""
    assert number in menu_match.FILLER_WORDS
    assert menu_match.normalise(f"{number} patty") == "patty"


def test_a_number_word_on_its_own_is_not_an_item(items):
    """"do" alone names nothing, so it must not reach for the nearest item."""
    for number in ("do", "teen", "two"):
        assert "match" not in menu_match.resolve_item(number, items)


def test_the_thresholds_are_the_ones_the_section_sets():
    assert menu_match.FUZZY_FLOOR == 0.80
    assert menu_match.FUZZY_MARGIN == 0.08
    assert sorted(menu_match.FILLER_WORDS) == sorted(
        ["wala", "wali", "wale", "ek", "one", "a", "an", "the", "please", "plz"]
        # 16 section 2zn item 4(b).
        + ["do", "teen", "char", "chaar", "paanch", "two", "three", "four", "five"]
    )


# ------------------------------------------- item 3(f): the two tools' shapes


def test_check_item_availability_returns_the_match(items):
    result = tools.check_item_availability(item="zingr burgr")
    print(result)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "Zinger Burger"
    assert result["items"][0]["price"] == "Rs. 350"


def test_check_item_availability_passes_ambiguity_back(items):
    result = tools.check_item_availability(item="zinger")
    print(result)
    assert result["ambiguous"] == ["Zinger Burger", "Zinger Shawarma"]
    assert "items" not in result


def test_check_item_availability_passes_no_match_back(items):
    result = tools.check_item_availability(item="pizza")
    print(result)
    assert result["no_match"] is True
    assert len(result["closest"]) == 3


def test_a_category_query_still_lists_the_category(items):
    """A category is a list, not a name, so it never goes near the matcher."""
    result = tools.check_item_availability(category="Lemonades")
    print([row["name"] for row in result["items"]])
    assert result["total"] == 4
    assert {row["category"] for row in result["items"]} == {"Lemonades"}


def test_build_order_builds_nothing_while_an_item_is_ambiguous(items):
    result = tools.build_order(items=[{"name": "zinger", "quantity": 1}])
    print(result)
    assert result["source"] == "order"
    assert result["error"] == "Ask the guest which one: Zinger Burger or Zinger Shawarma."
    assert result["options"] == ["Zinger Burger", "Zinger Shawarma"]
    assert "draft_id" not in result


def test_build_order_builds_nothing_for_something_we_do_not_serve(items):
    result = tools.build_order(items=[{"name": "pizza", "quantity": 1}])
    print(result)
    assert result["error"] == "We don't serve pizza."
    assert len(result["closest"]) == 3
    assert "draft_id" not in result


def test_build_order_reports_only_the_first_problem_item(items):
    """One question at a time is how a guest at a counter is asked."""
    result = tools.build_order(
        items=[{"name": "zinger", "quantity": 1}, {"name": "pizza", "quantity": 1}]
    )
    print(result)
    assert "options" in result
    assert "closest" not in result
