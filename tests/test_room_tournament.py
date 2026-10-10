"""A room's tournament: every size, the fillers, and the rule that humans are never
replaced or doubled. Pure: no database."""

from collections import Counter

import pytest

from game.deck import load_deck
from game.draft import Pick, replay, why_not
from game.tournament import (CUP_STAGES, ROOM_SIZES, Side, league_of, play_room,
                             play_tournament)

DECK = load_deck()
LEAGUE = league_of(DECK)


def eleven(seed, formation="433"):
    moves, s = [], replay(DECK, seed, formation, [])
    while not s.complete:
        moves.append(Pick(next(i for i, c in enumerate(s.deal.cards)
                               if why_not(c, s.formation, s.picks) is None)))
        s = replay(DECK, seed, formation, moves)
    return s


def humans(n):
    out = []
    for i in range(n):
        s = eleven(100 + i)
        out.append(Side(f"P{i}", f"friend{i}", f"F{i}", s.formation, s.picks, owner=i + 1))
    return out


@pytest.mark.parametrize("size", [2, 4, 8, 16])
@pytest.mark.parametrize("n", [1, 2])
def test_a_cup_is_a_straight_knockout_filled_with_real_sides(size, n):
    people = humans(n)
    t = play_room(DECK, LEAGUE, 5, people, size)
    assert len(t.sides) == size
    assert [s for s in t.sides if s.owner is not None] == people
    clubs = [s.club for s in t.sides if s.owner is None]
    assert len(clubs) == size - n == len(set(clubs))          # one season per club
    assert t.groups == {} and t.tables == {}
    assert t.stages == CUP_STAGES[size]
    per_round = [sum(1 for x in t.ties if x.stage == st) for st in t.stages]
    assert per_round == [size // 2 ** (i + 1) for i in range(len(t.stages))]
    assert t.champion is t.ties[-1].winner and t.ties[-1].stage == "Final"
    assert len(t.ties[-1].legs) == 1                          # the final is one match


def test_every_side_in_a_cup_plays_the_first_round():
    t = play_room(DECK, LEAGUE, 9, humans(3), 8)
    first = [x for x in t.ties if x.stage == "Quarter-finals"]
    assert Counter(id(s) for x in first for s in (x.a, x.b)) == Counter({id(s): 1 for s in t.sides})


def test_a_room_of_two_is_one_final():
    a, b = humans(2)
    t = play_room(DECK, LEAGUE, 3, [a, b], 2)
    assert len(t.fixtures) == 1 and {t.fixtures[0].home, t.fixtures[0].away} == {a, b}
    assert t.champion in (a, b)


def test_a_full_room_draws_no_real_sides():
    t = play_room(DECK, LEAGUE, 3, humans(4), 4)
    assert all(s.owner is not None for s in t.sides)


def test_a_room_of_32_plays_the_group_format():
    people = humans(3)
    t = play_room(DECK, LEAGUE, 11, people, 32)
    assert len(t.sides) == 32 and len(t.tables) == 8
    assert t.stages == ["Round of 16", "Quarter-finals", "Semi-finals", "Final"]
    played = Counter()
    for f in t.fixtures:
        if f.stage == "Group stage":
            played[id(f.home)] += 1
            played[id(f.away)] += 1
    assert all(played[id(p)] == 6 for p in people)


def test_a_room_is_a_pure_function_of_its_seed_and_elevens():
    def scores():
        t = play_room(DECK, LEAGUE, 77, humans(2), 8)
        return [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in t.fixtures]
    assert scores() == scores()


def test_the_solo_game_is_a_room_of_one_in_thirty_two():
    s = eleven(2024)
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    solo = play_tournament(DECK, LEAGUE, 2024, you)
    room = play_room(DECK, LEAGUE, 2024, [you], 32)
    assert [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in solo.fixtures] \
        == [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in room.fixtures]


@pytest.mark.parametrize("size, n", [(3, 1), (64, 1), (4, 5), (8, 0)])
def test_impossible_rooms_are_refused(size, n):
    with pytest.raises(ValueError):
        play_room(DECK, LEAGUE, 1, humans(n) if n <= 4 else humans(4) * 2, size)


def test_room_sizes_are_the_five_formats():
    assert ROOM_SIZES == (2, 4, 8, 16, 32)
