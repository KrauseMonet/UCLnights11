"""Engine 2 (C39): tiredness and substitutes. Engine 1 stays exactly as it was."""

import hashlib
import json
import random
import statistics

import dataclasses

import pytest

from game import match
from game.deck import Card, load_deck
from game.formations import FORMATIONS
from game.journey import player_totals
from game.positions import arrange, fits
from game.tournament import Side, auto_plan, best_xi, club_bench, league_of, play_room, play_tournament

LEAGUE = match.League(attack=80.0, defence=80.0)
SLOTS = FORMATIONS["433"].slots
LINE_POSITIONS = {"GK": ("GK",), "DF": ("RB", "CB", "LB"), "MF": ("DM", "CM", "AM"), "FW": ("RW", "ST", "LW")}


def card(pos, rating=80, n=0, tag=""):
    return Card(id=f"{tag}{pos}{n}", name=f"{pos} {n}", title=f"{pos} {n}", pos=pos,
                positions=LINE_POSITIONS[pos], source="declared", nation=None, rating=rating,
                season=2004, label="2004–05", club="T", club_name="T", short="T", key=f"k{tag}", crest="T")


def eleven(rating=80, tag=""):
    xi = ([card("GK", rating, 0, tag)] + [card("DF", rating, i, tag) for i in range(4)]
          + [card("MF", rating, i, tag) for i in range(3)] + [card("FW", rating, i, tag) for i in range(3)])
    return tuple(arrange(SLOTS, xi))


def bench(rating=80, tag=""):
    return (card("DF", rating, 7, tag), card("MF", rating, 7, tag), card("FW", rating, 7, tag))


def sheet(rating=80, tag="", bench_rating=None, plan=match.AUTO_PLAN):
    return match.Teamsheet(SLOTS, eleven(rating, tag),
                           bench(bench_rating if bench_rating is not None else rating, tag), plan)


def on_pitch(r, side, sheet_):
    """Each person's (came on, went off) in this match."""
    end = 120 if r.extra_time else 90
    when = {c.id: [0, end] for c in sheet_.xi}
    for s in r.subs:
        if s.side == side:
            when[s.off.id][1] = s.minute
            when[s.on.id] = [s.minute, end]
    return when


# -- tiredness ---------------------------------------------------------------------

def test_tiredness_runs_from_fresh_to_spent_and_stops_at_ninety():
    assert match.tiredness(0) == -1 and match.tiredness(45) == 0
    assert match.tiredness(90) == 1 and match.tiredness(120) == 1


def test_a_tired_side_defends_worse_than_it_attacks_and_a_keeper_never_tires():
    men = [(c.rating, c.pos, 0) for c in eleven()]
    early, late = match._fit(men, 10), match._fit(men, 80)
    assert late[1] < early[1] and late[0] < early[0]
    assert early[1] - late[1] > early[0] - late[0]          # defending suffers more
    u = match.tiredness(89)
    gk, df = match.DEFENCE_WEIGHT["GK"], match.DEFENCE_WEIGHT["DF"]
    assert match._fit([(80, "GK", 0), (80, "DF", 0)], 89)[1] == pytest.approx(
        (gk * 80 + df * (80 - match.TIRE * u)) / (gk + df))


def test_goals_come_later_in_a_match():
    rng = random.Random(4)
    home, away = sheet(plan=()), sheet(tag="b", plan=())
    goals = [g for _ in range(3000) for g in match.play_v2(rng, home, away, LEAGUE).goals]
    assert sum(g.minute > 45 for g in goals) / len(goals) > 0.53


def test_a_substitute_comes_on_fresh_and_helps():
    # Two equal sides; only one has a bench. After an hour it should outscore the other.
    rng = random.Random(6)
    late = [0, 0]
    for i in range(3000):
        with_bench, without = sheet(tag="a"), sheet(tag="b", plan=())
        home, away = (with_bench, without) if i % 2 else (without, with_bench)
        r = match.play_v2(rng, home, away, LEAGUE, neutral=True)
        for g in r.goals:
            if g.minute > 60:
                late[(g.side == 0) == bool(i % 2)] += 1   # index 1: the side with the bench
    assert late[1] > 1.1 * late[0]


