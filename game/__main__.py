"""Command line: ``uv run python -m game --validate`` or ``--play SEED``.

``--validate`` plays random home/away matches between the deck's best elevens
and prints them beside real Champions League regulation-time results
(etl.openfootball). The means are calibrated by construction (BASE_HOME and
BASE_AWAY ARE the real means), so the rows to read are the draw rate, the
result split and the spread -- those depend on K and on how wide the deck's
quality range is, and they are REPORTED, not tuned to match.
"""

from __future__ import annotations

import argparse
import random
import statistics

from game import match
from game.deck import load_deck
from game.draft import Pick, replay, why_not
from game.tournament import best_xi, league_of, leaders, play_tournament, Side


def validate(trials: int) -> None:
    from etl.openfootball import targets

    deck = load_deck()
    league = league_of(deck)
    xis = [best_xi(cs)[1] for cs in deck.club_seasons]
    rng = random.Random(7)
    home, away = [], []
    for _ in range(trials):
        a, b = rng.sample(range(len(xis)), 2)
        r = match.play(rng, xis[a], xis[b], league)
        home.append(r.home_goals)
        away.append(r.away_goals)
    totals = [h + a for h, a in zip(home, away)]
    sim = {
        "home_goals": statistics.mean(home), "away_goals": statistics.mean(away),
        "total_sd": statistics.pstdev(totals),
        "home_win": sum(h > a for h, a in zip(home, away)) / trials,
        "draw": sum(h == a for h, a in zip(home, away)) / trials,
        "away_win": sum(h < a for h, a in zip(home, away)) / trials,
    }
    real = targets()
    print(f"{trials} simulated matches between {len(xis)} club-seasons' best elevens "
          f"against {real['matches']} real ones")
    print(f"{'':12}{'engine':>9}{'real':>9}")
    for k in ("home_goals", "away_goals", "total_sd", "home_win", "draw", "away_win"):
        print(f"{k:12}{sim[k]:9.3f}{real[k]:9.3f}")


def play(seed: int) -> None:
    """Draft automatically (best takeable card each deal) and play a tournament."""
    deck = load_deck()
    moves: list[Pick] = []
    s = replay(deck, seed, "433", moves)
    while not s.complete:
        best = max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                   key=lambda i: s.deal.cards[i].rating)
        moves.append(Pick(best))
        s = replay(deck, seed, "433", moves)
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    t = play_tournament(deck, league_of(deck), seed, you)
    for c in s.picks:
        print(f"  {c.pos} {c.name:28} {c.rating} ({c.club_name} {c.label})")
    print(f"reached: {t.reached(you)}; champion: {t.champion.name}")
    for card, side, n in leaders(t)[:5]:
        print(f"  {n} {card.name} ({side.short})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--play", type=int)
    args = ap.parse_args()
    if args.validate:
        validate(args.trials)
    elif args.play is not None:
        play(args.play)
    else:
        ap.print_help()
