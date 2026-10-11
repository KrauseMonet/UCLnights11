"""The tournament analysis (C28): how the whole competition played, and how your side
played within it, read off the matches the engine already decided.

Nothing here is new information. Goals and results are calibrated (C8); shots,
possession, passing and saves are declared (C26); marks are declared (C27). Every
board reads ``journey.player_totals``, the same totals the journey card shows.

A rate (a mark, a pass accuracy) is only ranked for a player who played at least
half as many matches as anyone did, so a man with one good night doesn't top a
board that others earned over seven. Half rather than a fixed count, because a room
of two plays a single final. An empty rate is None, never 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from game.journey import PlayerTotals, best_mark_key, player_totals, rank_key, side_result
from game.tournament import ALL_STAGES, FINISHES, Fixture, Side, Tournament

GOAL_BUCKETS = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 90), (91, 120)]
BOARD_SIZE = 5
MIN_PASSES_PER_MATCH = 20       # a pass-accuracy board also needs this many passes a match
REACHED_ORDER = FINISHES


@dataclass
class SideRow:
    side: Side
    reached: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    possession: float = 0.0          # summed; divided by played on the way out
    shots: int = 0
    on_target: int = 0
    passes: int = 0
    completed: int = 0
    clean_sheets: int = 0
    mark: float | None = None


@dataclass
class StageRow:
    stage: str
    matches: int = 0
    goals: int = 0
    shots: int = 0
    extra_time: int = 0
    shootouts: int = 0


@dataclass
class Analysis:
    matches: int
    goals: int
    shots: int
    on_target: int
    passes: int
    completed: int
    extra_time: int
    shootouts: int
    home: tuple[int, int, int]                     # home win / draw / away win, non-neutral matches
    goal_minutes: list[int]                        # per GOAL_BUCKETS, every goal
    your_minutes: tuple[list[int], list[int]] | None   # scored, conceded
    stages: list[StageRow]
    sides: list[SideRow]
    you: SideRow | None
    boards: dict[str, list[tuple[PlayerTotals, float]]]
    min_apps: int
    biggest_win: Fixture | None
    most_goals: Fixture | None
    totals: dict = field(repr=False, default_factory=dict)


def _bucket(minute: int) -> int:
    return next(i for i, (lo, hi) in enumerate(GOAL_BUCKETS) if lo <= minute <= hi)


def tournament_analysis(t: Tournament, you: Side | None = None, totals: dict | None = None) -> Analysis:
    totals = totals if totals is not None else player_totals(t)
    rows = {id(s): SideRow(s, t.reached(s)) for s in t.sides}
    stages = {st: StageRow(st) for st in ALL_STAGES}
    minutes = [0] * len(GOAL_BUCKETS)
    scored, conceded = [0] * len(GOAL_BUCKETS), [0] * len(GOAL_BUCKETS)
    home = [0, 0, 0]
    shots = on_target = passes = completed = goals = extra = pens = 0
    biggest = most = None

    for f in t.fixtures:
        r = f.result
        st = stages[f.stage]
        st.matches += 1
        st.goals += r.home_goals + r.away_goals
        st.extra_time += r.extra_time
        st.shootouts += r.pens is not None
        goals += r.home_goals + r.away_goals
        extra += r.extra_time
        pens += r.pens is not None
        for g in r.goals:
            b = _bucket(g.minute)
            minutes[b] += 1
            if you is not None and you in (f.home, f.away):
                mine = (g.side == 0) == (f.home is you)
                (scored if mine else conceded)[b] += 1
        neutral = f.stage == "Final"
        if not neutral:
            home[0 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 2] += 1
        margin, total = abs(r.home_goals - r.away_goals), r.home_goals + r.away_goals
        if biggest is None or (margin, total) > _margin(biggest):
            biggest = f
        if most is None or (total, margin) > _total(most):
            most = f
        for idx, side in ((0, f.home), (1, f.away)):
            row = rows[id(side)]
            gf, ga = (r.home_goals, r.away_goals) if idx == 0 else (r.away_goals, r.home_goals)
            res = side_result(f, idx)
            row.played += 1
            row.won += res == "w"
            row.drawn += res == "d"
            row.lost += res == "l"
            row.gf += gf
            row.ga += ga
            row.clean_sheets += ga == 0
            if r.stats is not None:
                s = r.stats[idx]
                row.possession += s.possession
                row.shots += s.shots
                row.on_target += s.on_target
                row.passes += s.passes
                row.completed += s.completed
                shots += s.shots
                on_target += s.on_target
                passes += s.passes
                completed += s.completed
                st.shots += s.shots

    for row in rows.values():
        row.possession = row.possession / row.played if row.played else 0.0
        marks = [p.mark for p in totals.values() if p.side is row.side and p.mark is not None]
        row.mark = round(sum(marks) / len(marks), 2) if marks else None
    order = sorted(rows.values(), key=lambda r: (REACHED_ORDER.index(r.reached), -(r.won * 3 + r.drawn),
                                                  -(r.gf - r.ga), -r.gf, r.side.name))

    players = list(totals.values())
    most_apps = max((p.apps for p in players), default=0)
    min_apps = max(1, math.ceil(most_apps / 2))
    regulars = [p for p in players if p.apps >= min_apps]
    # Outfield only: a keeper's few short passes topping "best passing" would read as a glitch.
    passers = [p for p in regulars if p.card.pos != "GK" and p.passes >= MIN_PASSES_PER_MATCH * p.apps]
    keepers = [p for p in players if p.card.pos == "GK"]

    def board(pool, value, key=None):
        ranked = sorted((p for p in pool if value(p) is not None and value(p) > 0), key=key or rank_key(value))
        return [(p, value(p)) for p in ranked[:BOARD_SIZE]]

    boards = {
        "goals": board(players, lambda p: p.goals),
        "assists": board(players, lambda p: p.assists),
        "on_target": board(players, lambda p: p.on_target),
        "mark": board(regulars, lambda p: p.mark, best_mark_key),
        "accuracy": board(passers, lambda p: p.accuracy),
        "saves": board(keepers, lambda p: p.saves),
        "clean_sheets": board(keepers, lambda p: p.clean_sheets),
    }
    return Analysis(
        matches=len(t.fixtures), goals=goals, shots=shots, on_target=on_target, passes=passes,
        completed=completed, extra_time=extra, shootouts=pens, home=tuple(home), goal_minutes=minutes,
        your_minutes=(scored, conceded) if you is not None else None,
        stages=[s for s in stages.values() if s.matches], sides=order,
        you=rows[id(you)] if you is not None else None, boards=boards, min_apps=min_apps,
        biggest_win=biggest, most_goals=most, totals=totals,
    )


def _margin(f: Fixture) -> tuple[int, int]:
    r = f.result
    return abs(r.home_goals - r.away_goals), r.home_goals + r.away_goals


def _total(f: Fixture) -> tuple[int, int]:
    r = f.result
    return r.home_goals + r.away_goals, abs(r.home_goals - r.away_goals)

