"""A whole tournament: your eleven and 31 real quarter-final sides -- or, for a room of
friends (play_room), every friend's eleven and real sides filling the rest of a 2-, 4-,
8-, 16- or 32-team draw.

The format is the classic one (1999-2000 to 2023-24 in spirit): eight groups of
four seeded from four pots by strength, home and away; the top two go through;
the round of 16 pairs group winners with runners-up from other groups, winners
at home in the second leg; quarter- and semi-finals are an open draw; the final
is one match at a neutral ground. Level ties go to thirty minutes of extra time
in the second leg and then penalties -- no away-goals rule, as since 2021-22.

The opposition is 31 different clubs, each in one season drawn uniformly from
the deck (draw_opposition), and each fields the best eleven its rated players
allow (best_xi). Nobody is
invented: a club-season the deck holds can always field one, which etl.deck
guarantees before admitting it.

A room of 2 to 16 is a straight knockout (CUP_STAGES): an open draw each round,
two legs until the final, which is one match at a neutral ground. A room of 32 plays
the full format above. Either way the empty places go to real sides drawn exactly as
the solo opposition is, at most one season per club.

Everything is a pure function of the seed and the human elevens, so the server keeps
no tournament state at all.

``engine`` picks the match engine (game.match): 1, the original, which every existing
link and room replays with; or 2, with tiredness and substitutes (C39), where each club
side brings on its bench (club_bench) by match.AUTO_PLAN.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from game import match
from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation
from game.positions import arrange, fits, place

TEAMS = 32
GROUPS = "ABCDEFGH"
# A group's six matchdays: (home, away) by position in the group.
GROUP_ROUNDS = [((0, 1), (2, 3)), ((2, 0), (3, 1)), ((0, 3), (1, 2)),
                ((1, 0), (3, 2)), ((0, 2), (1, 3)), ((3, 0), (2, 1))]
STAGES = ["Group stage", "Round of 16", "Quarter-finals", "Semi-finals", "Final"]
# A room's size and the knockout rounds it plays. 32 plays the group format instead.
CUP_STAGES = {2: STAGES[4:], 4: STAGES[3:], 8: STAGES[2:], 16: STAGES[1:]}
ROOM_SIZES = (2, 4, 8, 16, 32)


@dataclass(eq=False)
class Side:
    key: str
    name: str
    short: str
    formation: Formation
    xi: list[Card]
    you: bool = False
    owner: int | None = None       # the account whose eleven this is, in a room
    club: str | None = None
    season: int | None = None
    label: str | None = None       # "2004–05"
    club_name: str | None = None   # "Milan"
    crest: str | None = None       # a crest key (game.crests), None for your own XI
    team: str = "#f2c25a"          # your own eleven: the logo's gold "11"
    deep: str = "#4c370b"
    ink: str = "#ffe08e"
    bench: list[Card] = field(default_factory=list)     # engine 2 only
    plan: tuple[match.Sub, ...] = ()

    def __post_init__(self) -> None:
        # Every side plays with each man in a slot of its formation, carrying the slot's
        # line (game.positions); a drafted eleven arrives as picks and is placed here.
        if any(c.slot is None for c in self.xi):
            self.xi = arrange(self.formation.slots, self.xi)

    @property
    def strength(self) -> float:
        return (match.attack(self.xi) + match.defence(self.xi)) / 2


_BEST: dict[int, tuple[Formation, list[Card]]] = {}


def best_xi(cs: ClubSeason) -> tuple[Formation, list[Card]]:
    """The strongest legal eleven a squad's rated players can field, placed in its slots.
    etl.deck works it out once (over every formation, a maximum-rating assignment of
    players to slots they hold) and stores it with the squad."""
    got = _BEST.get(id(cs))
    if got is None:
        code, xi = cs.best
        got = _BEST[id(cs)] = (FORMATIONS[code], [place(cs.cards[i], slot) for i, slot in xi])
    return got[0], list(got[1])


_BENCH: dict[int, list[Card]] = {}
BENCH_SIZE = 3


def club_bench(cs: ClubSeason) -> list[Card]:
    """A club's substitutes for engine 2: its best-rated outfield players outside the best
    eleven who could each come on for somebody in it, the formation still filled. The
    goalkeeper is never changed, so no keeper sits here."""
    got = _BENCH.get(id(cs))
    if got is None:
        f, xi = best_xi(cs)
        starters = {c.id for c in xi}
        rest = sorted((c for c in cs.cards if c.id not in starters and c.positions != ("GK",)),
                      key=lambda c: -c.rating)
        got = [c for c in rest
               if any(fits(f.slots, [*(x for x in xi if x is not off), c]) for off in xi if off.pos != "GK")]
        got = _BENCH[id(cs)] = got[:BENCH_SIZE]
    return list(got)


def club_side(cs: ClubSeason) -> Side:
    f, xi = best_xi(cs)
    return Side(cs.key, cs.title, cs.short, f, xi, club=cs.club, season=cs.season,
                label=cs.label, club_name=cs.name, crest=cs.crest,
                team=cs.team, deep=cs.deep, ink=cs.ink,
                bench=club_bench(cs), plan=match.AUTO_PLAN)


def teamsheet(side: Side) -> match.Teamsheet:
    return match.Teamsheet(side.formation.slots, tuple(side.xi), tuple(side.bench), side.plan)


def play_match(rng: random.Random, home: Side, away: Side, league: match.League, engine: int = 1,
               **kw) -> match.Result:
    """One match between two sides, by the chosen engine."""
    if engine == 1:
        return match.play(rng, home.xi, away.xi, league, **kw)
    if engine == 2:
        return match.play_v2(rng, teamsheet(home), teamsheet(away), league, **kw)
    raise ValueError(f"no engine {engine!r}")


def league_of(deck: Deck) -> match.League:
    """The zero point of the strength model: the deck's average best eleven."""
    sides = [best_xi(cs)[1] for cs in deck.club_seasons]
    return match.League(
        attack=sum(match.attack(x) for x in sides) / len(sides),
        defence=sum(match.defence(x) for x in sides) / len(sides),
    )


