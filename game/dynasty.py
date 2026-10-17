"""Dynasty mode (C64): one squad over ten seasons, each man ageing into his next real season.

Season 1 is a league draft exactly as every solo draft is (fourteen picks, a team sheet, a
plan). After each season every man moves on to the NEXT SEASON THE DECK HAS FOR HIM, within
JUMP seasons, at that season's own rating and positions, and with his club if he moved
(Figo 2000-01 at Barcelona comes back as Figo 2001-02 at Real Madrid). A man the deck has
no season for in that time has left. Nothing is made up for him: the deck holds only
quarter-finalists, so when his club missed the quarter-finals no squad lists him, and the
game cannot know how good he was that year.

Measured on the deck before choosing JUMP (2026-10-17): 40% of player-seasons have the very
next season in the deck, 54% one within three; a best-pick drafter's fourteen keep 6.6 men
after a season with JUMP 1 and 9.4 with JUMP 3, and 2.3 of the originals are still there
after five seasons. The men who carry on lose 0.7 rating points a season on average
(sd 2.6) for a best-pick drafter, 0.1 for a random one: strong picks are usually at their
peak. That decline is the deck's own ratings, not an ageing curve.

A TRANSFER WINDOW comes between seasons: the formation may change, up to RELEASES men may
be released, and the places left open are filled from deals, as in the draft (the
deal-time guarantee, two rerolls a window, one person once). A released man's place is
filled from a random deal, so releasing is a gamble, not a free upgrade. The kept men must
fit the new season's formation: as many as the slots can take start (best-rated first, a
greedy choice that is optimal because sets of men who can fill distinct slots form a
matroid), the best of the rest sit on the bench, where a keeper or a man without a
position the formation has may not, and the bench holds three. Anyone else has NO PLACE and
leaves, without counting as a release. That is common, because a man's positions are his
new season's own: over 150 best-pick dynasties of ten seasons keeping one formation and
releasing nobody, 127 windows of 547 (23%) would have left someone without a place (Figo
measured at RM with no RM in a 4-3-3, Rodri at DM in a 3-4-3). Refusing such a window would
make the drafter release a man he never chose to lose; choosing another shape keeps him.
Then a sheet and a plan, as after any bench draft.

A dynasty is a pure function of its state string, like every solo link (C10): no window
reads a result, so the squads of every season follow from the moves alone, and a season's
tournament is played only when it is asked for. Season 1's tournament IS the plain league
draft's (the same seed), and every later season is seeded by the dynasty's seed and its
number, so a later window never moves an earlier season. The opposition is drawn fresh
each season, as a solo tournament draws it.

State: ``ySEED-FORMATION-moves[-sheet][-plan]`` (season 1, a league draft's own string with
"y" for "l"), then each window after a "~": ``FORMATION-xRELEASES[-moves][-sheet][-plan]``,
the releases as base-36 indices into the previous season's picks ("x" alone for none).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from game import match
from game.daily import hash_seed
from game.deck import Card, ClubSeason, Deck
from game.draft import (
    BENCH,
    REDRAW_CAP,
    REROLLS_ALLOWED,
    Change,
    IllegalMove,
    Move,
    Pick,
    Reroll,
    Session,
    bench_reason,
    check_plan,
    check_sheet,
    decode_plan,
    decode_sheet,
    decode_solo,
    encode,
    encode_plan,
    encode_sheet,
    why_not,
)
from game.draft import replay as draft_replay
from game.formations import FORMATIONS
from game.positions import fits
from game.tournament import Side, Tournament, auto_plan, play_tournament

JUMP = 3            # a man moves on to a season at most this many years later, or leaves
RELEASES = 3        # men a window may release
LENGTH = 10         # a dynasty's seasons
MAX_SEASONS = 30    # how many a state may hold, carrying on past LENGTH
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class Fate:
    """What became of one man of last season's squad: ``next`` is his card this season (also
    for a released man, who could have stayed), ``reason`` one of "carried" (the next
    season), "skipped" (two or three seasons on), "released", "no place" (his new season's
    positions have no place in the formation, or the bench is full), "left" (no season of
    his in the deck within JUMP) or "end" (none, and the deck ends inside that time)."""

    card: Card
    next: Card | None
    reason: str


@dataclass
class Season:
    number: int                 # 1-based
    session: Session            # its squad; session.seed seeds its tournament
    fates: list[Fate]           # how last season's squad came into it (none for season 1)
    # Kept substitutes who join the squad once its eleven is full (see ``_window``).
    waiting: list[Card] = field(default_factory=list)

    def why_not(self, card: Card) -> str | None:
        """None if this season's squad can take the card now, else why not."""
        return why_not_window(self.session, self.waiting, card)


