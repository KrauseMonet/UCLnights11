"""The tournament on the real deck: format, draw rules and the honours."""

from collections import Counter

import pytest

from game.deck import load_deck
from game.draft import Pick, replay, why_not
from game.tournament import Side, best_xi, leaders, league_of, play_tournament


@pytest.fixture(scope="module")
def cup():
    deck = load_deck()
    moves, s = [], replay(deck, 2024, "433", [])
    while not s.complete:
        moves.append(Pick(next(i for i, c in enumerate(s.deal.cards)
                               if why_not(c, s.formation, s.picks) is None)))
        s = replay(deck, 2024, "433", moves)
    you = Side("YOU", "Your XI", "YOU", "#c9a227", "#0b1026", s.formation, s.picks, you=True)
    return play_tournament(deck, league_of(deck), 2024, you)


def test_thirty_two_sides_and_no_club_twice(cup):
    assert len(cup.sides) == 32
    clubs = [s.club for s in cup.sides if s.club]
    assert len(clubs) == len(set(clubs)) == 31


def test_every_side_plays_six_group_matches(cup):
    played = Counter()
    for f in cup.fixtures:
        if f.stage == "Group stage":
            played[id(f.home)] += 1
            played[id(f.away)] += 1
    assert set(played.values()) == {6} and len(played) == 32


def test_round_of_16_pairs_winners_with_runners_up_from_other_groups(cup):
    winners = {id(cup.tables[g][0].side): g for g in cup.tables}
    runners = {id(cup.tables[g][1].side): g for g in cup.tables}
    ties = [t for t in cup.ties if t.stage == "Round of 16"]
    assert len(ties) == 8
    for t in ties:
        assert id(t.a) in runners and id(t.b) in winners      # runner-up hosts the first leg
        assert runners[id(t.a)] != winners[id(t.b)]


def test_each_round_halves_the_field_and_the_final_names_the_champion(cup):
    sizes = [sum(1 for t in cup.ties if t.stage == s) for s in
             ("Round of 16", "Quarter-finals", "Semi-finals", "Final")]
    assert sizes == [8, 4, 2, 1]
    assert cup.champion is cup.ties[-1].winner
    assert cup.reached(cup.champion) == "Champions"


def test_a_two_legged_tie_goes_to_the_side_ahead_on_aggregate_or_on_penalties(cup):
    for t in cup.ties:
        if len(t.legs) != 2:
            continue
        a, b = t.aggregate()
        pens = t.legs[1].result.pens
        if pens is None:
            assert a != b
            assert t.winner is (t.a if a > b else t.b)
        else:
            assert a == b
            # The second leg is hosted by b, so pens[0] is b's.
            assert t.winner is (t.b if pens[0] > pens[1] else t.a)


def test_best_xi_fills_a_formation_from_rated_players_only():
    deck = load_deck()
    for cs in deck.club_seasons:
        f, xi = best_xi(cs)
        assert Counter(c.pos for c in xi) == Counter(f.lines)
        assert all(c in cs.cards for c in xi)


def test_scorers_are_counted_per_side_not_per_person(cup):
    rows = leaders(cup, "goals", 1000)
    total = sum(f.result.home_goals + f.result.away_goals for f in cup.fixtures)
    assert sum(n for *_, n in rows) == total
    assert len({(c.id, id(s)) for c, s, _ in rows}) == len(rows)