@dataclass(eq=False)
class Fixture:
    stage: str
    home: Side
    away: Side
    result: match.Result
    label: str            # "Matchday 3", "First leg", "Final"
    group: str | None = None


@dataclass
class Row:
    side: Side
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn


@dataclass(eq=False)
class Tie:
    stage: str
    a: Side               # hosts the first leg (or is listed first in the final)
    b: Side
    legs: list[Fixture]
    winner: Side

    def aggregate(self) -> tuple[int, int]:
        a = b = 0
        for f in self.legs:
            if f.home is self.a:
                a, b = a + f.result.home_goals, b + f.result.away_goals
            else:
                a, b = a + f.result.away_goals, b + f.result.home_goals
        return a, b


@dataclass
class Tournament:
    sides: list[Side]
    groups: dict[str, list[Side]]
    tables: dict[str, list[Row]]
    fixtures: list[Fixture] = field(default_factory=list)   # in the order they were played
    ties: list[Tie] = field(default_factory=list)
    champion: Side | None = None

    def you(self) -> Side:
        return next(s for s in self.sides if s.you)

    @property
    def stages(self) -> list[str]:
        """The knockout rounds this tournament played, in order."""
        return [st for st in STAGES[1:] if any(t.stage == st for t in self.ties)]

    def reached(self, side: Side) -> str:
        """How far a side went: the stage it went out in, or Champions."""
        if side is self.champion:
            return "Champions"
        out = None
        for t in self.ties:
            if side in (t.a, t.b) and t.winner is not side:
                out = t.stage
        if out == "Final":
            return "Runners-up"
        return out or "Group stage"


