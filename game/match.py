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

Engine 2 (``play_v2``, at the end) adds tiredness and substitutes; engine 1 (``play``)
is left exactly as it was (C39).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

from game.deck import Card
from game.positions import LINE, arrangement, place

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
    """One player's match. ``saves`` is a goalkeeper's; everyone else's stays 0.
    ``minutes`` is set by engine 2 only, where a substitute plays part of a match;
    engine 1's players all play the whole of it."""

    card: Card
    shots: int = 0
    on_target: int = 0
    passes: int = 0
    completed: int = 0
    saves: int = 0
    minutes: int | None = None


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


@dataclass(frozen=True)
class Substitution:
    """Engine 2: ``on`` replaced ``off`` after ``minute`` minutes. ``xi`` is the eleven
    after the change, placed and in slot order: everyone may have moved to make room."""

    minute: int
    side: int               # 0 = home, 1 = away
    off: Card
    on: Card
    xi: tuple[Card, ...] = ()


@dataclass
class Result:
    home_goals: int = 0
    away_goals: int = 0
    goals: list[Goal] = field(default_factory=list)
    extra_time: bool = False
    pens: tuple[int, int] | None = None
    stats: tuple[SideStats, SideStats] | None = None
    shots: list[Shot] = field(default_factory=list)     # in minute order
    subs: list[Substitution] = field(default_factory=list)  # engine 2 only, in minute order

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


# -- engine 2: tiredness and substitutes (C39) ---------------------------------
# Engine 1 above is left exactly as it was, because every shared link, saved result
# and room replays its tournament from scratch on every read: changing it would rewrite
# results people have already watched. Engine 2 is chosen per tournament.
#
# A match is played in blocks of BLOCK minutes. In each, a side's expected goals are
# engine 1's, worked out from the eleven ON THE PITCH and each man's tiredness: after
# FRESH_AT minutes played he defends worse than his rating, before it better, by TIRE
# points per FRESH_AT minutes, and attacks worse by ATTACK_TIRE of that. Over a whole
# ninety the tiredness averages zero, so two average sides still score the real rates.
# Tiredness hurting defending more than attacking is what moves goals late: if both
# sides tired alike in both, the strength edge would never change. TIRE is set so the
# share of goals after half-time matches the real one (SECOND_HALF_REAL); ATTACK_TIRE
# is declared. A substitute comes on fresh, which is the point of having one.

ENGINES = (1, 2)
BLOCK = 5                   # minutes: subs come on, and the rate is re-worked, between blocks
FRESH_AT = 45               # minutes played at which a man plays exactly to his rating
TIRE = 13.0                 # rating points of defending per FRESH_AT minutes either side of it (set by SECOND_HALF_REAL)
ATTACK_TIRE = 0.5           # attacking suffers this share of it
TIRE_UNTIL = 90             # tiredness stops growing here (declared; real extra time, 24 matches, scored 1.0 a match)
MAX_SUBS = 3
CONDITIONS = ("any", "behind", "level", "ahead", "not_ahead", "not_behind")
# Real goals after half-time, regulation (etl.openfootball.halves: 5,975 goals).
SECOND_HALF_REAL = 0.557


@dataclass(frozen=True)
class Sub:
    """One line of a side's plan: bring on ``bench[on]`` at the first break between blocks
    from ``minute`` on at which ``when`` holds (the score is the tie's, so in a second leg
    it is the aggregate). ``off`` names the person he replaces; None lets the engine pick
    the change that helps most (attack when behind, defence when ahead, both otherwise),
    and makes none if nothing helps. The goalkeeper is never changed."""

    on: int
    minute: int = 60
    when: str = "any"
    off: str | None = None

    def __post_init__(self) -> None:
        if self.when not in CONDITIONS:
            raise ValueError(f"no condition {self.when!r}")


# Clubs bring their bench on at roughly the minutes real managers do, and only when the
# change helps: a tired star is not swapped for a much worse man.
AUTO_PLAN = (Sub(0, 60), Sub(1, 70), Sub(2, 80))


@dataclass(frozen=True)
class Teamsheet:
    slots: tuple[str, ...]          # the formation
    xi: tuple[Card, ...]            # placed, in slot order
    bench: tuple[Card, ...] = ()
    plan: tuple[Sub, ...] = ()


def tiredness(played: float) -> float:
    """-1 at kick-off, 0 at FRESH_AT minutes played, +1 at ninety and after."""
    return (min(played, TIRE_UNTIL) - FRESH_AT) / FRESH_AT


