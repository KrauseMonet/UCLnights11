"""The sealed-bid auction draft (C68): friends buy their squads with one budget each, round
by round, instead of taking turns.

- **A market each round.** The room is dealt a few real squads, enough that every seat with
  places left has someone in it to bid on (the deal-time guarantee, per seat, as the turn
  draft's). How many squads a market holds grows with the seats still buying
  (``market_size``), measured so a seat usually wins someone every round.
- **Sealed bids.** Every seat bids in secret on up to MAX_BIDS men of the market, each bid
  at least MIN_BID and never so much that it couldn't then fill its other places at
  MIN_BID each (the reserve), so nobody ends short of a squad. A seat may pass, at most
  PASSES times; a seat that sends nothing gets a MIN_BID bid on a random man it can take,
  seeded by the round (the turn draft's A103), so nobody waits on anyone.
- **Settling a round.** Bids are taken from the highest down: the man goes to that bidder
  unless he is sold already or the bidder has won this round, since **a seat wins at most
  one man a round**, so its own amounts say whom it wants most. A tie goes to the seat with
  more places left, then to a seeded draw. **The winner pays the second price**: one
  MIN_BID more than the best other bid on that man, never more than he bid himself, and
  MIN_BID if nobody else wanted him. Bidding what a man is worth to you is then safe.
- **The football rules are the draft's**: a man stands only where he holds the position,
  a bench man is no keeper and holds a position the formation has (game.draft.why_not),
  and one person once in the room, in any season.

Like the turn draft it is a pure function, of (seed, the seats' formations, whether it has
a bench, and every closed round's bids): who holds whom, who has what left and what each
market holds are replayed, never stored.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.draft import BENCH, REDRAW_CAP, IllegalMove, why_not
from game.formations import FORMATIONS, Formation
from game.shared_draft import PICKS_EACH, Stranded

BUDGET = 200          # €m a seat
MIN_BID = 1
MAX_BIDS = 5          # bids a seat may make in one round
PASSES = 3            # rounds a seat may sit out by choice


def market_size(open_seats: int) -> int:
    """Squads in a round's market for this many seats still buying (C68, measured)."""
    return 1 + (open_seats + 2) // 3


@dataclass(frozen=True)
class Sale:
    round: int
    seat: int
    card: Card
    price: int
    bid: int                        # what the winner bid
    others: tuple[tuple[int, int], ...]   # (seat, amount) of every other bid on him


@dataclass
class Auction:
    seed: int
    formations: list[Formation]
    picks: list[list[Card]]
    spent: list[int]
    passes: list[int]
    taken: set[str] = field(default_factory=set)            # person ids, across the room
    sales: list[Sale] = field(default_factory=list)
    round: int = 1                                           # the round now open
    market: list[ClubSeason] = field(default_factory=list)  # its squads
    redraws: int = 0
    picks_each: int = PICKS_EACH
    budget: int = BUDGET

    @property
    def seats(self) -> int:
        return len(self.formations)

    @property
    def lots(self) -> list[Card]:
        """The open round's men, every squad of its market in turn; a bid names one by index."""
        return [c for cs in self.market for c in cs.cards]

    def places_left(self, seat: int) -> int:
        return self.picks_each - len(self.picks[seat])

    def money_left(self, seat: int) -> int:
        return self.budget - self.spent[seat]

    def max_bid(self, seat: int) -> int:
        """The most this seat may bid on one man: its money less MIN_BID for every other
        place it still has to fill."""
        return self.money_left(seat) - MIN_BID * (self.places_left(seat) - 1)

    def buying(self) -> list[int]:
        return [s for s in range(self.seats) if self.places_left(s) > 0]

    @property
    def complete(self) -> bool:
        return not self.buying()

    def reason(self, card: Card, seat: int) -> str | None:
        """None if ``seat`` can buy ``card`` now, else why not."""
        if self.places_left(seat) <= 0:
            return "your squad is full"
        if card.id in self.taken:
            return "already bought" if not any(c.id == card.id for c in self.picks[seat]) else "already yours"
        return why_not(card, self.formations[seat], self.picks[seat])

    def takeable(self, seat: int) -> list[int]:
        return [i for i, c in enumerate(self.lots) if self.reason(c, seat) is None]