def _table(sides: list[Side], fixtures: list[Fixture], rng: random.Random) -> list[Row]:
    rows = {id(s): Row(s) for s in sides}
    for f in fixtures:
        h, a, r = rows[id(f.home)], rows[id(f.away)], f.result
        for row, gf, ga in ((h, r.home_goals, r.away_goals), (a, r.away_goals, r.home_goals)):
            row.played += 1
            row.gf += gf
            row.ga += ga
            row.won += gf > ga
            row.drawn += gf == ga
            row.lost += gf < ga
    # Points, goal difference, goals scored; a full tie goes to a drawing of lots,
    # seeded so the same tournament always settles it the same way.
    lots = {id(s): rng.random() for s in sides}
    return sorted(rows.values(), key=lambda r: (-r.points, -(r.gf - r.ga), -r.gf, lots[id(r.side)]))


def _draw_groups(rng: random.Random, sides: list[Side]) -> dict[str, list[Side]]:
    ranked = sorted(sides, key=lambda s: -s.strength)
    pots = [ranked[i * 8:(i + 1) * 8] for i in range(4)]
    for _ in range(200):
        for pot in pots:
            rng.shuffle(pot)
        groups = {g: [pots[p][i] for p in range(4)] for i, g in enumerate(GROUPS)}
        if all(len({s.club for s in grp if s.club}) == sum(1 for s in grp if s.club)
               for grp in groups.values()):
            return groups
    return groups   # two seasons of one club in a group: rare, and legal enough


def _pairings(rng: random.Random, winners: list[Side], runners: list[Side],
              group_of: dict[int, str]) -> list[tuple[Side, Side]]:
    """Round of 16: each runner-up meets a winner from another group."""
    for _ in range(500):
        order = runners[:]
        rng.shuffle(order)
        pairs = list(zip(order, winners))
        if all(group_of[id(r)] != group_of[id(w)] and (r.club is None or r.club != w.club)
               for r, w in pairs):
            return pairs
    return list(zip(runners, winners))


def _two_legs(rng: random.Random, stage: str, a: Side, b: Side, league: match.League,
              engine: int) -> Tie:
    first = play_match(rng, a, b, league, engine)
    second = play_match(rng, b, a, league, engine, extra_time_if_level=True,
                        level_on=(first.away_goals, first.home_goals))
    legs = [Fixture(stage, a, b, first, "First leg"), Fixture(stage, b, a, second, "Second leg")]
    tie = Tie(stage, a, b, legs, a)
    ga, gb = tie.aggregate()
    if second.pens is not None:
        tie.winner = b if second.pens[0] > second.pens[1] else a
    else:
        tie.winner = a if ga > gb else b
    return tie


def draw_opposition(rng: random.Random, deck: Deck, n: int = TEAMS - 1) -> list[ClubSeason]:
    """n club-seasons (31 for a solo tournament), at most one per club.

    Drawn uniformly over club-seasons and skipping a club already drawn, so a
    club with many quarter-finals is still likelier to appear -- but a real
    tournament never holds the same club twice, and six Real Madrids in one draw
    read as a bug rather than a dream.
    """
    if n == 0:
        return []
    pool = list(deck.club_seasons)
    rng.shuffle(pool)
    out, clubs = [], set()
    for cs in pool:
        if cs.club not in clubs:
            out.append(cs)
            clubs.add(cs.club)
            if len(out) == n:
                return out
    raise ValueError(f"the deck holds only {len(clubs)} clubs; a tournament needs {n}")


def _knockout(rng: random.Random, t: Tournament, alive: list[Side], stages: list[str],
              league: match.League, engine: int) -> None:
    """Open-draw two-legged rounds, then a one-match final at a neutral ground."""
    for stage in stages[:-1]:
        rng.shuffle(alive)
        nxt = []
        for i in range(0, len(alive), 2):
            tie = _two_legs(rng, stage, alive[i], alive[i + 1], league, engine)
            t.ties.append(tie)
            t.fixtures += tie.legs
            nxt.append(tie.winner)
        alive = nxt

    a, b = alive
    final = play_match(rng, a, b, league, engine, neutral=True, extra_time_if_level=True)
    fx = Fixture("Final", a, b, final, "Final")
    t.fixtures.append(fx)
    t.ties.append(Tie("Final", a, b, [fx], a if final.winner == 0 else b))
    t.champion = t.ties[-1].winner


