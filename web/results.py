"""Saved results and the profile (C31).

A result is saved from a Journey the server built by replaying the tournament, never
from figures a browser sent, and keyed (account, source, natural key) so saving twice
is harmless. The profile reads one account's results and adds them up in Python: an
account holds dozens of results, not millions, and the cricket site found its own
profile fast enough the same way (its A108).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from game.journey import Journey
from web.accounts import Account

SOURCES = ("solo", "room", "daily")
RECENT = 20
BOARD = 8
MIN_APPS_FOR_MARK = 6          # a career mark needs this many matches behind it
FINISH_ORDER = ["Champions", "Runners-up", "Semi-finals", "Quarter-finals", "Round of 16", "Group stage"]


def crest_url(key: str | None) -> str | None:
    return f"/static/crests/{key}.webp" if key else None


def players_json(j: Journey) -> list[dict]:
    return [{"id": p.card.id, "name": p.card.name, "pos": p.card.pos, "short": p.card.short,
             "season": p.card.label, "crest": crest_url(p.card.crest), "rating": p.card.rating,
             "apps": p.apps, "goals": p.goals, "assists": p.assists, "mark": p.mark,
             "clean_sheets": p.clean_sheets, "saves": p.saves} for p in j.players]


def save(conn, account: Account, source: str, key: str, j: Journey, formation: str,
         reached: str | None = None) -> bool:
    """True if this call saved it; False if it was already saved."""
    if source not in SOURCES:
        raise ValueError(source)
    w, d, l = j.record
    reached = reached or j.reached
    row = conn.execute(
        "insert into results (account_id, source, natural_key, formation, reached, champion,"
        " won, drawn, lost, gf, ga, players) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " on conflict (account_id, source, natural_key) do nothing returning result_id",
        (account.account_id, source, key, formation, reached, reached == "Champions",
         w, d, l, j.goals_for, j.goals_against, json.dumps(players_json(j)))).fetchone()
    return row is not None


def is_saved(conn, account: Account, source: str, key: str) -> bool:
    return conn.execute("select 1 from results where account_id = %s and source = %s and natural_key = %s",
                        (account.account_id, source, key)).fetchone() is not None


def streaks(days: list[date], today: date) -> tuple[int, int]:
    """(current, best) runs of consecutive days played. The current run still counts
    until a day is actually MISSED, so it holds through today until today ends (the
    cricket site's A130)."""
    have = sorted(set(days))
    best = run = 0
    prev = None
    for d in have:
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    current = 0
    if have and (today - have[-1]).days <= 1:
        current, d = 1, have[-1]
        s = set(have)
        while d - timedelta(days=1) in s:
            current += 1
            d -= timedelta(days=1)
    return current, best


def profile(conn, account: Account, today: date) -> dict:
    rows = conn.execute(
        "select source, natural_key, formation, reached, champion, won, drawn, lost, gf, ga, players, created_at"
        "  from results where account_id = %s order by created_at desc", (account.account_id,)).fetchall()
    created = conn.execute("select created_at from accounts where account_id = %s", (account.account_id,)).fetchone()[0]
    daily = conn.execute("select day, met from daily_results where account_id = %s", (account.account_id,)).fetchall()

    cups = [r for r in rows if r[0] != "daily"]
    finishes = {f: 0 for f in FINISH_ORDER}
    for r in cups:
        if r[3] in finishes:
            finishes[r[3]] += 1
    best = next((f for f in FINISH_ORDER if finishes[f]), None)

    # Career numbers by person, across every saved result.
    people: dict[str, dict] = {}
    for r in rows:
        for p in r[10]:
            e = people.setdefault(p["id"], {"name": p["name"], "pos": p["pos"], "crest": p["crest"],
                                            "goals": 0, "assists": 0, "apps": 0, "picked": 0, "mark_sum": 0.0, "mark_apps": 0})
            e["goals"] += p["goals"]
            e["assists"] += p["assists"]
            e["apps"] += p["apps"]
            e["picked"] += 1
            if p["mark"] is not None:
                e["mark_sum"] += p["mark"] * p["apps"]
                e["mark_apps"] += p["apps"]
    def board(value, pool=None):
        pool = list(people.values()) if pool is None else pool
        ranked = sorted((e for e in pool if value(e)), key=lambda e: (-value(e), e["name"]))[:BOARD]
        return [{"name": e["name"], "pos": e["pos"], "crest": e["crest"], "value": value(e), "apps": e["apps"]} for e in ranked]
    marked = [e for e in people.values() if e["mark_apps"] >= MIN_APPS_FOR_MARK]

    current, best_streak = streaks([d for d, _ in daily], today)
    totals = defaultdict(int)
    for r in cups:
        totals["matches"] += r[5] + r[6] + r[7]
        totals["won"] += r[5]
        totals["gf"] += r[8]
        totals["ga"] += r[9]
    return {
        "username": account.username, "member_since": created.date().isoformat(),
        "tournaments": len(cups), "titles": finishes["Champions"], "finals": finishes["Champions"] + finishes["Runners-up"],
        "best_finish": best, "finishes": [{"stage": f, "n": n} for f, n in finishes.items()],
        "matches": totals["matches"], "won": totals["won"], "gf": totals["gf"], "ga": totals["ga"],
        "daily": {"played": len(daily), "met": sum(1 for _, m in daily if m), "streak": current, "best_streak": best_streak},
        "boards": {
            "goals": board(lambda e: e["goals"]),
            "assists": board(lambda e: e["assists"]),
            "picked": board(lambda e: e["picked"]),
            "mark": board(lambda e: round(e["mark_sum"] / e["mark_apps"], 2), marked),
        },
        "min_apps_for_mark": MIN_APPS_FOR_MARK,
        "recent": [{"source": r[0], "key": r[1], "formation": r[2], "reached": r[3], "champion": r[4],
                    "record": [r[5], r[6], r[7]], "gf": r[8], "ga": r[9], "at": r[11].isoformat(),
                    "star": max(r[10], key=lambda p: (p["mark"] or 0))["name"] if r[10] else None}
                   for r in rows[:RECENT]],
    }