# -- substitutions -------------------------------------------------------------------

def test_substitutions_keep_to_the_rules():
    # The home bench holds more men than may come on, a keeper, a man who fits nowhere in a
    # 4-3-3 and a plan naming one man twice, so each rule has something to refuse.
    rng = random.Random(8)
    made = capped = 0
    for i in range(600):
        xi = eleven(78 + i % 10, "h")
        wide = dataclasses.replace(card("MF", 90, 8, "h"), positions=("LM",))
        extra = (*bench(76 + i % 7, "h"), card("MF", 79, 9, "h"), card("GK", 90, 9, "h"), wide)
        plan = (match.Sub(4, 46, off=xi[0].id), match.Sub(5, 50), match.Sub(0, 55), match.Sub(0, 65),
                match.Sub(1, 60), match.Sub(2, 70), match.Sub(3, 75))
        h = match.Teamsheet(SLOTS, xi, extra, plan)
        a = sheet(84 - i % 9, "a", bench_rating=80)
        r = match.play_v2(rng, h, a, LEAGUE, extra_time_if_level=i % 2 == 0, level_on=(i % 3, 1))
        capped += sum(s.side == 0 for s in r.subs) == match.MAX_SUBS
        for side, sh in ((0, h), (1, a)):
            mine = [s for s in r.subs if s.side == side]
            made += len(mine)
            assert len(mine) <= match.MAX_SUBS
            assert len({s.on.id for s in mine}) == len(mine)
            people = [c for c in sh.xi]
            for s in sorted(mine, key=lambda s: s.minute):
                assert s.on.id in {c.id for c in sh.bench}
                assert s.off.id in {c.id for c in people}, "only a man on the pitch goes off"
                assert s.off.pos != "GK"
                people = [c for c in people if c.id != s.off.id] + [s.on]
                assert fits(SLOTS, people)
            assert [s.minute for s in mine] == sorted(s.minute for s in mine)
    assert made > 1000
    assert capped, "the home side wanted a fourth change often enough for the cap to act"


def test_scorers_and_assisters_are_on_the_pitch_when_they_score():
    rng = random.Random(9)
    for i in range(800):
        h, a = sheet(80, "h", bench_rating=82), sheet(80, "a", bench_rating=79)
        r = match.play_v2(rng, h, a, LEAGUE, extra_time_if_level=True)
        spans = (on_pitch(r, 0, h), on_pitch(r, 1, a))
        for g in r.goals:
            for c in (g.scorer, g.assist):
                if c is not None:
                    lo, hi = spans[g.side][c.id]
                    assert lo < g.minute <= hi, (c.id, g.minute, lo, hi)


def test_minutes_add_up_to_eleven_men_for_the_whole_match():
    rng = random.Random(10)
    for i in range(300):
        h, a = sheet(80, "h"), sheet(81, "a", bench_rating=77)
        r = match.play_v2(rng, h, a, LEAGUE, extra_time_if_level=i % 2 == 0)
        end = 120 if r.extra_time else 90
        for side, sh in ((0, h), (1, a)):
            st = r.stats[side]
            assert sum(p.minutes for p in st.players) == 11 * end
            spans = on_pitch(r, side, sh)
            assert {p.card.id: p.minutes for p in st.players} == {k: hi - lo for k, (lo, hi) in spans.items()}


def test_a_named_change_replaces_that_man_and_only_on_its_condition():
    xi = eleven(80, "h")
    striker = next(c for c in xi if c.slot == "ST")
    chase = (match.Sub(2, 60, "behind", off=striker.id),)
    h = match.Teamsheet(SLOTS, xi, bench(60, "h"), chase)   # a worse man: only the plan brings him on
    a = sheet(80, "a", plan=())
    rng = random.Random(11)
    for _ in range(200):
        # Two down on aggregate from the first leg: behind at the hour unless it was won back.
        r = match.play_v2(rng, h, a, LEAGUE, level_on=(0, 2))
        before = [g for g in r.goals if g.minute <= 60]
        behind = sum(g.side == 0 for g in before) < 2 + sum(g.side == 1 for g in before)
        subs = [s for s in r.subs if s.side == 0]
        if behind:
            assert [(s.minute, s.off.id, s.on.id) for s in subs] == [(60, striker.id, h.bench[2].id)]
        # Five up on aggregate: never behind, so never on.
        r = match.play_v2(rng, h, a, LEAGUE, level_on=(5, 0))
        assert not any(s.side == 0 for s in r.subs)


