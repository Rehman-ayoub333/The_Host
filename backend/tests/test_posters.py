"""Phase 7k: the posters the TV shows when nobody is talking (16 §2ze item 5).

Rehman's rule 2(d): the idle menu is full-screen pictures, no text, each one
carrying all its own information. The backend's share of that is this folder,
the `/posters` mount and `GET /api/posters`.

No picture here is a real poster: each test writes a few bytes to its own
tmp_path, outside the repository, and pytest removes them.
"""

import pytest
from fastapi.testclient import TestClient

import config
import main


# Enough of a file to be served; nothing here is a real picture.
PIXEL = b"\x89PNG\r\n\x1a\n not really a picture"

REAL_FOLDER = config.BASE_DIR / "data" / "posters"


@pytest.fixture
def posters(tmp_path, monkeypatch):
    """An empty poster folder of this test's own."""
    folder = tmp_path / "posters"
    folder.mkdir()
    monkeypatch.setattr(config, "POSTERS_DIR", folder)
    return folder


@pytest.fixture
def served(posters):
    with TestClient(main.app) as client:
        yield client


# ------------------------------------------------------- GET /api/posters


def test_the_endpoint_lists_pictures_in_file_name_order(served, posters):
    for name in ("03-drinks.webp", "01-burgers.jpg", "02-shakes.PNG", "10-team.jpeg"):
        (posters / name).write_bytes(PIXEL)

    body = served.get("/api/posters").json()
    print("GET /api/posters:", body)

    assert body == {
        "posters": [
            "/posters/01-burgers.jpg",
            "/posters/02-shakes.PNG",
            "/posters/03-drinks.webp",
            "/posters/10-team.jpeg",
        ]
    }


def test_the_endpoint_ignores_the_readme_and_anything_else(served, posters):
    (posters / "01-burgers.jpg").write_bytes(PIXEL)
    (posters / "README.txt").write_text("not a poster", encoding="utf-8")
    (posters / "notes.md").write_text("not a poster", encoding="utf-8")
    (posters / "Thumbs.db").write_bytes(b"not a poster")
    (posters / "poster.jpg.txt").write_text("not a poster", encoding="utf-8")
    (posters / "subfolder").mkdir()
    (posters / "subfolder" / "02-inside.jpg").write_bytes(PIXEL)

    body = served.get("/api/posters").json()
    print("GET /api/posters:", body)

    assert body == {"posters": ["/posters/01-burgers.jpg"]}


def test_the_folder_is_read_again_on_every_request(served, posters):
    assert served.get("/api/posters").json() == {"posters": []}

    # Rehman drops a poster in while the backend is running.
    (posters / "01-burgers.jpg").write_bytes(PIXEL)

    assert served.get("/api/posters").json() == {"posters": ["/posters/01-burgers.jpg"]}

    (posters / "01-burgers.jpg").unlink()

    assert served.get("/api/posters").json() == {"posters": []}


def test_an_empty_or_missing_folder_lists_nothing(served, posters):
    assert served.get("/api/posters").json() == {"posters": []}

    for entry in posters.iterdir():
        entry.unlink()
    posters.rmdir()

    response = served.get("/api/posters")
    assert response.status_code == 200
    assert response.json() == {"posters": []}


def test_the_endpoint_needs_no_token(served, posters):
    """Public, like /api/menu: the display has no token (2ze item 5)."""
    (posters / "01-burgers.jpg").write_bytes(PIXEL)
    response = served.get("/api/posters")

    assert response.status_code == 200
    assert "posters" in response.json()


# --------------------------------------------------------- the /posters mount


def test_the_mount_serves_a_poster(served, posters):
    (posters / "01-burgers.jpg").write_bytes(PIXEL)

    response = served.get("/posters/01-burgers.jpg")

    assert response.status_code == 200
    assert response.content == PIXEL


def test_the_mount_answers_404_for_a_poster_that_is_not_there(served, posters):
    assert served.get("/posters/99-missing.jpg").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/posters/../menu.json",
        "/posters/../../config.py",
        "/posters/..%2F..%2Fconfig.py",
        "/posters/subfolder/../../config.py",
    ],
)
def test_the_mount_rejects_a_path_outside_the_folder(served, posters, path):
    """A picture folder must not become a way to read the backend (2ze item 5)."""
    outside = posters.parent / "menu.json"
    outside.write_text('{"not": "a poster"}', encoding="utf-8")

    response = served.get(path)
    print(path, "->", response.status_code)

    assert response.status_code == 404
    assert b"not a poster" not in response.content
    assert b"not\": \"a poster" not in response.content


# ------------------------------------------- the folder that ships in the repo


def test_the_repository_ships_the_folder_with_its_readme():
    """2ze item 5: the folder is tracked in git, and says what a poster is."""
    readme = REAL_FOLDER / "README.txt"

    assert REAL_FOLDER.is_dir()
    assert readme.is_file()
    assert readme.read_text(encoding="utf-8").strip() == (
        "1920×1080 landscape, one picture per poster, shown in file-name order"
    )
