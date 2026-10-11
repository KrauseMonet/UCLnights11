"""Watching a room's tournament together (C52): one clock for every screen.

The tournament is played in full the moment a room completes (it is a pure function of
the room), so watching it together is only a matter of time. The watch is cut into
ROUNDS, one per matchday or leg in which at least one friend plays; a round is a
countdown, then every friend's match of that round at once, then a moment at full time.
At 0.1 s a match minute a league run to the final watches in about six minutes. The schedule is a list of
offsets from the moment the host kicked off, and where everyone is follows from that
moment and the clock, so the server stores one number and no screen waits on another.

A round with no friend in it is left out, so the friends who finished in the top eight
go straight from the last matchday to the round of 16. That says nothing early: whether
a friend plays round r+1 is settled by the results up to round r, which everyone has seen
by then. The watch ends a moment after the last round any friend plays.

What a screen may know is cut by the clock too (web.app.watch_out): a round's pairings
when its countdown begins, its results at kick-off, the standings after it at full time.

Only the host can move the clock, and only forward: a skip moves the kick-off moment
earlier, so every screen jumps to the same place.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from game.tournament import LEAGUE, Fixture, Side, Tournament, league_table

BREAK_S = 8.0         # the countdown before each round's kick-off
MINUTE_S = 0.1        # one match minute; a round where extra time can come gets 120 of them
AFTER_S = 5.0         # full time stays on screen this long before the next countdown
HOLD_S = 2.0          # and after the last round, this much longer before the watch ends
HOST_WAIT_S = 180.0   # after the room completes, a seat may kick off if the host hasn't

FIRST_PHASES = (LEAGUE, "Group stage")
PARTS = ("pairs", "results", "after")   # what a round lets out, in the order it does


@dataclass(frozen=True)
class Round:
    stage: str
    label: str
    fixtures: tuple[Fixture, ...]   # the friends' matches in it
    key: int                        # its place among every round the tournament played
    start: float                    # its countdown begins, seconds after kick-off
    minutes: int

    @property
    def kick(self) -> float:
        return self.start + BREAK_S

    @property
    def end(self) -> float:
        return self.kick + self.minutes * MINUTE_S + AFTER_S

    def at(self, part: int) -> float:
        """When part ``part`` of PARTS becomes known."""
        return (self.start, self.kick, self.end)[part]


def rounds(t: Tournament) -> list[Round]:
    """The rounds the room watches, in playing order. Fixtures are stored in the order
    they were played, a round's at the first appearance of its (stage, label); a second
    leg and a final may go to extra time, so they get 120 minutes whether they do or not
    (an allowance that depended on the result would give the result away)."""
    order: dict[tuple[str, str], list[Fixture]] = {}
    for f in t.fixtures:
        order.setdefault((f.stage, f.label), []).append(f)
    out, start = [], 0.0
    for key, ((stage, label), fixtures) in enumerate(order.items()):
        mine = tuple(f for f in fixtures if f.home.owner is not None or f.away.owner is not None)
        if not mine:
            continue
        r = Round(stage, label, mine, key, start, 120 if label in ("Second leg", "Final") else 90)
        out.append(r)
        start = r.end
    return out


def end_at(rs: list[Round]) -> float:
    return rs[-1].end + HOLD_S


def known(rs: list[Round], p: float) -> int:
    """How many parts are out at ``p`` seconds after kick-off: part j is part j % 3 of
    round j // 3, and they come out in that order, so a count says which."""
    n = 0
    for r in rs:
        for part in range(len(PARTS)):
            if r.at(part) <= p:
                n += 1
    return n


def current(rs: list[Round], p: float) -> int:
    """The round whose countdown began last; -1 before kick-off."""
    return max((i for i, r in enumerate(rs) if r.start <= p), default=-1)


SKIPS = ("kickoff", "fulltime", "phase", "end")


def skip_target(rs: list[Round], to: str, expect: int) -> float:
    """Where a host's skip lands, in seconds after kick-off. ``expect`` is the round the
    host's screen showed: kick-off and full time are that round's, so a click that
    arrives after the round moved on (a double click, a slow reply) lands somewhere
    already passed and changes nothing, rather than skipping a round nobody saw."""
    if to not in SKIPS:
        raise ValueError(f"no skip {to!r}")
    if to in ("kickoff", "fulltime"):
        if not 0 <= expect < len(rs):
            raise ValueError("no such round")
        # Full time is the whistle at the end of the round's allowance, so the result
        # stays on screen for AFTER_S like any other.
        return rs[expect].kick if to == "kickoff" else rs[expect].end - AFTER_S
    if to == "phase":
        return next((r.start for r in rs if r.stage not in FIRST_PHASES), end_at(rs))
    return end_at(rs)


@dataclass
class Standing:
    side: Side
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    points: int = 0            # first-phase points
    position: int | None = None  # in the league table, while it is being played
    out: str | None = None     # how far the side went, once it is out


def standings(t: Tournament, rs: list[Round], i: int) -> list[Standing]:
    """Every friend's record after round ``i``: matches, goals, league points and place,
    and whether they are out (no match in any later round the tournament played)."""
    last = rs[i].key
    keys: dict[tuple[str, str], int] = {}
    for f in t.fixtures:
        keys.setdefault((f.stage, f.label), len(keys))
    played = [f for f in t.fixtures if keys[(f.stage, f.label)] <= last]
    humans = [s for s in t.sides if s.owner is not None]
    table = None
    if t.format == "league" and rs[i].stage == LEAGUE:
        # The table so far; lots (a full tie) drawn from a fixed stream, display only.
        table = [r.side for r in league_table(t.sides, [f for f in played if f.stage == LEAGUE],
                                              random.Random(0))]
    out = []
    for s in humans:
        st = Standing(s)
        for f in played:
            if s is not f.home and s is not f.away:
                continue
            r = f.result
            us, them = (r.home_goals, r.away_goals) if f.home is s else (r.away_goals, r.home_goals)
            st.played += 1
            st.gf, st.ga = st.gf + us, st.ga + them
            if r.pens is not None:
                won = (r.pens[0] > r.pens[1]) == (f.home is s)
                st.won, st.lost = st.won + won, st.lost + (not won)
            else:
                st.won, st.drawn, st.lost = st.won + (us > them), st.drawn + (us == them), st.lost + (us < them)
            if f.stage in FIRST_PHASES:
                st.points += 3 * (us > them) + (us == them)
        if table is not None:
            st.position = table.index(s) + 1
        alive = any(keys[(f.stage, f.label)] > last for f in t.fixtures if s in (f.home, f.away))
        if not alive:
            st.out = t.reached(s)
        out.append(st)
    return out
