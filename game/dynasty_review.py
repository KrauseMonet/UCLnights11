"""The end of a dynasty (C76): every finished season read back side by side, off the
tournaments the engine already played, for the page that closes a dynasty.

Nothing here is new information. Results are the engine's (calibrated, C8); squad ratings
are averages of declared ratings (C2, ``game.squad_ratings``); marks are declared (C27).
Every per-man number comes from ``journey``, as the cup page, the analysis and the legacy
read it, so a total can't come out one way here and another way there (A175).

A draw is a draw here even when a shoot-out followed (``journey.side_result``), so a run
"unbeaten" survives a shoot-out lost and a "winning run" isn't extended by one won, as
``dynasty.record`` counts a season's W-D-L.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from game.deck import Card, Deck
from game.dynasty import Career, Fate, Season, careers_of, squad
from game.journey import Journey, PlayerTotals, journey, player_totals, side_result
from game.squad_ratings import SquadRatings, ranked, squad_ratings
from game.tournament import FINISHES, Fixture, Side, Tournament

BOARD_SIZE = 5
CLUBS_SHOWN = 8
KEPT = ("carried", "skipped")
GONE = ("left", "end", "no place")


@dataclass
class SeasonLine:
    number: int
    formation: str                  # its code
    reached: str
    position: int | None            # the league phase's place, 1 to 36
    points: int
    won: int
    drawn: int
    lost: int
    scored: int
    conceded: int
    clean_sheets: int
    ratings: SquadRatings           # the eleven by line, and the bench
    better_than: int | None         # the share of the deck's club-seasons the eleven rates above
    top_scorer: PlayerTotals | None
    star: PlayerTotals | None       # the best average mark of the season
    out_by: Side | None             # the side that put you out (None for champions and a league-phase exit)
    champion: Side
    kept: int | None                # men of last season's squad still in it (None for season 1)
    released: int
    left: int
    signed: int                     # men new to the squad this season (all fourteen in season 1)
    originals: int                  # men of season 1's squad in it


@dataclass(frozen=True)
class Moment:
    """One of your matches, as a record names it."""

    season: int
    fixture: Fixture
    side_index: int                 # 0 if you were at home

    @property
    def scored(self) -> int:
        r = self.fixture.result
        return r.home_goals if self.side_index == 0 else r.away_goals

    @property
    def conceded(self) -> int:
        r = self.fixture.result
        return r.away_goals if self.side_index == 0 else r.home_goals

    @property
    def opponent(self) -> Side:
        return self.fixture.away if self.side_index == 0 else self.fixture.home


@dataclass(frozen=True)
class Run:
    length: int
    first: Moment
    last: Moment


@dataclass
class Opponent:
    """Every match against one club, whichever of its seasons was drawn."""

    club: str
    side: Side                      # the latest of its sides you met, for its crest and colours
    won: int = 0
    drawn: int = 0
    lost: int = 0
    scored: int = 0
    conceded: int = 0

    @property
    def played(self) -> int:
        return self.won + self.drawn + self.lost


@dataclass
class Review:
    seasons: list[SeasonLine]
    matches: list[Moment]
    biggest_win: Moment | None
    heaviest_defeat: Moment | None
    most_goals: Moment | None
    unbeaten: Run | None
    winning: Run | None
    nemesis: Opponent | None        # most defeats against
    favourite: Opponent | None      # most wins against
    met: int                        # distinct clubs played
    careers: dict[str, Career]
    min_apps: int                   # the regulars' bar for the mark board
    boards: dict[str, list[tuple[Career, float]]]
    clubs: list[tuple[Card, int]]   # where the men came from: a card of the club, and how many
    clubs_total: int
    players: int                    # men who were ever in your squad
    journeys: list[Journey] = field(repr=False, default_factory=list)


def _position(t: Tournament, you: Side) -> int | None:
    return next((i + 1 for i, row in enumerate(t.table) if row.side is you), None)


def _out_by(t: Tournament, you: Side) -> Side | None:
    """The side that won the tie you went out in, if a tie put you out."""
    lost = [x for x in t.ties if you in (x.a, x.b) and x.winner is not you]
    return lost[-1].winner if lost else None


def _turnover(fates: list[Fate], first: bool, held: int) -> tuple[int | None, int, int, int]:
    if first:
        return None, 0, 0, held
    kept = sum(f.reason in KEPT for f in fates)
    return (kept, sum(f.reason == "released" for f in fates), sum(f.reason in GONE for f in fates), held - kept)


def season_line(deck: Deck, x: Season, t: Tournament, j: Journey, originals: set[str]) -> SeasonLine:
    you = t.you()
    w, d, l = (sum(side_result(m.fixture, m.side_index) == o for m in j.matches) for o in "wdl")
    row = next((r for r in t.table if r.side is you), None)
    s = x.session
    r = squad_ratings(you.xi, you.bench)
    men = squad(x)
    kept, released, left, signed = _turnover(x.fates, x.number == 1, len(men))
    scored = [p for p in j.players if p.goals]
    return SeasonLine(
        number=x.number, formation=s.formation.code, reached=j.reached, position=_position(t, you),
        points=row.points if row else 0, won=w, drawn=d, lost=l, scored=j.goals_for,
        conceded=j.goals_against, clean_sheets=j.clean_sheets, ratings=r,
        better_than=ranked(deck, r)["overall"],
        top_scorer=j.top(lambda p: p.goals) if scored else None, star=j.star,
        out_by=_out_by(t, you), champion=t.champion,
        kept=kept, released=released, left=left, signed=signed,
        originals=sum(c.id in originals for c in men),
    )


def _longest(moments: list[Moment], ok) -> Run | None:
    best = None
    start = None
    for i, m in enumerate(moments):
        if ok(m):
            start = i if start is None else start
            n = i - start + 1
            if best is None or n > best.length:
                best = Run(n, moments[start], m)
        else:
            start = None
    return best


# The records' matches. Each takes the first of equals (max() keeps the earliest).

def biggest_win(moments: list[Moment]) -> Moment | None:
    """The widest margin of victory, then the most goals scored."""
    return max((m for m in moments if m.scored > m.conceded),
               key=lambda m: (m.scored - m.conceded, m.scored), default=None)


def heaviest_defeat(moments: list[Moment]) -> Moment | None:
    """The widest margin of defeat, then the most goals conceded."""
    return max((m for m in moments if m.scored < m.conceded),
               key=lambda m: (m.conceded - m.scored, m.conceded), default=None)


def most_goals(moments: list[Moment]) -> Moment | None:
    """The most goals in a match, then the better result for you."""
    return max(moments, key=lambda m: (m.scored + m.conceded, m.scored - m.conceded), default=None)


def _board(pool, value, size=BOARD_SIZE):
    ranked_ = sorted((c for c in pool if value(c)), key=lambda c: (-value(c), -(c.mark or 0), c.card.name))
    return [(c, value(c)) for c in ranked_[:size]]


def review(deck: Deck, seasons: list[Season], tournaments: list[Tournament]) -> Review:
    """The dynasty over ``seasons``, each with its tournament (every season finished)."""
    if not tournaments or len(seasons) != len(tournaments):
        raise ValueError("a review needs every season's tournament")
    journeys = [journey(t, t.you(), player_totals(t)) for t in tournaments]
    originals = {c.id for c in squad(seasons[0])}
    lines = [season_line(deck, x, t, j, originals) for x, t, j in zip(seasons, tournaments, journeys)]

    moments = [Moment(x.number, m.fixture, m.side_index) for x, j in zip(seasons, journeys) for m in j.matches]
    unbeaten = _longest(moments, lambda m: m.scored >= m.conceded)
    winning = _longest(moments, lambda m: m.scored > m.conceded)

    clubs: dict[str, Opponent] = {}
    for m in moments:
        o = m.opponent
        rec = clubs.setdefault(o.club_name or o.name, Opponent(o.club_name or o.name, o))
        rec.side = o
        rec.scored += m.scored
        rec.conceded += m.conceded
        if m.scored > m.conceded:
            rec.won += 1
        elif m.scored < m.conceded:
            rec.lost += 1
        else:
            rec.drawn += 1
    opp = list(clubs.values())
    nemesis = max((o for o in opp if o.lost), key=lambda o: (o.lost, -o.won, o.played), default=None)
    favourite = max((o for o in opp if o.won), key=lambda o: (o.won, -o.lost, o.played), default=None)

    every = careers_of(tournaments, journeys)
    pool = [c for c in every.values() if c.mark is not None]
    most_apps = max((c.apps for c in pool), default=0)
    min_apps = max(1, -(-most_apps // 2))
    regulars = [c for c in pool if c.apps >= min_apps]
    boards = {
        "apps": _board(pool, lambda c: c.apps),
        "goals": _board(pool, lambda c: c.goals),
        "assists": _board(pool, lambda c: c.assists),
        "mark": [(c, c.mark) for c in sorted(regulars, key=lambda c: (-c.mark, -c.apps, c.card.name))[:BOARD_SIZE]],
        "clean_sheets": _board([c for c in pool if c.card.pos == "GK"], lambda c: c.clean_sheets),
        "seasons": _board(pool, lambda c: c.seasons),
    }

    # Where the men came from: each man counted once, at the club of the first card he
    # held with you (a signing, or one of the first fourteen).
    first: dict[str, Card] = {}
    for x in seasons:
        for c in squad(x):
            first.setdefault(c.id, c)
    by_club: dict[str, list[Card]] = {}
    for c in first.values():
        by_club.setdefault(c.club_name, []).append(c)
    clubs_out = sorted(((cs[-1], len(cs)) for cs in by_club.values()), key=lambda x: (-x[1], x[0].club_name))

    return Review(
        seasons=lines, matches=moments, biggest_win=biggest_win(moments),
        heaviest_defeat=heaviest_defeat(moments), most_goals=most_goals(moments),
        unbeaten=unbeaten, winning=winning, nemesis=nemesis, favourite=favourite, met=len(opp),
        careers=every, min_apps=min_apps, boards=boards, clubs=clubs_out[:CLUBS_SHOWN],
        clubs_total=len(by_club), players=len(first), journeys=journeys,
    )


def best_season(lines: list[SeasonLine]) -> SeasonLine:
    """Furthest, then most points, then goal difference; the earlier on a tie."""
    return min(lines, key=lambda s: (FINISHES.index(s.reached), -s.points, -(s.scored - s.conceded), s.number))


def worst_season(lines: list[SeasonLine]) -> SeasonLine:
    """Shortest, then fewest points, then goal difference; the later on a tie."""
    return max(lines, key=lambda s: (FINISHES.index(s.reached), -s.points, -(s.scored - s.conceded), s.number))
