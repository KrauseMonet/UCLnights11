"""The league phase's draw and fixture list (the format since 2024-25), as pure functions
of indices, so the rules can be tested on made-up sides.

THE DRAW. 36 sides in four pots of nine. Each side plays two opponents from every pot,
its own included, one at home and one away: eight different opponents, four at home.
A club never meets a club of its own association and meets at most two clubs of any one
association (UEFA's rules, as Wikipedia's 2024-25 league phase article states them). A
drafted eleven belongs to no association: it may meet anyone, but it too meets at most
two of any one association, so no human's eight are all Spanish.

The draw is a constraint search, as UEFA's own is done by software: every side has eight
places to fill (an opponent from pot p, at home or away), and the place with the fewest
opponents still possible is filled next, from those opponents in a seeded random order,
undoing a choice that leaves some place with none. A search that wanders too long starts
again from a new order, so every draw is a pure function of the seed. ``draw`` raises
DrawFailed rather than relax a rule; measured, no tournament comes near needing that.

THE FIXTURE LIST. Eight matchdays, every side once on each. UEFA's principles (Article
17 of the 2025-26 regulations): no side plays more than two home or two away matches in
a row, and each plays one home and one away match in the first two matchdays and again
in the last two. Built the same way, one match at a time, matchday by matchday.

Sets of sides are bitmasks (bit t is side t), which keeps the search fast enough to run
on every request: a draw and its fixture list take a few milliseconds.
"""

from __future__ import annotations

import random

POTS = 4
POT_SIZE = 9
TEAMS = POTS * POT_SIZE
MATCHDAYS = 2 * POTS
MAX_FROM_ONE = 2          # opponents from any one association
MAX_IN_POT = 4            # sides of one association in a pot
HOME, AWAY = 0, 1
# Choices one attempt at a draw may try before starting again from a new order. Short
# attempts beat long ones: measured over 300 draws, 300 choices gave a worst draw of 32 ms
# where 20,000 gave 2 s, because a search that has wandered rarely finds its way back.
SEARCH_NODES = 300
ATTEMPTS = 1000           # attempts at one draw
REDRAWS = 100             # draws tried for one fixture list


class DrawFailed(Exception):
    pass


class _Restart(Exception):
    pass


def pots(strength: list[float], assoc: list[str | None]) -> list[int]:
    """Each side's pot: nine to a pot, strongest first, except that a pot holds at most
    four sides of one association. With five, each would need two opponents from its own
    pot among the four others, who can take only eight such matches between them: no
    draw would exist. A side that would be a fifth waits for the next pot, which the
    strongest side not of its association below it takes its place in. Real pots,
    ranked by coefficient across many associations, have never needed this."""
    order = sorted(range(len(strength)), key=lambda t: (-strength[t], t))
    pot_of = [0] * len(strength)
    waiting = order
    for q in range(POTS):
        here, count, later = [], {}, []
        for t in waiting:
            a = assoc[t]
            if len(here) < POT_SIZE and (not a or count.get(a, 0) < MAX_IN_POT or q == POTS - 1):
                here.append(t)
                if a:
                    count[a] = count.get(a, 0) + 1
            else:
                later.append(t)
        for t in here:
            pot_of[t] = q
        waiting = later
    # The last pot takes what is left; if that is five of one association, its strongest
    # swaps with the weakest side of the pot above of an association with room below.
    for q in range(POTS - 1, 0, -1):
        while True:
            count = {}
            for t in order:
                if pot_of[t] == q and assoc[t]:
                    count[assoc[t]] = count.get(assoc[t], 0) + 1
            over = next((a for a, n in count.items() if n > MAX_IN_POT), None)
            if over is None:
                break
            down = next(t for t in order if pot_of[t] == q and assoc[t] == over)
            up = next(t for t in reversed(order) if pot_of[t] == q - 1 and assoc[t] != over
                      and (not assoc[t] or count.get(assoc[t], 0) < MAX_IN_POT))
            pot_of[down], pot_of[up] = q - 1, q
    return pot_of


def draw(rng: random.Random, pot_of: list[int], assoc: list[str | None]) -> list[tuple[int, int]]:
    """The 144 matches, (home, away) by side index. ``pot_of[t]`` is side t's pot (0-3),
    ``assoc[t]`` its association or None."""
    n = len(pot_of)
    if n != TEAMS or any(sum(1 for p in pot_of if p == q) != POT_SIZE for q in range(POTS)):
        raise ValueError("the league phase is four pots of nine")
    for _ in range(ATTEMPTS):
        try:
            return _draw_once(rng, pot_of, assoc)
        except _Restart:
            continue
    raise DrawFailed("no draw satisfies the rules")


