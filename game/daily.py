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
- **The bench (C42).** A day made with one is drafted fourteen picks deep, with a plan,
  and played by engine 2 (tiredness and substitutes), the opponent bringing on its own
  bench; its goal is measured the same way, the calibration drafter taking the best
  player for its bench too and using the automatic plan. Days made before keep eleven
  picks and engine 1, and play exactly as they did.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from game import match
from game.deck import ClubSeason, Deck
from game.draft import Change, IllegalMove, Pick, Reroll, Session, replay, why_not
from game.formations import FORMATIONS
from game.tournament import Side, auto_plan, best_xi, club_side, play_match

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
    bench: bool = False      # drafted with a bench and played by engine 2 (C42)
    edition: int = 0         # 0 as first made; n once an admin has made the day again n times (C55)

    @property
    def engine(self) -> int:
        return 2 if self.bench else 1


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


def draft(deck: Deck, ch: Challenge, moves: list, plan: tuple[Change, ...] | None = None,
          sheet: tuple[int, ...] | None = None) -> Session:
    """The day's draft so far. Rerolls are refused: everyone gets the same squads. A
    finished bench day may carry a team sheet (C44, for the daily C55)."""
    if any(isinstance(m, Reroll) for m in moves):
        raise IllegalMove("there are no rerolls in the daily challenge")
    return replay(deck, ch.seed, ch.formation, moves, ch.bench, plan, sheet)


def best_pick_draft(deck: Deck, seed: int, formation: str, bench: bool = False) -> Session:
    """The calibration drafter: the best-rated player it can take, every deal (for its
    bench too, in a day with one)."""
    moves: list = []
    s = replay(deck, seed, formation, moves, bench)
    while not s.complete:
        moves.append(Pick(max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                              key=lambda i: s.deal.cards[i].rating)))
        s = replay(deck, seed, formation, moves, bench)
    return s


def side_of(s: Session) -> Side:
    """A finished daily draft as the side that plays: the eleven where its sheet puts them
    (without one, where Side would have placed the first eleven picks), its bench and plan."""
    subs = s.subs()
    return Side("YOU", "Your XI", "YOU", s.formation, s.xi, you=True,
                bench=s.bench, plan=auto_plan(s.bench) if subs is None else subs)


def auto_changes(bench) -> tuple[Change, ...]:
    """The automatic plan as plan lines, for storing the plan a match was played with."""
    return tuple(Change(x.on, x.minute, x.when) for x in auto_plan(bench))


def play(league: match.League, match_seed: int, you: Side, opponent: ClubSeason, engine: int = 1) -> match.Result:
    """Ninety minutes, neutral ground, your eleven at "home" on the card."""
    return play_match(random.Random(match_seed), you, club_side(opponent), league, engine, neutral=True)


def success_rate(league: match.League, you: Side, opponent: ClubSeason, kind: str, target: int,
                 seed: int, runs: int = CALIBRATION_RUNS, engine: int = 1) -> float:
    hits = 0
    for i in range(runs):
        r = play(league, hash_seed(f"{seed}:cal:{i}"), you, opponent, engine)
        hits += met(kind, target, r.home_goals, r.away_goals)
    return hits / runs


def hash_seed(text: str) -> int:
    return random.Random(text).randrange(1, 2**31 - 1)


def make_challenge(deck: Deck, league: match.League, day: str, seed: int, bench: bool = False) -> Challenge:
    """The day's challenge: its formation, opponent and goal, measured into the band.

    The four kinds are tried in a shuffled order, so the days vary; a kind that can't
    be made to fit (no opponent puts it in the band) gives way to the next. The two
    harder kinds may face any side in the deck, the two plainer ones only the strongest."""
    rng = random.Random(f"{seed}:challenge")
    formation = rng.choice(sorted(FORMATIONS))
    you = side_of(best_pick_draft(deck, seed, formation, bench))
    engine = 2 if bench else 1
    strongest = sorted(deck.club_seasons, key=lambda cs: -sum(c.rating for c in best_xi(cs)[1]))
    pools = {"win": strongest[:OPPONENT_POOL], "score": strongest[:OPPONENT_POOL],
             "win_by": strongest, "clean_sheet": strongest}
    lo, hi = SUCCESS_BAND
    best = None
    for kind in rng.sample(KINDS, len(KINDS)):
        target = TARGETS[kind]
        for _ in range(MAX_CANDIDATES // len(KINDS)):
            opponent = rng.choice(pools[kind])
            p = success_rate(league, you, opponent, kind, target, seed, engine=engine)
            gap = 0.0 if lo <= p <= hi else min(abs(p - lo), abs(p - hi))
            if best is None or gap < best[0]:
                best = (gap, Challenge(day, seed, formation, opponent.key, kind, target, round(p, 3), bench))
            if gap == 0.0:
                return best[1]
    return best[1]