def _market(rng: random.Random, deck: Deck, a: Auction) -> list[ClubSeason]:
    """``market_size`` distinct squads, drawn on until every seat still buying has someone
    in them it can take. Past the size wanted, a squad is added only if it holds someone for
    a seat nothing yet covers."""
    want = market_size(len(a.buying()))
    out: list[ClubSeason] = []
    uncovered = set(a.buying())
    for _ in range(REDRAW_CAP):
        if len(out) >= want and not uncovered:
            return out
        cs = rng.choice(deck.club_seasons)
        helps = {s for s in uncovered if any(a.reason(c, s) is None for c in cs.cards)}
        if cs in out or (len(out) >= want and not helps):
            a.redraws += 1
            continue
        out.append(cs)
        uncovered -= helps
    raise Stranded("no market holds someone every seat still buying can take")


Bids = dict[int, list[tuple[int, int]]]     # seat -> [(lot, amount)]; [] is a pass


def check_bids(a: Auction, seat: int, bids: list[tuple[int, int]]) -> None:
    """Raises IllegalMove unless ``bids`` are a seat's legal bids in the open round."""
    if a.complete:
        raise IllegalMove("the auction is over")
    if a.places_left(seat) <= 0:
        raise IllegalMove("your squad is full")
    if not bids:
        if a.passes[seat] >= PASSES:
            raise IllegalMove(f"you have passed {PASSES} times already")
        return
    if len(bids) > MAX_BIDS:
        raise IllegalMove(f"at most {MAX_BIDS} bids a round")
    lots = a.lots
    if len({lot for lot, _ in bids}) < len(bids):
        raise IllegalMove("one bid a man")
    for lot, amount in bids:
        if not 0 <= lot < len(lots):
            raise IllegalMove(f"no man {lot} in this market")
        why = a.reason(lots[lot], seat)
        if why:
            raise IllegalMove(f"{lots[lot].name}: {why}")
        if not MIN_BID <= amount <= a.max_bid(seat):
            raise IllegalMove(f"a bid is from €{MIN_BID}m to €{a.max_bid(seat)}m: you must keep "
                              f"€{MIN_BID}m for each other place")


def auto_bid(a: Auction, seat: int) -> list[tuple[int, int]]:
    """The bid made for a seat that sent none: MIN_BID on a random man it can take, seeded
    by the round and seat, so a replay never re-rolls it."""
    return [(random.Random(f"{a.seed}:auction auto:{a.round}:{seat}").choice(a.takeable(seat)), MIN_BID)]


def settle(a: Auction, sent: Bids) -> list[Sale]:
    """Close the open round: every seat's bids (an auto bid for a seat that sent none),
    settled from the highest down, at most one man for each seat, at the second price."""
    lots = a.lots
    bids: list[tuple[int, int, int]] = []          # (seat, lot, amount)
    for seat in a.buying():
        mine = sent.get(seat)
        if mine is None:
            mine = auto_bid(a, seat)
        elif not mine:
            a.passes[seat] += 1
        bids += [(seat, lot, amount) for lot, amount in mine]
    lot_draw = random.Random(f"{a.seed}:auction ties:{a.round}")
    draw = {seat: lot_draw.random() for seat in range(a.seats)}
    order = sorted(bids, key=lambda b: (-b[2], -a.places_left(b[0]), draw[b[0]]))
    won: set[int] = set()
    sold: set[int] = set()
    sales = []
    for seat, lot, amount in order:
        if lot in sold or seat in won:
            continue
        others = tuple((s, x) for s, l, x in bids if l == lot and s != seat)
        price = min(amount, max((x for _, x in others), default=0) + MIN_BID) if others else MIN_BID
        sales.append(Sale(a.round, seat, lots[lot], price, amount, others))
        sold.add(lot)
        won.add(seat)
    for s in sales:
        a.picks[s.seat].append(s.card)
        a.spent[s.seat] += s.price
        a.taken.add(s.card.id)
    a.sales += sales
    return sales


