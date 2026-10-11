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

A LEAGUE DRAFT (C50) is a bench draft whose tournament is the league phase, not the group
format: every solo draft made since. Its state string starts with "l" in place of the
"b"; the draft itself, its plan and its sheet are a bench draft's exactly. Rooms keep the
format with the room (by its size), so a room's seat never holds an "l" state.

A finished bench draft may carry a PLAN (C41): for each substitute, from which minute he
comes on, on what score, and for whom (a starter, by his slot) or for whoever it helps
most to replace. With no plan the automatic one applies (game.tournament.auto_plan).

A finished bench draft may also carry a TEAM SHEET (C44): who stands in each slot and
who sits on the bench, chosen after the last pick. Without one, the eleven are the first
eleven picks placed by most-played position (game.positions.arrange) and the bench is the
last three, as before. With one, any of the fourteen may start, in any slot whose
position he holds, and any outfield man may sit on the bench; keepers stay on. A change is
made one man at a time (``move``): to a slot, or to the bench for a substitute, everyone
else moving as little as possible to make room. Swapping two starters alone would rarely
do anything: measured over 200 drafts, two starters each held the other's position 0.23
times a draft, while 3.4 starters held another position the shape has. A plan follows its
men through a change of sheet (``carry_plan``).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from game.deck import Card, ClubSeason, Deck
from game.formations import FORMATIONS, Formation
from game.match import Sub
from game.positions import BIG, arrange, arrangement, assign, fits, place

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
    return bench_reason(card, formation)


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
    sheet: tuple[int, ...] | None = None              # None: the picks' own order (C44)

    @property
    def total(self) -> int:
        return 11 + self.bench_size

    @property
    def complete(self) -> bool:
        return len(self.picks) == self.total

    @property
    def xi(self) -> list[Card]:
        """The eleven placed in their slots, in slot order: as the sheet says, or the first
        eleven picks by most-played position (game.positions.arrange)."""
        if self.sheet is not None:
            return [place(self.picks[i], slot) for i, slot in zip(self.sheet, self.formation.slots)]
        return arrange(self.formation.slots, self.picks[:11])

    @property
    def bench(self) -> list[Card]:
        if self.sheet is not None:
            return [self.picks[i] for i in self.sheet[11:]]
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


def default_sheet(s: Session) -> tuple[int, ...]:
    """The sheet a finished draft has without one: the first eleven picks where
    ``arrange`` puts them, then the bench in pick order."""
    at = arrangement(s.formation.slots, s.picks[:11])
    return (*sorted(range(11), key=lambda i: at[i]), *range(11, len(s.picks)))


def check_sheet(s: Session, sheet: tuple[int, ...]) -> None:
    """A sheet fits a finished bench draft: every pick once, each starter in a slot whose
    position he holds, and on the bench only outfield men the formation has a place for."""
    if not s.bench_size or not s.complete:
        raise IllegalMove("a team sheet needs a finished draft with a bench")
    if sorted(sheet) != list(range(s.total)):
        raise IllegalMove("a team sheet names every player once")
    for i, slot in zip(sheet, s.formation.slots):
        if slot not in s.picks[i].positions:
            raise IllegalMove(f"{s.picks[i].name} doesn't play {slot}")
    for i in sheet[11:]:
        reason = bench_reason(s.picks[i], s.formation)
        if reason:
            raise IllegalMove(f"{s.picks[i].name}: {reason}")


def bench_reason(card: Card, formation: Formation) -> str | None:
    """Why a man can't sit on the bench, or None: the engine never changes a keeper, and a
    substitute must hold a position the formation has."""
    if card.positions == ("GK",):
        return "keepers stay on"
    if not set(card.positions) & set(formation.slots):
        return f"no {'/'.join(card.positions)} in a {formation.label}"
    return None


def _settle(s: Session, men: list[int], prefer: dict[int, int], fixed: tuple[int, int] | None = None
            ) -> tuple[int, ...] | None:
    """The eleven ``men`` (pick indices) in slot order, each where he ``prefer``s to stand
    if he can and otherwise moving as few men as possible (each move costs 100, plus how
    far down his positions the new one is); ``fixed`` pins one man to one slot. None if
    they can't fill the formation."""
    slots = s.formation.slots
    cost = []
    for i in men:
        ps = s.picks[i].positions
        cost.append([BIG if slot not in ps or (fixed is not None and fixed[0] == i and fixed[1] != j)
                     else 0 if prefer.get(i) == j else 100 + ps.index(slot)
                     for j, slot in enumerate(slots)])
    col = assign(cost)
    if any(cost[r][col[r]] >= BIG for r in range(len(men))):
        return None
    out = [0] * len(slots)
    for r, i in enumerate(men):
        out[col[r]] = i
    return tuple(out)