def _fit(men: Sequence[tuple[int, str, int]], at: float) -> tuple[float, float]:
    """(attack, defence) of the men on the pitch at minute ``at``, tiredness included;
    each man is (rating, line, minute he came on). A goalkeeper does not tire."""
    att = dfn = wa = wd = 0.0
    for rating, line, entered in men:
        u = 0.0 if line == "GK" else tiredness(at - entered)
        a, d = ATTACK_WEIGHT[line], DEFENCE_WEIGHT[line]
        att += a * (rating - ATTACK_TIRE * TIRE * u)
        dfn += d * (rating - TIRE * u)
        wa, wd = wa + a, wd + d
    return att / wa, dfn / wd


_ARRANGED: dict[tuple, tuple[int, ...] | None] = {}
_PLACED: dict[tuple, tuple[Card, ...]] = {}


def _arranged(slots: tuple[str, ...], people: Sequence[Card]) -> tuple[int, ...] | None:
    """game.positions.arrangement (a slot index per man), or None if they cannot all be
    placed. A side weighs the same few changes at every break of every match, so the
    answers are kept: a man's positions are fixed by his club-season, which the key names."""
    key = (slots, tuple((c.key, c.id) for c in people))
    got = _ARRANGED.get(key, False)
    if got is False:
        if len(_ARRANGED) > 200_000:
            _ARRANGED.clear()
        try:
            got = tuple(arrangement(slots, people))
        except ValueError:
            got = None
        _ARRANGED[key] = got
    return got


def _measure(when: str, fit: tuple[float, float]) -> float:
    if when == "behind":
        return fit[0]
    if when == "ahead":
        return fit[1]
    return (fit[0] + fit[1]) / 2


def _holds(when: str, diff: int) -> bool:
    return {"any": True, "behind": diff < 0, "level": diff == 0, "ahead": diff > 0,
            "not_ahead": diff <= 0, "not_behind": diff >= 0}[when]


class _Side:
    """One side's state as a match is played."""

    def __init__(self, sheet: Teamsheet):
        self.sheet = sheet
        self.xi = tuple(sheet.xi)                        # replaced, never changed, at a substitution
        self.canon = {c.id: c for c in sheet.xi}          # how each man is credited
        self.entered = {c.id: 0 for c in sheet.xi}
        self.left: dict[str, int] = {}
        self.used: set[int] = set()                      # plan lines that have fired
        self.subs = 0

    def fit(self, at: float) -> tuple[float, float]:
        return _fit([(c.rating, c.pos, self.entered[c.id]) for c in self.xi], at)

    def _swap(self, off: Card, on: Card, minute: int) -> tuple[list[Card], list[tuple[int, str, int]]] | None:
        """The men on the pitch with ``on`` for ``off``, and each one's slot, or None if
        they cannot fill the formation."""
        people = [c for c in self.xi if c.id != off.id] + [on]
        at = _arranged(self.sheet.slots, people)
        if at is None:
            return None
        entered = {**self.entered, on.id: minute}
        return people, [(c.rating, LINE[self.sheet.slots[j]], entered[c.id]) for c, j in zip(people, at)]

    def _place(self, people: list[Card]) -> list[Card]:
        key = (self.sheet.slots, tuple((c.key, c.id) for c in people))
        got = _PLACED.get(key)
        if got is None:
            if len(_PLACED) > 50_000:
                _PLACED.clear()
            at = _arranged(self.sheet.slots, people)
            order = sorted(range(len(people)), key=lambda i: at[i])
            got = _PLACED[key] = tuple(place(people[i], self.sheet.slots[at[i]]) for i in order)
        return list(got)

    def change(self, minute: int, diff: int) -> list[tuple[Card, Card]]:
        """Make whatever substitutions the plan calls for at this break."""
        made = []
        for n, sub in enumerate(self.sheet.plan):
            if self.subs >= MAX_SUBS:
                break
            if n in self.used or minute < sub.minute or not _holds(sub.when, diff):
                continue
            if not 0 <= sub.on < len(self.sheet.bench):
                continue
            on = self.sheet.bench[sub.on]
            if on.id in self.entered:
                continue
            mid = minute + BLOCK / 2
            best = None
            if sub.off is None:
                now = _measure(sub.when, self.fit(mid))
                for off in self.xi:
                    if off.pos == "GK":
                        continue
                    swap = self._swap(off, on, minute)
                    if swap is None:
                        continue
                    gain = _measure(sub.when, _fit(swap[1], mid)) - now
                    if gain > 0 and (best is None or gain > best[0]):
                        best = (gain, off, swap[0])
            else:
                off = next((c for c in self.xi if c.id == sub.off and c.pos != "GK"), None)
                swap = self._swap(off, on, minute) if off is not None else None
                if swap is not None:
                    best = (0.0, off, swap[0])
            if best is None:
                continue
            _, off, people = best
            xi = self._place(people)
            self.used.add(n)
            self.subs += 1
            self.xi = tuple(xi)
            self.entered[on.id] = minute
            self.left[off.id] = minute
            self.canon.setdefault(on.id, next(c for c in xi if c.id == on.id))
            made.append((self.canon[off.id], self.canon[on.id], self.xi))
        return made

    def credit(self, g: Goal) -> Goal:
        return Goal(g.minute, g.side, self.canon[g.scorer.id],
                    self.canon[g.assist.id] if g.assist is not None else None)

    def minutes(self, end: int) -> dict[str, int]:
        return {pid: self.left.get(pid, end) - start for pid, start in self.entered.items()}


