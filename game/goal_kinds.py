"""How each goal was scored (C61): a header from a corner, a penalty, a left-footed volley.

The engine has already decided who scored, who assisted and when; this only says how, so
it can never change a result, a statistic or anything pinned. Each goal's kind comes from
a random stream of its OWN, named by the match and by that goal (its minute, side, scorer,
assister and the score before it), so a goal keeps its kind whatever happens after it --
which a live match needs (C60), since a change made at a break may rewrite the rest -- and
an old link gains kinds without replaying any differently.

**Measured** (etl.goal_kinds, Transfermarkt's Champions League events, 2012-13 on): how an
assisted goal was made, given the assister's line; whether it was headed, given how it was
made and the scorer's line; an unassisted goal's kind (foot, header, penalty, direct free
kick), given the scorer's line; and which foot, from the scorer's own record where he has
one. **Declared** (``FLAVOUR``, judgement at the user's direction): whether a foot shot was
from long range, a tap-in, a volley or the end of a solo run. Transfermarkt's own tags for
these follow its editors' habits, not the football, so they could not be measured.

Nothing here reads a rating, so a blind draft (C23, C33) learns nothing from a kind.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from game.deck import Card
from game.match import Goal

# Of foot shots, by how the goal was made (None: unassisted), the share given each declared
# flavour; the rest are plain finishes. Declared, not measured (see above).
FLAVOUR: dict[str | None, dict[str, float]] = {
    None:        {"long_range": 0.30, "solo_run": 0.12, "tap_in": 0.15, "volley": 0.05},
    "pass":      {"long_range": 0.14, "solo_run": 0.05, "tap_in": 0.14, "volley": 0.03},
    "cross":     {"tap_in": 0.30, "volley": 0.25},
    "corner":    {"tap_in": 0.30, "volley": 0.30, "long_range": 0.10},
    "free_kick": {"tap_in": 0.25, "volley": 0.30, "long_range": 0.05},
    "header":    {"tap_in": 0.30, "volley": 0.30},
    "rebound":   {"tap_in": 0.60, "volley": 0.10, "long_range": 0.05},
}
DECLARED = frozenset(k for row in FLAVOUR.values() for k in row)


@dataclass(frozen=True)
class Kind:
    finish: str              # "foot", "header", "penalty" or "free_kick" (a direct one)
    made: str | None         # how an assisted goal was made ("pass", "cross", ...); None alone
    foot: str | None = None  # "left" or "right", for a foot shot
    flavour: str | None = None   # a foot shot's declared flavour, or None for a plain finish


def _choose(rng: random.Random, shares: dict[str, float]) -> str:
    keys = sorted(shares)
    x = rng.random() * sum(shares[k] for k in keys)
    for k in keys:
        x -= shares[k]
        if x < 0:
            return k
    return keys[-1]


def match_name(stage: str, label: str, home: Sequence[Card], away: Sequence[Card]) -> str:
    """What names a match for its goals' streams: never its result."""
    return "|".join([stage, label, ",".join(c.id for c in home), ",".join(c.id for c in away)])


def goal_name(match: str, g: Goal, before: tuple[int, int]) -> str:
    return (f"{match}|{g.minute}.{g.side}.{g.scorer.id}.{g.assist.id if g.assist else '-'}"
            f"|{before[0]}-{before[1]}")


def kind_of(model: dict, rng: random.Random, g: Goal) -> Kind:
    line = g.scorer.pos if g.scorer.pos != "GK" else "DF"
    if g.assist is not None:
        made = _choose(rng, model["made_by"][g.assist.pos])
        finish = "header" if rng.random() < model["headed"][made][line] else "foot"
    else:
        made = None
        finish = _choose(rng, model["unassisted"][line])
    if finish != "foot":
        return Kind(finish, made)
    right = model["foot"].get(g.scorer.id, model["right"])
    foot = "right" if rng.random() < right else "left"
    shares = FLAVOUR[made]
    plain = 1 - sum(shares.values())
    flavour = _choose(rng, {**shares, "": plain})
    return Kind("foot", made, foot, flavour or None)


def kinds(model: dict, match: str, goals: Sequence[Goal]) -> list[Kind]:
    """Each goal's kind, in the order given (the match's goals, in minute order)."""
    out, score = [], [0, 0]
    for g in goals:
        rng = random.Random("goalkind|" + goal_name(match, g, (score[0], score[1])))
        out.append(kind_of(model, rng, g))
        score[g.side] += 1
    return out