def _split(s: Session) -> tuple[list[int], list[int]]:
    sheet = s.sheet if s.sheet is not None else default_sheet(s)
    return list(sheet[:11]), list(sheet[11:])


def move(s: Session, man: int, to: str) -> tuple[int, ...]:
    """The sheet after moving ``man`` (a pick index) ``to`` "s<j>", slot j, or "b<k>", bench
    place k. A starter sent to a slot stands there and the rest make room; a starter sent to
    the bench swaps with that substitute, who comes in where the starter stood if he can; a
    substitute sent to a slot replaces its starter likewise; two substitutes swap places."""
    if not s.bench_size or not s.complete:
        raise IllegalMove("a team sheet needs a finished draft with a bench")
    m = re.fullmatch(r"([sb])(\d{1,2})", to)
    xi, bench = _split(s)
    if m is None or not 0 <= int(m[2]) < (11 if m[1] == "s" else len(bench)) or not 0 <= man < len(s.picks):
        raise IllegalMove(f"no place {to!r}")
    kind, n = m[1], int(m[2])
    where = {i: j for j, i in enumerate(xi)}
    name = s.picks[man].name
    if man in where and kind == "s":
        if where[man] == n:
            raise IllegalMove(f"{name} is already there")
        if s.formation.slots[n] not in s.picks[man].positions:
            raise IllegalMove(f"{name} doesn't play {s.formation.slots[n]}")
        eleven = _settle(s, xi, where, (man, n))
    elif man in where or kind == "s":
        off, on = (man, bench[n]) if man in where else (xi[n], man)
        reason = bench_reason(s.picks[off], s.formation)
        if reason:
            raise IllegalMove(f"{s.picks[off].name}: {reason}")
        eleven = _settle(s, [on if i == off else i for i in xi], {**where, on: where[off]})
        bench[bench.index(on)] = off
    else:
        k = bench.index(man)
        if k == n:
            raise IllegalMove(f"{name} is already there")
        bench[k], bench[n] = bench[n], bench[k]
        eleven = tuple(xi)
    if eleven is None:
        raise IllegalMove(f"that leaves nobody who can play every place in the {s.formation.label}")
    return (*eleven, *bench)


def targets(s: Session) -> dict[int, list[str]]:
    """For each pick index, every place ``move`` would take him: what the page offers."""
    slots = s.formation.slots
    xi, bench = _split(s)
    cards = s.picks
    out: dict[int, list[str]] = {}
    for a, man in enumerate(xi):
        c, rest = cards[man], [cards[i] for i in xi if i != man]
        out[man] = [f"s{j}" for j, slot in enumerate(slots)
                    if j != a and slot in c.positions and fits([x for n, x in enumerate(slots) if n != j], rest)]
        if bench_reason(c, s.formation) is None:
            out[man] += [f"b{k}" for k, i in enumerate(bench) if fits(slots, [*rest, cards[i]])]
    for k, man in enumerate(bench):
        out[man] = [f"s{j}" for j, i in enumerate(xi) if bench_reason(cards[i], s.formation) is None
                    and fits(slots, [*(cards[x] for x in xi if x != i), cards[man]])]
        out[man] += [f"b{n}" for n in range(len(bench)) if n != k]
    return out


def carry_plan(before: Session, after: Session, plan: tuple[Change, ...] | None) -> tuple[Change, ...] | None:
    """A plan made for one sheet, for another: each line follows its substitute (dropped if
    he now starts) and its named starter (back to "best change" if he no longer starts or
    can no longer be replaced by that man). The automatic plan stays automatic."""
    if plan is None:
        return None
    bench = [c.id for c in after.bench]
    xi = after.xi
    starters = [c.id for c in xi]
    out = []
    for c in plan:
        man = before.bench[c.on].id
        if man not in bench:
            continue
        on = bench.index(man)
        off = None
        if c.off is not None and (who := before.xi[c.off].id) in starters:
            j = starters.index(who)
            off = j if j in can_replace(after.formation, xi, after.bench[on]) else None
        out.append(Change(on, c.minute, c.when, off))
    return tuple(out)


