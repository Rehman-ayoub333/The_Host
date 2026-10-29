"""Phase 7n: the guests' feedback forms inside THE HOST (16 section 2zi item 4).

Rehman hosts the form on Netlify and wanted the reviews in THE HOST. Netlify
keeps the submissions; the import reads them with his personal access token and
stores anything new. The whole form is pulled every minute, so the only thing
stopping duplicates is the unique `netlify_id`, and that is tested here first.

Nothing in this file is a real token or a real site id, and the module is built
so that neither can reach a log or an error message: a failure is one line with
the exception type only (item 4(b)).
"""

import asyncio
import csv
import io

import httpx
import pytest
from fastapi.testclient import TestClient

import config
import data
import main
import netlify_feedback


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}

FAKE_TOKEN = "test-netlify-token-not-a-real-one"
FAKE_SITE = "test-site-id"

SUBMISSION = {
    "id": "sub-1",
    "created_at": "2026-10-29T18:00:00.000Z",
    "data": {
        "item": "Chicken Burger",
        "overall_rating": "5",
        "taste_rating": "4",
        "presentation_rating": "5",
        "value_rating": "Great value",
        "liked_most": "The sauce",
        "improvement": "  More   napkins  ",
        "buy_again": "Definitely",
        "one_word": "Crispy",
    },
}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "NETLIFY_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", FAKE_SITE)
    monkeypatch.setattr(config, "NETLIFY_FORM_NAME", "feedback")
    netlify_feedback.STATUS.__init__()
    netlify_feedback._off_logged = False


def fake_api(monkeypatch, *, forms=None, submissions=None, fail=None):
    """Stand in for Netlify, so no test ever reaches the network.

    The paths asserted here are the ones the API documentation gives:
    /sites/{site_id}/forms and /forms/{form_id}/submissions.
    """
    asked = []

    async def _get(client, path, **params):
        asked.append((path, params))
        if fail is not None:
            raise fail
        if path.endswith("/forms"):
            return forms if forms is not None else [{"id": "form-9", "name": "feedback"}]
        return submissions if submissions is not None else [SUBMISSION]

    monkeypatch.setattr(netlify_feedback, "_get", _get)
    return asked


# ---------------------------------- item 4(b): the import, and importing twice


def test_one_submission_is_stored_with_every_field(ctx, monkeypatch, configured):
    fake_api(monkeypatch)

    added = asyncio.run(netlify_feedback.import_once())

    assert added == 1
    rows = data.list_form_feedback()
    assert len(rows) == 1
    row = rows[0]
    assert row["netlify_id"] == "sub-1"
    assert row["item"] == "Chicken Burger"
    assert row["overall_rating"] == 5
    assert row["taste_rating"] == 4
    assert row["presentation_rating"] == 5
    assert row["value_rating"] == "Great value"
    assert row["liked_most"] == "The sauce"
    # Whitespace is collapsed, as everywhere else a guest's words are stored.
    assert row["improvement"] == "More napkins"
    assert row["buy_again"] == "Definitely"
    assert row["one_word"] == "Crispy"


def test_importing_the_same_submission_again_changes_nothing(ctx, monkeypatch, configured):
    fake_api(monkeypatch)

    assert asyncio.run(netlify_feedback.import_once()) == 1
    assert asyncio.run(netlify_feedback.import_once()) == 0

    assert len(data.list_form_feedback()) == 1


def test_a_second_submission_is_added_beside_the_first(ctx, monkeypatch, configured):
    second = {**SUBMISSION, "id": "sub-2", "created_at": "2026-10-29T19:00:00.000Z"}
    fake_api(monkeypatch, submissions=[SUBMISSION, second])

    assert asyncio.run(netlify_feedback.import_once()) == 2

    rows = data.list_form_feedback()
    # Newest first (item 4(c)).
    assert [row["netlify_id"] for row in rows] == ["sub-2", "sub-1"]