def test_the_automatic_plan_only_makes_a_change_that_helps():
    rng = random.Random(12)
    poor = sheet(85, "h", bench_rating=55)
    for _ in range(200):
        r = match.play_v2(rng, poor, sheet(80, "a", plan=()), LEAGUE)
        assert not r.subs
    good = sheet(85, "h", bench_rating=84)
    assert any(match.play_v2(rng, good, sheet(80, "a", plan=()), LEAGUE).subs for _ in range(20))


# -- statistics ------------------------------------------------------------------------

def test_every_side_s_numbers_add_up_and_the_timeline_replays_them():
    rng = random.Random(13)
    for i in range(300):
        h, a = sheet(88, "h", bench_rating=80), sheet(74, "a")
        r = match.play_v2(rng, h, a, LEAGUE, extra_time_if_level=i % 3 == 0)
        hs, as_ = r.stats
        end = 120 if r.extra_time else 90
        assert hs.possession + as_.possession == pytest.approx(1)
        assert [x.minute for x in r.shots] == sorted(x.minute for x in r.shots)
        assert all(1 <= x.minute <= end for x in r.shots)
        for side, st, other, conceded in ((0, hs, as_, r.away_goals), (1, as_, hs, r.home_goals)):
            scored = r.home_goals if side == 0 else r.away_goals
            assert scored <= st.on_target <= st.shots and 0 <= st.completed <= st.passes
            assert st.saves == other.on_target - conceded
            keeper = [p for p in st.players if p.card.pos == "GK"]
            assert len(keeper) == 1 and keeper[0].saves == st.saves and keeper[0].shots == 0
            mine = [x for x in r.shots if x.side == side]
            assert len(mine) == st.shots and sum(x.on_target for x in mine) == st.on_target
            assert sorted(x.minute for x in mine if x.goal) == sorted(g.minute for g in r.goals if g.side == side)
            for p in st.players:
                assert p.on_target >= sum(1 for g in r.goals if g.side == side and g.scorer is p.card)
            # A goal is credited to the very card in its side's lines (journey counts by it).
            for g in r.goals:
                if g.side == side:
                    assert any(p.card is g.scorer for p in st.players)
                    assert g.assist is None or any(p.card is g.assist for p in st.players)


def test_a_substitute_s_passes_follow_his_minutes():
    rng = random.Random(14)
    share = []
    for _ in range(400):
        r = match.play_v2(rng, sheet(80, "h", bench_rating=80), sheet(80, "a", plan=()), LEAGUE)
        for s in (s for s in r.subs if s.side == 0):
            line = next(p for p in r.stats[0].players if p.card.id == s.on.id)
            share.append(line.passes / max(1, r.stats[0].passes) / (line.minutes / 990))
    assert 0.6 < statistics.mean(share) < 1.4      # about his share of the side's player-minutes


def test_the_statistics_never_take_from_the_tournament_s_stream(monkeypatch):
    h, a = sheet(88, "h", bench_rating=82), sheet(74, "a")
    after = []
    for stats_on in (True, False):
        if not stats_on:
            monkeypatch.setattr(match, "_match_stats_v2", lambda *args: (None, []))
        rng = random.Random(15)
        rows = []
        for i in range(200):
            r = match.play_v2(rng, h, a, LEAGUE, extra_time_if_level=i % 2 == 0)
            rows.append((r.home_goals, r.away_goals, r.pens, [(s.minute, s.on.id) for s in r.subs]))
        after.append((rows, rng.random()))
    assert after[0] == after[1]


# Thirty matches of engine 2 as first calibrated (TIRE 13). A DELIBERATE change to the
# engine changes this; update it then, and only then.
V2_PINNED = "9565bdde1348f252a8c1e6b98666cb19d3b534fa9f2e9d2d4418e90c122a9e42"


