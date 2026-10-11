"""Players' tournaments and the journey card's numbers (C27)."""

import random

import pytest

from game import journey, match
from game.deck import load_deck
from game.formations import FORMATIONS
from game.match import PlayerLine
from game.tournament import Fixture, Side, Tournament, best_xi, league_of, play_tournament
from tests.test_match import card, eleven

LEAGUE = match.League(attack=80.0, defence=80.0)


def line(pos, **kw):
    return PlayerLine(card(pos), **kw)


def test_a_quiet_draw_is_the_base_mark():
    assert journey.match_mark(line("FW"), 0, 0, 1, "d") == journey.MARK_BASE


def test_goals_assists_and_clean_sheets_raise_a_mark_and_it_stays_in_range():
    quiet = journey.match_mark(line("FW"), 0, 0, 1, "d")
    assert journey.match_mark(line("FW", shots=1, on_target=1), 1, 0, 1, "d") > quiet
    assert journey.match_mark(line("FW"), 0, 1, 1, "d") > quiet
    keeper = journey.match_mark(line("GK", saves=4), 0, 0, 0, "w")
    assert keeper > journey.match_mark(line("GK", saves=4), 0, 0, 2, "w")
    assert journey.match_mark(line("FW", shots=9, on_target=9), 9, 0, 0, "w") == journey.MARK_RANGE[1]
    assert journey.match_mark(line("GK"), 0, 0, 12, "l") == journey.MARK_RANGE[0]


def test_a_player_with_almost_no_passes_is_not_marked_on_accuracy():
    few = line("FW", passes=3, completed=0)
    assert journey.match_mark(few, 0, 0, 1, "d") == journey.match_mark(line("FW"), 0, 0, 1, "d")


def _tournament_of(fixtures, sides):
    t = Tournament(sides, {}, {})
    t.fixtures = fixtures
    return t


def test_one_man_on_two_sides_is_two_rows():
    # A friend drafted him and his real club was drawn: his numbers must not be added.
    shared = card("FW", 90, 9)
    xa = eleven()[:-1] + [shared]
    xb = eleven(85)[:-1] + [shared]
    a = Side("A", "A", "A", FORMATIONS["433"], xa)
    b = Side("B", "B", "B", FORMATIONS["433"], xb)
    r = match.play(random.Random(4), xa, xb, LEAGUE)
    totals = journey.player_totals(_tournament_of([Fixture("Final", a, b, r, "Final")], [a, b]))
    assert (id(a), shared.id) in totals and (id(b), shared.id) in totals
    assert totals[(id(a), shared.id)].side is a and totals[(id(b), shared.id)].side is b
    assert len(totals) == 22


@pytest.fixture(scope="module")
def real():
    deck = load_deck()
    league = league_of(deck)
    f, xi = best_xi(deck.club_seasons[40])
    you = Side("YOU", "Your XI", "YOU", f, xi, you=True)
    t = play_tournament(deck, league, 77, you)
    return t, you, journey.player_totals(t)


def test_a_journey_adds_up_to_its_matches(real):
    t, you, totals = real
    j = journey.journey(t, you, totals)
    mine = [f for f in t.fixtures if you in (f.home, f.away)]
    assert len(j.matches) == len(mine) and sum(j.record) == len(mine)
    assert j.reached == t.reached(you)
    assert sum(p.goals for p in j.players) == j.goals_for
    assert all(p.apps == len(mine) for p in j.players)
    assert sum(p.minutes for p in j.players) == 11 * sum(120 if f.result.extra_time else 90 for f in mine)
    assert j.shots == sum(p.shots for p in j.players)
    assert [p.card.pos for p in j.players] == sorted((p.card.pos for p in j.players), key=journey.LINE_ORDER.get)


def test_every_goal_in_a_tournament_is_somebody_s(real):
    t, _, totals = real
    assert sum(p.goals for p in totals.values()) == sum(f.result.home_goals + f.result.away_goals for f in t.fixtures)
    assert sum(p.assists for p in totals.values()) == sum(1 for f in t.fixtures for g in f.result.goals if g.assist)


def test_no_award_for_nobody():
    xi = eleven()
    a = Side("A", "A", "A", FORMATIONS["433"], xi)
    b = Side("B", "B", "B", FORMATIONS["433"], eleven())
    r = match.Result(stats=match.match_stats(xi, b.xi, 1.0, 1.0, match.Result(), True))
    t = _tournament_of([Fixture("Final", a, b, r, "Final")], [a, b])
    t.ties = []
    t.champion = a
    j = journey.journey(t, a)
    assert j.top(lambda p: p.goals) is None and j.top(lambda p: p.assists) is None
    assert j.star is not None


def test_extra_time_counts_a_hundred_and_twenty_minutes():
    xa, xb = eleven(), eleven()
    a = Side("A", "A", "A", FORMATIONS["433"], xa)
    b = Side("B", "B", "B", FORMATIONS["433"], xb)
    r = next(r for seed in range(500)
             for r in [match.play(random.Random(seed), xa, xb, LEAGUE, neutral=True, extra_time_if_level=True)]
             if r.extra_time)
    totals = journey.player_totals(_tournament_of([Fixture("Final", a, b, r, "Final")], [a, b]))
    assert {p.minutes for p in totals.values()} == {120}


def test_a_knockout_play_off_is_a_knockout_on_the_journey():
    """The form strip rings knockout matches; the league phase's play-offs are one (C50)."""
    deck = load_deck()
    league = league_of(deck)
    f, xi = best_xi(deck.club_seasons[40])
    you = Side("YOU", "Your XI", "YOU", f, xi, you=True)
    for seed in range(40):
        t = play_tournament(deck, league, seed, you, fmt="league")
        lines = journey.journey(t, you).matches
        if any(m.fixture.stage == "Knockout play-offs" for m in lines):
            break
    else:
        pytest.fail("no tournament put this side in the play-offs")
    assert [m.knockout for m in lines] == [m.fixture.stage != "League phase" for m in lines]
