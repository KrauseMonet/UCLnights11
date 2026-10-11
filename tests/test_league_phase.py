"""The league phase (C50): the draw's rules on made-up sides, the fixture list's
principles, the table's tie-breakers, and the knockout bracket on real tournaments."""

import random
from collections import Counter
from types import SimpleNamespace

import pytest

from game import league_phase as lp
from game.deck import load_deck
from game.draft import Pick, replay, why_not
from game.tournament import (LEAGUE, LEAGUE_STAGES, MAX_PER_ASSOCIATION, PLAYOFFS, Fixture, Side,
                             league_of, league_table, play_room, play_tournament)

DECK = load_deck()
LEAGUE_MODEL = league_of(DECK)

# A mix of associations like a real draw's: five each from the big five, then smaller.
MIX = (["ENG"] * 5 + ["ESP"] * 5 + ["GER"] * 5 + ["ITA"] * 5 + ["FRA"] * 5 + ["POR"] * 3
       + ["NED"] * 2 + ["GRE"] * 2 + ["UKR"] * 2 + [None] * 2)


def made_up(seed: int):
    rng = random.Random(seed)
    assoc = MIX[:]
    rng.shuffle(assoc)
    strength = [rng.random() for _ in assoc]
    return strength, assoc, lp.pots(strength, assoc)


def opponents(matches, t):
    return [a if h == t else h for h, a in matches if t in (h, a)]


@pytest.mark.parametrize("seed", range(6))
def test_each_side_plays_one_home_and_one_away_from_every_pot(seed):
    _, assoc, pot = made_up(seed)
    matches = lp.draw(random.Random(seed), pot, assoc)
    assert len(matches) == 144
    for t in range(36):
        assert len(set(opponents(matches, t))) == 8                     # eight different opponents
        for q in range(4):
            assert sum(1 for h, a in matches if h == t and pot[a] == q) == 1
            assert sum(1 for h, a in matches if a == t and pot[h] == q) == 1


@pytest.mark.parametrize("seed", range(6))
def test_no_club_meets_its_own_association_or_three_of_one(seed):
    _, assoc, pot = made_up(seed)
    matches = lp.draw(random.Random(seed), pot, assoc)
    for t in range(36):
        met = Counter(assoc[o] for o in opponents(matches, t) if assoc[o])
        assert assoc[t] is None or assoc[t] not in met
        assert max(met.values()) <= lp.MAX_FROM_ONE                   # a drafted eleven too


def test_a_draw_with_no_solution_is_refused_not_relaxed(monkeypatch):
    """Five of one association in a pot: each needs two opponents from it among four who
    can take eight such matches. The draw must say so, never quietly drop a rule."""
    monkeypatch.setattr(lp, "ATTEMPTS", 3)
    assoc = ["ITA"] * 5 + [None] * 31
    pot = [0] * 9 + [1] * 9 + [2] * 9 + [3] * 9
    with pytest.raises(lp.DrawFailed):
        lp.draw(random.Random(1), pot, assoc)


def test_pots_are_nine_strongest_first_with_at_most_four_of_one_association():
    assoc = ["ITA"] * 5 + [None] * 31
    strength = [100 - i for i in range(36)]                # the five Italians are the five strongest
    pot = lp.pots(strength, assoc)
    assert Counter(pot) == {0: 9, 1: 9, 2: 9, 3: 9}
    assert pot[:4] == [0, 0, 0, 0] and pot[4] == 1         # the fifth waits for the next pot
    assert pot[5:10] == [0] * 5 and pot[10] == 1           # the next five strongest fill pot 1


def test_five_of_one_association_at_the_bottom_are_split_too():
    assoc = [None] * 31 + ["GRE"] * 5
    strength = [100 - i for i in range(36)]                # the five Greeks are the five weakest
    pot = lp.pots(strength, assoc)
    assert Counter(pot) == {0: 9, 1: 9, 2: 9, 3: 9}
    assert Counter(pot[i] for i in range(31, 36)) == {3: 4, 2: 1}


@pytest.mark.parametrize("seed", range(6))
def test_the_fixture_list_keeps_every_principle(seed):
    _, assoc, pot = made_up(seed)
    matches, days = lp.fixtures(random.Random(seed), pot, assoc)
    assert len(days) == 8 and sorted(m for d in days for m in d) == sorted(matches)
    for t in range(36):
        venues = []
        for day in days:
            [(h, a)] = [m for m in day if t in m]                      # once each matchday
            venues.append(lp.HOME if h == t else lp.AWAY)
        assert venues[0] != venues[1] and venues[6] != venues[7]
        assert all(len(set(venues[i:i + 3])) == 2 for i in range(6))  # never three in a row