def _draw_once(rng: random.Random, pot_of: list[int], assoc: list[str | None]) -> list[tuple[int, int]]:
    n = len(pot_of)
    bit = [1 << t for t in range(n)]
    members = [sum(bit[t] for t in range(n) if pot_of[t] == p) for p in range(POTS)]
    of_assoc: dict[str, int] = {}
    for t, a in enumerate(assoc):
        if a:
            of_assoc[a] = of_assoc.get(a, 0) | bit[t]
    everyone = (1 << n) - 1
    # free[v][p]: the sides whose place "an opponent from pot p, venue v" is still open.
    free = [[everyone] * POTS for _ in (HOME, AWAY)]
    met = [0] * n                                          # opponents so far
    barred = [of_assoc.get(assoc[t], 0) if assoc[t] else 0 for t in range(n)]
    count = [dict() for _ in range(n)]                     # association -> opponents of it
    full: dict[str, int] = {}                              # association -> sides with two of it
    places = [(t, p, v) for t in range(n) for p in range(POTS) for v in (HOME, AWAY)]
    rank = {s: rng.random() for s in places}               # breaks ties between places
    filled = set()
    matches: list[tuple[int, int]] = []
    nodes = 0

    def options(t: int, p: int, v: int) -> int:
        m = members[p] & free[1 - v][pot_of[t]] & ~met[t] & ~bit[t] & ~barred[t]
        a = assoc[t]
        return m & ~full.get(a, 0) if a else m

    def meet(t: int, u: int, step: int) -> None:
        """Count u's association against t (step 1) or take it back (step -1)."""
        a = assoc[u]
        if not a:
            return
        before = count[t].get(a, 0)
        count[t][a] = before + step
        if step == 1 and before + 1 == MAX_FROM_ONE:
            barred[t] |= of_assoc[a]
            full[a] = full.get(a, 0) | bit[t]
        elif step == -1 and before == MAX_FROM_ONE:
            barred[t] &= ~of_assoc[a]
            full[a] &= ~bit[t]

    def solve() -> bool:
        nonlocal nodes
        best, best_n, best_m = None, 99, 0
        for s in places:
            if s in filled:
                continue
            m = options(*s)
            c = m.bit_count()
            if c == 0:
                return False
            if c < best_n or (c == best_n and rank[s] < rank[best]):
                best, best_n, best_m = s, c, m
        if best is None:
            return True
        t, p, v = best
        choices = [u for u in range(n) if best_m >> u & 1]
        rng.shuffle(choices)
        for u in choices:
            nodes += 1
            if nodes > SEARCH_NODES:
                raise _Restart
            mine, theirs = (t, p, v), (u, pot_of[t], 1 - v)
            filled.update((mine, theirs))
            free[v][p] &= ~bit[t]
            free[1 - v][pot_of[t]] &= ~bit[u]
            met[t] |= bit[u]
            met[u] |= bit[t]
            meet(t, u, 1)
            meet(u, t, 1)
            matches.append((t, u) if v == HOME else (u, t))
            if solve():
                return True
            matches.pop()
            meet(u, t, -1)
            meet(t, u, -1)
            met[u] &= ~bit[t]
            met[t] &= ~bit[u]
            free[1 - v][pot_of[t]] |= bit[u]
            free[v][p] |= bit[t]
            filled.difference_update((mine, theirs))
        return False

    if not solve():
        raise _Restart
    return matches


def venue_ok(last: tuple[int, ...], v: int, day: int) -> bool:
    """Whether a side whose last venues (HOME/AWAY, up to two, latest last) are ``last``
    may play at ``v`` on matchday ``day`` (0-7): never three in a row at one venue, and
    one of each in the first two matchdays and in the last two."""
    if day in (1, MATCHDAYS - 1) and last[-1] == v:
        return False
    return not (day >= 2 and last[-1] == v and last[-2] == v)


def fixtures(rng: random.Random, pot_of: list[int], assoc: list[str | None]
             ) -> tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]:
    """The draw and its fixture list: (matches, matchdays). A draw no fixture list fits is
    drawn again, as UEFA's software only completes a draw it can schedule."""
    for _ in range(REDRAWS):
        matches = draw(rng, pot_of, assoc)
        days = schedule(rng, matches, pot_of)
        if days is not None:
            return matches, days
    raise DrawFailed("no draw has a fixture list")


PAIRINGS = (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))