def play_tournament(deck: Deck, league: match.League, seed: int, you: Side,
                    engine: int = 1) -> Tournament:
    """Your eleven against 31 real sides: the solo game."""
    return _group_tournament(deck, league, seed, [you], engine)


def play_room(deck: Deck, league: match.League, seed: int, humans: list[Side],
              size: int, engine: int = 1) -> Tournament:
    """A room's tournament: every human eleven, and real sides filling the other places.

    ``size`` is one of ROOM_SIZES. 32 plays groups and knockouts exactly as the solo
    game does; the smaller sizes are straight knockouts, so 2 is a single final."""
    if size not in ROOM_SIZES:
        raise ValueError(f"a room holds {', '.join(map(str, ROOM_SIZES))} sides, not {size}")
    if not 1 <= len(humans) <= size:
        raise ValueError(f"{len(humans)} players cannot fill a {size}-side room")
    if size == TEAMS:
        return _group_tournament(deck, league, seed, humans, engine)
    rng = random.Random(f"{seed}:cup")
    sides = list(humans) + [club_side(cs) for cs in draw_opposition(rng, deck, size - len(humans))]
    t = Tournament(sides, {}, {})
    _knockout(rng, t, list(sides), CUP_STAGES[size], league, engine)
    return t


def _group_tournament(deck: Deck, league: match.League, seed: int,
                      humans: list[Side], engine: int) -> Tournament:
    rng = random.Random(f"{seed}:cup")
    sides = list(humans) + [club_side(cs) for cs in draw_opposition(rng, deck, TEAMS - len(humans))]
    groups = _draw_groups(rng, sides)
    t = Tournament(sides, groups, {})

    group_fixtures: dict[str, list[Fixture]] = defaultdict(list)
    for md, rounds in enumerate(GROUP_ROUNDS, start=1):
        for g in GROUPS:
            for h, a in rounds:
                home, away = groups[g][h], groups[g][a]
                f = Fixture("Group stage", home, away, play_match(rng, home, away, league, engine),
                            f"Matchday {md}", group=g)
                group_fixtures[g].append(f)
                t.fixtures.append(f)
    for g in GROUPS:
        t.tables[g] = _table(groups[g], group_fixtures[g], rng)

    group_of = {id(s): g for g in GROUPS for s in groups[g]}
    winners = [t.tables[g][0].side for g in GROUPS]
    runners = [t.tables[g][1].side for g in GROUPS]
    # The runner-up hosts the first leg; the group winner is at home in the second.
    alive = []
    for r, w in _pairings(rng, winners, runners, group_of):
        tie = _two_legs(rng, "Round of 16", r, w, league, engine)
        t.ties.append(tie)
        t.fixtures += tie.legs
        alive.append(tie.winner)

    _knockout(rng, t, alive, STAGES[2:], league, engine)
    return t


def leaders(t: Tournament, what: str = "goals", limit: int = 10) -> list[tuple[Card, Side, int]]:
    """Top scorers (or assisters), one row per (person, SIDE).

    Keyed on the side as well as the person because the same man can turn up in
    two drawn club-seasons, and adding his goals for both would credit him with a
    tournament no single team had.
    """
    counts: dict[tuple[str, int], list] = {}
    for f in t.fixtures:
        for g in f.result.goals:
            card = g.scorer if what == "goals" else g.assist
            if card is None:
                continue
            side = f.home if g.side == 0 else f.away
            entry = counts.setdefault((card.id, id(side)), [card, side, 0])
            entry[2] += 1
    rows = sorted(counts.values(), key=lambda e: (-e[2], -e[0].rating, e[0].name))
    return [tuple(e) for e in rows[:limit]]