def test_it_asks_netlify_for_the_two_documented_paths(ctx, monkeypatch, configured):
    """The endpoints of https://docs.netlify.com/api/get-started/."""
    asked = fake_api(monkeypatch)

    asyncio.run(netlify_feedback.import_once())

    assert asked[0][0] == f"/sites/{FAKE_SITE}/forms"
    assert asked[1][0] == "/forms/form-9/submissions"


def test_the_form_is_found_by_its_name_among_several(ctx, monkeypatch, configured):
    forms = [
        {"id": "form-1", "name": "contact"},
        {"id": "form-9", "name": "Feedback"},
    ]
    asked = fake_api(monkeypatch, forms=forms)

    asyncio.run(netlify_feedback.import_once())

    assert asked[1][0] == "/forms/form-9/submissions"


def test_no_form_of_that_name_is_reported_not_crashed(ctx, monkeypatch, configured):
    fake_api(monkeypatch, forms=[{"id": "a", "name": "contact"}, {"id": "b", "name": "x"}])

    assert asyncio.run(netlify_feedback.import_once()) == 0

    assert netlify_feedback.STATUS.state == "failing"
    assert data.list_form_feedback() == []


def test_a_values_payload_at_the_top_level_still_imports(ctx, monkeypatch, configured):
    """Read defensively: `data` wins, but a flat payload is not lost."""
    flat = {"id": "sub-flat", "created_at": "2026-10-29T18:30:00.000Z", "item": "Blue Lemonade"}
    fake_api(monkeypatch, submissions=[flat])

    assert asyncio.run(netlify_feedback.import_once()) == 1

    assert data.list_form_feedback()[0]["item"] == "Blue Lemonade"


def test_a_submission_with_no_id_is_skipped(ctx, monkeypatch, configured):
    fake_api(monkeypatch, submissions=[{"data": {"item": "Chicken Burger"}}])

    assert asyncio.run(netlify_feedback.import_once()) == 0
    assert data.list_form_feedback() == []


def test_a_rating_that_is_not_a_number_is_stored_as_nothing(ctx, monkeypatch, configured):
    odd = {"id": "sub-odd", "data": {"overall_rating": "five stars", "item": "X"}}
    fake_api(monkeypatch, submissions=[odd])

    asyncio.run(netlify_feedback.import_once())

    assert data.list_form_feedback()[0]["overall_rating"] is None


# ------------------------------- item 4(b): errors do not crash the task


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("no route"),
        httpx.ReadTimeout("slow"),
        httpx.HTTPStatusError("401", request=None, response=None),
        ValueError("not json"),
    ],
    ids=["connect", "timeout", "status", "decode"],
)
def test_an_api_error_is_one_line_and_the_task_survives(
    ctx, monkeypatch, configured, caplog, failure
):
    import logging

    fake_api(monkeypatch, fail=failure)

    with caplog.at_level(logging.INFO, logger="netlify_feedback"):
        assert asyncio.run(netlify_feedback.import_once()) == 0

    assert netlify_feedback.STATUS.state == "failing"
    assert netlify_feedback.STATUS.last_error == type(failure).__name__
    lines = [record.getMessage() for record in caplog.records]
    assert lines == [f"feedback import failed {type(failure).__name__}"]
    # Never the token, never the site id, never a URL.
    for line in lines:
        assert FAKE_TOKEN not in line
        assert FAKE_SITE not in line
        assert "api.netlify.com" not in line


def test_the_status_never_carries_a_secret(ctx, monkeypatch, configured):
    fake_api(monkeypatch, fail=httpx.ConnectError("https://api.netlify.com failed"))

    asyncio.run(netlify_feedback.import_once())

    printed = str(netlify_feedback.STATUS.view())
    assert FAKE_TOKEN not in printed
    assert FAKE_SITE not in printed
    assert "api.netlify.com" not in printed


# ---------------------------------------- item 4(b): no token means off


