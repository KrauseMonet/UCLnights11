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

Every match also carries its statistics (``MatchStats``): possession, shots, shots
on target, passes and passes completed, for each side and each player. They are
drawn AFTER the result, from a random stream seeded by the match itself, so they
never touch the tournament's stream and cannot change a single result (C26). The
goals are part of them -- every goal is a shot on target by its scorer -- and the
rest grows from the same expected goals that decided the score, so a side that
dominated on paper usually dominated the numbers too. Unlike goals, these have no
real yardstick: the constants are declared, at the user's direction, and
``game --validate`` reports what they produce.
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
class PlayerLine:
    """One player's match. ``saves`` is a goalkeeper's; everyone else's stays 0."""

    card: Card
    shots: int = 0
    on_target: int = 0
    passes: int = 0
    completed: int = 0
    saves: int = 0


@dataclass
class SideStats:
    """A side's numbers. The totals are its players' lines added up, so the two can
    never disagree."""

    possession: float               # share of the ball, 0-1; the two sides sum to 1
    players: list[PlayerLine]

    @property
    def shots(self) -> int:
        return sum(p.shots for p in self.players)

    @property
    def on_target(self) -> int:
        return sum(p.on_target for p in self.players)

    @property
    def passes(self) -> int:
        return sum(p.passes for p in self.players)

    @property
    def completed(self) -> int:
        return sum(p.completed for p in self.players)

    @property
    def saves(self) -> int:
        return sum(p.saves for p in self.players)


@dataclass(frozen=True)
class Shot:
    """One shot, for replaying a match as it happens (C30). A goal is a shot on target
    at its goal's minute; every other shot is given a minute of its own."""

    minute: int
    side: int               # 0 = home, 1 = away
    on_target: bool
    goal: bool


@dataclass
class Result:
    home_goals: int = 0
    away_goals: int = 0
    goals: list[Goal] = field(default_factory=list)
    extra_time: bool = False
    pens: tuple[int, int] | None = None
    stats: tuple[SideStats, SideStats] | None = None
    shots: list[Shot] = field(default_factory=list)     # in minute order

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


# -- match statistics ---------------------------------------------------------
# Declared game design, set by judgement at the user's direction (C26); there is no
# open Champions League source they are fitted to. `game --validate` prints what they
# produce. Each side's shots grow from the expected goals that decided the score:

SAVED_PER_XG = 1.9          # shots on target kept out, per expected goal
OFF_PER_XG = 3.0            # shots off target or blocked, per expected goal ...
OFF_BASE = 4.0              # ... plus a floor: even a blunt side shoots from range
SHOT_POSSESSION = 0.5       # +/- this share of off-target shots, from 0% to 100% possession
SHOT_XG_CAP = 3.2           # a rout's chances stop growing here: 20 on target reads as a bug

# Possession and passing follow CONTROL, a weighted mean of the eleven's ratings in
# which midfield counts most.
CONTROL_WEIGHT = {"GK": 0.1, "DF": 0.5, "MF": 1.0, "FW": 0.35}
POSSESSION_K = 0.012        # share of the ball per rating point of control edge
POSSESSION_HOME = 0.02      # the home side's extra share
POSSESSION_SD = 0.06
POSSESSION_RANGE = (0.25, 0.75)
PASSES_AT_HALF = 480        # a side's passes over ninety minutes with half the ball
PASSES_SD = 0.08
ACCURACY_BASE = 0.81
ACCURACY_K = 0.006          # per rating point of a player above eighty
ACCURACY_POSSESSION = 0.30  # more of the ball, more short safe passes
ACCURACY_SD = 0.03
ACCURACY_RANGE = (0.55, 0.95)

# Who shoots and who passes, by line. A shot that misses is picked as a scorer is
# (SCORE_WEIGHT), so forwards shoot most; passes lean on midfield.
PASS_WEIGHT = {"GK": 0.45, "DF": 1.05, "MF": 1.35, "FW": 0.6}


def control(xi: Sequence[Card]) -> float:
    return _weighted(xi, CONTROL_WEIGHT)


def _clamp(x: float, lo_hi: tuple[float, float]) -> float:
    return min(max(x, lo_hi[0]), lo_hi[1])


def _match_key(home: Sequence[Card], away: Sequence[Card], neutral: bool, r: Result) -> str:
    return "|".join([
        ",".join(c.id for c in home), ",".join(c.id for c in away), str(neutral),
        f"{r.home_goals}-{r.away_goals}-{r.extra_time}-{r.pens}",
        ";".join(f"{g.minute}.{g.side}.{g.scorer.id}" for g in r.goals),
    ])