def test_venue_ok_is_the_regulations():
    H, A = lp.HOME, lp.AWAY
    assert not lp.venue_ok((H,), H, 1) and lp.venue_ok((H,), A, 1)        # matchdays 1-2
    assert not lp.venue_ok((H, A), A, 7) and lp.venue_ok((A, A), H, 7)    # matchdays 7-8
    assert not lp.venue_ok((A, A), A, 4) and lp.venue_ok((H, A), A, 4)    # three in a row


def test_the_draw_is_a_pure_function_of_its_seed():
    _, assoc, pot = made_up(3)
    assert lp.fixtures(random.Random(9), pot, assoc) == lp.fixtures(random.Random(9), pot, assoc)


# -- the table ---------------------------------------------------------------

def side(key):
    return SimpleNamespace(key=key)


def fx(home, away, hg, ag):
    return Fixture(LEAGUE, home, away, SimpleNamespace(home_goals=hg, away_goals=ag), "Matchday 1")


def ranked(sides, fixtures):
    return [r.side.key for r in league_table(sides, fixtures, random.Random(0))]


def rows(sides, fixtures):
    return {r.side.key: r for r in league_table(sides, fixtures, random.Random(0))}


def level(r, x, y, *fields):
    return all(getattr(r[x], f) == getattr(r[y], f) for f in fields) and r[x].gf - r[x].ga == r[y].gf - r[y].ga


def test_level_on_points_and_goals_away_goals_decide():
    a, b, x, y, z = (side(k) for k in "abxyz")
    # a: D 2-2 away, L 0-1 home, W 1-0 home; b: W 1-0 away, D 2-2 home, L 0-1 home. Level
    # on points, goal difference, goals and wins; a scored more away, b won more away, so
    # the later rule would put b first if away goals were not asked first.
    fixtures = [fx(x, a, 2, 2), fx(a, y, 0, 1), fx(a, z, 1, 0),
                fx(y, b, 0, 1), fx(b, x, 2, 2), fx(b, z, 0, 1)]
    r = rows([a, b, x, y, z], fixtures)
    assert level(r, "a", "b", "points", "gf", "won")
    assert r["a"].away_gf > r["b"].away_gf and r["a"].away_won < r["b"].away_won
    order = ranked([a, b, x, y, z], fixtures)
    assert order.index("a") < order.index("b")


def test_then_wins():
    w1, w2, o1, o2, o3 = (side(k) for k in ("w1", "w2", "o1", "o2", "o3"))
    fixtures = [fx(w1, o1, 1, 0), fx(w1, o2, 0, 1), fx(o3, w1, 1, 1), fx(w1, o3, 0, 0),   # W L D D
                fx(o3, w2, 1, 1), fx(w2, o1, 1, 1), fx(w2, o2, 0, 0), fx(w2, o1, 0, 0), fx(w2, o2, 0, 0)]
    r = rows([w1, w2, o1, o2, o3], fixtures)
    assert level(r, "w1", "w2", "points", "gf", "away_gf") and r["w1"].won > r["w2"].won
    order = ranked([w1, w2, o1, o2, o3], fixtures)
    assert order.index("w1") < order.index("w2")


def test_then_away_wins():
    a, b, p, q = side("a"), side("b"), side("p"), side("q")
    fixtures = [fx(a, p, 1, 0), fx(q, a, 0, 1), fx(a, q, 1, 2),       # W home, W away, L home
                fx(b, p, 1, 0), fx(b, q, 1, 0), fx(q, b, 2, 1)]       # W home, W home, L away
    r = rows([a, b, p, q], fixtures)
    assert level(r, "a", "b", "points", "gf", "away_gf", "won") and r["a"].away_won > r["b"].away_won
    order = ranked([a, b, p, q], fixtures)
    assert order.index("a") < order.index("b")


def test_level_on_everything_of_their_own_the_opponents_decide():
    a, b, strong, weak, filler = (side(k) for k in ("a", "b", "strong", "weak", "filler"))
    # a and b each beat one opponent 1-0 at home; a's opponent then wins twice elsewhere.
    fixtures = [fx(a, strong, 1, 0), fx(b, weak, 1, 0),
                fx(strong, filler, 3, 0), fx(strong, weak, 3, 0)]
    order = ranked([a, b, strong, weak, filler], fixtures)
    assert order.index("a") < order.index("b")


# -- real tournaments ------------------------------------------------------------

def you(seed=2024):
    s = replay(DECK, seed, "433", [])
    moves = []
    while not s.complete:
        moves.append(Pick(next(i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None)))
        s = replay(DECK, seed, "433", moves)
    return Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)


@pytest.fixture(scope="module")
def cups():
    return [play_tournament(DECK, LEAGUE_MODEL, seed, you(), fmt="league") for seed in (1, 2, 3)]


