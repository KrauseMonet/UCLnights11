"""The deck build: the ratings format, and the refusals that keep a card honest."""

import json

import pytest

from etl import deck as build
from etl.deck import BuildError, fields_xi, parse_ratings


def test_ratings_file_is_read_by_club():
    clubs, errors = parse_ratings(
        "// a comment\n# Liverpool F.C.\nSteven Gerrard|91\nLuis García (footballer, born 1978)|82|MF\n",
        "2004.txt")
    assert errors == []
    assert clubs["Liverpool F.C."]["Steven Gerrard"] == (91, None)
    assert clubs["Liverpool F.C."]["Luis García (footballer, born 1978)"] == (82, "MF")


@pytest.mark.parametrize("line, fragment", [
    ("Steven Gerrard|ninety", "not an integer"),
    ("Steven Gerrard|0", "outside"),
    ("Steven Gerrard|91|WINGER", "position"),
    ("Steven Gerrard", "expected"),
])
def test_bad_ratings_are_refused(line, fragment):
    _, errors = parse_ratings(f"# Liverpool F.C.\n{line}\n", "x.txt")
    assert errors and fragment in errors[0]


def test_a_player_before_any_club_is_refused():
    _, errors = parse_ratings("Steven Gerrard|91\n", "x.txt")
    assert errors and "header" in errors[0]


def test_a_player_rated_twice_is_refused():
    _, errors = parse_ratings("# Liverpool F.C.\nSteven Gerrard|91\nSteven Gerrard|90\n", "x.txt")
    assert errors and "twice" in errors[0]


def test_fields_xi_needs_a_whole_formation():
    assert fields_xi({"GK": 1, "DF": 4, "MF": 3, "FW": 3})
    assert fields_xi({"GK": 1, "DF": 3, "MF": 5, "FW": 2})        # 3-5-2
    assert not fields_xi({"GK": 0, "DF": 6, "MF": 6, "FW": 6})    # nobody in goal
    assert not fields_xi({"GK": 1, "DF": 2, "MF": 9, "FW": 9})


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """A one-squad world: squads.json, clubs.csv and a ratings folder."""
    players = [{"id": f"Q{i}", "title": t, "pos": p, "nation": "ENG"} for i, (t, p) in enumerate(
        [("Keeper", "GK")] + [(f"Back {i}", "DF") for i in range(4)]
        + [(f"Mid {i}", "MF") for i in range(3)] + [(f"Fwd {i}", "FW") for i in range(3)])]
    (tmp_path / "squads.json").write_text(json.dumps({"squads": [
        {"season": 2004, "club": "Test F.C.", "article": "2004–05 Test F.C. season", "players": players}]}))
    (tmp_path / "clubs.csv").write_text("title,name,short,primary,secondary\nTest F.C.,Test,TST,#000000,#FFFFFF\n")
    (tmp_path / "ratings").mkdir()
    monkeypatch.setattr(build, "SQUADS", tmp_path / "squads.json")
    monkeypatch.setattr(build, "CLUBS", tmp_path / "clubs.csv")
    monkeypatch.setattr(build, "RATINGS", tmp_path / "ratings")
    return tmp_path, [p["title"] for p in players]


def write_ratings(root, titles, extra=""):
    (root / "ratings" / "2004.txt").write_text(
        "# Test F.C.\n" + "".join(f"{t}|80\n" for t in titles) + extra)


def test_a_rated_squad_that_can_field_an_eleven_enters_the_deck(sources):
    root, titles = sources
    write_ratings(root, titles)
    deck = build.build()
    assert [s["key"] for s in deck["club_seasons"]] == ["2004-TST"]
    assert len(deck["club_seasons"][0]["players"]) == 11


def test_a_rating_for_a_player_not_in_the_squad_is_refused(sources):
    # The check that caught "Alessandro" Tacchinardi (it is Alessio) and Raúl Bravo.
    root, titles = sources
    write_ratings(root, titles, "Someone Else|85\n")
    with pytest.raises(BuildError, match="not in the squad"):
        build.build()


def test_a_squad_that_cannot_field_an_eleven_is_left_out_and_reported(sources):
    root, titles = sources
    write_ratings(root, titles[1:])   # no goalkeeper rated
    deck = build.build()
    assert deck["club_seasons"] == []
    assert deck["skipped"] and "cannot field" in deck["skipped"][0]


def test_the_committed_deck_is_current():
    """data/deck.json is regenerated from its inputs, so a stale one serves old ratings."""
    assert build.OUT.read_text() == build.serialise(build.build())
