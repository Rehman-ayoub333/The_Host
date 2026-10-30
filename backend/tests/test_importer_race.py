"""Phase 7o, 16 section 2zj item 7: the feedback importer never races a test.

The lifespan starts the importer as a background task -- main.py's "at startup
then every minute". With a real NETLIFY_TOKEN in backend/.env that task is
live, so on 30 Oct it reached Netlify while the suite ran and wrote its outcome
into the one module-level STATUS object, which is precisely what the /health
tests assert is pristine:

    FAILED tests/test_main.py::test_health_reports_the_menu_row_count
    FAILED tests/test_metrics.py::test_health_reports_its_components
    "feedback_import": {"state": null, "last_error": "ConnectError", ...}

Both passed on their own and as a pair, and failed in a full run: the result
depended on whether the laptop's network answered inside the test's window.
conftest replaces `import_loop` for every test, so there is nothing left to
race. These tests are the proof of that, and they are deliberately written the
way the failing ones were -- a configured token and a started lifespan.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import config
import main
import netlify_feedback


TOKEN = "operator-token-for-tests"


def test_the_lifespan_does_not_start_the_real_import_loop(monkeypatch):
    """The whole race, in one assertion: the loop conftest installed is a
    no-op, so no request leaves the machine however the token is set."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    # A token that would make the real importer live.
    monkeypatch.setattr(config, "NETLIFY_TOKEN", "a-token-shaped-string")
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", "a-site-id")
    monkeypatch.setattr(config, "ACTIVE", None, raising=False)

    # If anything still called the real importer, this would raise rather than
    # quietly reach the network.
    def never(*args, **kwargs):
        raise AssertionError("the real importer ran during a test")

    monkeypatch.setattr(netlify_feedback, "import_once", never)

    with TestClient(main.app) as client:
        body = client.get("/health").json()

    print("feedback_import after a started lifespan:", body["feedback_import"])
    assert body["feedback_import"] == {
        "state": "off",
        "last_ok": None,
        "last_error": None,
        "imported": 0,
    }


def test_the_status_object_is_pristine_for_every_test():
    """2zi item 4(b) resets it; item 7 is what keeps it reset."""
    print("STATUS:", netlify_feedback.STATUS.view())
    assert netlify_feedback.STATUS.view() == {
        "state": "off",
        "last_ok": None,
        "last_error": None,
        "imported": 0,
    }


def test_the_patched_loop_returns_at_once():
    """It is awaited by the lifespan's create_task, so it has to be a coroutine
    that simply ends -- not a sleep, and not a loop that keeps a task alive
    past the end of the test."""
    result = asyncio.run(netlify_feedback.import_loop())
    print("the patched loop returned:", result)
    assert result is None


def test_the_importer_s_own_functions_are_untouched():
    """Only the background task is neutralised: `import_once` and the row
    builder are the importer's real ones, so test_feedback_import still tests
    the importer rather than a double."""
    assert netlify_feedback.import_once.__module__ == "netlify_feedback"
    assert callable(netlify_feedback.submission_row)
    assert callable(netlify_feedback.configured)
    # Not asserted: whether the importer is configured. That depends on the
    # machine, and depending on it is the bug this test exists for.


@pytest.mark.parametrize("path", ["/health", "/api/metrics"])
def test_the_two_endpoints_that_failed_on_30_october(monkeypatch, path):
    """The same shape as the two failures, with a live-looking token."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(config, "NETLIFY_TOKEN", "a-token-shaped-string")
    monkeypatch.setattr(config, "NETLIFY_SITE_ID", "a-site-id")
    monkeypatch.setattr(main, "ACTIVE", None)

    with TestClient(main.app) as client:
        response = client.get(path, headers={"X-Operator-Token": TOKEN})

    assert response.status_code == 200
    print(f"{path}: {response.status_code}")
    # Whatever else they carry, nothing in them came from the network.
    assert netlify_feedback.STATUS.last_error is None
    assert netlify_feedback.STATUS.state == "off"