def test_with_no_token_the_import_is_off_and_says_so_once(ctx, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(config, "NETLIFY_TOKEN", "")
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", "")
    netlify_feedback.STATUS.__init__()
    netlify_feedback._off_logged = False

    with caplog.at_level(logging.INFO, logger="netlify_feedback"):
        assert asyncio.run(netlify_feedback.import_once()) == 0
        assert asyncio.run(netlify_feedback.import_once()) == 0

    assert netlify_feedback.STATUS.state == "off"
    lines = [record.getMessage() for record in caplog.records]
    assert lines == ["feedback import off"]


def test_a_token_with_no_site_id_is_still_off(ctx, monkeypatch):
    monkeypatch.setattr(config, "NETLIFY_TOKEN", FAKE_TOKEN)
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", "")

    assert netlify_feedback.configured() is False


def test_the_loop_stops_itself_when_the_feature_is_off(ctx, monkeypatch):
    """Nothing can change without a restart, so it does not spin for ever."""
    monkeypatch.setattr(config, "NETLIFY_TOKEN", "")
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", "")

    asyncio.run(asyncio.wait_for(netlify_feedback.import_loop(), timeout=5))


# ----------------------------------------------- item 4(c): the endpoints


def test_the_feedback_endpoint_has_both_lists_and_the_summary(ctx, served, monkeypatch, configured):
    fake_api(monkeypatch)
    asyncio.run(netlify_feedback.import_once())
    data.create_feedback("chicken burger", "Really good", 5, "Ahmed")

    body = served.get("/api/feedback", headers=AUTH).json()

    assert set(body) == {"form", "spoken", "summary", "import_status"}
    assert len(body["form"]) == 1
    assert body["form"][0]["item"] == "Chicken Burger"
    assert len(body["spoken"]) == 1
    assert body["spoken"][0]["comment"] == "Really good"
    assert body["summary"] == {
        "count": 1,
        "avg_overall": 5,
        "avg_taste": 4,
        "avg_presentation": 5,
        "buy_again_yes_pct": 100,
    }


def test_the_summary_averages_several_rows_and_counts_buy_again(ctx):
    for index, (overall, taste, presentation, buy_again) in enumerate(
        [(5, 4, 5, "Definitely"), (3, 3, 2, "Probably"), (1, 1, 1, "No")]
    ):
        data.insert_form_feedback(
            {
                "netlify_id": f"sub-{index}",
                "overall_rating": overall,
                "taste_rating": taste,
                "presentation_rating": presentation,
                "buy_again": buy_again,
            }
        )

    summary = data.form_feedback_summary()

    assert summary["count"] == 3
    assert summary["avg_overall"] == 3
    assert summary["avg_taste"] == round((4 + 3 + 1) / 3, 2)
    assert summary["avg_presentation"] == round((5 + 2 + 1) / 3, 2)
    # "Definitely" and "Probably" of three answers.
    assert summary["buy_again_yes_pct"] == 67


def test_an_empty_form_averages_nothing_rather_than_zero(ctx):
    summary = data.form_feedback_summary()

    assert summary == {
        "count": 0,
        "avg_overall": None,
        "avg_taste": None,
        "avg_presentation": None,
        "buy_again_yes_pct": None,
    }


def test_the_feedback_csv_has_the_columns_and_the_rows(ctx, served, monkeypatch, configured):
    fake_api(monkeypatch)
    asyncio.run(netlify_feedback.import_once())

    response = served.get("/api/feedback.csv", headers=AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"bite-and-pour-feedback-{data._today()}.csv" in response.headers[
        "content-disposition"
    ]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == list(data.FORM_FEEDBACK_COLUMNS)
    assert rows[1][0] == "sub-1"
    assert rows[1][2] == "Chicken Burger"


@pytest.mark.parametrize("path", ["/api/feedback", "/api/feedback.csv"])
def test_both_endpoints_need_the_operator_token(served, path):
    assert served.get(path).status_code == 401
    assert served.get(path, headers={"X-Operator-Token": "wrong"}).status_code == 401


def test_health_reports_the_import_without_a_token(ctx, served):
    body = served.get("/health").json()

    assert set(body["feedback_import"]) == {"state", "last_ok", "last_error", "imported"}
    assert body["feedback_import"]["state"] in ("off", "ok", "failing")