def test_engine_2_is_still_the_one_calibrated():
    h, a = sheet(90, "h", bench_rating=84), sheet(72, "a", bench_rating=70)
    rows = []
    for i in range(30):
        r = match.play_v2(random.Random(i), h, a, LEAGUE, extra_time_if_level=i % 2 == 0)
        rows.append([r.home_goals, r.away_goals, r.pens,
                     [(g.minute, g.side, g.scorer.id) for g in r.goals],
                     [(s.minute, s.side, s.off.id, s.on.id) for s in r.subs],
                     [[s.possession, [(p.card.id, p.minutes, p.shots, p.on_target, p.passes, p.completed, p.saves)
                                      for p in s.players]] for s in r.stats]])
    assert hashlib.sha256(json.dumps(rows).encode()).hexdigest() == V2_PINNED


# -- the deck and the tournament -------------------------------------------------------

def test_a_club_bench_is_its_best_outfield_men_who_can_come_on():
    deck = load_deck()
    for cs in deck.club_seasons:
        f, xi = best_xi(cs)
        b = club_bench(cs)
        starters = {c.id for c in xi}
        assert len(b) <= 3 and all(c.id not in starters and "GK" not in c.positions[:1] for c in b)
        assert [c.rating for c in b] == sorted((c.rating for c in b), reverse=True)
        for c in b:
            assert any(fits(f.slots, [*(x for x in xi if x is not off), c]) for off in xi if off.pos != "GK")
        # Nobody left out could have come on and is better than the worst man picked
        # (or, with a short bench, could have come on at all).
        worst = b[-1].rating if len(b) == 3 else -1
        for c in cs.cards:
            if c.id in starters or c in b or c.positions == ("GK",) or c.rating <= worst:
                continue
            assert not any(fits(f.slots, [*(x for x in xi if x is not off), c]) for off in xi if off.pos != "GK")


def test_a_tournament_uses_the_engine_it_is_given_and_the_minutes_follow():
    deck = load_deck()
    league = league_of(deck)
    f, xi = best_xi(deck.club_seasons[0])
    you = Side("YOU", "Your XI", "YOU", f, xi, you=True)
    one = play_tournament(deck, league, 3, you)
    assert not any(fx.result.subs for fx in one.fixtures)
    two = play_tournament(deck, league, 3, you, engine=2)
    assert sum(len(fx.result.subs) for fx in two.fixtures) > 200
    totals = player_totals(two)
    subs = [p for p in totals.values() if p.minutes < 90 * p.apps]
    assert subs, "a man who came on or went off played less than the whole of every match"
    for fx in two.fixtures:
        for st in fx.result.stats:
            assert sum(p.minutes for p in st.players) == 11 * (120 if fx.result.extra_time else 90)
    with pytest.raises(ValueError):
        play_room(deck, league, 3, [you], 2, engine=3)


# Engine 1's results, as every shared link and room replays them: three solo tournaments
# and three rooms. Engine 2 was added with this unchanged (and 240 tournaments' every
# result and statistic fingerprinted equal before and after).
ENGINE1_PINNED = "cdd6743c334f06a6ce25d4e43a618cbc36af79c0cdd112b17403d578b5e17fc7"


def test_engine_1_is_what_every_link_replays():
    deck = load_deck()
    league = league_of(deck)
    rows = []
    for seed in range(3):
        f, xi = best_xi(deck.club_seasons[seed * 40])
        you = Side("YOU", "Your XI", "YOU", f, xi, you=True)
        for t in (play_tournament(deck, league, seed, you), play_room(deck, league, seed, [you], 8)):
            for fx in t.fixtures:
                r = fx.result
                rows.append([fx.home.key, fx.away.key, r.home_goals, r.away_goals, r.pens,
                             [(g.minute, g.scorer.id) for g in r.goals],
                             [[s.possession, [(p.shots, p.passes) for p in s.players]] for s in r.stats]])
    assert hashlib.sha256(json.dumps(rows).encode()).hexdigest() == ENGINE1_PINNED


def test_the_automatic_plan_brings_the_best_rated_on_first():
    b = [card("MF", 80, 1), card("FW", 92, 2), card("DF", 86, 3)]
    assert [(x.on, x.minute) for x in auto_plan(b)] == [(1, 60), (2, 70), (0, 80)]
    assert auto_plan([]) == ()
