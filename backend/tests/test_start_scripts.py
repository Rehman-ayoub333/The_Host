"""Phase 7c, 16 section 2r item 3: the dashboard starts as a production build.

The gala depends on `start-dashboard.ps1` defaulting to the production server,
so the parts that would actually hurt if someone reverted them are guarded
here: the default path must not be the development server, the node-server
preset must stay pinned (without it the build emits a Cloudflare Workers
bundle that cannot be started on the booth laptop at all), and the address must
stay port 8080. The script is read as text; nothing here starts a server.
"""

from pathlib import Path

import config


REPO_ROOT = config.BASE_DIR.parent
SCRIPT = REPO_ROOT / "scripts" / "start-dashboard.ps1"
START_ALL = REPO_ROOT / "scripts" / "start-all.ps1"
STOP_ALL = REPO_ROOT / "scripts" / "stop-all.ps1"
RUNBOOK = REPO_ROOT / "docs" / "GALA-RUNBOOK.md"


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def script_code() -> str:
    """The script with its comment lines dropped, so prose cannot satisfy a
    test about what the script actually runs."""
    return "\n".join(
        line for line in script_text().splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_dashboard_script_exists():
    print("script path:", SCRIPT)
    assert SCRIPT.is_file()


def test_the_default_path_is_the_production_server_not_the_dev_server():
    code = script_code()
    # The production entry and the pinned preset are both required: the entry
    # does not exist under the default Cloudflare target.
    assert 'NITRO_PRESET = "node-server"' in code
    assert "server\\index.mjs" in code
    assert "bun run build" in code

    # `bun run dev` may be reached only inside the -Dev branch.
    dev_branch = code.split("if ($Dev)", 1)
    assert len(dev_branch) == 2, "the -Dev switch is gone"
    assert "bun run dev" not in dev_branch[0]


def test_the_dev_switch_is_still_available():
    code = script_code()
    assert "param([switch]$Dev)" in code
    assert "bun run dev" in code.split("if ($Dev)", 1)[1]


def test_the_address_stays_port_8080():
    text = script_text()
    assert '$env:PORT = "8080"' in text
    assert "http://localhost:8080/" in text


def test_a_stale_or_missing_build_is_rebuilt():
    text = script_text()
    # 2r item 3: missing .output, or anything under src newer than the build.
    assert ".output is missing" in text
    assert "LastWriteTime" in text
    assert "-Recurse" in text


def test_the_runbook_says_the_gala_uses_the_production_dashboard():
    """16 section 2r item 3: the runbook says the gala uses the default."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "production build" in text
    assert "(production)" in text
    # The operator has to be able to spot the wrong one from the window text.
    assert "DEVELOPMENT server, not for the gala" in text
    assert "-Dev" in text


def test_the_runbook_carries_no_secret():
    text = RUNBOOK.read_text(encoding="utf-8")
    for forbidden in ("AIza", "host-spec", "HOST-HANDOFF", "AGENT-STATE"):
        assert forbidden not in text, forbidden


def test_the_script_reads_no_configuration_and_names_no_secret():
    text = script_text()
    for forbidden in ("AIza", ".env", "OPERATOR_TOKEN", "GEMINI_API_KEY"):
        assert forbidden not in text.replace(
            "never prints or echoes any .env file", ""
        ), forbidden


# ------------------- 16 section 2x item 4(d): stopping both halves


def test_the_stop_script_exists_and_stops_both_ports():
    """Closing the two windows start-all.ps1 opens leaves both servers running.

    The 7h check found python still listening on 8000 and node on 8080 after
    both windows had been stopped, so this script exists to stop the processes
    themselves. It is read as text; nothing here stops anything.
    """
    assert STOP_ALL.is_file()
    text = STOP_ALL.read_text(encoding="utf-8")

    assert "Get-NetTCPConnection" in text
    assert "-State Listen" in text
    assert "Stop-Process" in text
    assert "OwningProcess" in text
    # Both ports, and a line for each outcome.
    assert "8000, 8080" in text or "8000,8080" in text
    assert "stopped $name (pid $id) on $port" in text
    assert 'nothing listening on $port' in text


def test_the_stop_script_reads_no_configuration_and_names_no_secret():
    text = STOP_ALL.read_text(encoding="utf-8")
    for forbidden in ("AIza", "OPERATOR_TOKEN", "GEMINI_API_KEY"):
        assert forbidden not in text, forbidden
    # The only mention of .env is the comment promising never to open it.
    assert text.count(".env") == 1
    assert "backend/.env is never opened" in text


def test_start_all_points_at_the_stop_script():
    lines = [
        line.strip() for line in START_ALL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert 'Write-Host "To stop both: scripts\\stop-all.ps1"' in lines[-1]
    assert "Close either window to stop that half." not in START_ALL.read_text(
        encoding="utf-8"
    )


def test_the_runbook_says_how_to_stop_and_carries_the_visit_protocol():
    """16 section 2x item 4(d): the stop script, 21 Part D and 21 Part E.

    The Vice Chancellor's name is deliberately not in the runbook: THE HOST
    carries it in its own instruction (21 Part E item 7).
    """
    text = RUNBOOK.read_text(encoding="utf-8")

    assert ".\\scripts\\stop-all.ps1" in text
    assert "Closing the two windows is not enough" in text
    # Part D, the confirmed roles.
    assert "Operator and project lead" in text
    assert "Kitchen and orders" in text
    assert "Guests, display and backup" in text
    assert "share the one laptop for the order statuses" in text
    # Part E, the visit.
    assert "When the Vice Chancellor comes" in text
    assert "Sir, please speak to THE HOST." in text
    assert "on the house" in text
    assert "Rehman Ayoub would be glad to answer" in text
    assert "THE HOST is never asked to judge who someone is" in text
    # Item 7 without the name itself.
    assert "Rauf" not in text


def test_the_runbook_carries_the_phase_7k_rules():
    """16 §2ze item 7: the posters, always Cash or QR, and the name rule."""
    text = RUNBOOK.read_text(encoding="utf-8")
    # Read with the line wraps removed: these are sentences, not single lines.
    unwrapped = " ".join(text.split())

    # The posters: where they go, what they must carry, and the order.
    assert "backend\\data\\posters\\" in text
    assert "1920×1080 landscape, one picture per poster" in unwrapped
    assert "shown in file-name order" in unwrapped
    assert "01-burgers.jpg" in text
    # Cash or QR, and what the operator sees if neither is sent.
    assert "**Always Cash or QR.**" in unwrapped
    assert "Choose Cash or QR." in unwrapped
    # The name rule, and the quiet cancel for a prank. 21 Part E item 7, and
    # still without the name itself.
    assert "The name rule" in unwrapped
    assert "by that name alone" in unwrapped
    assert "Rehman cancels the order quietly on the dashboard" in unwrapped
    assert "Nobody else is on the house, and the system enforces it" in unwrapped
    for name in ("Rauf", "Azam"):
        assert name not in text, name
