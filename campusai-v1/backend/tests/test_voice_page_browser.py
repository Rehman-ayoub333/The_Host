"""Phase 5d, 16 section 2i items 2 and 7: the voice page in a real browser.

At the 5c live test `?debug=mic` printed nothing in Rehman's Chrome, so the
readout is proved here in Chromium with a fake microphone rather than by
reading the code. The same run checks that a guest's transcript line is not
rendered on the booth screen (2i item 6).

The page is served by a stand-in that only hands out the static files and plays
the part of `/ws/session`; no Gemini connection and no real backend is involved.
Skipped unless Playwright and its Chromium are both installed.
"""

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
CHROMIUM = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "ms-playwright"
    / "chromium-1234"
    / "chrome-win64"
    / "chrome.exe"
)

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed"
).sync_playwright

pytestmark = pytest.mark.skipif(
    not CHROMIUM.exists(), reason=f"the pre-installed Chromium is not at {CHROMIUM}"
)

# What the stand-in socket says as soon as the page connects: one guest line and
# one THE HOST line, so the screen has both to show or withhold.
GUEST_LINE = "a guest said this out loud"
HOST_LINE = "and THE HOST answered"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _build_app():
    """The smallest thing that can serve the voice page and one socket."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route, WebSocketRoute
    from starlette.staticfiles import StaticFiles

    async def vision(_request):
        return JSONResponse({"ok": True})

    async def session(websocket):
        await websocket.accept()
        for index, (role, text) in enumerate(
            (("visitor", GUEST_LINE), ("agent", HOST_LINE)), start=1
        ):
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "speech_transcript",
                        "event_id": index,
                        "timestamp": "2026-10-14T00:00:00",
                        "session_id": "browsertest",
                        "role": role,
                        "text": text,
                        "final": True,
                    }
                )
            )
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass

    return Starlette(
        routes=[
            Route("/api/vision", vision, methods=["POST"]),
            WebSocketRoute("/ws/session", session),
            Mount("/", app=StaticFiles(directory=str(FRONTEND), html=True)),
        ]
    )


@pytest.fixture
def page_server():
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_build_app(), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        pytest.fail("the stand-in page server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def booth(page_server):
    """The voice page with ?debug=mic, booth started, console lines captured."""
    lines: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(CHROMIUM),
            args=[
                # A microphone and camera that need no hardware and no click.
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = browser.new_context(permissions=["microphone", "camera"])
        page = context.new_page()
        page.on(
            "console",
            lambda entry: lines.append(f"{entry.type}: {entry.text}"),
        )
        page.goto(f"{page_server}/?debug=mic")
        page.wait_for_selector("#startBtn")
        page.click("#startBtn")
        # The overlay goes when the booth is up; the readout runs from then on.
        page.wait_for_selector("#startOverlay", state="hidden", timeout=30000)
        yield page, lines
        context.close()
        browser.close()


def test_mic_debug_prints_at_load_and_while_the_booth_is_idle(booth):
    page, lines = booth
    # 2i item 2: the one line that cannot be missed, written at page load.
    assert any("mic debug on" in line for line in lines), lines

    # 2h item 6: the readout runs while the booth is idle, not only in a session.
    assert page.evaluate("document.body.dataset.state") == "idle"
    page.wait_for_timeout(2000)
    levels = [line for line in lines if "mic level" in line]
    assert len(levels) >= 2, lines
    for line in levels:
        assert "peak" in line


def test_a_guest_transcript_line_is_not_rendered(booth):
    page, lines = booth
    page.click("#talkBtn")
    page.wait_for_function(
        "() => document.querySelectorAll('#transcript .line').length > 0",
        timeout=15000,
    )
    page.wait_for_timeout(500)

    shown = page.inner_text("#transcript")
    # 2i item 6: THE HOST's line shows, the guest's own words do not.
    assert HOST_LINE in shown
    assert GUEST_LINE not in shown
    assert page.evaluate(
        "document.querySelectorAll('#transcript .line-user').length"
    ) == 0
    assert page.evaluate(
        "document.querySelectorAll('#transcript .line-agent').length"
    ) == 1