def schedule(rng: random.Random, matches: list[tuple[int, int]], pot_of: list[int]
             ) -> list[list[tuple[int, int]]] | None:
    """The matches in eight matchdays, or None if this way of building them finds none.

    Built in four blocks of two matchdays, in each of which every side plays once at home
    and once away; that keeps every principle ``venue_ok`` checks, whatever order the
    blocks come in. The pots pair up (1 and 2, 3 and 4, or another pairing): two blocks
    hold the matches inside each pair of pots, two the matches across. A block is a set
    of matches giving each side one home and one away match, so it runs in chains
    (A hosts B, B hosts C, ...) and splits into its two matchdays by taking alternate
    links, which needs every chain to close after an even number of links. Across pairs
    the chains alternate between two pots, so they always do; inside a pair, each side's
    four matches are split into two blocks every way there is, until one works."""
    order = list(PAIRINGS)
    rng.shuffle(order)
    for pairing in order:
        blocks = _blocks(rng, matches, pot_of, pairing)
        if blocks is not None:
            rng.shuffle(blocks)
            days = []
            for block in blocks:
                halves = _halves(block)
                rng.shuffle(halves)
                days += halves
            return days
    return None


def _blocks(rng: random.Random, matches: list[tuple[int, int]], pot_of: list[int],
            pairing: tuple[tuple[int, int], ...]) -> list[list[tuple[int, int]]] | None:
    side_of = {p: k for k, pair in enumerate(pairing) for p in pair}
    inside: list[list[tuple[int, int]]] = [[], []]
    across: dict[frozenset, list[tuple[int, int]]] = {}
    for h, a in matches:
        if side_of[pot_of[h]] == side_of[pot_of[a]]:
            inside[side_of[pot_of[h]]].append((h, a))
        else:
            across.setdefault(frozenset((pot_of[h], pot_of[a])), []).append((h, a))
    # Across: pot p of one pair meets both pots of the other over two blocks, each block
    # pairing every pot with one from the other pair.
    (p1, p2), (q1, q2) = pairing
    cross = [across[frozenset((p1, q1))] + across[frozenset((p2, q2))],
             across[frozenset((p1, q2))] + across[frozenset((p2, q1))]]
    first, second = [], []
    for edges in inside:
        split = _two_blocks(rng, edges)
        if split is None:
            return None
        first += split[0]
        second += split[1]
    return [first, second, *cross]


def _two_blocks(rng: random.Random, edges: list[tuple[int, int]]
                ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]] | None:
    """Split matches giving each side two home and two away into two blocks of one each,
    both made of even chains. Seen as host-to-guest links, each side's two home matches
    and two away matches pair up into cycles of choices, and each cycle can be taken one
    of two ways; every combination is tried, in a seeded order."""
    by_host: dict[int, list[int]] = {}
    by_guest: dict[int, list[int]] = {}
    for i, (h, a) in enumerate(edges):
        by_host.setdefault(h, []).append(i)
        by_guest.setdefault(a, []).append(i)
    # Each edge has two neighbours: the host's other home match and the guest's other
    # away match. The edges fall into cycles; alternate edges of a cycle share a block.
    cycles, seen = [], set()
    for start in range(len(edges)):
        if start in seen:
            continue
        cycle, i, via_host = [], start, True
        while i not in seen:
            seen.add(i)
            cycle.append(i)
            h, a = edges[i]
            pair = by_host[h] if via_host else by_guest[a]
            i = pair[0] if pair[1] == i else pair[1]
            via_host = not via_host
        cycles.append(cycle)
    choices = list(range(2 ** len(cycles)))
    rng.shuffle(choices)
    for bits in choices[:4096]:
        one = [edges[i] for k, cycle in enumerate(cycles) for j, i in enumerate(cycle) if (j % 2) == (bits >> k & 1)]
        two = [edges[i] for k, cycle in enumerate(cycles) for j, i in enumerate(cycle) if (j % 2) != (bits >> k & 1)]
        if _even_chains(one) and _even_chains(two):
            return one, two
    return None


def _even_chains(block: list[tuple[int, int]]) -> bool:
    nxt = dict(block)
    seen = set()
    for start in nxt:
        if start in seen:
            continue
        n, t = 0, start
        while t not in seen:
            seen.add(t)
            t = nxt[t]
            n += 1
        if n % 2:
            return False
    return True


def _halves(block: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """A block's two matchdays: alternate links of each chain."""
    nxt = dict(block)
    halves: list[list[tuple[int, int]]] = [[], []]
    seen = set()
    for start in sorted(nxt):
        t, k = start, 0
        while t not in seen:
            seen.add(t)
            halves[k].append((t, nxt[t]))
            t, k = nxt[t], 1 - k
    return halves