def test_thirty_five_clubs_at_most_five_of_one_association(cups):
    for t in cups:
        clubs = [s for s in t.sides if not s.you]
        assert len(t.sides) == 36 and len({s.club for s in clubs}) == 35
        assert max(Counter(s.association for s in clubs).values()) <= MAX_PER_ASSOCIATION


def test_everyone_plays_eight_league_matches_and_the_table_ranks_all_36(cups):
    for t in cups:
        league = [f for f in t.fixtures if f.stage == LEAGUE]
        assert len(league) == 144 and len(t.table) == 36
        assert Counter(id(s) for f in league for s in (f.home, f.away)) == Counter({id(s): 8 for s in t.sides})
        assert [f.label for f in league] == sorted((f.label for f in league), key=lambda x: int(x.split()[-1]))


def test_the_play_offs_are_ninth_to_24th_by_section_and_the_seed_hosts_the_second_leg(cups):
    for t in cups:
        pos = {id(r.side): i + 1 for i, r in enumerate(t.table)}
        ties = [x for x in t.ties if x.stage == PLAYOFFS]
        assert sorted(pos[id(s)] for x in ties for s in (x.a, x.b)) == list(range(9, 25))
        for x in ties:
            seed, guest = pos[id(x.b)], pos[id(x.a)]
            assert 9 <= seed <= 16 and seed + guest in (32, 33, 34)       # 9/10 v 23/24 and so on
            assert x.legs[1].home is x.b
        assert {t.reached(r.side) for r in t.table[24:]} == {LEAGUE}       # 25th-36th go out
        assert all(t.reached(x.a if x.winner is x.b else x.b) == PLAYOFFS for x in ties)


def test_the_round_of_16_bracket_is_fixed_by_league_position(cups):
    feeds = {1: (15, 18), 2: (15, 18), 3: (13, 20), 4: (13, 20), 5: (11, 22), 6: (11, 22), 7: (9, 24), 8: (9, 24)}
    for t in cups:
        pos = {id(r.side): i + 1 for i, r in enumerate(t.table)}
        playoff_tie = {id(x.winner): x for x in t.ties if x.stage == PLAYOFFS}
        last16 = [x for x in t.ties if x.stage == "Round of 16"]
        assert sorted(pos[id(x.b)] for x in last16) == list(range(1, 9))   # the top eight host the second leg
        for x in last16:
            lo, hi = feeds[pos[id(x.b)]]
            came = playoff_tie[id(x.a)]
            assert {pos[id(came.a)], pos[id(came.b)]} <= set(range(lo, lo + 2)) | set(range(hi - 1, hi + 1))
        halves = {pos[id(x.b)]: x.half for x in last16}
        assert halves[1] != halves[2] and halves[3] != halves[4] and halves[5] != halves[6] and halves[7] != halves[8]


def test_the_quarter_finals_pair_sections_a_with_d_and_b_with_c_in_each_half(cups):
    for t in cups:
        pos = {id(r.side): i + 1 for i, r in enumerate(t.table)}
        section = {}
        for x in t.ties:
            if x.stage == "Round of 16":
                section[id(x.winner)] = ("ABCD"[(pos[id(x.b)] - 1) // 2], x.half)
        for x in t.ties:
            if x.stage == "Quarter-finals":
                (sa, ha), (sb, hb) = section[id(x.a)], section[id(x.b)]
                assert ha == hb == x.half and {sa, sb} in ({"A", "D"}, {"B", "C"})
        sf = [x for x in t.ties if x.stage == "Semi-finals"]
        assert sorted(x.half for x in sf) == [0, 1]
        final = t.ties[-1]
        assert {final.a, final.b} == {x.winner for x in sf} and final.legs[0].home is sf[0].winner
        assert t.stages == LEAGUE_STAGES[1:]


def test_a_room_of_one_in_36_is_the_solo_league_tournament():
    me = you(77)
    solo = play_tournament(DECK, LEAGUE_MODEL, 77, me, fmt="league")
    room = play_room(DECK, LEAGUE_MODEL, 77, [me], 36)
    assert [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in solo.fixtures] \
        == [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in room.fixtures]


def test_a_league_tournament_is_a_pure_function_of_its_seed():
    def run():
        t = play_tournament(DECK, LEAGUE_MODEL, 5, you(5), engine=1, fmt="league")
        return [(f.stage, f.label, f.home.key, f.away.key, f.result.home_goals, f.result.away_goals)
                for f in t.fixtures]
    assert run() == run()


def test_an_unknown_format_is_refused():
    with pytest.raises(ValueError):
        play_tournament(DECK, LEAGUE_MODEL, 1, you(1), fmt="swiss")
