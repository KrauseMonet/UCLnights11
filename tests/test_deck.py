"""The deck build: the ratings format, and the refusals that keep a card honest."""

import json

import pytest

from etl import deck as build
from etl.deck import BuildError, measured_positions, parse_positions, parse_ratings


def test_ratings_file_is_read_by_club():
    clubs, errors = parse_ratings(
        "// a comment\n# Liverpool F.C.\nSteven Gerrard|91\nLuis García (footballer, born 1978)|82\n",
        "2004.txt")
    assert errors == []
    assert clubs["Liverpool F.C."]["Steven Gerrard"] == 91
    assert clubs["Liverpool F.C."]["Luis García (footballer, born 1978)"] == 82


@pytest.mark.parametrize("line, fragment", [
    ("Steven Gerrard|ninety", "not an integer"),
    ("Steven Gerrard|0", "outside"),
    ("Steven Gerrard|91|MF", "data/positions"),     # the old line column: positions moved (C35)
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


def test_declared_positions_are_read_by_club_most_played_first():
    clubs, errors = parse_positions("// x\n# Liverpool F.C.\nSteven Gerrard|CM,RM,AM\n", "2004.txt")
    assert errors == []
    assert clubs["Liverpool F.C."]["Steven Gerrard"] == ["CM", "RM", "AM"]


@pytest.mark.parametrize("line, fragment", [
    ("Steven Gerrard|CM,WINGER", "not among"),
    ("Steven Gerrard|CM,RM,AM,ST,RW", "at most 4"),
    ("Steven Gerrard|CM,CM", "twice"),
    ("Steven Gerrard|", "expected"),
])
def test_bad_declared_positions_are_refused(line, fragment):
    _, errors = parse_positions(f"# Liverpool F.C.\n{line}\n", "x.txt")
    assert errors and fragment in errors[0]


def test_measured_positions_keep_every_start_most_started_first_up_to_four():
    # Kimmich 2015-16 as Transfermarkt has him: CB 16, DM 6, CM 2, RB 1.
    assert measured_positions({"CB": 16, "DM": 6, "CM": 2, "RB": 1}) == ["CB", "DM", "CM", "RB"]
    # A fifth position is the least-started one, dropped; a single start still counts.
    assert measured_positions({"RW": 9, "CM": 1, "AM": 3, "LW": 2, "ST": 1}) == ["RW", "AM", "LW", "CM"]
    # Four is a maximum, not a target.
    assert measured_positions({"CB": 30}) == ["CB"]
    assert measured_positions({"CB": 3, "LB": 0}) == ["CB"]


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """A one-squad world: squads.json, clubs.csv, a ratings folder and positions."""
    players = [{"id": f"Q{i}", "title": t, "pos": p, "nation": "ENG"} for i, (t, p) in enumerate(
        [("Keeper", "GK")] + [(f"Back {i}", "DF") for i in range(4)]
        + [(f"Mid {i}", "MF") for i in range(3)] + [(f"Fwd {i}", "FW") for i in range(3)])]
    (tmp_path / "squads.json").write_text(json.dumps({"squads": [
        {"season": 2004, "club": "Test F.C.", "article": "2004–05 Test F.C. season", "players": players}]}))
    (tmp_path / "clubs.csv").write_text("title,name,short,primary,secondary\nTest F.C.,Test,TST,#000000,#FFFFFF\n")
    (tmp_path / "associations.json").write_text(json.dumps({"Test F.C.": "ENG"}))
    (tmp_path / "ratings").mkdir()
    (tmp_path / "positions").mkdir()
    (tmp_path / "positions" / "measured.json").write_text(json.dumps(
        {"source": {"measured_from": 2013}, "club_seasons": []}))
    monkeypatch.setattr(build, "SQUADS", tmp_path / "squads.json")
    monkeypatch.setattr(build, "CLUBS", tmp_path / "clubs.csv")
    monkeypatch.setattr(build, "ASSOCIATIONS", tmp_path / "associations.json")
    monkeypatch.setattr(build, "RATINGS", tmp_path / "ratings")
    monkeypatch.setattr(build, "POSITION_FILES", tmp_path / "positions")
    monkeypatch.setattr(build, "MEASURED", tmp_path / "positions" / "measured.json")
    return tmp_path, [p["title"] for p in players]


# A 4-3-3 for the eleven above, one position each.
FOUR_THREE_THREE = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"]


def write_ratings(root, titles, extra=""):
    (root / "ratings" / "2004.txt").write_text(
        "# Test F.C.\n" + "".join(f"{t}|80\n" for t in titles) + extra)


def write_positions(root, titles, codes=FOUR_THREE_THREE, extra=""):
    (root / "positions" / "2004.txt").write_text(
        "# Test F.C.\n" + "".join(f"{t}|{c}\n" for t, c in zip(titles, codes)) + extra)


def test_a_rated_squad_that_can_field_an_eleven_enters_the_deck(sources):
    root, titles = sources
    write_ratings(root, titles)
    write_positions(root, titles)
    deck = build.build()
    [cs] = deck["club_seasons"]
    assert cs["key"] == "2004-TST" and len(cs["players"]) == 11
    assert cs["best"]["formation"] == "433"
    assert sorted(slot for _, slot in cs["best"]["xi"]) == sorted(FOUR_THREE_THREE)
    by_id = {p["id"]: p for p in cs["players"]}
    assert all(slot in by_id[pid]["positions"] for pid, slot in cs["best"]["xi"])
    assert {p["source"] for p in cs["players"]} == {"declared"}


def test_a_player_s_line_comes_from_his_first_position(sources):
    root, titles = sources
    write_ratings(root, titles)
    write_positions(root, titles, ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "LW,ST", "ST", "CM,RW"])
    lines = {p["title"]: p["pos"] for p in build.build()["club_seasons"][0]["players"]}
    assert lines["Fwd 0"] == "FW" and lines["Fwd 2"] == "MF" and lines["Back 0"] == "DF"


def test_a_rating_for_a_player_not_in_the_squad_is_refused(sources):
    # The check that caught "Alessandro" Tacchinardi (it is Alessio) and Raúl Bravo.
    root, titles = sources
    write_ratings(root, titles, "Someone Else|85\n")
    write_positions(root, titles)
    with pytest.raises(BuildError, match="not in the squad"):
        build.build()


def test_a_rated_player_without_positions_is_refused(sources):
    root, titles = sources
    write_ratings(root, titles)
    write_positions(root, titles[:-1], FOUR_THREE_THREE[:-1])
    with pytest.raises(BuildError, match="no positions"):
        build.build()


def test_a_club_season_carries_its_association_and_one_without_is_refused(sources):
    """The league-phase draw (C50) keeps a club from its own association's clubs, so a
    club the source gives no association must not reach the deck as one with none."""
    root, titles = sources
    write_ratings(root, titles)
    write_positions(root, titles)
    [cs] = build.build()["club_seasons"]
    assert cs["association"] == "ENG"
    (root / "associations.json").write_text("{}")
    with pytest.raises(BuildError, match="no association"):
        build.build()


def test_positions_for_a_player_who_is_not_rated_are_refused(sources):
    root, titles = sources
    write_ratings(root, titles)
    write_positions(root, titles, extra="Someone Else|ST\n")
    with pytest.raises(BuildError, match="not rated"):
        build.build()


def measured_world(root, titles, starts):
    """Move the test squad to 2013-14, a measured season, with these starts per player."""
    squads = json.loads((root / "squads.json").read_text())
    squads["squads"][0]["season"] = 2013
    (root / "squads.json").write_text(json.dumps(squads))
    (root / "ratings" / "2013.txt").write_text("# Test F.C.\n" + "".join(f"{t}|80\n" for t in titles))
    (root / "positions" / "measured.json").write_text(json.dumps({"source": {"measured_from": 2013},
        "club_seasons": [{"season": 2013, "club": "Test F.C.",
                          "players": {t: {"starts": starts.get(t, {})} for t in titles}}]}))


def test_measured_starts_give_a_measured_player_his_positions(sources):
    root, titles = sources
    measured_world(root, titles, {t: {c: 5, "ST": 1} if c != "GK" else {"GK": 30}
                                  for t, c in zip(titles, FOUR_THREE_THREE)})
    [cs] = build.build()["club_seasons"]
    back = next(p for p in cs["players"] if p["title"] == "Back 0")
    assert back["positions"] == ["RB", "ST"] and back["source"] == "measured"


def test_a_declaration_cannot_override_a_measured_player(sources):
    root, titles = sources
    measured_world(root, titles, {t: {c: 5} for t, c in zip(titles, FOUR_THREE_THREE)})
    (root / "positions" / "2013.txt").write_text("# Test F.C.\nBack 0|LW\n")
    with pytest.raises(BuildError, match="measured starts"):
        build.build()


def test_a_measured_player_with_no_starts_takes_a_declared_fallback(sources):
    root, titles = sources
    starts = {t: {c: 5} for t, c in zip(titles, FOUR_THREE_THREE)}
    starts["Keeper"] = {}                     # a reserve keeper who never started
    measured_world(root, titles, starts)
    with pytest.raises(BuildError, match="no positions"):
        build.build()
    (root / "positions" / "2013.txt").write_text("# Test F.C.\nKeeper|GK\n")
    keeper = next(p for p in build.build()["club_seasons"][0]["players"] if p["title"] == "Keeper")
    assert keeper["positions"] == ["GK"] and keeper["source"] == "declared"


def test_a_squad_that_cannot_field_an_eleven_is_left_out_and_reported(sources):
    root, titles = sources
    write_ratings(root, titles)
    # Eleven men, but two left-backs and no right-back: no formation has room for both.
    write_positions(root, titles, ["GK", "LB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"])
    deck = build.build()
    assert deck["club_seasons"] == []
    assert deck["skipped"] and "cannot field" in deck["skipped"][0]


def test_the_committed_deck_is_current():
    """data/deck.json is regenerated from its inputs, so a stale one serves old ratings."""
    assert build.OUT.read_text() == build.serialise(build.build())


def test_every_club_season_in_the_deck_has_a_built_crest():
    """A crest key with no served file is a broken image on every card of that side."""
    from game.deck import load_deck
    served = build.ROOT / "web" / "static" / "crests"
    missing = sorted({cs.crest for cs in load_deck().club_seasons if not (served / f"{cs.crest}.webp").exists()})
    assert missing == []


def test_a_season_wears_its_own_crest_where_one_is_recorded():
    from game.crests import crest_key
    assert crest_key("BAY", 1994) == "BAY-1900"      # 1979-1996 crest
    assert crest_key("BAY", 1998) == "BAY-1996"
    assert crest_key("BAY", 2010) == "BAY-2002"
    assert crest_key("BAY", 2025) == "BAY"           # the current one
    assert crest_key("PSG", 2012) == "PSG-2002"      # the 2013 redesign came after 2012-13
    assert crest_key("LIV", 2004) == "LIV"           # no era recorded: the current crest


def test_club_colours_read_at_wcag_aa():
    """Computed from clubs.csv, not read from deck.json: a test of the derivation itself."""
    import csv
    from game.colours import contrast, palette
    with build.CLUBS.open(newline="", encoding="utf-8") as f:
        clubs = list(csv.DictReader(f))
    bad = []
    for c in clubs:
        p = palette(c["primary"], c["secondary"])
        if contrast(p["ink"], p["deep"]) < 4.5:
            bad.append(c["short"])
    assert bad == []


def test_a_near_white_primary_hands_over_to_the_secondary():
    from game.colours import palette
    assert palette("#FFFFFF", "#00529F")["team"] == "#00529F"     # Real Madrid: blue, not white
    assert palette("#DA291C", "#FBE122")["team"] == "#DA291C"     # Manchester United: red, not yellow