def replay(deck: Deck, seed: int, formation_code: str, moves: list[Move], bench: bool = False,
           plan: tuple[Change, ...] | None = None, sheet: tuple[int, ...] | None = None) -> Session:
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
    if sheet is not None:
        check_sheet(s, sheet)
        s.sheet = sheet
    if plan is not None:
        check_plan(s, plan)
        s.plan = plan
    return s


# -- state strings: "SEED-FORMATION" or "SEED-FORMATION-m.m.m", m an index or "r";
# a bench draft's seed carries a "b": "bSEED-FORMATION-m.m.m", a league draft's an "l"
# ("lSEED-..."), and a finished one of either may end
# in a plan, "-p" and its changes: "p0b60o9.1a70.2a80" is substitute 0 from 60' if
# behind for the man in slot 9, then substitutes 1 and 2 from 70' and 80' whatever the
# score for whoever it helps most. "p" alone is a plan of no changes. A team sheet (C44)
# comes before the plan, "-s" and one character per place, each a pick's index in base
# 36: the eleven in slot order, then the bench ("b5-433-...-s0a123456789bcd-p...").

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


SHEET_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def encode_sheet(sheet: tuple[int, ...]) -> str:
    return "s" + "".join(SHEET_DIGITS[i] for i in sheet)


def decode_sheet(text: str) -> tuple[int, ...]:
    if not text.startswith("s") or len(text) != 1 + 11 + BENCH or any(ch not in SHEET_DIGITS for ch in text[1:]):
        raise IllegalMove(f"not a team sheet: {text!r}")
    return tuple(SHEET_DIGITS.index(ch) for ch in text[1:])


def encode(seed: int, formation: str, moves: list[Move], bench: bool = False,
           plan: tuple[Change, ...] | None = None, sheet: tuple[int, ...] | None = None,
           league: bool = False) -> str:
    if league and not bench:
        raise ValueError("a league draft is a bench draft")
    tokens = ["r" if isinstance(m, Reroll) else str(m.index) for m in moves]
    kind = "l" if league else "b" if bench else ""
    out = f"{kind}{seed}-{formation}" + (f"-{'.'.join(tokens)}" if tokens else "")
    out += f"-{encode_sheet(sheet)}" if sheet is not None else ""
    return out + (f"-{encode_plan(plan)}" if plan is not None else "")


def is_league(state: str) -> bool:
    """Whether a solo state plays the league phase (C50) rather than the group format."""
    return state.startswith("l")


def decode(state: str) -> tuple[int, str, list[Move]]:
    """An eleven-pick draft's state. A bench draft's is refused: rooms and the daily know
    nothing of a bench, so nothing that reads them may take one for an eleven."""
    seed, formation, moves, bench, _ = decode_state(state)
    if bench:
        raise IllegalMove(f"a bench draft is not an eleven: {state!r}")
    return seed, formation, moves


def decode_state(state: str) -> tuple[int, str, list[Move], bool, tuple[Change, ...] | None]:
    """(seed, formation, moves, whether it is a bench draft, its plan or None). A state
    with a team sheet is refused: only a solo link carries one, read by ``decode_solo``
    (a room keeps a seat's sheet in its own column), and so is a league draft's: a room
    plays the format its size says, and the daily plays one match."""
    if is_league(state):
        raise IllegalMove(f"a league draft has no place in this state: {state!r}")
    seed, formation, moves, bench, plan, sheet = decode_solo(state)
    if sheet is not None:
        raise IllegalMove(f"a team sheet has no place in this state: {state!r}")
    return seed, formation, moves, bench, plan


def decode_solo(state: str) -> tuple[int, str, list[Move], bool, tuple[Change, ...] | None,
                                     tuple[int, ...] | None]:
    """(seed, formation, moves, bench, plan, sheet): a solo link, which may carry a sheet.
    A league draft is a bench draft here; ``is_league`` tells it apart."""
    bench = state.startswith(("b", "l"))
    parts = (state[1:] if bench else state).split("-")
    plan = sheet = None
    if bench and len(parts) >= 4 and parts[-1].startswith("p"):
        plan = decode_plan(parts.pop())
    if bench and len(parts) == 4 and parts[-1].startswith("s"):
        sheet = decode_sheet(parts.pop())
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
    return int(parts[0]), parts[1], moves, bench, plan, sheet