@dataclass(frozen=True)
class Window:
    formation: str
    releases: tuple[int, ...]   # indices into the previous season's picks
    moves: tuple[Move, ...]
    sheet: tuple[int, ...] | None = None
    plan: tuple[Change, ...] | None = None


_CAREERS: dict[int, tuple[Deck, dict[str, dict[int, list[Card]]]]] = {}


def careers(deck: Deck) -> dict[str, dict[int, list[Card]]]:
    """Every person's cards by season, kept per deck. Keyed by the deck's identity and
    checked against the deck itself, so a deck made later at a freed address gets its own."""
    got = _CAREERS.get(id(deck))
    if got is None or got[0] is not deck:
        out: dict[str, dict[int, list[Card]]] = {}
        for cs in deck.club_seasons:
            for c in cs.cards:
                out.setdefault(c.id, {}).setdefault(cs.season, []).append(c)
        got = _CAREERS[id(deck)] = (deck, out)
    return got[1]


def last_season(deck: Deck) -> int:
    return max(cs.season for cs in deck.club_seasons)


def advance(deck: Deck, card: Card) -> Card | None:
    """His card in the next season the deck has for him within JUMP, or None. Three
    person-seasons sit in two squads (a move mid-season); his own club's is taken first,
    then the deck's order."""
    seasons = careers(deck).get(card.id, {})
    for k in range(1, JUMP + 1):
        cards = seasons.get(card.season + k)
        if cards:
            return next((c for c in cards if c.club == card.club), cards[0])
    return None


def fate(deck: Deck, card: Card) -> Fate:
    n = advance(deck, card)
    if n is not None:
        return Fate(card, n, "carried" if n.season == card.season + 1 else "skipped")
    return Fate(card, None, "end" if card.season + JUMP > last_season(deck) else "left")


def season_seed(seed: int, number: int) -> int:
    """The seed of season ``number`` (2 on): its window's squad and its tournament. Season 1
    is the draft itself and plays from the draft's own seed, so it is the plain league
    draft's tournament."""
    return hash_seed(f"{seed}:dynasty season {number}")


def split_kept(formation, kept: list[Card]) -> tuple[list[Card], list[Card], list[Card]]:
    """The kept men as (those who start, those on the bench, those with no place), each
    in kept order: as many start as the slots can take, best-rated first; then the best
    of the rest the bench can hold (never a keeper, only a position the formation has)."""
    slots = formation.slots
    eleven: list[Card] = []
    by_rating = sorted(kept, key=lambda c: -c.rating)
    for c in by_rating:
        if len(eleven) < len(slots) and fits(slots, [*eleven, c]):
            eleven.append(c)
    bench = [c for c in by_rating if c not in eleven and bench_reason(c, formation) is None][:BENCH]
    return ([c for c in kept if c in eleven], [c for c in kept if c in bench],
            [c for c in kept if c not in eleven and c not in bench])


def why_not_window(s: Session, waiting: list[Card], card: Card) -> str | None:
    if any(c.id == card.id for c in waiting):
        return "already on your bench"
    return why_not(card, s.formation, s.picks)


