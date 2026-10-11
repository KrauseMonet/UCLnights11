"""The daily challenge (C32): the same eleven squads for everyone, one match against a
real side, and a goal to reach in it.

Pure: the web layer supplies the seeds (derived from a secret, so a day can't be worked
out ahead) and stores what is made here.

- **The deal** is a solo draft (game.draft) in the day's formation, from the day's seed,
  with no rerolls, so every player is dealt the same squads in the same order.
- **The match** is ninety minutes on neutral ground against the day's opponent fielding
  its best eleven: no extra time, no penalties. Its seed is not the deal's.
- **The goal** is one of four kinds. Each day's is chosen by MEASURING it: the drafter
  who takes the best player every deal plays it CALIBRATION_RUNS times, and a goal is
  kept only if that drafter reaches it between 30% and 60% of the time. The best-pick
  drafter is a strong one, so a human usually finds the day a little harder than the
  number says; the number is stored with the day.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from game import match
from game.deck import Card, ClubSeason, Deck
from game.draft import IllegalMove, Pick, Reroll, Session, replay, why_not
from game.formations import FORMATIONS
from game.tournament import best_xi

KINDS = ("win", "win_by", "clean_sheet", "score")
TARGETS = {"win": 1, "win_by": 2, "clean_sheet": 0, "score": 3}
CALIBRATION_RUNS = 200
SUCCESS_BAND = (0.30, 0.60)
MAX_CANDIDATES = 40
OPPONENT_POOL = 80          # the strongest club-seasons: a daily opponent is a big night


@dataclass(frozen=True)
class Challenge:
    day: str                 # ISO date
    seed: int                # the deal
    formation: str
    opponent: str            # club-season key
    kind: str
    target: int
    success_rate: float


def met(kind: str, target: int, gf: int, ga: int) -> bool:
    if kind == "win":
        return gf > ga
    if kind == "win_by":
        return gf - ga >= target
    if kind == "clean_sheet":
        return gf > ga and ga == 0
    if kind == "score":
        return gf >= target
    raise ValueError(kind)


def describe(kind: str, target: int) -> str:
    return {"win": "Win the match", "win_by": f"Win by {target} or more",
            "clean_sheet": "Win without conceding", "score": f"Score {target} or more"}[kind]


def draft(deck: Deck, ch: Challenge, moves: list) -> Session:
    """The day's draft so far. Rerolls are refused: everyone gets the same squads."""
    if any(isinstance(m, Reroll) for m in moves):
        raise IllegalMove("there are no rerolls in the daily challenge")
    return replay(deck, ch.seed, ch.formation, moves)


def best_pick_xi(deck: Deck, seed: int, formation: str) -> list[Card]:
    """The calibration drafter: the best-rated player it can take, every deal. Returns the
    eleven placed in its slots, as it plays."""
    moves: list = []
    s = replay(deck, seed, formation, moves)
    while not s.complete:
        moves.append(Pick(max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                              key=lambda i: s.deal.cards[i].rating)))
        s = replay(deck, seed, formation, moves)
    return s.xi


def play(league: match.League, match_seed: int, xi: list[Card], opponent: ClubSeason) -> match.Result:
    """Ninety minutes, neutral ground, your eleven at "home" on the card."""
    _, opp = best_xi(opponent)
    return match.play(random.Random(match_seed), xi, opp, league, neutral=True)


def success_rate(league: match.League, xi: list[Card], opponent: ClubSeason, kind: str, target: int,
                 seed: int, runs: int = CALIBRATION_RUNS) -> float:
    hits = 0
    for i in range(runs):
        r = play(league, hash_seed(f"{seed}:cal:{i}"), xi, opponent)
        hits += met(kind, target, r.home_goals, r.away_goals)
    return hits / runs


def hash_seed(text: str) -> int:
    return random.Random(text).randrange(1, 2**31 - 1)


def make_challenge(deck: Deck, league: match.League, day: str, seed: int) -> Challenge:
    """The day's challenge: its formation, opponent and goal, measured into the band.

    The four kinds are tried in a shuffled order, so the days vary; a kind that can't
    be made to fit (no opponent puts it in the band) gives way to the next. The two
    harder kinds may face any side in the deck, the two plainer ones only the strongest."""
    rng = random.Random(f"{seed}:challenge")
    formation = rng.choice(sorted(FORMATIONS))
    xi = best_pick_xi(deck, seed, formation)
    strongest = sorted(deck.club_seasons, key=lambda cs: -sum(c.rating for c in best_xi(cs)[1]))
    pools = {"win": strongest[:OPPONENT_POOL], "score": strongest[:OPPONENT_POOL],
             "win_by": strongest, "clean_sheet": strongest}
    lo, hi = SUCCESS_BAND
    best = None
    for kind in rng.sample(KINDS, len(KINDS)):
        target = TARGETS[kind]
        for _ in range(MAX_CANDIDATES // len(KINDS)):
            opponent = rng.choice(pools[kind])
            p = success_rate(league, xi, opponent, kind, target, seed)
            gap = 0.0 if lo <= p <= hi else min(abs(p - lo), abs(p - hi))
            if best is None or gap < best[0]:
                best = (gap, Challenge(day, seed, formation, opponent.key, kind, target, round(p, 3)))
            if gap == 0.0:
                return best[1]
    return best[1]
