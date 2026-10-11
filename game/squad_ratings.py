"""A finished side's ratings, line by line, for the page shown after a draft.

Every figure here is an average of the cards' own ratings, which are declared judgement
(C2), so these are too: nothing is derived from match data. Each line's average reads the
LINE OF THE SLOT a man stands in (game.positions), as the engine does, so Kimmich at
right-back counts towards the defence.

Two of the numbers are the engine's own: ``engine_attack`` and ``engine_defence`` are the
weighted means ``match.attack`` and ``match.defence`` that actually decide a match (the
midfield carries both). The line averages are what a team sheet shows; those two are
what the dice read.

Each figure is set against the deck: the share of its club-seasons, at their best eleven
(``tournament.best_xi``) and their bench (``tournament.club_bench``), that the side rates
strictly above.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from typing import Sequence

from game import match
from game.deck import Card, Deck

FIGURES = ("overall", "attack", "midfield", "defence", "goalkeeper", "bench",
           "engine_attack", "engine_defence")


def _mean(cards: Sequence[Card]) -> float | None:
    return sum(c.rating for c in cards) / len(cards) if cards else None


@dataclass(frozen=True)
class SquadRatings:
    overall: float
    attack: float | None          # the forwards' line; None if a shape had none
    midfield: float | None
    defence: float | None         # the back line, keeper not included
    goalkeeper: float | None
    bench: float | None           # None without a bench
    engine_attack: float
    engine_defence: float

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)


def squad_ratings(xi: Sequence[Card], bench: Sequence[Card] = ()) -> SquadRatings:
    """``xi`` must be placed (every card has a slot), so each man counts in his slot's line."""
    if len(xi) != 11 or any(c.slot is None for c in xi):
        raise ValueError("the eleven must be complete and placed in its slots")
    line = lambda name: [c for c in xi if c.pos == name]  # noqa: E731
    return SquadRatings(
        overall=_mean(xi), attack=_mean(line("FW")), midfield=_mean(line("MF")),
        defence=_mean(line("DF")), goalkeeper=_mean(line("GK")), bench=_mean(bench),
        engine_attack=match.attack(xi), engine_defence=match.defence(xi),
    )


_FIELD: dict[int, dict[str, list[float]]] = {}


def deck_field(deck: Deck) -> dict[str, list[float]]:
    """Every figure for every club-season in the deck, sorted, to rank a side against."""
    got = _FIELD.get(id(deck))
    if got is None:
        from game.tournament import best_xi, club_bench   # tournament imports nothing from here
        rows = [squad_ratings(best_xi(cs)[1], club_bench(cs)) for cs in deck.club_seasons]
        got = _FIELD[id(deck)] = {k: sorted(v for r in rows if (v := getattr(r, k)) is not None)
                                  for k in FIGURES}
    return got


def better_than(value: float | None, field: list[float]) -> int | None:
    """The share of ``field`` strictly below ``value``, as a whole percentage."""
    if value is None or not field:
        return None
    return round(100 * bisect_left(field, value) / len(field))


def ranked(deck: Deck, r: SquadRatings) -> dict[str, int | None]:
    f = deck_field(deck)
    return {k: better_than(getattr(r, k), f[k]) for k in FIGURES}
