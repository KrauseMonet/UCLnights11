"""The draft: eleven picks, one per dealt squad, into a chosen formation.

Each turn deals one club-season uniformly at random from the deck (so Bayern,
with 24 quarter-final seasons, turns up 24 times as often as APOEL with one --
rarity should feel like an event). The drafter takes ONE rated player from it
into an open slot in that player's own line, or spends a reroll.

A deal that offers nothing takeable -- every player already picked, or every
line he could fill already full -- is redrawn before it is shown. That is the
deal-time guarantee, and ``redraws`` counts it so a deck too thin to serve its
drafters is visible rather than hidden.

The draft is a pure function of (seed, formation, moves): the server keeps no
session and replays the moves on every request.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation

REROLLS_ALLOWED = 2
REDRAW_CAP = 2_000


class IllegalMove(Exception):
    pass


@dataclass(frozen=True)
class Reroll:
    pass


@dataclass(frozen=True)
class Pick:
    index: int   # into the dealt squad's cards


Move = Pick | Reroll


def open_lines(formation: Formation, picks: list[Card]) -> dict[str, int]:
    return {pos: n - sum(1 for c in picks if c.pos == pos) for pos, n in formation.lines.items()}


def why_not(card: Card, formation: Formation, picks: list[Card]) -> str | None:
    """None if the card can be taken now, else the reason it cannot."""
    if any(c.id == card.id for c in picks):
        return "already in your eleven"
    if open_lines(formation, picks)[card.pos] <= 0:
        return {"GK": "goalkeeper taken", "DF": "defence full", "MF": "midfield full",
                "FW": "attack full"}[card.pos]
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

    @property
    def complete(self) -> bool:
        return len(self.picks) == 11


def _deal(rng: random.Random, deck: Deck, s: Session) -> ClubSeason:
    for _ in range(REDRAW_CAP):
        cs = rng.choice(deck.club_seasons)
        if any(why_not(c, s.formation, s.picks) is None for c in cs.cards):
            s.dealt.append(cs.key)
            return cs
        s.redraws += 1
    raise RuntimeError("no squad in the deck can fill an open slot")


def replay(deck: Deck, seed: int, formation_code: str, moves: list[Move]) -> Session:
    """Replay a draft from scratch. Raises IllegalMove on a move the deal did not offer."""
    formation = FORMATIONS.get(formation_code)
    if formation is None:
        raise IllegalMove(f"unknown formation {formation_code!r}")
    rng = random.Random(seed)
    s = Session(seed=seed, formation=formation)
    s.deal = _deal(rng, deck, s)
    for move in moves:
        if s.complete:
            raise IllegalMove("the eleven is already complete")
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


# -- state strings: "SEED-FORMATION" or "SEED-FORMATION-m.m.m", m an index or "r"

def encode(seed: int, formation: str, moves: list[Move]) -> str:
    tokens = ["r" if isinstance(m, Reroll) else str(m.index) for m in moves]
    return f"{seed}-{formation}" + (f"-{'.'.join(tokens)}" if tokens else "")


def decode(state: str) -> tuple[int, str, list[Move]]:
    parts = state.split("-")
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
    if len(moves) > 11 + REROLLS_ALLOWED:
        raise IllegalMove("too many moves")
    return int(parts[0]), parts[1], moves
