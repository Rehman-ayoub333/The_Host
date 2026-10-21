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


def test_the_script_reads_no_configuration_and_names_no_secret():
    text = script_text()
    for forbidden in ("AIza", ".env", "OPERATOR_TOKEN", "GEMINI_API_KEY"):
        assert forbidden not in text.replace(
            "never prints or echoes any .env file", ""
        ), forbidden