def _stats_rng(home: Sequence[Card], away: Sequence[Card], neutral: bool, r: Result) -> random.Random:
    """A stream of its own, seeded by everything that makes this match this match.
    Python seeds a Random from a string through SHA-512, so it is the same in every
    process, and nothing is drawn from the tournament's stream."""
    return random.Random(f"stats|{_match_key(home, away, neutral, r)}")


def shot_timeline(home: Sequence[Card], away: Sequence[Card], neutral: bool, r: Result) -> list[Shot]:
    """When each shot came, for watching a match unfold (C30). Drawn from a third
    stream, so neither the result nor a single statistic changes: goals keep their
    minutes, and the other shots are spread over the time played (to 120 after extra
    time). A side's shots, on target and goals at the whistle are its statistics."""
    rng = random.Random(f"timeline|{_match_key(home, away, neutral, r)}")
    end = 120 if r.extra_time else 90
    out = [Shot(g.minute, g.side, True, True) for g in r.goals]
    for side, st in enumerate(r.stats):
        goals = sum(1 for g in r.goals if g.side == side)
        saved, off = st.on_target - goals, st.shots - st.on_target
        out += [Shot(rng.randint(1, end), side, True, False) for _ in range(saved)]
        out += [Shot(rng.randint(1, end), side, False, False) for _ in range(off)]
    out.sort(key=lambda x: (x.minute, x.side, not x.goal))
    return out


def _side_stats(rng: random.Random, xi: Sequence[Card], possession: float, lam: float,
                goals: list[Goal], side: int, saves_against: int, minutes: float) -> SideStats:
    lines = [PlayerLine(c) for c in xi]
    line_of = {id(c): ln for c, ln in zip(xi, lines)}
    # Goals first: each is a shot on target by its scorer.
    for g in goals:
        if g.side == side:
            ln = line_of[id(g.scorer)]
            ln.shots += 1
            ln.on_target += 1
    lam = min(lam, SHOT_XG_CAP)
    saved = poisson(rng, SAVED_PER_XG * lam * minutes)
    off = poisson(rng, (OFF_BASE + OFF_PER_XG * lam) * minutes
                  * (1 + SHOT_POSSESSION * (possession - 0.5) * 2))
    for n, on in ((saved, True), (off, False)):
        for _ in range(n):
            ln = line_of[id(_pick(rng, xi, SCORE_WEIGHT))]
            ln.shots += 1
            ln.on_target += on
    # Passes: the side's total, shared out by line and quality, each player completing
    # his own share at an accuracy that rises with his rating and the side's possession.
    total = max(0, round(PASSES_AT_HALF * 2 * possession * minutes * rng.gauss(1, PASSES_SD)))
    weights = [PASS_WEIGHT[c.pos] * math.exp(0.03 * (c.rating - 80)) * rng.uniform(0.8, 1.2) for c in xi]
    shares = [total * w / sum(weights) for w in weights]
    counts = [int(x) for x in shares]
    for i in sorted(range(len(xi)), key=lambda i: shares[i] - counts[i], reverse=True)[:total - sum(counts)]:
        counts[i] += 1
    for ln, n in zip(lines, counts):
        acc = _clamp(ACCURACY_BASE + ACCURACY_K * (ln.card.rating - 80)
                     + ACCURACY_POSSESSION * (possession - 0.5) + rng.gauss(0, ACCURACY_SD), ACCURACY_RANGE)
        ln.passes, ln.completed = n, round(n * acc)
    keeper = next((ln for ln in lines if ln.card.pos == "GK"), None)
    if keeper is not None:
        keeper.saves = saves_against
    return SideStats(possession, lines)


def match_stats(home: Sequence[Card], away: Sequence[Card], lh: float, la: float,
                r: Result, neutral: bool) -> tuple[SideStats, SideStats]:
    rng = _stats_rng(home, away, neutral, r)
    edge = control(home) - control(away)
    p = 0.5 + POSSESSION_K * edge + (0 if neutral else POSSESSION_HOME) + rng.gauss(0, POSSESSION_SD)
    p = round(_clamp(p, POSSESSION_RANGE), 3)
    minutes = 1 + (EXTRA_TIME_SHARE if r.extra_time else 0)
    # Saves are the shots on target that didn't go in; draw the away side's first so
    # the home keeper can be credited with them, and vice versa.
    a = _side_stats(rng, away, 1 - p, la, r.goals, 1, 0, minutes)
    h = _side_stats(rng, home, p, lh, r.goals, 0, a.on_target - r.away_goals, minutes)
    keeper = next((ln for ln in a.players if ln.card.pos == "GK"), None)
    if keeper is not None:
        keeper.saves = h.on_target - r.home_goals
    return h, a


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
    r.stats = match_stats(home, away, lh, la, r, neutral)
    if r.stats is not None:
        r.shots = shot_timeline(home, away, neutral, r)
    return r
