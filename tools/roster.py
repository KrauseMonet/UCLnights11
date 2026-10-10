"""Print a season's squads compactly, for rating: ``uv run python -m tools.roster 2004``.

Each player is ``title|POS``; titles are exactly what a ratings CSV must use.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    squads = json.loads((ROOT / "data" / "squads.json").read_text())["squads"]
    for season in map(int, sys.argv[1:]):
        for s in squads:
            if s["season"] == season:
                print(f"## {s['club']} ({len(s['players'])})")
                print("; ".join(f"{p['title']}|{p['pos']}" for p in s["players"]))