@dataclass(frozen=True)
class _Block:
    lo: int                         # the block is minutes lo+1 .. hi
    hi: int
    xi: tuple[tuple[Card, ...], tuple[Card, ...]]
    lam: tuple[float, float]        # per ninety minutes


def play_v2(
    rng: random.Random,
    home: Teamsheet,
    away: Teamsheet,
    league: League,
    neutral: bool = False,
    extra_time_if_level: bool = False,
    level_on: tuple[int, int] = (0, 0),
) -> Result:
    """Engine 2's match: engine 1's arguments, with teamsheets (bench and plan) for
    elevens. Draws from ``rng`` only the goals (and a shoot-out); the statistics come from
    a stream of the match's own, as in engine 1."""
    bh, ba = (BASE_NEUTRAL, BASE_NEUTRAL) if neutral else (BASE_HOME, BASE_AWAY)
    sides = (_Side(home), _Side(away))
    r = Result()
    blocks: list[_Block] = []
    score = [0, 0]

    def play_to(start: int, end: int) -> None:
        for lo in range(start, end, BLOCK):
            hi = min(lo + BLOCK, end)
            for s, me in enumerate(sides):
                diff = (score[s] + level_on[s]) - (score[1 - s] + level_on[1 - s])
                for off, on, xi in me.change(lo, diff):
                    r.subs.append(Substitution(lo, s, off, on, xi))
            mid = (lo + hi) / 2
            fh, fa = sides[0].fit(mid), sides[1].fit(mid)
            lh = bh * math.exp(K * ((fh[0] - league.attack) - (fa[1] - league.defence)))
            la = ba * math.exp(K * ((fa[0] - league.attack) - (fh[1] - league.defence)))
            blocks.append(_Block(lo, hi, (sides[0].xi, sides[1].xi), (lh, la)))
            for s, lam in ((0, lh), (1, la)):
                n = poisson(rng, lam * (hi - lo) / 90)
                r.goals += [sides[s].credit(g) for g in _goals(rng, sides[s].xi, n, s, lo + 1, hi)]
                score[s] += n

    play_to(0, 90)
    if extra_time_if_level and score[0] + level_on[0] == score[1] + level_on[1]:
        r.extra_time = True
        play_to(90, 120)
        if score[0] + level_on[0] == score[1] + level_on[1]:
            r.pens = shootout(rng, sides[0].xi, sides[1].xi)
    r.home_goals, r.away_goals = score
    r.goals.sort(key=lambda g: (g.minute, g.side))
    end = 120 if r.extra_time else 90
    r.stats, r.shots = _match_stats_v2(sides, blocks, r, neutral, end)
    return r


def _match_key_v2(sides: tuple[_Side, _Side], neutral: bool, r: Result) -> str:
    return "|".join([
        ",".join(c.id for c in sides[0].sheet.xi), ",".join(c.id for c in sides[1].sheet.xi),
        ",".join(c.id for c in sides[0].sheet.bench), ",".join(c.id for c in sides[1].sheet.bench),
        str(neutral), f"{r.home_goals}-{r.away_goals}-{r.extra_time}-{r.pens}",
        ";".join(f"{g.minute}.{g.side}.{g.scorer.id}" for g in r.goals),
        ";".join(f"{s.minute}.{s.side}.{s.off.id}.{s.on.id}" for s in r.subs),
    ])


