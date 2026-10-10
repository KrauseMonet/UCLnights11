"""The turn-by-turn shared draft (C29), after the cricket site's: friends take turns in a
snake order, each turn deals one real squad to the seat whose turn it is, and a player
taken by anyone is gone for everyone.

Like the solo draft it is a pure function, here of (seed, the seats' formations, the
room's moves): the server stores the moves and replays them on every request, so whose
turn it is, what was dealt and who holds whom are never stored, only derived.

- **Snake order**: seats 0,1,2 then 2,1,0 then 0,1,2, so going first in one round means
  going last in the next. Seat order is the order people sat down, host first.
- **One squad per turn**, dealt to the seat whose turn it is, redrawn until it holds
  someone that seat can take (the deal-time guarantee, per seat).
- **Exclusive by person**: once anyone takes a man, nobody else can take him, in any
  season. Picks go into the picker's own formation, a player into his own line.
- **No rerolls.** Every move is an index into the deal, so a move's turn is its place in
  the list; another kind of move would shift the snake for everyone.
- **Eleven rounds**: every seat makes exactly eleven picks, so nobody finishes early.
- **Stranded**: if no squad in the deck holds anyone a seat can still take, the draft
  cannot go on. With 243 squads and at most 32 seats this needs a deck far thinner
  than this one; it is reported rather than worked round.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.draft import REDRAW_CAP, IllegalMove, why_not
from game.formations import FORMATIONS, Formation

PICKS_EACH = 11
TIMER_CHOICES = (15, 30, 45)
DEFAULT_TIMER = 30


class Stranded(RuntimeError):
    """No squad in the deck holds anyone the seat on turn can take."""


def turn_seat(move_no: int, seats: int) -> int:
    """The seat (0-based) that makes move `move_no`, snaking round by round."""
    rnd, pos = divmod(move_no, seats)
    return pos if rnd % 2 == 0 else seats - 1 - pos


@dataclass
class SharedDraft:
    seed: int
    formations: list[Formation]
    picks: list[list[Card]]
    moves: list[int] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)          # person ids, across the room
    deal: ClubSeason | None = None
    redraws: int = 0
    log: list[tuple[int, Card]] = field(default_factory=list)   # (seat, card), in order

    @property
    def seats(self) -> int:
        return len(self.formations)

    @property
    def total(self) -> int:
        return PICKS_EACH * self.seats

    @property
    def complete(self) -> bool:
        return len(self.moves) >= self.total

    @property
    def active(self) -> int | None:
        return None if self.complete else turn_seat(len(self.moves), self.seats)

    @property
    def round(self) -> int:
        return min(len(self.moves) // self.seats + 1, PICKS_EACH)

    def reason(self, card: Card, seat: int) -> str | None:
        """None if `seat` can take `card` now, else why not."""
        if card.id in self.taken and not any(c.id == card.id for c in self.picks[seat]):
            return "already drafted"
        return why_not(card, self.formations[seat], self.picks[seat])

    def takeable(self, seat: int) -> list[int]:
        return [i for i, c in enumerate(self.deal.cards) if self.reason(c, seat) is None] if self.deal else []


def _deal(rng: random.Random, deck: Deck, d: SharedDraft) -> ClubSeason:
    seat = d.active
    for _ in range(REDRAW_CAP):
        cs = rng.choice(deck.club_seasons)
        if any(d.reason(c, seat) is None for c in cs.cards):
            return cs
        d.redraws += 1
    raise Stranded(f"no squad holds anyone seat {seat + 1} can still take")


def replay_shared(deck: Deck, seed: int, formations: list[str], moves: list[int]) -> SharedDraft:
    """Replay a room's draft from scratch. Raises IllegalMove on a move the deal did not
    offer, and Stranded if the deck runs dry for a seat."""
    if not formations:
        raise IllegalMove("a shared draft needs at least one seat")
    try:
        forms = [FORMATIONS[f] for f in formations]
    except KeyError as e:
        raise IllegalMove(f"unknown formation {e.args[0]!r}") from None
    if len(moves) > PICKS_EACH * len(forms):
        raise IllegalMove("too many moves")
    rng = random.Random(f"{seed}:shared")
    d = SharedDraft(seed, forms, [[] for _ in forms])
    d.deal = _deal(rng, deck, d)
    for index in moves:
        seat = d.active
        cards = d.deal.cards
        if not 0 <= index < len(cards):
            raise IllegalMove(f"no player {index} in this squad")
        card = cards[index]
        why = d.reason(card, seat)
        if why:
            raise IllegalMove(f"{card.name}: {why}")
        d.picks[seat].append(card)
        d.taken.add(card.id)
        d.moves.append(index)
        d.log.append((seat, card))
        d.deal = None if d.complete else _deal(rng, deck, d)
    return d


def autopick(d: SharedDraft) -> int:
    """The pick made for a seat whose clock ran out: a RANDOM player it can take, as on
    the cricket site (its A103 chose random over "worst available", which punished a
    dropped connection twice). Seeded by the move number, so the same room always
    auto-picks the same man and a replay never re-rolls it."""
    options = d.takeable(d.active)
    return random.Random(f"{d.seed}:afk:{len(d.moves)}").choice(options)


def best_pick(d: SharedDraft) -> int:
    """The host's "finish the draft": the best-rated player the seat on turn can take."""
    return max(d.takeable(d.active), key=lambda i: d.deal.cards[i].rating)


def encode_moves(moves: list[int]) -> str:
    return ".".join(map(str, moves))


def decode_moves(text: str | None) -> list[int]:
    if not text:
        return []
    out = []
    for tok in text.split("."):
        if not tok.isdigit() or len(tok) > 3:
            raise IllegalMove(f"bad move {tok!r}")
        out.append(int(tok))
    return out