def _window(deck: Deck, prev: Session, w: Window, number: int, seed: int
            ) -> tuple[Session, list[Fate], list[Card]]:
    formation = FORMATIONS.get(w.formation)
    if formation is None:
        raise IllegalMove(f"unknown formation {w.formation!r}")
    if len(w.releases) > RELEASES:
        raise IllegalMove(f"a window releases at most {RELEASES}")
    if len(set(w.releases)) < len(w.releases) or any(not 0 <= i < len(prev.picks) for i in w.releases):
        raise IllegalMove("a release names a man the squad hasn't got, or one twice")
    fates = [fate(deck, c) for c in prev.picks]
    for i in w.releases:
        if fates[i].next is None:
            raise IllegalMove(f"{fates[i].card.name} has already left")
        fates[i] = Fate(fates[i].card, fates[i].next, "released")
    kept = [f.next for f in fates if f.next is not None and f.reason != "released"]
    eleven, waiting, unplaced = split_kept(formation, kept)
    fates = [Fate(f.card, f.next, "no place") if f.next in unplaced else f for f in fates]

    s = Session(seed=season_seed(seed, number), formation=formation, picks=list(eleven), bench_size=BENCH)
    rng = random.Random(f"{seed}:dynasty window {number}")

    def seat_waiting() -> None:
        # The kept substitutes join once the eleven is full, so every pick before is an
        # eleven's pick, as draft.why_not counts them.
        nonlocal waiting
        if len(s.picks) >= 11 and waiting:
            s.picks += waiting
            waiting = []

    def why(card: Card) -> str | None:
        return why_not_window(s, waiting, card)

    def deal() -> ClubSeason | None:
        if s.complete:
            return None
        for _ in range(REDRAW_CAP):
            cs = rng.choice(deck.club_seasons)
            if any(why(c) is None for c in cs.cards):
                s.dealt.append(cs.key)
                return cs
            s.redraws += 1
        raise RuntimeError("no squad in the deck can fill an open slot")

    seat_waiting()
    s.deal = deal()
    for m in w.moves:
        if s.complete:
            raise IllegalMove("the squad is already complete")
        if isinstance(m, Reroll):
            if s.rerolls_left <= 0:
                raise IllegalMove("no rerolls left")
            s.rerolls_left -= 1
        else:
            cards = s.deal.cards
            if not 0 <= m.index < len(cards):
                raise IllegalMove(f"no player {m.index} in this squad")
            reason = why(cards[m.index])
            if reason:
                raise IllegalMove(f"{cards[m.index].name}: {reason}")
            s.picks.append(cards[m.index])
            seat_waiting()
        s.deal = deal()
    if w.sheet is not None:
        check_sheet(s, w.sheet)
        s.sheet = w.sheet
    if w.plan is not None:
        check_plan(s, w.plan)
        s.plan = w.plan
    return s, fates, waiting


def replay(deck: Deck, state: str) -> list[Season]:
    """Every season of a dynasty so far. Only the last season's squad may be unfinished."""
    seed, formation, moves, sheet, plan, windows = decode(state)
    first = draft_replay(deck, seed, formation, moves, True, plan, sheet)
    seasons = [Season(1, first, [])]
    for number, w in enumerate(windows, start=2):
        prev = seasons[-1].session
        if not prev.complete:
            raise IllegalMove(f"season {number - 1}'s squad isn't complete")
        s, fates, waiting = _window(deck, prev, w, number, seed)
        seasons.append(Season(number, s, fates, waiting))
    return seasons


def side_of(s: Session) -> Side:
    """A finished season's squad as the side it plays as: its sheet, bench and plan."""
    subs = s.subs()
    return Side("YOU", "Your XI", "YOU", s.formation, s.xi, you=True,
                bench=s.bench, plan=auto_plan(s.bench) if subs is None else subs)


def season_tournament(deck: Deck, league: match.League, season: Season) -> Tournament:
    """A season's league phase, on engine 2. Raises IllegalMove until its squad is done."""
    if not season.session.complete:
        raise IllegalMove(f"season {season.number}'s squad isn't complete")
    return play_tournament(deck, league, season.session.seed, side_of(season.session), engine=2, fmt="league")


@dataclass(frozen=True)
class Record:
    """How a season went for your side: how far, and its matches' W-D-L and goals."""

    reached: str
    won: int
    drawn: int
    lost: int
    scored: int
    conceded: int


def record(t: Tournament) -> Record:
    you = t.you()
    w = d = l = gf = ga = 0
    for f in t.fixtures:
        if you not in (f.home, f.away):
            continue
        mine, theirs = ((f.result.home_goals, f.result.away_goals) if f.home is you
                        else (f.result.away_goals, f.result.home_goals))
        gf, ga = gf + mine, ga + theirs
        w, d, l = w + (mine > theirs), d + (mine == theirs), l + (mine < theirs)
    return Record(t.reached(you), w, d, l, gf, ga)


# -- state strings ----------------------------------------------------------------------

def _moves_token(moves) -> str:
    return ".".join("r" if isinstance(m, Reroll) else str(m.index) for m in moves)


