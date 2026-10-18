"""The open auction draft (C69): one man at a time, bid up out loud until the clock runs
out, the other way a room can auction its squads (the sealed-bid rounds are
game.auction, C68). The host chooses which.

- **Nominations take turns.** The seats still buying nominate in seat order. The nominator
  is dealt a real squad (holding someone he can take: the deal-time guarantee) and puts
  one man from it up for sale, **opening the bidding at MIN_BID himself**, so he must be
  willing to buy him: only a man he could take can be nominated. He has the room's turn
  timer to choose; when it runs out, a random man of the deal is put up for him, seeded
  by the lot (the turn draft's A103).
- **Bidding.** Any other seat that can take the man (the draft's football rules and one
  person once, as in game.auction) may raise the price by MIN_RAISE or more, up to its
  money less MIN_BID for every other place it has left, so nobody ends short of a squad.
  The leader can't outbid himself.
- **The clock.** A lot closes LOT_SECONDS after it is put up, or BID_SECONDS after the last
  bid, whichever is later; a bid that reaches the server up to GRACE_S after that still
  counts (a phone's lag, the turn clock's grace, C29), and the lot is sold only once that
  has passed. A lot nobody else could bid on is sold at once. The winner pays his bid.
- **The host's finish** sells the open lot to its leader and fills every place left with
  a random man each seat could take, at MIN_BID.

A pure function of (seed, formations, bench, nomination timer, and the events with the
server's times, in seconds from the auction's start), like the sealed-bid rounds: the
server appends an event only when the clock says it is due (``due``) and refuses one the
clock doesn't allow, and the replay checks the same rules, so a stored auction always
replays as it was played.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.auction import BUDGET, MIN_BID, Auction, Sale
from game.deck import Card, ClubSeason, Deck
from game.draft import BENCH, REDRAW_CAP, IllegalMove
from game.formations import FORMATIONS
from game.shared_draft import PICKS_EACH, Stranded

# The rooms that may choose an open auction; any room may choose sealed bids. Measured with
# bots (C69: 8 s to nominate, a raise every 1.5 s, jump bids): 8 minutes for 2 seats, 18 for
# 4, 38 for 8 (43 at most), 81 for 16, so 16 and 36 auction sealed.
ROOM_SIZES = (2, 4, 8)
MIN_RAISE = 1
LOT_SECONDS = 12.0      # a lot's first clock, from the nomination
BID_SECONDS = 8.0       # the clock after each bid
GRACE_S = 1.0           # a late bid or nomination still counts this long (C29's grace)


@dataclass
class Lot:
    number: int
    nominator: int
    card: Card
    leader: int
    price: int
    ends: float                                              # seconds from the start
    bids: list[tuple[int, int, float]] = field(default_factory=list)   # (seat, amount, t)


@dataclass(frozen=True)
class Event:
    t: float               # seconds from the auction's start, by the server's clock
    kind: str              # "n" nominate, "a" auto-nominate, "b" bid, "c" close, "f" finish
    seat: int = -1
    value: int = -1        # the deal index nominated, or the amount bid


@dataclass
class OpenAuction(Auction):
    deal: ClubSeason | None = None        # dealt to the nominator while he chooses
    nominator: int | None = None
    nominate_by: float = 0.0              # when his time runs out
    lot: Lot | None = None
    lots_done: int = 0
    timer: float = 30.0
    events: list[Event] = field(default_factory=list)

    def can_bid(self, seat: int, amount: int | None = None) -> str | None:
        """None if ``seat`` may raise the open lot (to ``amount``, or by MIN_RAISE), else why not."""
        lot = self.lot
        if lot is None:
            return "nothing is up for sale"
        if seat == lot.leader:
            return "you lead the bidding"
        why = self.reason(lot.card, seat)
        if why:
            return why
        amount = lot.price + MIN_RAISE if amount is None else amount
        if amount < lot.price + MIN_RAISE:
            return f"the next bid is at least €{lot.price + MIN_RAISE}m"
        if amount > self.max_bid(seat):
            return f"you can bid up to €{self.max_bid(seat)}m: €{MIN_BID}m stays for each other place"
        return None

    def contested(self) -> bool:
        """Whether anyone but the leader could still raise the open lot."""
        return any(self.can_bid(s) is None for s in range(self.seats))

    def due(self, now: float) -> str | None:
        """The event the clock says is due now: "c" to close the lot, "a" to nominate for a
        seat out of time, or None."""
        if self.complete:
            return None
        if self.lot is not None:
            return "c" if now >= self.lot.ends + GRACE_S or not self.contested() else None
        return "a" if now >= self.nominate_by + GRACE_S else None


def _next_nominator(a: OpenAuction, after: int | None) -> int | None:
    start = -1 if after is None else after
    for k in range(1, a.seats + 1):
        s = (start + k) % a.seats
        if a.places_left(s) > 0:
            return s
    return None


def _deal(a: OpenAuction, deck: Deck) -> ClubSeason:
    rng = random.Random(f"{a.seed}:open deal:{a.lots_done}")
    for _ in range(REDRAW_CAP):
        cs = rng.choice(deck.club_seasons)
        if any(a.reason(c, a.nominator) is None for c in cs.cards):
            return cs
        a.redraws += 1
    raise Stranded(f"no squad holds anyone seat {a.nominator + 1} can still take")


def _ready(a: OpenAuction, deck: Deck, t: float) -> None:
    """The next nominator is dealt a squad and his clock starts at ``t``."""
    a.nominator = _next_nominator(a, a.nominator)
    if a.nominator is None:
        a.deal = None
        return
    a.deal = _deal(a, deck)
    a.nominate_by = t + a.timer


def _put_up(a: OpenAuction, t: float, index: int) -> None:
    cards = a.deal.cards
    if not 0 <= index < len(cards):
        raise IllegalMove(f"no player {index} in this squad")
    why = a.reason(cards[index], a.nominator)
    if why:
        raise IllegalMove(f"{cards[index].name}: {why}")
    a.lot = Lot(a.lots_done + 1, a.nominator, cards[index], a.nominator, MIN_BID, t + LOT_SECONDS)
    a.deal = None


def _sell(a: OpenAuction, deck: Deck, t: float) -> None:
    lot = a.lot
    a.sales.append(Sale(lot.number, lot.leader, lot.card, lot.price, lot.price,
                        tuple((s, x) for s, x, _ in lot.bids if s != lot.leader)))
    a.picks[lot.leader].append(lot.card)
    a.spent[lot.leader] += lot.price
    a.taken.add(lot.card.id)
    a.lot = None
    a.lots_done += 1
    _ready(a, deck, t)


def auto_index(a: OpenAuction) -> int:
    """The man put up for a nominator out of time: random among those he can take, seeded by the lot."""
    options = [i for i, c in enumerate(a.deal.cards) if a.reason(c, a.nominator) is None]
    return random.Random(f"{a.seed}:open auto:{a.lots_done}").choice(options)


def apply(a: OpenAuction, deck: Deck, e: Event) -> None:
    """Apply one event, or raise IllegalMove if the auction and its clock don't allow it."""
    if a.complete:
        raise IllegalMove("the auction is over")
    if a.events and e.t < a.events[-1].t:
        raise IllegalMove("events run forwards in time")
    if e.kind == "n":
        if a.lot is not None:
            raise IllegalMove("a man is already up for sale")
        if e.seat != a.nominator:
            raise IllegalMove("it isn't your turn to nominate")
        if e.t > a.nominate_by + GRACE_S:
            raise IllegalMove("your time to nominate has run out")
        _put_up(a, e.t, e.value)
    elif e.kind == "a":
        if a.lot is not None or e.t < a.nominate_by + GRACE_S:
            raise IllegalMove("the nominator still has time")
        _put_up(a, e.t, auto_index(a))
    elif e.kind == "b":
        why = a.can_bid(e.seat, e.value)
        if why:
            raise IllegalMove(why)
        if e.t > a.lot.ends + GRACE_S:
            raise IllegalMove("that lot has closed")
        a.lot.leader, a.lot.price = e.seat, e.value
        a.lot.bids.append((e.seat, e.value, e.t))
        a.lot.ends = max(a.lot.ends, e.t + BID_SECONDS)
    elif e.kind == "c":
        if a.lot is None:
            raise IllegalMove("nothing is up for sale")
        if e.t < a.lot.ends + GRACE_S and a.contested():
            raise IllegalMove("the lot is still open")
        _sell(a, deck, e.t)
    elif e.kind == "f":
        if a.lot is not None:
            _sell(a, deck, e.t)
        while not a.complete:
            _put_up(a, e.t, auto_index(a))
            _sell(a, deck, e.t)
    else:
        raise IllegalMove(f"no event {e.kind!r}")
    a.events.append(e)


