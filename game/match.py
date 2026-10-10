"""The match engine: two elevens in, a ninety-minute result with its goals out.

Goals are Poisson. A side's expected goals are a base rate (home, away or
neutral, from real Champions League results -- see etl.openfootball) scaled by
how far its ATTACK sits above the league's and the opponent's DEFENCE sits
below the league's:

    lambda = base * exp(K * ((attack - league_attack) - (defence_opp - league_defence)))

Attack and defence are weighted means of the eleven's ratings, the weights set
by line: forwards carry an attack, goalkeeper and defenders a defence, and the
midfield both. Centring on the league's own means is what keeps ``base`` the
real scoring rate: two average sides score exactly the real averages, so the
calibration and the strength model cannot drift into each other.

The constants are declared game design, like the ratings: ``K`` decides how
much a rating gap matters, and ``game --validate`` reports what it does to the
draw rate rather than tuning it to one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

from game.deck import Card

# Real Champions League home/away scoring, regulation time (etl.openfootball:
# 1,962 matches, 2011-12 to 2025-26). Neutral is their mean.
BASE_HOME = 1.72
BASE_AWAY = 1.33
BASE_NEUTRAL = (BASE_HOME + BASE_AWAY) / 2

K = 0.075                  # per rating point of (attack - opposing defence)
EXTRA_TIME_SHARE = 30 / 90  # thirty more minutes, at the same rate

ATTACK_WEIGHT = {"GK": 0.0, "DF": 0.15, "MF": 0.6, "FW": 1.0}
DEFENCE_WEIGHT = {"GK": 1.6, "DF": 1.0, "MF": 0.45, "FW": 0.1}
SCORE_WEIGHT = {"GK": 0.0, "DF": 0.14, "MF": 0.5, "FW": 1.0}
ASSIST_WEIGHT = {"GK": 0.02, "DF": 0.35, "MF": 1.0, "FW": 0.7}
ASSISTED_SHARE = 0.72
PENALTY_BASE = 0.76


def _weighted(xi: Sequence[Card], weights: dict[str, float]) -> float:
    total = sum(weights[c.pos] for c in xi)
    return sum(c.rating * weights[c.pos] for c in xi) / total


def attack(xi: Sequence[Card]) -> float:
    return _weighted(xi, ATTACK_WEIGHT)


def defence(xi: Sequence[Card]) -> float:
    return _weighted(xi, DEFENCE_WEIGHT)


@dataclass(frozen=True)
class League:
    """The deck's average attack and defence, the zero point of the strength model."""

    attack: float
    defence: float


@dataclass(frozen=True)
class Goal:
    minute: int
    side: int               # 0 = home, 1 = away
    scorer: Card
    assist: Card | None


@dataclass
class Result:
    home_goals: int = 0
    away_goals: int = 0
    goals: list[Goal] = field(default_factory=list)
    extra_time: bool = False
    pens: tuple[int, int] | None = None

    @property
    def winner(self) -> int | None:
        """0 or 1, or None for a draw that was not settled."""
        if self.pens is not None:
            return 0 if self.pens[0] > self.pens[1] else 1
        if self.home_goals == self.away_goals:
            return None
        return 0 if self.home_goals > self.away_goals else 1


def expected_goals(xi: Sequence[Card], opp: Sequence[Card], league: League, base: float) -> float:
    edge = (attack(xi) - league.attack) - (defence(opp) - league.defence)
    return base * math.exp(K * edge)


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method: exact, and fine for the small means football has."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _pick(rng: random.Random, xi: Sequence[Card], weights: dict[str, float], skip: Card | None = None) -> Card | None:
    pool = [(c, weights[c.pos] * math.exp(0.06 * (c.rating - 80))) for c in xi if c is not skip]
    total = sum(w for _, w in pool)
    if total <= 0:
        return None
    x = rng.random() * total
    for c, w in pool:
        x -= w
        if x <= 0:
            return c
    return pool[-1][0]


def _goals(rng: random.Random, xi: Sequence[Card], n: int, side: int, lo: int, hi: int) -> list[Goal]:
    out = []
    for _ in range(n):
        minute = rng.randint(lo, hi)
        scorer = _pick(rng, xi, SCORE_WEIGHT)
        assist = _pick(rng, xi, ASSIST_WEIGHT, skip=scorer) if rng.random() < ASSISTED_SHARE else None
        out.append(Goal(minute, side, scorer, assist))
    return out


def shootout(rng: random.Random, home: Sequence[Card], away: Sequence[Card]) -> tuple[int, int]:
    """Five each, then sudden death. Takers in order of rating, outfield first."""
    def takers(xi):
        order = sorted((c for c in xi if c.pos != "GK"), key=lambda c: -c.rating)
        return order or list(xi)

    def keeper(xi):
        gks = [c for c in xi if c.pos == "GK"]
        return gks[0].rating if gks else 70

    sides = (takers(home), takers(away))
    keepers = (keeper(away), keeper(home))   # the keeper each side shoots against
    score, taken = [0, 0], [0, 0]

    def kick(s: int) -> None:
        taker = sides[s][taken[s] % len(sides[s])]
        p = PENALTY_BASE + 0.003 * (taker.rating - 80) - 0.003 * (keepers[s] - 80)
        if rng.random() < p:
            score[s] += 1
        taken[s] += 1

    def decided() -> bool:
        left = (5 - taken[0], 5 - taken[1])
        return score[0] > score[1] + left[1] or score[1] > score[0] + left[0]

    for _ in range(5):
        for s in (0, 1):
            kick(s)
            if decided():
                return score[0], score[1]
    while score[0] == score[1]:
        kick(0)
        kick(1)
    return score[0], score[1]


def play(
    rng: random.Random,
    home: Sequence[Card],
    away: Sequence[Card],
    league: League,
    neutral: bool = False,
    extra_time_if_level: bool = False,
    level_on: tuple[int, int] = (0, 0),
) -> Result:
    """Play one match.

    ``extra_time_if_level`` plays thirty more minutes, then penalties, when the
    tie is level at the end -- ``level_on`` carries the first leg's score (from
    THIS match's home side's point of view), so the second leg of a two-legged
    tie goes to extra time on the aggregate, not on its own score.
    """
    bh, ba = (BASE_NEUTRAL, BASE_NEUTRAL) if neutral else (BASE_HOME, BASE_AWAY)
    lh = expected_goals(home, away, league, bh)
    la = expected_goals(away, home, league, ba)
    r = Result()
    hg, ag = poisson(rng, lh), poisson(rng, la)
    r.goals = _goals(rng, home, hg, 0, 1, 90) + _goals(rng, away, ag, 1, 1, 90)
    r.home_goals, r.away_goals = hg, ag
    if extra_time_if_level and hg + level_on[0] == ag + level_on[1]:
        r.extra_time = True
        eh = poisson(rng, lh * EXTRA_TIME_SHARE)
        ea = poisson(rng, la * EXTRA_TIME_SHARE)
        r.goals += _goals(rng, home, eh, 0, 91, 120) + _goals(rng, away, ea, 1, 91, 120)
        r.home_goals += eh
        r.away_goals += ea
        if r.home_goals + level_on[0] == r.away_goals + level_on[1]:
            r.pens = shootout(rng, home, away)
    r.goals.sort(key=lambda g: (g.minute, g.side))
    return r
