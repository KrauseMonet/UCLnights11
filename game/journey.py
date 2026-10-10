"""Players' tournaments: every man's numbers added up over his side's matches, a mark
out of ten for each match he played, and a side's whole journey for its card (C27).

One function (``player_totals``) adds the numbers up, and the journey card, the
tournament's leaderboards and the analysis all read it, so a tie or a total can
never come out one way on one screen and another way on the next (the cricket site's
A175). Rows are keyed by (side, person): the same man can play for two sides in one
tournament -- a friend drafted him and his real club was drawn -- and adding those
together would credit him with a tournament no single team had.

The MARK is declared game design, like the ratings: a broadcaster's 6-out-of-10 for a
quiet game, built from the match statistics (themselves declared, C26). It is a
summary of what the engine already decided, never an input to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from game.deck import Card
from game.match import PlayerLine
from game.tournament import Fixture, Side, Tournament

# -- the mark ------------------------------------------------------------------
MARK_BASE = 6.4
MARK_GOAL = 0.9
MARK_ASSIST = 0.75
MARK_ON_TARGET = 0.15           # a shot on target that didn't go in
MARK_ACCURACY = 4.0             # per unit of pass accuracy above ACCURACY_PAR ...
ACCURACY_PAR = 0.84
MARK_MIN_PASSES = 10            # ... once a player has made this many
MARK_SAVE = 0.2
MARK_CONCEDED = {"GK": -0.3, "DF": -0.1, "MF": -0.05, "FW": 0.0}
MARK_CLEAN_SHEET = {"GK": 0.8, "DF": 0.6, "MF": 0.2, "FW": 0.0}
MARK_WIN, MARK_LOSS = 0.3, -0.3
MARK_RANGE = (3.0, 10.0)

KNOCKOUT_STAGES = ("Round of 16", "Quarter-finals", "Semi-finals", "Final")


def match_mark(line: PlayerLine, goals: int, assists: int, conceded: int, result: str) -> float:
    """``result`` is "w", "d" or "l" from this player's side (a shoot-out is a draw
    that went on)."""
    pos = line.card.pos
    m = MARK_BASE + MARK_GOAL * goals + MARK_ASSIST * assists
    m += MARK_ON_TARGET * (line.on_target - goals)
    if line.passes >= MARK_MIN_PASSES:
        m += MARK_ACCURACY * (line.completed / line.passes - ACCURACY_PAR)
    m += MARK_SAVE * line.saves + MARK_CONCEDED[pos] * conceded
    if conceded == 0:
        m += MARK_CLEAN_SHEET[pos]
    m += {"w": MARK_WIN, "l": MARK_LOSS}.get(result, 0.0)
    return round(min(max(m, MARK_RANGE[0]), MARK_RANGE[1]), 1)


# -- one player's tournament ---------------------------------------------------

@dataclass
class PlayerTotals:
    card: Card
    side: Side
    apps: int = 0
    minutes: int = 0
    goals: int = 0
    assists: int = 0
    shots: int = 0
    on_target: int = 0
    passes: int = 0
    completed: int = 0
    saves: int = 0
    clean_sheets: int = 0
    marks: list[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float | None:
        """None for a player who made no pass, never 0%."""
        return self.completed / self.passes if self.passes else None

    @property
    def mark(self) -> float | None:
        return round(sum(self.marks) / len(self.marks), 2) if self.marks else None


def side_result(f: Fixture, side_index: int) -> str:
    r = f.result
    if r.pens is not None or r.home_goals == r.away_goals:
        return "d"
    won = (r.home_goals > r.away_goals) == (side_index == 0)
    return "w" if won else "l"


def player_totals(t: Tournament) -> dict[tuple[int, str], PlayerTotals]:
    """Every player of every side, keyed by (id(side), person id)."""
    out: dict[tuple[int, str], PlayerTotals] = {}
    for f in t.fixtures:
        r = f.result
        if r.stats is None:
            continue
        minutes = 120 if r.extra_time else 90
        for idx, side, st in ((0, f.home, r.stats[0]), (1, f.away, r.stats[1])):
            conceded = r.away_goals if idx == 0 else r.home_goals
            result = side_result(f, idx)
            for line in st.players:
                c = line.card
                goals = sum(1 for g in r.goals if g.side == idx and g.scorer is c)
                assists = sum(1 for g in r.goals if g.side == idx and g.assist is c)
                p = out.setdefault((id(side), c.id), PlayerTotals(c, side))
                p.apps += 1
                p.minutes += minutes
                p.goals += goals
                p.assists += assists
                p.shots += line.shots
                p.on_target += line.on_target
                p.passes += line.passes
                p.completed += line.completed
                p.saves += line.saves
                p.clean_sheets += conceded == 0
                p.marks.append(match_mark(line, goals, assists, conceded, result))
    return out


# Leaderboard orders, shared by every screen that ranks players: the count, then the
# better mark, then the name, so ties settle the same way everywhere.
def rank_key(value):
    return lambda p: (-value(p), -(p.mark or 0), p.card.name)


def best_mark_key(p: PlayerTotals):
    return (-(p.mark or 0), -(p.goals + p.assists), p.card.name)


# -- a side's journey ----------------------------------------------------------

@dataclass
class MatchLine:
    fixture: Fixture
    side_index: int
    outcome: str            # w / d / l, a shoot-out counted as its winner's w
    knockout: bool


@dataclass
class Journey:
    side: Side
    reached: str
    matches: list[MatchLine]
    players: list[PlayerTotals]      # the eleven, back to front
    goals_for: int
    goals_against: int
    possession: float | None         # mean share over the matches
    shots: int
    on_target: int
    passes: int
    completed: int
    clean_sheets: int

    @property
    def record(self) -> tuple[int, int, int]:
        return tuple(sum(m.outcome == o for m in self.matches) for o in "wdl")

    def top(self, value) -> PlayerTotals | None:
        """The leader by `value`, or None when nobody has any (no top scorer of 0)."""
        best = sorted(self.players, key=rank_key(value))
        return best[0] if best and value(best[0]) > 0 else None

    @property
    def star(self) -> PlayerTotals | None:
        rated = [p for p in self.players if p.mark is not None]
        return sorted(rated, key=best_mark_key)[0] if rated else None


LINE_ORDER = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}


def journey(t: Tournament, side: Side, totals: dict | None = None) -> Journey:
    totals = totals if totals is not None else player_totals(t)
    lines = []
    for f in t.fixtures:
        if side not in (f.home, f.away):
            continue
        idx = 0 if f.home is side else 1
        outcome = side_result(f, idx)
        if f.result.pens is not None:
            mine, theirs = f.result.pens if idx == 0 else f.result.pens[::-1]
            outcome = "w" if mine > theirs else "l"
        lines.append(MatchLine(f, idx, outcome, f.stage in KNOCKOUT_STAGES))
    stats = [m.fixture.result.stats[m.side_index] for m in lines if m.fixture.result.stats]
    gf = sum(m.fixture.result.home_goals if m.side_index == 0 else m.fixture.result.away_goals for m in lines)
    ga = sum(m.fixture.result.away_goals if m.side_index == 0 else m.fixture.result.home_goals for m in lines)
    players = sorted((totals[(id(side), c.id)] for c in side.xi if (id(side), c.id) in totals),
                     key=lambda p: (LINE_ORDER[p.card.pos], -p.card.rating))
    return Journey(
        side=side, reached=t.reached(side), matches=lines, players=players,
        goals_for=gf, goals_against=ga,
        possession=sum(s.possession for s in stats) / len(stats) if stats else None,
        shots=sum(s.shots for s in stats), on_target=sum(s.on_target for s in stats),
        passes=sum(s.passes for s in stats), completed=sum(s.completed for s in stats),
        clean_sheets=sum(1 for m in lines if (m.fixture.result.away_goals if m.side_index == 0
                                              else m.fixture.result.home_goals) == 0),
    )
