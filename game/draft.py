"""The draft: eleven picks, one per dealt squad, into a chosen formation.

Each turn deals one club-season uniformly at random from the deck (so Bayern,
with 24 quarter-final seasons, turns up 24 times as often as APOEL with one --
rarity should feel like an event). The drafter takes ONE rated player from it
into the formation, or spends a reroll. A player can stand only in a slot whose
position he holds (C35, game.positions); a pick is legal while the whole eleven so far
can still be given distinct slots, and where each man stands is settled afresh after
every pick, so the order of a draft never strands anyone.

A deal that offers nothing takeable -- every player already picked, or none who
fits the places left -- is redrawn before it is shown. That is the
deal-time guarantee, and ``redraws`` counts it so a deck too thin to serve its
drafters is visible rather than hidden.

The draft is a pure function of (seed, formation, moves): the server keeps no
session and replays the moves on every request.

A BENCH DRAFT (C40) takes three more picks after the eleven, for the bench: men who can
come on in engine 2 (game.match.play_v2). A bench man holds a position the formation
has, so he can always come on for whoever stands there, and is never a goalkeeper,
because the engine never changes the keeper. Its state string starts with "b"; a plain
one is the original eleven-pick draft, played by engine 1, and always will be.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation
from game.positions import arrange, fits

REROLLS_ALLOWED = 2
REDRAW_CAP = 2_000
BENCH = 3


class IllegalMove(Exception):
    pass


@dataclass(frozen=True)
class Reroll:
    pass


@dataclass(frozen=True)
class Pick:
    index: int   # into the dealt squad's cards


Move = Pick | Reroll


def why_not(card: Card, formation: Formation, picks: list[Card]) -> str | None:
    """None if the card can be taken now, else the reason it cannot. Once the eleven is
    full, a pick is for the bench."""
    if len(picks) >= 11:
        return why_not_bench(card, formation, picks)
    if any(c.id == card.id for c in picks):
        return "already in your eleven"
    if not set(card.positions) & set(formation.slots):
        return f"no {'/'.join(card.positions)} in a {formation.label}"
    if not fits(formation.slots, [*picks, card]):
        if card.positions == ("GK",):
            return "goalkeeper taken"
        return f"no {'/'.join(card.positions)} place left"
    return None


def why_not_bench(card: Card, formation: Formation, picks: list[Card]) -> str | None:
    """A bench pick, made with the eleven full."""
    if any(c.id == card.id for c in picks[:11]):
        return "already in your eleven"
    if any(c.id == card.id for c in picks[11:]):
        return "already on your bench"
    if card.positions == ("GK",):
        return "keepers stay on"
    if not set(card.positions) & set(formation.slots):
        return f"no {'/'.join(card.positions)} in a {formation.label}"
    return None


@dataclass
class Session:
    seed: int
    formation: Formation
    picks: list[Card] = field(default_factory=list)
    deal: ClubSeason | None = None
    rerolls_left: int = REROLLS_ALLOWED
    redraws: int = 0
    dealt: list[str] = field(default_factory=list)   # club-season keys, in order
    bench_size: int = 0                               # BENCH in a bench draft, else 0

    @property
    def total(self) -> int:
        return 11 + self.bench_size

    @property
    def complete(self) -> bool:
        return len(self.picks) == self.total

    @property
    def xi(self) -> list[Card]:
        """The eleven placed in their slots, in slot order (game.positions.arrange)."""
        return arrange(self.formation.slots, self.picks[:11])

    @property
    def bench(self) -> list[Card]:
        return self.picks[11:]


def _deal(rng: random.Random, deck: Deck, s: Session) -> ClubSeason:
    for _ in range(REDRAW_CAP):
        cs = rng.choice(deck.club_seasons)
        if any(why_not(c, s.formation, s.picks) is None for c in cs.cards):
            s.dealt.append(cs.key)
            return cs
        s.redraws += 1
    raise RuntimeError("no squad in the deck can fill an open slot")


def replay(deck: Deck, seed: int, formation_code: str, moves: list[Move], bench: bool = False) -> Session:
    """Replay a draft from scratch. Raises IllegalMove on a move the deal did not offer."""
    formation = FORMATIONS.get(formation_code)
    if formation is None:
        raise IllegalMove(f"unknown formation {formation_code!r}")
    rng = random.Random(seed)
    s = Session(seed=seed, formation=formation, bench_size=BENCH if bench else 0)
    s.deal = _deal(rng, deck, s)
    for move in moves:
        if s.complete:
            raise IllegalMove("the squad is already complete" if bench else "the eleven is already complete")
        if isinstance(move, Reroll):
            if s.rerolls_left <= 0:
                raise IllegalMove("no rerolls left")
            s.rerolls_left -= 1
        else:
            cards = s.deal.cards
            if not 0 <= move.index < len(cards):
                raise IllegalMove(f"no player {move.index} in this squad")
            card = cards[move.index]
            reason = why_not(card, formation, s.picks)
            if reason:
                raise IllegalMove(f"{card.name}: {reason}")
            s.picks.append(card)
        s.deal = None if s.complete else _deal(rng, deck, s)
    return s


# -- state strings: "SEED-FORMATION" or "SEED-FORMATION-m.m.m", m an index or "r";
# a bench draft's seed carries a "b": "bSEED-FORMATION-m.m.m".

def encode(seed: int, formation: str, moves: list[Move], bench: bool = False) -> str:
    tokens = ["r" if isinstance(m, Reroll) else str(m.index) for m in moves]
    return f"{'b' if bench else ''}{seed}-{formation}" + (f"-{'.'.join(tokens)}" if tokens else "")


def decode(state: str) -> tuple[int, str, list[Move]]:
    """An eleven-pick draft's state. A bench draft's is refused: rooms and the daily know
    nothing of a bench, so nothing that reads them may take one for an eleven."""
    seed, formation, moves, bench = decode_state(state)
    if bench:
        raise IllegalMove(f"a bench draft is not an eleven: {state!r}")
    return seed, formation, moves


def decode_state(state: str) -> tuple[int, str, list[Move], bool]:
    """(seed, formation, moves, whether it is a bench draft)."""
    bench = state.startswith("b")
    parts = (state[1:] if bench else state).split("-")
    if len(parts) not in (2, 3) or not parts[0].isdigit():
        raise IllegalMove(f"not a draft state: {state!r}")
    moves: list[Move] = []
    if len(parts) == 3 and parts[2]:
        for tok in parts[2].split("."):
            if tok == "r":
                moves.append(Reroll())
            elif tok.isdigit() and len(tok) <= 3:
                moves.append(Pick(int(tok)))
            else:
                raise IllegalMove(f"bad move {tok!r}")
    if len(moves) > 11 + (BENCH if bench else 0) + REROLLS_ALLOWED:
        raise IllegalMove("too many moves")
    return int(parts[0]), parts[1], moves, bench
