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

A finished bench draft may carry a PLAN (C41): for each substitute, from which minute he
comes on, on what score, and for whom (a starter, by his slot) or for whoever it helps
most to replace. With no plan the automatic one applies (game.tournament.auto_plan).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation
from game.match import Sub
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


@dataclass(frozen=True)
class Change:
    """One line of a plan: bench man ``on`` comes on at the first break from ``minute``
    at which ``when`` holds, for the starter in slot ``off`` of the formation, or, with
    ``off`` None, for whoever it helps most to replace (and then only if it helps)."""

    on: int
    minute: int
    when: str
    off: int | None = None


PLAN_MINUTES = tuple(range(45, 90, 5))      # 45' to 85': a plan for the ninety minutes
WHEN = {"a": "any", "b": "behind", "l": "level", "h": "ahead", "n": "not_ahead", "w": "not_behind"}
WHEN_CODE = {v: k for k, v in WHEN.items()}


def can_replace(formation: Formation, xi: list[Card], man: Card) -> list[int]:
    """The slots (indices into the formation) whose starter ``man`` could come on for, the
    eleven still filling the formation. Never the goalkeeper's."""
    return [j for j, c in enumerate(xi)
            if formation.slots[j] != "GK" and fits(formation.slots, [*(x for x in xi if x is not c), man])]


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
    plan: tuple[Change, ...] | None = None            # None: the automatic plan

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

    def subs(self) -> tuple[Sub, ...] | None:
        """The plan as the engine reads it (a named starter by his person), or None for
        the automatic plan."""
        if self.plan is None:
            return None
        xi = self.xi
        return tuple(Sub(c.on, c.minute, c.when, None if c.off is None else xi[c.off].id) for c in self.plan)


def _deal(rng: random.Random, deck: Deck, s: Session) -> ClubSeason:
    for _ in range(REDRAW_CAP):
        cs = rng.choice(deck.club_seasons)
        if any(why_not(c, s.formation, s.picks) is None for c in cs.cards):
            s.dealt.append(cs.key)
            return cs
        s.redraws += 1
    raise RuntimeError("no squad in the deck can fill an open slot")


def check_plan(s: Session, plan: tuple[Change, ...]) -> None:
    """A plan fits a finished bench draft: each substitute once, each starter replaced at
    most once and never the keeper, and only by a man who could come on for him."""
    if not s.bench_size or not s.complete:
        raise IllegalMove("a plan needs a finished draft with a bench")
    if len(plan) > len(s.bench):
        raise IllegalMove("more changes than substitutes")
    if len({c.on for c in plan}) < len(plan):
        raise IllegalMove("a substitute can come on only once")
    named = [c.off for c in plan if c.off is not None]
    if len(set(named)) < len(named):
        raise IllegalMove("two changes for one man")
    xi = s.xi
    for c in plan:
        if not 0 <= c.on < len(s.bench):
            raise IllegalMove(f"no substitute {c.on}")
        if c.minute not in PLAN_MINUTES or c.when not in WHEN_CODE:
            raise IllegalMove("a change comes from 45' to 85', on a score the plan knows")
        if c.off is not None and c.off not in can_replace(s.formation, xi, s.bench[c.on]):
            raise IllegalMove(f"{s.bench[c.on].name} can't come on for the man in slot {c.off}")


def replay(deck: Deck, seed: int, formation_code: str, moves: list[Move], bench: bool = False,
           plan: tuple[Change, ...] | None = None) -> Session:
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
    if plan is not None:
        check_plan(s, plan)
        s.plan = plan
    return s


# -- state strings: "SEED-FORMATION" or "SEED-FORMATION-m.m.m", m an index or "r";
# a bench draft's seed carries a "b": "bSEED-FORMATION-m.m.m", and a finished one may end
# in a plan, "-p" and its changes: "p0b60o9.1a70.2a80" is substitute 0 from 60' if
# behind for the man in slot 9, then substitutes 1 and 2 from 70' and 80' whatever the
# score for whoever it helps most. "p" alone is a plan of no changes.

def encode_plan(plan: tuple[Change, ...]) -> str:
    return "p" + ".".join(f"{c.on}{WHEN_CODE[c.when]}{c.minute}" + ("" if c.off is None else f"o{c.off}")
                          for c in plan)


def decode_plan(text: str) -> tuple[Change, ...]:
    if not text.startswith("p"):
        raise IllegalMove(f"not a plan: {text!r}")
    out = []
    for tok in filter(None, text[1:].split(".")):
        m = PLAN_TOKEN.fullmatch(tok)
        if m is None:
            raise IllegalMove(f"bad change {tok!r}")
        on, when, minute, off = m.groups()
        out.append(Change(int(on), int(minute), WHEN[when], None if off is None else int(off)))
    if len(out) > BENCH:
        raise IllegalMove("more changes than substitutes")
    return tuple(out)


PLAN_TOKEN = re.compile(r"(\d)([" + "".join(WHEN) + r"])(\d{2})(?:o(\d{1,2}))?")


def encode(seed: int, formation: str, moves: list[Move], bench: bool = False,
           plan: tuple[Change, ...] | None = None) -> str:
    tokens = ["r" if isinstance(m, Reroll) else str(m.index) for m in moves]
    out = f"{'b' if bench else ''}{seed}-{formation}" + (f"-{'.'.join(tokens)}" if tokens else "")
    return out + (f"-{encode_plan(plan)}" if plan is not None else "")


def decode(state: str) -> tuple[int, str, list[Move]]:
    """An eleven-pick draft's state. A bench draft's is refused: rooms and the daily know
    nothing of a bench, so nothing that reads them may take one for an eleven."""
    seed, formation, moves, bench, _ = decode_state(state)
    if bench:
        raise IllegalMove(f"a bench draft is not an eleven: {state!r}")
    return seed, formation, moves


def decode_state(state: str) -> tuple[int, str, list[Move], bool, tuple[Change, ...] | None]:
    """(seed, formation, moves, whether it is a bench draft, its plan or None)."""
    bench = state.startswith("b")
    parts = (state[1:] if bench else state).split("-")
    plan = None
    if bench and len(parts) == 4:
        plan = decode_plan(parts.pop())
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
    return int(parts[0]), parts[1], moves, bench, plan
