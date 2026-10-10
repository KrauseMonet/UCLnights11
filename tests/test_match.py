"""The match engine on hand-built elevens, where the right answer is obvious."""

import random
import statistics

import pytest

from game import match
from game.deck import Card

LEAGUE = match.League(attack=80.0, defence=80.0)


def card(pos, rating=80, n=0):
    return Card(id=f"{pos}{n}", name=f"{pos} {n}", title=f"{pos} {n}", pos=pos, nation=None,
                rating=rating, season=2004, label="2004–05", club="T", club_name="T", short="T", key="k")


def eleven(rating=80):
    return ([card("GK", rating)] + [card("DF", rating, i) for i in range(4)]
            + [card("MF", rating, i) for i in range(3)] + [card("FW", rating, i) for i in range(3)])


def test_an_average_side_scores_exactly_the_base_rate():
    xi = eleven(80)
    assert match.expected_goals(xi, xi, LEAGUE, match.BASE_HOME) == pytest.approx(match.BASE_HOME)


def test_a_better_attack_scores_more_and_a_better_defence_concedes_less():
    base = match.expected_goals(eleven(80), eleven(80), LEAGUE, 1.5)
    assert match.expected_goals(eleven(90), eleven(80), LEAGUE, 1.5) > base
    assert match.expected_goals(eleven(80), eleven(90), LEAGUE, 1.5) < base


def test_poisson_has_the_right_mean():
    rng = random.Random(1)
    draws = [match.poisson(rng, 1.7) for _ in range(40000)]
    assert statistics.mean(draws) == pytest.approx(1.7, abs=0.03)


def test_scorers_are_never_the_goalkeeper_and_goals_land_in_regulation():
    rng = random.Random(3)
    xi = eleven()
    for _ in range(300):
        r = match.play(rng, xi, xi, LEAGUE)
        assert len(r.goals) == r.home_goals + r.away_goals
        assert all(g.scorer.pos != "GK" and 1 <= g.minute <= 90 for g in r.goals)
        assert r.extra_time is False and r.pens is None


def test_extra_time_follows_the_aggregate_not_the_second_legs_own_score():
    rng = random.Random(5)
    xi = eleven()
    for _ in range(400):
        # First leg 2-0 to the side now AWAY: the tie is only level if the home side wins by two.
        r = match.play(rng, xi, xi, LEAGUE, extra_time_if_level=True, level_on=(0, 2))
        level_after_90 = r.home_goals - sum(1 for g in r.goals if g.minute > 90 and g.side == 0) \
            == r.away_goals - sum(1 for g in r.goals if g.minute > 90 and g.side == 1) + 2
        assert r.extra_time == level_after_90


def test_a_shootout_always_has_a_winner_and_stops_when_decided():
    rng = random.Random(7)
    for _ in range(2000):
        h, a = match.shootout(rng, eleven(), eleven())
        assert h != a
        assert max(h, a) <= 5 or abs(h - a) == 1   # beyond five each it is sudden death


def test_winner_reads_penalties_before_the_score():
    r = match.Result(home_goals=1, away_goals=1, pens=(3, 4))
    assert r.winner == 1
    assert match.Result(home_goals=2, away_goals=1).winner == 0
    assert match.Result(home_goals=1, away_goals=1).winner is None
