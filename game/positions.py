"""Positions (C35): what a player can play, and where an eleven's players stand.

A player-season holds up to four positions, most-played first. For 2013-14 onwards they
are MEASURED: every position he started at least once for that club that season, in
Transfermarkt's line-ups (etl.positions). Before that no open per-match source exists,
so they are DECLARED, written by hand like the ratings and saying so.

A formation is eleven slots, each a position. A player can stand only in a slot whose
position he holds. Nobody is ever stuck in the wrong place by the ORDER of a draft: a
pick is legal when the whole eleven so far can still be given distinct slots (a
bipartite matching), and where everyone actually stands is worked out afresh each time,
favouring each man's most-played positions. So drafting a right-back after Kimmich moves
Kimmich into midfield rather than refusing the right-back.

The engine still reads lines: a placed player carries the LINE OF HIS SLOT, so Kimmich
at right-back defends as a defender and in midfield passes as a midfielder.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence, TypeVar

# Display order: back to front, right to left as a team sheet reads.
POSITIONS = ("GK", "RB", "CB", "LB", "DM", "CM", "AM", "RM", "LM", "RW", "ST", "LW")
LINE = {"GK": "GK", "RB": "DF", "CB": "DF", "LB": "DF",
        "DM": "MF", "CM": "MF", "AM": "MF", "RM": "MF", "LM": "MF",
        "RW": "FW", "ST": "FW", "LW": "FW"}
NAMES = {"GK": "goalkeeper", "RB": "right-back", "CB": "centre-back", "LB": "left-back",
         "DM": "defensive midfielder", "CM": "central midfielder", "AM": "attacking midfielder",
         "RM": "right midfielder", "LM": "left midfielder", "RW": "right winger",
         "ST": "striker", "LW": "left winger"}
MAX_POSITIONS = 4

assert set(LINE) == set(POSITIONS) == set(NAMES)

C = TypeVar("C")


def _edges(slots: Sequence[str], cards: Sequence) -> list[list[int]]:
    return [[j for j, s in enumerate(slots) if s in c.positions] for c in cards]


def matching(slots: Sequence[str], cards: Sequence) -> list[int] | None:
    """A slot index for every card, all distinct, or None if no such assignment exists.
    Kuhn's augmenting paths: at most eleven men and eleven places, so it is instant."""
    edges = _edges(slots, cards)
    owner = [-1] * len(slots)

    def augment(i: int, seen: list[bool]) -> bool:
        for j in edges[i]:
            if not seen[j]:
                seen[j] = True
                if owner[j] < 0 or augment(owner[j], seen):
                    owner[j] = i
                    return True
        return False

    for i in range(len(cards)):
        if not augment(i, [False] * len(slots)):
            return None
    slot_of = [-1] * len(cards)
    for j, i in enumerate(owner):
        if i >= 0:
            slot_of[i] = j
    return slot_of


def fits(slots: Sequence[str], cards: Sequence) -> bool:
    return matching(slots, cards) is not None


BIG = 10 ** 9


def assign(cost: list[list[int]]) -> list[int]:
    """The cheapest assignment of rows to distinct columns (rows <= columns): the
    Hungarian method, O(rows^2 x columns). Returns the column of each row."""
    n, m = len(cost), len(cost[0]) if cost else 0
    if n == 0:
        return []
    u, v = [0] * (n + 1), [0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [float("inf")] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    col = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            col[p[j] - 1] = j - 1
    return col


def arrangement(slots: Sequence[str], cards: Sequence) -> list[int]:
    """Where each card stands: a slot index per card, every card in a slot he holds,
    favouring the positions he played most (his first listed costs 0, his second 1...).
    Raises ValueError if the cards cannot all be placed."""
    cost = [[c.positions.index(s) if s in c.positions else BIG for s in slots] for c in cards]
    out = assign(cost)
    if any(cost[i][j] >= BIG for i, j in enumerate(out)):
        raise ValueError("these players cannot all be placed in this formation")
    return out


def place(card: C, slot: str) -> C:
    """The card as it plays in `slot`: its line becomes the slot's line."""
    return replace(card, pos=LINE[slot], slot=slot)


def arrange(slots: Sequence[str], cards: Sequence[C]) -> list[C]:
    """The cards placed and in slot order (goalkeeper first, as the formation lists its
    slots). Fewer than eleven cards leave the empty slots out."""
    at = arrangement(slots, cards)
    order = sorted(range(len(cards)), key=lambda i: at[i])
    return [place(cards[i], slots[at[i]]) for i in order]


def best_eleven(slots: Sequence[str], cards: Sequence[C]) -> tuple[int, list[tuple[C, str]]] | None:
    """The highest-rated eleven these cards can field in these slots, as (total rating,
    [(card, slot)] in slot order), or None if they cannot fill every slot. Among equal
    totals the one closest to each man's most-played positions wins."""
    if len(cards) < len(slots):
        return None
    # Rows are slots, columns cards. Rating dominates; the position rank breaks ties.
    cost = [[(100 - c.rating) * 10 + c.positions.index(s) if s in c.positions else BIG
             for c in cards] for s in slots]
    col = assign(cost)
    if any(cost[j][i] >= BIG for j, i in enumerate(col)):
        return None
    xi = [(cards[i], slots[j]) for j, i in enumerate(col)]
    return sum(c.rating for c, _ in xi), xi
