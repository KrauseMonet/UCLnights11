"""The tournament analysis adds up to the tournament it reads (C28)."""

import pytest
from fastapi.testclient import TestClient

from game import analysis, journey
from game.deck import load_deck
from game.tournament import Side, best_xi, league_of, play_room, play_tournament
from web.app import app


@pytest.fixture(scope="module")
def solo():
    deck = load_deck()
    f, xi = best_xi(deck.club_seasons[60])
    you = Side("YOU", "Your XI", "YOU", f, xi, you=True)
    t = play_tournament(deck, league_of(deck), 31, you)
    return t, you, analysis.tournament_analysis(t, you)


def test_the_totals_are_the_tournament_s(solo):
    t, _, a = solo
    assert a.matches == len(t.fixtures) == 125
    assert a.goals == sum(f.result.home_goals + f.result.away_goals for f in t.fixtures)
    assert sum(a.goal_minutes) == a.goals
    assert sum(s.matches for s in a.stages) == a.matches and sum(s.goals for s in a.stages) == a.goals
    assert sum(a.home) == a.matches - 1                    # every match but the neutral final
    assert sum(r.gf for r in a.sides) == sum(r.ga for r in a.sides) == a.goals
    assert sum(r.shots for r in a.sides) == a.shots


def test_your_goals_by_minute_are_yours(solo):
    t, you, a = solo
    scored, conceded = a.your_minutes
    assert sum(scored) == a.you.gf and sum(conceded) == a.you.ga


def test_sides_are_listed_furthest_first(solo):
    t, _, a = solo
    assert a.sides[0].side is t.champion and a.sides[0].reached == "Champions"
    order = [analysis.REACHED_ORDER.index(r.reached) for r in a.sides]
    assert order == sorted(order)


def test_rate_boards_need_half_the_most_matches_and_passing_is_outfield(solo):
    _, _, a = solo
    most = max(p.apps for p in a.totals.values())
    assert a.min_apps == -(-most // 2)
    assert all(p.apps >= a.min_apps for p, _ in a.boards["mark"] + a.boards["accuracy"])
    assert all(p.card.pos != "GK" for p, _ in a.boards["accuracy"])
    assert all(p.card.pos == "GK" for p, _ in a.boards["saves"] + a.boards["clean_sheets"])


def test_a_board_agrees_with_the_journey_totals(solo):
    # One set of totals for every screen (the cricket site's A175).
    t, _, a = solo
    totals = journey.player_totals(t)
    for p, v in a.boards["goals"]:
        assert totals[(id(p.side), p.card.id)].goals == v
    best = max(totals.values(), key=lambda p: (p.goals, p.mark or 0))
    assert a.boards["goals"][0][1] == best.goals


def test_a_room_of_two_still_has_boards():
    # A single final: "half the most matches" is one, so the rate boards aren't empty.
    deck = load_deck()
    f, xi = best_xi(deck.club_seasons[3])
    me = Side("P0", "me", "ME", f, xi, owner=1, you=True)
    t = play_room(deck, league_of(deck), 9, [me], 2)
    a = analysis.tournament_analysis(t, me)
    assert a.matches == 1 and a.min_apps == 1 and a.boards["mark"]
    assert a.home == (0, 0, 0)


def test_the_analysis_route():
    c = TestClient(app)
    s = c.post("/api/draft", json={"seed": 12}).json()
    while not s["complete"]:
        i = next(x["i"] for x in s["deal"]["cards"] if x["takeable"])
        s = c.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    r = c.get(f"/api/tournament/{s['state']}/analysis").json()
    a = r["analysis"]
    # 144 league matches, 16 in the play-offs, 16 + 8 + 4 and the final.
    assert r["you"]["you"] and a["hero"]["matches"] == 189 and len(a["sides"]) == 36
    assert len(a["buckets"]) == len(a["goal_minutes"]) == 7
    assert sum(a["your_minutes"]["scored"]) == next(x for x in a["sides"] if x.get("you"))["gf"]
    assert c.get("/api/tournament/1-433/analysis").status_code == 409


def test_goal_minutes_fall_in_the_right_quarter_hour():
    edges = {1: 0, 15: 0, 16: 1, 30: 1, 45: 2, 46: 3, 75: 4, 76: 5, 90: 5, 91: 6, 120: 6}
    assert {m: analysis._bucket(m) for m in edges} == edges


def test_no_goalkeeper_is_ranked_for_passing_even_on_a_full_board(solo, monkeypatch):
    # Keepers make enough passes to qualify by volume, so on a board long enough to
    # hold everyone they would appear if the outfield rule were missing.
    t, you, _ = solo
    monkeypatch.setattr(analysis, "BOARD_SIZE", 10_000)
    a = analysis.tournament_analysis(t, you)
    keepers = [p for p in a.totals.values() if p.card.pos == "GK" and p.apps >= a.min_apps
               and p.passes >= analysis.MIN_PASSES_PER_MATCH * p.apps]
    assert keepers, "the test needs keepers who would otherwise qualify"
    assert all(p.card.pos != "GK" for p, _ in a.boards["accuracy"])