def replay(deck: Deck, seed: int, formations: list[str], rounds: list[Bids], bench: bool = False) -> Auction:
    """The auction after its closed ``rounds``, with the next round's market dealt. Raises
    IllegalMove on a bid the round didn't allow, Stranded if the deck runs dry."""
    if not formations:
        raise IllegalMove("an auction needs at least one seat")
    try:
        forms = [FORMATIONS[f] for f in formations]
    except KeyError as e:
        raise IllegalMove(f"unknown formation {e.args[0]!r}") from None
    n = len(forms)
    a = Auction(seed, forms, [[] for _ in forms], [0] * n, [0] * n,
                picks_each=PICKS_EACH + (BENCH if bench else 0))
    for sent in rounds:
        if a.complete:
            raise IllegalMove("the auction is already over")
        a.market = _market(random.Random(f"{seed}:auction market:{a.round}"), deck, a)
        for seat, bids in sent.items():
            if not 0 <= seat < n:
                raise IllegalMove(f"no seat {seat}")
            check_bids(a, seat, bids)
        settle(a, sent)
        a.round += 1
    a.market = [] if a.complete else _market(random.Random(f"{seed}:auction market:{a.round}"), deck, a)
    return a


@dataclass(frozen=True)
class Recap:
    """What an auction came to (C72): each seat's buys, dearest first, and the room's
    biggest buys and bargains. A BARGAIN is declared, not measured: a man bought for
    BARGAIN or less, the best-rated first."""

    buys: list[list[Sale]]
    biggest: list[Sale]
    bargains: list[Sale]


BARGAIN = 5            # €m
RECAP_SHOWN = 3


def recap(a: Auction) -> Recap:
    """For a sealed or an open auction alike: both record every sale."""
    buys: list[list[Sale]] = [[] for _ in range(a.seats)]
    for s in a.sales:
        buys[s.seat].append(s)
    for b in buys:
        b.sort(key=lambda s: (-s.price, -s.card.rating, s.card.name))
    biggest = sorted(a.sales, key=lambda s: (-s.price, -s.card.rating, s.card.name))[:RECAP_SHOWN]
    bargains = sorted((s for s in a.sales if s.price <= BARGAIN),
                      key=lambda s: (-s.card.rating, s.price, s.card.name))[:RECAP_SHOWN]
    return Recap(buys, biggest, bargains)


# -- the rounds as text, for storage: rounds split by "/", seats by ";", a seat's bids by ","
# ("0:3.40,7.12;1:-;2:3.35" is seat 0 bidding 40 on man 3 and 12 on man 7, seat 1 passing and
# seat 2 bidding 35 on man 3; a seat that sent nothing isn't listed).

def encode_rounds(rounds: list[Bids]) -> str:
    def seat(s: int, bids: list[tuple[int, int]]) -> str:
        return f"{s}:" + (",".join(f"{lot}.{x}" for lot, x in bids) if bids else "-")
    return "/".join(";".join(seat(s, b) for s, b in sorted(r.items())) for r in rounds)


def decode_rounds(text: str | None) -> list[Bids]:
    if not text:
        return []
    out = []
    for rnd in text.split("/"):
        r: Bids = {}
        for part in filter(None, rnd.split(";")):
            s, _, bids = part.partition(":")
            if not s.isdigit() or int(s) in r or not bids:
                raise IllegalMove(f"bad round {rnd!r}")
            r[int(s)] = [] if bids == "-" else [_bid(b) for b in bids.split(",")]
        out.append(r)
    return out


def _bid(text: str) -> tuple[int, int]:
    lot, _, x = text.partition(".")
    if not (lot.isdigit() and x.isdigit() and len(lot) <= 3 and len(x) <= 4):
        raise IllegalMove(f"bad bid {text!r}")
    return int(lot), int(x)
