"""How real Champions League goals were scored: ``data/goal_kinds.json`` (C61).

From the transfermarkt-datasets project's match events (CC0,
https://github.com/dcaribou/transfermarkt-datasets), every Champions League goal it
records (2012-13 on) with its kind (right foot, left foot, header, penalty, direct free
kick) and, for an assisted goal, how it was made (a pass, a cross, a corner, a header
knocked down, a shot parried or blocked, a free kick). The scorer's and assister's line is
the position each played in that match (etl.positions' mapping).

Measured here, as conditional shares the engine's goals are given a kind from (the engine
has already decided who scored, who assisted, and when; game.goal_kinds):

- how an assisted goal was made, given the assister's line;
- whether an assisted goal was headed, given how it was made and the scorer's line;
- an unassisted goal's kind, given the scorer's line;
- each deck player's right-foot share of the goals he scored with a foot, in every
  competition the dataset holds, for a player with at least ``FOOT_MIN`` of them.

**Left out, measured:** own goals (they would move a goal's credit to the other side) and
Transfermarkt's finer tags ("Counter attack goal", "Tap-in", "Long distance kick", "Solo
run", "Deflected shot on goal"): they follow its editors' habits, not the football --
counter-attack goals go from 1 a season in 2012-13 to 63 in 2025-26 -- so they are counted
as foot shots, and the finer flavours are declared in game.goal_kinds instead. A penalty's
"assist" (the man fouled) and a goal whose kind or assist is not recorded are counted as
unassisted and left out respectively, as the note in each table says.

Run: ``uv run python -m etl.goal_kinds`` (downloads game_events, ~45 MB, into the gitignored
data/transfermarkt/ on the first run, beside etl.positions' files).
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from etl import positions
from game.positions import LINE

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "goal_kinds.json"
DOWNLOADS = positions.DOWNLOADS
FILES = ("games.csv.gz", "game_lineups.csv.gz", "game_events.csv.gz")
COMPETITION = "CL"
FOOT_MIN = 5            # foot goals before a player's own right-foot share is used
MADE_MIN = 20           # assisted goals before a way of making one is kept
CELL_MIN = 40           # goals before a (made by, scorer line) cell is used; else the row's

# Transfermarkt's words -> ours.
KIND = {"Right-footed shot": "right", "Left-footed shot": "left", "Header": "header",
        "Penalty": "penalty", "Direct free kick": "free_kick",
        # Its finer tags and rarities are foot shots whose foot it does not say (see above).
        "Counter attack goal": "foot", "Tap-in": "foot", "Long distance kick": "foot",
        "Solo run": "foot", "Deflected shot on goal": "foot", "Chest": "foot",
        "Penalty rebound": "foot", "Direct corner": "free_kick"}
MADE = {"Pass": "pass", "Cross": "cross", "Corner": "corner", "Header": "header",
        "Shot on goal": "rebound", "Free kick": "free_kick", "Goal-kick": "goal_kick",
        "Throw-in": "throw_in"}
FOUL = ("Penalty", "Fouled", "Handball")     # a penalty's or free kick's "assist": who won it
LINES = ("GK", "DF", "MF", "FW")


def parse(description: str) -> tuple[str | None, str | None, bool]:
    """(our kind, how it was made, assisted) from an event's description, e.g.
    ", Header, 1. Tournament Goal Assist: , Cross, 1. Tournament Assist". The kind is None
    for an own goal or one whose kind is not recorded; ``made`` is None when unassisted or
    not recorded, and ``assisted`` says which."""
    fields = [x.strip() for x in description.split(",")]
    kind = KIND.get(fields[1] if len(fields) > 1 else "")   # an own goal is in none of them
    if "Assist:" not in description:
        return kind, None, False
    after = description.split("Assist:", 1)[1].strip()
    if not after or after.startswith("Without"):
        return kind, None, False
    made = [x.strip() for x in after.split(",")]
    word = made[1] if made[0] == "" and len(made) > 1 else made[0]
    if any(word.startswith(w) for w in FOUL):
        return kind, None, False
    return kind, MADE.get(word), True


def read() -> tuple[list[dict], dict[str, Counter]]:
    """(Champions League goals, each with its kind, how it was made and both men's lines;
    every player's foot goals in all competitions, by Transfermarkt id)."""
    games = set()
    with gzip.open(DOWNLOADS / "games.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["competition_id"] == COMPETITION:
                games.add(r["game_id"])
    line_of = {}
    with gzip.open(DOWNLOADS / "game_lineups.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["game_id"] in games:
                pos = positions.TM_POSITION.get(r["position"])
                if pos is not None:
                    line_of[(r["game_id"], r["player_id"])] = LINE[pos]
    goals, feet = [], defaultdict(Counter)
    with gzip.open(DOWNLOADS / "game_events.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["type"] != "Goals":
                continue
            kind, made, assisted = parse(r["description"])
            if kind in ("right", "left"):
                feet[r["player_id"]][kind] += 1
            if r["game_id"] not in games:
                continue
            goals.append({"kind": kind, "made": made, "assisted": assisted,
                          "own": r["description"].lstrip(", ").startswith("Own-goal"),
                          "line": line_of.get((r["game_id"], r["player_id"])),
                          "by": line_of.get((r["game_id"], r["player_assist_id"])) if assisted else None})
    return goals, feet


def shares(c: Counter) -> dict[str, float]:
    n = sum(c.values())
    return {k: round(v / n, 4) for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))}


def build(goals: list[dict], feet: dict[str, Counter], tm_of: dict[str, str | None]) -> dict:
    kinded = [g for g in goals if g["kind"] is not None]
    own = sum(1 for g in goals if g["own"])
    # How a goal was made is measured where it was made often enough (a goal-kick's 7 and a
    # throw-in's 2 are not), so the commentary has nothing it cannot back.
    made_n = Counter(g["made"] for g in kinded if g["assisted"])
    assisted = [g for g in kinded if g["assisted"] and g["made"] is not None
                and made_n[g["made"]] >= MADE_MIN]
    unassisted = [g for g in kinded if not g["assisted"]]

    # How an assisted goal was made, by the assister's line. A goalkeeper's assists are
    # too few to measure apart (a handful of goal-kicks and long balls); his are passes.
    made_by = {}
    for line in LINES[1:]:
        made_by[line] = shares(Counter(g["made"] for g in assisted if g["by"] == line))
    made_by["GK"] = {"pass": 1.0}

    # Whether an assisted goal was headed, by how it was made and the scorer's line.
    headed = {}
    for made in sorted({g["made"] for g in assisted}):
        row = [g for g in assisted if g["made"] == made]
        whole = sum(g["kind"] == "header" for g in row) / len(row)
        cells = {}
        for line in LINES[1:]:
            cell = [g for g in row if g["line"] == line]
            cells[line] = round(sum(g["kind"] == "header" for g in cell) / len(cell), 4) \
                if len(cell) >= CELL_MIN else round(whole, 4)
        headed[made] = {"n": len(row), "all": round(whole, 4), **cells}

    # An unassisted goal's kind, by the scorer's line ("foot" stands for either foot).
    def fold(k: str) -> str:
        return "foot" if k in ("right", "left") else k
    alone = {line: shares(Counter(fold(g["kind"]) for g in unassisted if g["line"] == line))
             for line in LINES[1:]}

    right = sum(c["right"] for c in feet.values())
    left = sum(c["left"] for c in feet.values())
    ch = Counter(g["kind"] for g in kinded if g["kind"] in ("right", "left"))
    foot = {}
    for qid, tm in sorted(tm_of.items()):
        c = feet.get(tm) if tm else None
        if c and c["right"] + c["left"] >= FOOT_MIN:
            foot[qid] = round(c["right"] / (c["right"] + c["left"]), 3)
    return {
        "source": {"dataset": positions.DATASET, "competition": COMPETITION,
                   "goal_events": len(goals), "own_goals": own,
                   "no_kind": sum(1 for g in goals if g["kind"] is None) - own,
                   "kinds": dict(Counter(g["kind"] for g in kinded).most_common()),
                   "assisted_share": round(len([g for g in kinded if g["assisted"]]) / len(kinded), 4),
                   "foot_min": FOOT_MIN, "cell_min": CELL_MIN, "made_min": MADE_MIN,
                   "made_dropped": {k: v for k, v in made_n.items() if k and v < MADE_MIN},
                   "all_competitions_right": round(right / (right + left), 4)},
        "made_by": made_by,
        "headed": headed,
        "unassisted": alone,
        "right": round(ch["right"] / (ch["right"] + ch["left"]), 4),
        "foot": foot,
    }


def main() -> None:
    files = positions.download(FILES)
    goals, feet = read()
    deck = json.loads((ROOT / "data" / "deck.json").read_text())
    people = sorted({p["id"] for s in deck["club_seasons"] for p in s["players"]})
    tm_of = positions.transfermarkt_ids(people)
    doc = build(goals, feet, tm_of)
    doc["source"]["files"] = {k: f"sha256:{v}" for k, v in files.items()}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    s = doc["source"]
    print(f"wrote {OUT.relative_to(ROOT)}: {s['goal_events']} goal events, {s['own_goals']} own goals, "
          f"assisted {s['assisted_share']:.1%}, {len(doc['foot'])} players with a foot share",
          file=sys.stderr)
    print(json.dumps({k: v for k, v in doc.items() if k != "foot"}, indent=1))


if __name__ == "__main__":
    main()
