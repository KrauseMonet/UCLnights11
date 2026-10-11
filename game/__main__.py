"""Command line: ``uv run python -m game --validate`` or ``--play SEED``.

``--validate`` plays random home/away matches between the deck's best elevens
and prints them beside real Champions League regulation-time results
(etl.openfootball). The means are calibrated by construction (BASE_HOME and
BASE_AWAY ARE the real means), so the rows to read are the draw rate, the
result split and the spread -- those depend on K and on how wide the deck's
quality range is, and they are REPORTED, not tuned to match.

``--engine 2`` plays engine 2 (tiredness and substitutes, C39) between club sides with
their benches, and adds the share of goals after half-time (which TIRE is set by) and
extra time's goals (which it is not).
"""

from __future__ import annotations

import argparse
import random
import statistics

from game import match
from game.deck import load_deck
from game.draft import Pick, replay, why_not
from game.tournament import (best_xi, club_side, league_of, leaders, play_match, play_tournament,
                             Side)


def validate(trials: int, engine: int = 1) -> None:
    from etl.openfootball import targets

    deck = load_deck()
    league = league_of(deck)
    xis = [best_xi(cs)[1] for cs in deck.club_seasons]
    clubs = [club_side(cs) for cs in deck.club_seasons]
    rng = random.Random(7)
    home, away, sides, results = [], [], [], []
    for _ in range(trials):
        a, b = rng.sample(range(len(xis)), 2)
        if engine == 1:
            r = match.play(rng, xis[a], xis[b], league)
        else:
            r = play_match(rng, clubs[a], clubs[b], league, engine)
        results.append(r)
        home.append(r.home_goals)
        away.append(r.away_goals)
        sides += r.stats
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
    goals = [g for r in results for g in r.goals]
    first, second = real["halves"]
    print(f"{'2nd half':12}{sum(g.minute > 45 for g in goals) / len(goals):9.3f}{second / (first + second):9.3f}")
    if engine == 2:
        timing_report(deck, league, results, real["extra_time"])
    match_stats_report(sides)


def timing_report(deck, league, results: list[match.Result], real_et: tuple[int, int]) -> None:
    """Engine 2's substitutes, and extra time: thirty minutes played on from level
    regulation matches between club sides."""
    subs = [s for r in results for s in r.subs]
    n_sides = 2 * len(results)
    print(f"\nsubstitutes per side {len(subs) / n_sides:.2f} "
          f"(none {sum(1 for r in results for s in (0, 1) if not any(x.side == s for x in r.subs)) / n_sides:.0%}); "
          f"mean minute {statistics.mean(s.minute for s in subs):.1f}")
    on = {(id(r), s.side, s.on.id) for r in results for s in r.subs}
    by_subs = sum(1 for r in results for g in r.goals if (id(r), g.side, g.scorer.id) in on)
    print(f"goals by substitutes {by_subs / sum(len(r.goals) for r in results):.1%}")
    clubs = [club_side(cs) for cs in deck.club_seasons]
    rng = random.Random(8)
    et = []
    while len(et) < 4000:
        a, b = rng.sample(range(len(clubs)), 2)
        r = play_match(rng, clubs[a], clubs[b], league, 2, neutral=True, extra_time_if_level=True)
        if r.extra_time:
            et.append(sum(1 for g in r.goals if g.minute > 90))
    print(f"extra-time goals per match: engine {statistics.mean(et):.3f}, "
          f"real {real_et[1] / real_et[0]:.3f} ({real_et[0]} matches, too few to set anything by)")


def match_stats_report(sides: list[match.SideStats]) -> None:
    """What the declared statistics constants produce, per side per match. There is no
    real column: these have no open source to be checked against (C26)."""
    def row(name, xs, fmt="{:.2f}"):
        print(f"{name:14}" + "".join(f"{fmt.format(v):>9}" for v in
              (statistics.mean(xs), statistics.pstdev(xs), min(xs), max(xs))))
    print(f"\nmatch statistics, per side ({len(sides)} sides); declared, no real column")
    print(f"{'':14}{'mean':>9}{'sd':>9}{'min':>9}{'max':>9}")
    row("shots", [s.shots for s in sides])
    row("on target", [s.on_target for s in sides])
    row("possession", [s.possession for s in sides])
    row("passes", [s.passes for s in sides], "{:.0f}")
    row("completed", [s.completed for s in sides], "{:.0f}")
    row("pass accuracy", [s.completed / s.passes for s in sides if s.passes])
    row("saves", [s.saves for s in sides])
    goals = sum(p.on_target for s in sides for p in s.players if p.card.pos == "GK")
    print(f"goalkeepers' shots on target: {goals}")


def play(seed: int) -> None:
    """Draft automatically (best takeable card each deal) and play a tournament, in the
    league-phase format every new draft plays (C50), on engine 1 without a bench."""
    deck = load_deck()
    moves: list[Pick] = []
    s = replay(deck, seed, "433", moves)
    while not s.complete:
        best = max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                   key=lambda i: s.deal.cards[i].rating)
        moves.append(Pick(best))
        s = replay(deck, seed, "433", moves)
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    t = play_tournament(deck, league_of(deck), seed, you, fmt="league")
    for c in s.picks:
        print(f"  {c.pos} {c.name:28} {c.rating} ({c.club_name} {c.label})")
    place = next(i for i, r in enumerate(t.table, start=1) if r.side is you)
    print(f"league phase: {place} of {len(t.table)}; reached: {t.reached(you)}; champion: {t.champion.name}")
    for card, side, n in leaders(t)[:5]:
        print(f"  {n} {card.name} ({side.short})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--play", type=int)
    ap.add_argument("--engine", type=int, default=1, choices=match.ENGINES)
    args = ap.parse_args()
    if args.validate:
        validate(args.trials, args.engine)
    elif args.play is not None:
        play(args.play)
    else:
        ap.print_help()