def encode_window(w: Window) -> str:
    out = f"{w.formation}-x{''.join(_B36[i] for i in w.releases)}"
    out += f"-{_moves_token(w.moves)}" if w.moves else ""
    out += f"-{encode_sheet(w.sheet)}" if w.sheet is not None else ""
    return out + (f"-{encode_plan(w.plan)}" if w.plan is not None else "")


def encode_dynasty(seed: int, formation: str, moves: list[Move], sheet: tuple[int, ...] | None = None,
                   plan: tuple[Change, ...] | None = None, windows: list[Window] = ()) -> str:
    head = "y" + encode(seed, formation, moves, True, plan, sheet, league=True)[1:]
    return "~".join([head, *(encode_window(w) for w in windows)])


def _decode_moves(token: str) -> tuple[Move, ...]:
    out: list[Move] = []
    for tok in token.split("."):
        if tok == "r":
            out.append(Reroll())
        elif tok.isdigit() and len(tok) <= 3:
            out.append(Pick(int(tok)))
        else:
            raise IllegalMove(f"bad move {tok!r}")
    return tuple(out)


def decode_window(text: str) -> Window:
    parts = text.split("-")
    if len(parts) < 2 or not parts[1].startswith("x"):
        raise IllegalMove(f"not a transfer window: {text!r}")
    formation, releases = parts[0], parts[1][1:]
    if any(ch not in _B36 for ch in releases):
        raise IllegalMove(f"bad releases {releases!r}")
    rest = parts[2:]
    moves: tuple[Move, ...] = ()
    sheet = plan = None
    if rest and rest[-1].startswith("p"):
        plan = decode_plan(rest.pop())
    if rest and rest[-1].startswith("s"):
        sheet = decode_sheet(rest.pop())
    if len(rest) > 1:
        raise IllegalMove(f"not a transfer window: {text!r}")
    if rest:
        moves = _decode_moves(rest[0])
    if len(moves) > 11 + BENCH + REROLLS_ALLOWED:
        raise IllegalMove("too many moves")
    return Window(formation, tuple(_B36.index(ch) for ch in releases), moves, sheet, plan)


def is_dynasty(state: str) -> bool:
    return state.startswith("y")


def decode(state: str):
    """(seed, formation, moves, sheet, plan, windows) of a dynasty's state."""
    if not is_dynasty(state):
        raise IllegalMove(f"not a dynasty: {state!r}")
    head, *rest = state.split("~")
    if len(rest) + 1 > MAX_SEASONS:
        raise IllegalMove(f"a dynasty holds at most {MAX_SEASONS} seasons")
    seed, formation, moves, _, plan, sheet = decode_solo("l" + head[1:])
    return seed, formation, moves, sheet, plan, [decode_window(w) for w in rest]


def season_states(state: str) -> list[str]:
    """The state up to and including each season: what season n's tournament is a function of."""
    blocks = state.split("~")
    return ["~".join(blocks[:n]) for n in range(1, len(blocks) + 1)]


def last_block(state: str) -> Window:
    """The last season's block, season 1's included (its releases empty)."""
    seed, formation, moves, sheet, plan, windows = decode(state)
    return windows[-1] if windows else Window(formation, (), tuple(moves), sheet, plan)


def edit_last(state: str, **fields) -> str:
    """The state with its last season's block changed (``moves``, ``sheet`` or ``plan``)."""
    seed, formation, moves, sheet, plan, windows = decode(state)
    if windows:
        windows[-1] = replace(windows[-1], **fields)
        return encode_dynasty(seed, formation, moves, sheet, plan, windows)
    first = replace(Window(formation, (), tuple(moves), sheet, plan), **fields)
    return encode_dynasty(seed, first.formation, list(first.moves), first.sheet, first.plan)


def open_window(state: str, formation: str, releases: tuple[int, ...], reshape: bool = False) -> str:
    """A new season's window after the last season, or, with ``reshape``, the last window
    chosen again (another formation or other releases), which is allowed only before its
    first pick or reroll: after one, the deals already shown would change."""
    seed, first_formation, moves, sheet, plan, windows = decode(state)
    w = Window(formation, tuple(sorted(releases)), ())
    if reshape:
        if not windows or windows[-1].moves:
            raise IllegalMove("this season's window can't be changed now")
        windows[-1] = w
    else:
        windows.append(w)
    return encode_dynasty(seed, first_formation, moves, sheet, plan, windows)