def replay(deck: Deck, seed: int, formations: list[str], events: list[Event], bench: bool = False,
           timer: float = 30.0) -> OpenAuction:
    """The auction after ``events``: the first nominator is dealt a squad at time 0."""
    if not formations:
        raise IllegalMove("an auction needs at least one seat")
    try:
        forms = [FORMATIONS[f] for f in formations]
    except KeyError as e:
        raise IllegalMove(f"unknown formation {e.args[0]!r}") from None
    n = len(forms)
    a = OpenAuction(seed, forms, [[] for _ in forms], [0] * n, [0] * n,
                    picks_each=PICKS_EACH + (BENCH if bench else 0), budget=BUDGET, timer=timer)
    _ready(a, deck, 0.0)
    for e in events:
        apply(a, deck, e)
    return a


# -- events as text, for storage: "t:k:seat:value" joined by ";", t in hundredths of a second
# ("1250:n:0:3;1830:b:1:12;2730:c" is seat 0 putting up man 3 of his deal at 12.5 s, seat 1
# bidding €12m at 18.3 s, and the lot closing at 27.3 s).

def encode_events(events: list[Event]) -> str:
    def one(e: Event) -> str:
        head = f"{round(e.t * 100)}:{e.kind}"
        return head if e.kind in ("a", "c", "f") else f"{head}:{e.seat}:{e.value}"
    return ";".join(one(e) for e in events)


def decode_events(text: str | None) -> list[Event]:
    if not text:
        return []
    out = []
    for part in text.split(";"):
        bits = part.split(":")
        if not bits[0].isdigit() or len(bits) not in (2, 4) or bits[1] not in "nabcf" or len(bits[1]) != 1:
            raise IllegalMove(f"bad event {part!r}")
        t = int(bits[0]) / 100
        if len(bits) == 2:
            if bits[1] not in "acf":
                raise IllegalMove(f"bad event {part!r}")
            out.append(Event(t, bits[1]))
        else:
            if bits[1] not in "nb" or not bits[2].isdigit() or not bits[3].isdigit() or len(bits[3]) > 4:
                raise IllegalMove(f"bad event {part!r}")
            out.append(Event(t, bits[1], int(bits[2]), int(bits[3])))
    return out
