"""Phase 5: the README is a committed, public document (16 section 2e item 8).

These guard the two things that would actually hurt: a secret or an internal
planning reference reaching GitHub, and a missing section.
"""

import re
import subprocess
from pathlib import Path

import config


REPO_ROOT = config.BASE_DIR.parent
README = REPO_ROOT / "README.md"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_the_readme_exists_at_the_repository_root():
    print("README path:", README)
    assert README.is_file()
    assert len(readme_text()) > 2000


def test_the_readme_carries_no_secret_and_no_internal_reference():
    text = readme_text()
    for forbidden in ("AIza", "token=", "host-spec", "HOST-HANDOFF", "AGENT-STATE"):
        print(f"{forbidden!r} present:", forbidden in text)
        assert forbidden not in text
    # No license claim: that decision is not the code's to make.
    assert not re.search(r"\blicen[cs]e\b", text, re.IGNORECASE)


def test_the_readme_has_every_required_section():
    headings = [line.strip() for line in readme_text().splitlines() if line.startswith("#")]
    for heading in headings:
        print("heading:", heading)
    required = (
        "# THE HOST",
        "## What it does",
        "## Key features",
        "## Architecture",
        "## How it works",
        "## Tech stack",
        "## Getting started (Windows)",
        "## Configuration",
        "## REST and WebSocket reference",
        "## Testing",
        "## Reliability, privacy and security",
        "## Project structure",
        "## Roadmap",
        "## Credits",
    )
    for heading in required:
        assert heading in headings, f"missing section: {heading}"
    assert "```mermaid" in readme_text()


def test_the_readme_documents_every_env_variable():
    text = readme_text()
    example = (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")
    names = [line.split("=", 1)[0] for line in example.splitlines() if "=" in line]
    print("variables in .env.example:", names)
    for name in names:
        assert f"`{name}`" in text, f"{name} is not in the configuration table"


def test_the_readme_is_not_git_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "README.md"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    # git check-ignore exits 1 when the path is NOT ignored.
    print("git check-ignore exit code:", result.returncode)
    assert result.returncode == 1


def test_the_readme_names_the_whole_team():
    text = readme_text()
    for name in ("Rehman Ayoub", "Saad Saleem", "Umair Saddiqui"):
        assert name in text
    assert "Government College University Faisalabad" in text
    # The Phase 5f README: the supervisor and the campus too.
    assert "## Team" in text
    assert "Ma'am Marva" in text
    assert "Department of Computer Science" in text
    assert "Samundri Campus" in text


def test_the_readme_is_the_final_public_one():
    """16 §2ze item 7: the final README, for a public repository."""
    text = readme_text()

    # The formal title and the tagline. The title is read with its line wrap
    # removed, because it is too long for one line of the file.
    unwrapped = " ".join(text.split())
    assert (
        "A Real-Time Multimodal Agentic AI Host for Intelligent Customer Interaction "
        "and Order Management" in unwrapped
    )
    assert "See. Understand. Act." in text
    # The two-screen stall.
    assert "## The stall: two screens" in text
    # The features this phase and the last few added.
    assert "## The menu and the posters" in text
    assert "backend/data/posters/" in text
    assert "1920×1080 landscape, one picture per poster, shown in file-name order" in text
    assert "Collected · Cash" in text or "`CASH` or `QR`" in text
    assert "GET /api/posters" in text
    assert "Download today's sales (CSV)" in text
    # The guest-of-honour rule, without ever naming him.
    assert "decided in code, not in a prompt" in text
    assert "Rauf" not in text
    # The team, the supervisor and the credit.
    assert "Lovable" in text


def test_the_readme_carries_the_real_test_counts():
    """16 §2ze item 7: "the real counts after this phase", not a round number."""
    text = readme_text()

    assert "**890 backend tests and 237 dashboard tests pass.**" in text


def test_the_readme_describes_the_phase_5f_reliability_work():
    text = readme_text()
    # 2k item 2's window, 2k item 3's status, 2l item 3's names, 2l item 4.
    assert "thirty seconds" in text
    assert "Reconnecting" in text
    assert "number 5 for Rehman is ready!" in text
    assert "cancelled as abandoned" in text


def test_the_readme_describes_pay_first_and_the_7l_controls():
    """16 §2zf item 9: the README is the public record of how the stall runs."""
    text = readme_text()
    unwrapped = " ".join(text.split())

    # Pay first, in the order it really happens.
    assert "Shall I place it — cash or QR?" in unwrapped
    assert "**Paid · Cash** or **Paid · QR**" in unwrapped
    assert "Only that press sends it to the kitchen" in unwrapped
    assert "cancelled by itself after ten minutes" in unwrapped
    # Collection is one button again.
    assert "is one **Collected**" in unwrapped

    # The note box, and that it is never spoken or stored.
    assert "without ever reading it out or mentioning it" in unwrapped
    assert "Operator note sent" in unwrapped

    # The TV's own script and the dashboard's reload.
    assert "open-display.ps1" in text
    assert "Reload display screen" in unwrapped
    assert "`POST /api/session/note`" in text
    assert "`POST /api/display/reload`" in text
    assert "`display_reload`" in text

    # A returning guest.
    assert "returning guest is welcomed back" in unwrapped
