"""16 section 2zi item 4(b): the guests' feedback forms, pulled into THE HOST.

Rehman hosts the form himself on Netlify and wanted the reviews inside THE
HOST, next to the feedback guests speak at the stall. Netlify Forms keeps the
submissions; this reads them with Rehman's personal access token and inserts
anything new.

Verified against Netlify's own API documentation
(https://docs.netlify.com/api/get-started/): the base URL is
`https://api.netlify.com/api/v1/`, the token travels as
`Authorization: Bearer <token>`, a site's forms are
`GET /api/v1/sites/{site_id}/forms` and a form's submissions are
`GET /api/v1/forms/{form_id}/submissions`.

The token and the site id are never logged and never put in an error message:
a failure is one line with the exception type only, and the next minute tries
again. With no token the whole feature is off and says so once.
"""

import asyncio
import logging

import httpx

import config
import data


log = logging.getLogger(__name__)

API_ROOT = "https://api.netlify.com/api/v1"
TIMEOUT_S = 15
# Netlify pages submissions; one gala evening is far inside one page, and a
# bigger page is one request rather than several.
PER_PAGE = 100

# The form's own fields, as Rehman's page posts them (`netlify-deploy/`). A
# submission that is missing one simply stores NULL for it.
FIELDS = (
    "item",
    "overall_rating",
    "taste_rating",
    "presentation_rating",
    "value_rating",
    "liked_most",
    "improvement",
    "buy_again",
    "one_word",
)
RATINGS = ("overall_rating", "taste_rating", "presentation_rating")


class Status:
    """What preflight and /health report, with no secret anywhere in it.

    16 section 2zi item 4(e): "off" when there is no token, "ok" after an
    import that worked, "failing" after one that did not.
    """

    def __init__(self):
        self.state = "off"
        self.last_ok = None
        self.last_error = None
        self.imported = 0

    def view(self) -> dict:
        return {
            "state": self.state,
            "last_ok": self.last_ok,
            # The exception type only -- never a URL, a token or a site id.
            "last_error": self.last_error,
            "imported": self.imported,
        }


STATUS = Status()
_off_logged = False


def configured() -> bool:
    return bool(config.NETLIFY_TOKEN and config.NETLIFY_SITE_ID)


def _rating(value):
    """A star count as the form sends it, or None when it is not a number."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value):
    if value is None:
        return None
    cleaned = " ".join(str(value).split())[:1000]
    return cleaned or None


def submission_row(submission: dict) -> dict:
    """One Netlify submission mapped onto the `form_feedback` columns.

    The submitted values live in the submission's `data` object. Older
    responses put them at the top level as well, so both are read and `data`
    wins: a payload that is shaped either way imports the same.
    """
    submission = submission or {}
    values = submission.get("data")
    values = values if isinstance(values, dict) else {}
    row = {
        "netlify_id": str(submission.get("id") or "").strip(),
        "created_at": _text(submission.get("created_at")),
    }
    for field in FIELDS:
        raw = values.get(field, submission.get(field))
        row[field] = _rating(raw) if field in RATINGS else _text(raw)
    return row


async def _get(client: httpx.AsyncClient, path: str, **params):
    response = await client.get(
        f"{API_ROOT}{path}",
        headers={"Authorization": f"Bearer {config.NETLIFY_TOKEN}"},
        params=params or None,
        timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()


def pick_form(forms, name: str) -> dict | None:
    """The form called `name`, or the site's only form if it is named oddly.

    Rehman's page posts `form-name=feedback`, so the name is what finds it.
    Falling back to a single lone form means a renamed form still imports
    rather than silently returning nothing.
    """
    forms = [form for form in (forms or []) if isinstance(form, dict)]
    wanted = str(name or "").strip().lower()
    for form in forms:
        if str(form.get("name") or "").strip().lower() == wanted:
            return form
    return forms[0] if len(forms) == 1 else None


async def import_once() -> int:
    """One pass: find the form, read its submissions, insert the new ones.

    Returns how many rows were new. Never raises: a network or API error is
    logged as one line with the exception type and retried next minute
    (16 section 2zi item 4(b)).
    """
    global _off_logged
    if not configured():
        STATUS.state = "off"
        if not _off_logged:
            log.info("feedback import off")
            _off_logged = True
        return 0
    try:
        async with httpx.AsyncClient() as client:
            forms = await _get(client, f"/sites/{config.NETLIFY_SITE_ID}/forms")
            form = pick_form(forms, config.NETLIFY_FORM_NAME)
            if form is None or not form.get("id"):
                # Not an error: the form has not been created or detected yet.
                STATUS.state = "failing"
                STATUS.last_error = "no form named " + str(config.NETLIFY_FORM_NAME)
                log.info("feedback import found no form")
                return 0
            submissions = await _get(
                client, f"/forms/{form['id']}/submissions", per_page=PER_PAGE
            )
    except Exception as exc:
        STATUS.state = "failing"
        STATUS.last_error = type(exc).__name__
        # The type only. A URL would carry the site id, and a response body
        # could carry the token back.
        log.info("feedback import failed %s", type(exc).__name__)
        return 0

    added = 0
    for submission in submissions or []:
        row = submission_row(submission)
        if not row["netlify_id"]:
            continue
        try:
            if await asyncio.to_thread(data.insert_form_feedback, row):
                added += 1
        except Exception as exc:
            STATUS.state = "failing"
            STATUS.last_error = type(exc).__name__
            log.info("feedback import could not store a row %s", type(exc).__name__)
            return added
    STATUS.state = "ok"
    STATUS.last_ok = data.now_iso()
    STATUS.last_error = None
    STATUS.imported += added
    if added:
        log.info("feedback import added %s", added)
    return added


async def import_loop() -> None:
    """At startup, then every FEEDBACK_IMPORT_INTERVAL_S (item 4(b))."""
    while True:
        await import_once()
        if not configured():
            # Nothing will change without a restart: .env is read at import.
            return
        await asyncio.sleep(config.FEEDBACK_IMPORT_INTERVAL_S)
