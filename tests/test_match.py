"""The match engine on hand-built elevens, where the right answer is obvious."""

import random
import statistics

import pytest

from game import match
from game.deck import Card

LEAGUE = match.League(attack=80.0, defence=80.0)


# A hand-built man plays anywhere in his line, so any 1-4-3-3 of them fills a 4-3-3.
LINE_POSITIONS = {"GK": ("GK",), "DF": ("RB", "CB", "LB"), "MF": ("DM", "CM", "AM", "RM"), "FW": ("RW", "ST", "LW")}


def card(pos, rating=80, n=0):
    return Card(id=f"{pos}{n}", name=f"{pos} {n}", title=f"{pos} {n}", pos=pos,
                positions=LINE_POSITIONS[pos], source="declared", nation=None,
                rating=rating, season=2004, label="2004–05", club="T", club_name="T", short="T", key="k", crest="T")


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


# -- match statistics (C26) ---------------------------------------------------

def strong_and_weak():
    return eleven(90), eleven(72)


def test_every_side_s_numbers_add_up():
    rng = random.Random(11)
    for i in range(400):
        h, a = strong_and_weak() if i % 2 else (eleven(), eleven())
        r = match.play(rng, h, a, LEAGUE, extra_time_if_level=i % 3 == 0)
        hs, as_ = r.stats
        assert hs.possession + as_.possession == pytest.approx(1)
        for st, scored, other, conceded in ((hs, r.home_goals, as_, r.away_goals),
                                            (as_, r.away_goals, hs, r.home_goals)):
            assert scored <= st.on_target <= st.shots
            assert 0 <= st.completed <= st.passes
            assert st.saves == other.on_target - conceded      # every shot on target is a goal or a save
            keeper = [p for p in st.players if p.card.pos == "GK"]
            assert keeper[0].saves == st.saves and keeper[0].shots == 0
            assert all(p.saves == 0 for p in st.players if p.card.pos != "GK")
        for side, st in ((0, hs), (1, as_)):
            for p in st.players:
                goals = sum(1 for g in r.goals if g.side == side and g.scorer is p.card)
                assert p.on_target >= goals


def test_the_same_match_always_has_the_same_numbers():
    h, a = strong_and_weak()
    one = match.play(random.Random(5), h, a, LEAGUE).stats
    two = match.play(random.Random(5), h, a, LEAGUE).stats
    key = lambda st: [(p.shots, p.on_target, p.passes, p.completed, p.saves) for s in st for p in s.players]  # noqa: E731
    assert key(one) == key(two) and one[0].possession == two[0].possession


def test_the_statistics_never_take_from_the_tournament_s_stream():
    # A tournament's matches share one random stream. If the statistics drew from it,
    # every later result would change and every shared link would replay differently.
    # So play() must take exactly the draws the goals need. (An earlier version of this
    # test switched the statistics off and compared tournaments; a stray draw outside
    # match_stats passed it, because both runs made it.)
    h, a = strong_and_weak()
    for seed in range(200):
        played = random.Random(seed)
        r = match.play(played, h, a, LEAGUE)
        goals_only = random.Random(seed)
        lh = match.expected_goals(h, a, LEAGUE, match.BASE_HOME)
        la = match.expected_goals(a, h, LEAGUE, match.BASE_AWAY)
        hg, ag = match.poisson(goals_only, lh), match.poisson(goals_only, la)
        match._goals(goals_only, h, hg, 0, 1, 90)
        match._goals(goals_only, a, ag, 1, 1, 90)
        assert (hg, ag) == (r.home_goals, r.away_goals)
        assert played.random() == goals_only.random(), seed


def test_a_stronger_side_has_more_of_the_ball_and_the_shots():
    rng = random.Random(2)
    h, a = strong_and_weak()
    runs = [match.play(rng, h, a, LEAGUE, neutral=True).stats for _ in range(300)]
    assert statistics.mean(s[0].possession for s in runs) > 0.6
    assert statistics.mean(s[0].shots for s in runs) > 1.5 * statistics.mean(s[1].shots for s in runs)
    assert statistics.mean(s[0].completed / s[0].passes for s in runs) > statistics.mean(s[1].completed / s[1].passes for s in runs)


def test_extra_time_means_more_of_everything():
    xi = eleven()
    normal = [match.play(random.Random(i), xi, xi, LEAGUE).stats[0] for i in range(300)]
    longer = [s for i in range(3000) for r in [match.play(random.Random(i), xi, xi, LEAGUE, extra_time_if_level=True)]
              if r.extra_time for s in [r.stats[0]]][:300]
    assert statistics.mean(s.passes for s in longer) > 1.2 * statistics.mean(s.passes for s in normal)
    assert statistics.mean(s.shots for s in longer) > 1.15 * statistics.mean(s.shots for s in normal)


# -- the shot timeline (C30) ----------------------------------------------------

def test_the_timeline_replays_to_exactly_the_statistics():
    rng = random.Random(17)
    late = 0
    for i in range(300):
        h, a = strong_and_weak() if i % 2 else (eleven(), eleven())
        r = match.play(rng, h, a, LEAGUE, extra_time_if_level=i % 3 == 0)
        end = 120 if r.extra_time else 90
        assert [x.minute for x in r.shots] == sorted(x.minute for x in r.shots)
        assert all(1 <= x.minute <= end for x in r.shots)
        for side, st in enumerate(r.stats):
            mine = [x for x in r.shots if x.side == side]
            assert len(mine) == st.shots and sum(x.on_target for x in mine) == st.on_target
            assert sorted(x.minute for x in mine if x.goal) == sorted(g.minute for g in r.goals if g.side == side)
            assert all(x.on_target for x in mine if x.goal)
        late += sum(1 for x in r.shots if x.minute > 90 and not x.goal)
    assert late, "shots in extra time are spread into it, not squeezed into ninety minutes"


# The statistics of 30 matches, as the site showed them before the shot timeline (C30)
# existed: checked equal by fingerprinting 20 tournaments' every result and statistic
# before and after. A DELIBERATE change to the statistics model changes this; update it
# then, and only then.
STATS_PINNED = "4e68156386128f2d63fd57ee09633b68defde89df1cbbb3118e9c37ae5cd7a5f"


def test_the_statistics_are_still_the_ones_the_site_showed():
    # Switching the timeline off and comparing (the first version of this test) can't
    # see a stray draw placed inside the statistics themselves; only a pinned record can.
    import hashlib
    import json
    h, a = eleven(90), eleven(72)
    rows = []
    for i in range(30):
        r = match.play(random.Random(i), h, a, LEAGUE, extra_time_if_level=i % 2 == 0)
        rows.append([[s.possession, [(p.shots, p.on_target, p.passes, p.completed, p.saves) for p in s.players]]
                     for s in r.stats])
    assert hashlib.sha256(json.dumps(rows).encode()).hexdigest() == STATS_PINNED
