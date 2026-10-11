"""A whole tournament: your eleven and 35 real quarter-final sides -- or, for a room of
friends (play_room), every friend's eleven and real sides filling the rest of a 2-, 4-,
8-, 16- or 36-team draw.

THE LEAGUE PHASE (C50; every new draft and room plays it, the format since 2024-25): 36
sides in four pots of nine by strength, drawn by game.league_phase so that each plays
two from every pot, one at home and one away, never a club of its own association and
at most two of any one, over eight matchdays. One table of 36, ranked by points, goal
difference, goals, away goals, wins, away wins, and then the points, goal difference
and goals of the opponents each side met; a drawing of lots settles the rest (in place
of disciplinary points and the UEFA coefficient, which the engine has neither of). The
top eight go to the round of 16; 9th to 24th play two-legged knockout play-offs, 9/10
against 23/24, 11/12 against 21/22, 13/14 against 19/20, 15/16 against 17/18, each
seeded side drawn against one of its section's two and at home in the second leg. The
bracket is then fixed: 1/2 meet the play-off winners from 15-18, 3/4 those from 13/14
and 19/20, 5/6 those from 11/12 and 21/22, 7/8 those from 9/10 and 23/24, the league
side at home in the second leg; each seed is drawn into one half (so 1 and 2 can meet
only in the final) and against one of its two play-off winners. Quarter-finals pair
section A with D and B with C in each half, and the draw decides only who hosts the
first leg, as in the semi-finals. Rules as Wikipedia's 2024-25 knockout phase article
states them. The opposition is at most five clubs of one association (four league
places and a European Performance Spot, the most an association enters without a
holder's place; there are no holders here), and the draw needs no more.

THE GROUP FORMAT (retired for new play; every link and room made before C50 still plays
it, exactly as it did) is the classic one (1999-2000 to 2023-24 in spirit): eight groups of
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
two legs until the final, which is one match at a neutral ground. A room of 36 plays
the league phase, and one of 32 (made before C50) the group format. Either way the empty
places go to real sides drawn exactly as the solo opposition is, at most one season per
club.

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

from game import league_phase, match
from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation
from game.positions import arrange, fits, place

TEAMS = 32
GROUPS = "ABCDEFGH"
# A group's six matchdays: (home, away) by position in the group.
GROUP_ROUNDS = [((0, 1), (2, 3)), ((2, 0), (3, 1)), ((0, 3), (1, 2)),
                ((1, 0), (3, 2)), ((0, 2), (1, 3)), ((3, 0), (2, 1))]
STAGES = ["Group stage", "Round of 16", "Quarter-finals", "Semi-finals", "Final"]
LEAGUE_TEAMS = league_phase.TEAMS
LEAGUE, PLAYOFFS = "League phase", "Knockout play-offs"
LEAGUE_STAGES = [LEAGUE, PLAYOFFS, *STAGES[1:]]
ALL_STAGES = [STAGES[0], LEAGUE, PLAYOFFS, *STAGES[1:]]
KNOCKOUT_ROUNDS = [PLAYOFFS, *STAGES[1:]]
# How far a side went, furthest first. Both formats' first rounds are here, because saved
# results and old links hold the group format's.
FINISHES = ["Champions", "Runners-up", "Semi-finals", "Quarter-finals", "Round of 16", PLAYOFFS,
            LEAGUE, STAGES[0]]
MAX_PER_ASSOCIATION = 5         # clubs of one association in a league-phase draw
# A room's size and the knockout rounds it plays. 36 plays the league phase, 32 the group
# format; new rooms are made only in ROOM_SIZES, so a room of 32 is one made before C50.
CUP_STAGES = {2: STAGES[4:], 4: STAGES[3:], 8: STAGES[2:], 16: STAGES[1:]}
ROOM_SIZES = (2, 4, 8, 16, LEAGUE_TEAMS)
PLAYABLE_SIZES = (2, 4, 8, 16, TEAMS, LEAGUE_TEAMS)
# The knockout play-offs: (seeded positions, unseeded positions), 0-based, by section.
PLAYOFF_SECTIONS = [((8, 9), (22, 23)), ((10, 11), (20, 21)), ((12, 13), (18, 19)), ((14, 15), (16, 17))]
# The round of 16: each section's two league seeds and the play-off section whose winners they meet.
R16_SECTIONS = {"A": ((0, 1), 3), "B": ((2, 3), 2), "C": ((4, 5), 1), "D": ((6, 7), 0)}


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
    association: str | None = None # a club's UEFA association ("ENG"), None for a drafted XI
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


def auto_plan(bench: list[Card]) -> tuple[match.Sub, ...]:
    """The automatic plan for a bench: match.AUTO_PLAN's minutes, the best-rated man first,
    as a club brings its bench on. A drafted bench is in the order it was picked, which
    says nothing about who should come on when (C40)."""
    order = sorted(range(len(bench)), key=lambda i: (-bench[i].rating, i))
    return tuple(match.Sub(i, sub.minute, sub.when, sub.off) for i, sub in zip(order, match.AUTO_PLAN))


def club_side(cs: ClubSeason) -> Side:
    f, xi = best_xi(cs)
    bench = club_bench(cs)
    return Side(cs.key, cs.title, cs.short, f, xi, club=cs.club, season=cs.season,
                label=cs.label, club_name=cs.name, crest=cs.crest, association=cs.association,
                team=cs.team, deep=cs.deep, ink=cs.ink,
                bench=bench, plan=auto_plan(bench))


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
    half: int | None = None   # the league format's knockouts: which half of the bracket


@dataclass
class Row:
    side: Side
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0
    away_gf: int = 0      # the league phase's tie-breakers
    away_won: int = 0

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
    half: int | None = None

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
    format: str = "groups"                                 # or "league"
    table: list[Row] = field(default_factory=list)         # the league phase's
    pots: list[list[Side]] = field(default_factory=list)   # the league phase's draw

    def you(self) -> Side:
        return next(s for s in self.sides if s.you)

    @property
    def stages(self) -> list[str]:
        """The knockout rounds this tournament played, in order."""
        return [st for st in KNOCKOUT_ROUNDS if any(t.stage == st for t in self.ties)]

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
        return out or (LEAGUE if self.format == "league" else STAGES[0])


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
              engine: int, half: int | None = None) -> Tie:
    first = play_match(rng, a, b, league, engine)
    second = play_match(rng, b, a, league, engine, extra_time_if_level=True,
                        level_on=(first.away_goals, first.home_goals))
    legs = [Fixture(stage, a, b, first, "First leg", half=half),
            Fixture(stage, b, a, second, "Second leg", half=half)]
    tie = Tie(stage, a, b, legs, a, half)
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

    _final(rng, t, *alive, league, engine)


def _final(rng: random.Random, t: Tournament, a: Side, b: Side, league: match.League, engine: int) -> None:
    """One match at a neutral ground, ``a`` listed first."""
    final = play_match(rng, a, b, league, engine, neutral=True, extra_time_if_level=True)
    fx = Fixture("Final", a, b, final, "Final")
    t.fixtures.append(fx)
    t.ties.append(Tie("Final", a, b, [fx], a if final.winner == 0 else b))
    t.champion = t.ties[-1].winner


def play_tournament(deck: Deck, league: match.League, seed: int, you: Side,
                    engine: int = 1, fmt: str = "groups") -> Tournament:
    """Your eleven against the real sides: the solo game. ``fmt`` is "league" (35 sides,
    every draft since C50) or "groups" (31, every link made before)."""
    if fmt == "league":
        return _league_tournament(deck, league, seed, [you], engine)
    if fmt != "groups":
        raise ValueError(f"no format {fmt!r}")
    return _group_tournament(deck, league, seed, [you], engine)


def play_room(deck: Deck, league: match.League, seed: int, humans: list[Side],
              size: int, engine: int = 1) -> Tournament:
    """A room's tournament: every human eleven, and real sides filling the other places.

    ``size`` is one of PLAYABLE_SIZES. 36 plays the league phase and 32 the group format,
    each exactly as the solo game does; the smaller sizes are straight knockouts, so 2
    is a single final."""
    if size not in PLAYABLE_SIZES:
        raise ValueError(f"a room holds {', '.join(map(str, PLAYABLE_SIZES))} sides, not {size}")
    if not 1 <= len(humans) <= size:
        raise ValueError(f"{len(humans)} players cannot fill a {size}-side room")
    if size == LEAGUE_TEAMS:
        return _league_tournament(deck, league, seed, humans, engine)
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


def draw_league_opposition(rng: random.Random, deck: Deck, n: int) -> list[ClubSeason]:
    """n club-seasons for a league phase: as draw_opposition (uniform over club-seasons, at
    most one per club), and at most MAX_PER_ASSOCIATION clubs of one association."""
    if n == 0:
        return []
    pool = list(deck.club_seasons)
    rng.shuffle(pool)
    out, clubs, per = [], set(), {}
    for cs in pool:
        if cs.club in clubs or per.get(cs.association, 0) >= MAX_PER_ASSOCIATION:
            continue
        out.append(cs)
        clubs.add(cs.club)
        per[cs.association] = per.get(cs.association, 0) + 1
        if len(out) == n:
            return out
    raise ValueError(f"the deck allows only {len(out)} clubs; a league phase needs {n}")


def league_table(sides: list[Side], fixtures: list[Fixture], rng: random.Random) -> list[Row]:
    """The league phase's one table, by its tie-breakers (see the module's docstring)."""
    rows = {id(s): Row(s) for s in sides}
    met: dict[int, list[int]] = {id(s): [] for s in sides}
    for f in fixtures:
        h, a, r = rows[id(f.home)], rows[id(f.away)], f.result
        met[id(f.home)].append(id(f.away))
        met[id(f.away)].append(id(f.home))
        for row, gf, ga in ((h, r.home_goals, r.away_goals), (a, r.away_goals, r.home_goals)):
            row.played += 1
            row.gf += gf
            row.ga += ga
            row.won += gf > ga
            row.drawn += gf == ga
            row.lost += gf < ga
        a.away_gf += r.away_goals
        a.away_won += r.away_goals > r.home_goals

    def opponents(row: Row) -> tuple[int, int, int]:
        them = [rows[k] for k in met[id(row.side)]]
        return (sum(o.points for o in them), sum(o.gf - o.ga for o in them), sum(o.gf for o in them))

    lots = {id(s): rng.random() for s in sides}
    return sorted(rows.values(), key=lambda r: (
        -r.points, -(r.gf - r.ga), -r.gf, -r.away_gf, -r.won, -r.away_won,
        *(-x for x in opponents(r)), lots[id(r.side)]))


def _league_tournament(deck: Deck, league: match.League, seed: int,
                       humans: list[Side], engine: int) -> Tournament:
    # Two streams: one for the opposition and every match, one for the draws (pots, the
    # league phase, the fixture list, the knockout draws and the table's lots), so a
    # change in how the draw searches never moves a match's result.
    rng = random.Random(f"{seed}:league")
    draws = random.Random(f"{seed}:league draw")
    sides = list(humans) + [club_side(cs) for cs in
                            draw_league_opposition(rng, deck, LEAGUE_TEAMS - len(humans))]
    assoc = [s.association for s in sides]
    pot_of = league_phase.pots([s.strength for s in sides], assoc)
    _, days = league_phase.fixtures(draws, pot_of, assoc)
    t = Tournament(sides, {}, {}, format="league",
                   pots=[[s for s, p in zip(sides, pot_of) if p == q] for q in range(league_phase.POTS)])

    played = []
    for md, day in enumerate(days, start=1):
        for h, a in sorted(day):
            home, away = sides[h], sides[a]
            f = Fixture(LEAGUE, home, away, play_match(rng, home, away, league, engine), f"Matchday {md}")
            played.append(f)
    t.fixtures += played
    t.table = league_table(sides, played, draws)
    pos = [r.side for r in t.table]

    def tie(stage: str, a: Side, b: Side, half: int | None = None) -> Side:
        x = _two_legs(rng, stage, a, b, league, engine, half)
        t.ties.append(x)
        t.fixtures += x.legs
        return x.winner

    # Play-offs: each seeded side drawn against one of its section's two unseeded sides,
    # who host the first leg.
    winners = []
    for seeded, unseeded in PLAYOFF_SECTIONS:
        guests = [pos[i] for i in unseeded]
        draws.shuffle(guests)
        winners.append([tie(PLAYOFFS, g, pos[i]) for i, g in zip(seeded, guests)])
    # Round of 16: each section's seeds drawn into the two halves and against its two
    # play-off winners; listed in bracket order, half by half (A, D, B, C), so the
    # quarter-finals pair neighbours.
    bracket: list[dict[str, tuple[Side, Side]]] = [{}, {}]
    for name, (seeds, section) in R16_SECTIONS.items():
        top = [pos[i] for i in seeds]
        guests = list(winners[section])
        draws.shuffle(top)
        draws.shuffle(guests)
        for h in (0, 1):
            bracket[h][name] = (guests[h], top[h])
    last16 = {(h, name): tie(STAGES[1], *bracket[h][name], h) for h in (0, 1) for name in "ADBC"}
    # Quarter- and semi-finals: fixed pairings; the draw decides who hosts the first leg.
    last8 = {}
    for h in (0, 1):
        for k, (x, y) in enumerate((("A", "D"), ("B", "C"))):
            pair = [last16[(h, x)], last16[(h, y)]]
            draws.shuffle(pair)
            last8[(h, k)] = tie(STAGES[2], *pair, h)
    finalists = []
    for h in (0, 1):
        pair = [last8[(h, 0)], last8[(h, 1)]]
        draws.shuffle(pair)
        finalists.append(tie(STAGES[3], *pair, h))
    _final(rng, t, *finalists, league, engine)
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
