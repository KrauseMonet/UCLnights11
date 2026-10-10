"""Real Champions League results (openfootball, CC0) -- the engine's outside yardstick.

The ratings are judgement, so nothing about them can be checked against the
archive. The ENGINE can: given two sides, does it score goals at the rate real
Champions League matches do, with real home advantage and a real draw rate?
These files answer that, and ``game --validate`` prints the comparison.

Only regulation-time results of home/away matches are used: a final is played
at a neutral ground, and a match that went to extra time has no clean ninety-
minute score in the file.

Run: ``uv run python -m etl.openfootball`` (fetches into data/openfootball/ and
prints the targets).
"""

from __future__ import annotations

import json
import re
import statistics
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "openfootball"
RAW = "https://raw.githubusercontent.com/openfootball/champions-league/master/{season}/cl.txt"
SEASONS = [f"{y}-{str(y + 1)[-2:]}" for y in range(2011, 2026)]

MATCH = re.compile(r"^\s*(?:\d{1,2}[:.]\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+)-(\d+)\b(.*)$")


def fetch() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        path = DIR / f"{season}.txt"
        if path.exists():
            continue
        req = urllib.request.Request(RAW.format(season=season), headers={"User-Agent": "Campeones/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            path.write_bytes(resp.read())


def results() -> list[tuple[int, int]]:
    """(home goals, away goals) of every regulation-time home/away match."""
    out = []
    for path in sorted(DIR.glob("*.txt")):
        section = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("▪") or line.startswith("»"):
                section = line.lower()
            if section.rstrip().endswith("final"):   # "Final" or "Finals, Final"
                continue
            m = MATCH.match(line)
            if not m:
                continue
            rest = m.group(5).lower()
            if "a.e.t" in rest or "pen" in rest or "aet" in rest:
                continue
            out.append((int(m.group(3)), int(m.group(4))))
    return out


def targets() -> dict:
    games = results()
    home = [h for h, _ in games]
    away = [a for _, a in games]
    totals = [h + a for h, a in games]
    return {
        "matches": len(games),
        "home_goals": statistics.mean(home),
        "away_goals": statistics.mean(away),
        "total_sd": statistics.pstdev(totals),
        "home_win": sum(h > a for h, a in games) / len(games),
        "draw": sum(h == a for h, a in games) / len(games),
        "away_win": sum(h < a for h, a in games) / len(games),
    }


if __name__ == "__main__":
    fetch()
    print(json.dumps(targets(), indent=1))