def _side_stats_v2(rng: random.Random, me: _Side, side: int, blocks: list[_Block], possession: float,
                   goals: list[Goal], saves_against: int, end: int) -> tuple[SideStats, list[Shot]]:
    """Engine 1's statistics, block by block: shots come from each block's own expected
    goals and from the men on the pitch then, and passes are shared among them."""
    mins = me.minutes(end)
    lines = {pid: PlayerLine(me.canon[pid], minutes=mins[pid]) for pid in me.entered}
    shots = []
    for g in goals:
        if g.side == side:
            ln = lines[g.scorer.id]
            ln.shots += 1
            ln.on_target += 1
            shots.append(Shot(g.minute, side, True, True))
    for b in blocks:
        lam, share = min(b.lam[side], SHOT_XG_CAP), (b.hi - b.lo) / 90
        saved = poisson(rng, SAVED_PER_XG * lam * share)
        off = poisson(rng, (OFF_BASE + OFF_PER_XG * lam) * share
                      * (1 + SHOT_POSSESSION * (possession - 0.5) * 2))
        for n, on in ((saved, True), (off, False)):
            for _ in range(n):
                ln = lines[_pick(rng, b.xi[side], SCORE_WEIGHT).id]
                ln.shots += 1
                ln.on_target += on
                shots.append(Shot(rng.randint(b.lo + 1, b.hi), side, on, False))
    # Passes: the side's total over the match, each block's share split among the men on
    # the pitch by line and quality; each man's own spread is drawn once.
    scale = rng.gauss(1, PASSES_SD)
    spread = {pid: rng.uniform(0.8, 1.2) for pid in me.entered}
    shares = {pid: 0.0 for pid in me.entered}
    split: dict[int, tuple[list[tuple[str, float]], float]] = {}   # each eleven's weights, once
    for b in blocks:
        xi = b.xi[side]
        if id(xi) not in split:
            w = [(c.id, PASS_WEIGHT[c.pos] * math.exp(0.03 * (c.rating - 80)) * spread[c.id]) for c in xi]
            split[id(xi)] = (w, sum(x for _, x in w))
        w, total_w = split[id(xi)]
        block_total = PASSES_AT_HALF * 2 * possession * (b.hi - b.lo) / 90 * scale
        for pid, x in w:
            shares[pid] += block_total * x / total_w
    total = max(0, round(sum(shares.values())))
    counts = {pid: int(x) for pid, x in shares.items()}
    for pid in sorted(shares, key=lambda p: shares[p] - counts[p], reverse=True)[:total - sum(counts.values())]:
        counts[pid] += 1
    for pid, ln in lines.items():
        acc = _clamp(ACCURACY_BASE + ACCURACY_K * (ln.card.rating - 80)
                     + ACCURACY_POSSESSION * (possession - 0.5) + rng.gauss(0, ACCURACY_SD), ACCURACY_RANGE)
        ln.passes, ln.completed = counts[pid], round(counts[pid] * acc)
    keeper = next((ln for ln in lines.values() if ln.card.pos == "GK"), None)
    if keeper is not None:
        keeper.saves = saves_against
    return SideStats(possession, list(lines.values())), shots


def _match_stats_v2(sides: tuple[_Side, _Side], blocks: list[_Block], r: Result, neutral: bool,
                    end: int) -> tuple[tuple[SideStats, SideStats], list[Shot]]:
    rng = random.Random(f"stats2|{_match_key_v2(sides, neutral, r)}")
    played = sum(b.hi - b.lo for b in blocks)
    ch = sum(control(b.xi[0]) * (b.hi - b.lo) for b in blocks) / played
    ca = sum(control(b.xi[1]) * (b.hi - b.lo) for b in blocks) / played
    p = 0.5 + POSSESSION_K * (ch - ca) + (0 if neutral else POSSESSION_HOME) + rng.gauss(0, POSSESSION_SD)
    p = round(_clamp(p, POSSESSION_RANGE), 3)
    a, a_shots = _side_stats_v2(rng, sides[1], 1, blocks, 1 - p, r.goals, 0, end)
    h, h_shots = _side_stats_v2(rng, sides[0], 0, blocks, p, r.goals, a.on_target - r.away_goals, end)
    keeper = next((ln for ln in a.players if ln.card.pos == "GK"), None)
    if keeper is not None:
        keeper.saves = h.on_target - r.home_goals
    shots = sorted(h_shots + a_shots, key=lambda x: (x.minute, x.side, not x.goal))
    return (h, a), shots
