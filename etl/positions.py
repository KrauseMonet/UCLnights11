"""Measured positions, 2013-14 onwards: ``data/positions/measured.json`` (C35).

For every player a club-season's squad lists, how many times he STARTED in each
position for that club that season, from Transfermarkt's line-ups as published by the
transfermarkt-datasets project (CC0, https://github.com/dcaribou/transfermarkt-datasets).
Each starter in a Transfermarkt line-up carries the position he played in that match;
substitutes carry no match position (on the bench he keeps one label all season), so
only starts count. Its line-ups begin with 2013-14; earlier seasons are declared by hand
(data/positions/<season>.txt).

A player is linked by his Wikidata id's Transfermarkt id (P2446), never by name. A
club-season's Transfermarkt club is the one its squad's players started most for that
season; the share is recorded so a wrong mapping would show.

The file holds raw start counts for every listed player with a Transfermarkt id, rated or
not, so a rating added later needs no re-fetch. Turning counts into a player's positions
(most-started first, at most four) is etl.deck's job.

Run: ``uv run python -m etl.positions`` (downloads ~130 MB into data/transfermarkt/,
gitignored, on the first run; Wikidata answers are cached under data/wiki/).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from etl.wiki import CACHE, USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
SQUADS = ROOT / "data" / "squads.json"
OUT = ROOT / "data" / "positions" / "measured.json"
DOWNLOADS = ROOT / "data" / "transfermarkt"
DATASET = "https://github.com/dcaribou/transfermarkt-datasets"
BASE = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/"
FILES = ("games.csv.gz", "game_lineups.csv.gz")
MEASURED_FROM = 2013          # the first season its line-ups cover

# Transfermarkt's match positions -> ours. A second striker is a striker (the user's
# choice, 2026-10-11); a sweeper is a centre-back. "Attack", "Midfield", "Defender" and
# the like name only a line, so they cannot give a position and are counted as dropped.
TM_POSITION = {
    "Goalkeeper": "GK", "Right-Back": "RB", "Centre-Back": "CB", "Sweeper": "CB", "Left-Back": "LB",
    "Defensive Midfield": "DM", "Central Midfield": "CM", "Attacking Midfield": "AM",
    "Right Midfield": "RM", "Left Midfield": "LM", "Right Winger": "RW",
    "Centre-Forward": "ST", "Second Striker": "ST", "Left Winger": "LW",
}


def download(files: tuple[str, ...] = FILES) -> dict[str, str]:
    """The dataset's files, fetched once; returns their SHA-256s."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in files:
        path = DOWNLOADS / name
        if not path.exists():
            print(f"downloading {name} ...", file=sys.stderr)
            req = urllib.request.Request(BASE + name, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=600) as resp, path.with_suffix(".part").open("wb") as f:
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
            path.with_suffix(".part").rename(path)
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _wikidata(params: dict) -> dict:
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 7:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 10))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 7:
                raise
            time.sleep(5)
    raise AssertionError("unreachable")


def transfermarkt_ids(qids: list[str]) -> dict[str, str | None]:
    """Each person's Transfermarkt player id (Wikidata P2446), cached per batch of 50."""
    out: dict[str, str | None] = {}
    unique = sorted(set(qids))
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        path = CACHE / "wikidata" / (hashlib.sha1("|".join(batch).encode()).hexdigest()[:16] + ".json")
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = _wikidata({"action": "wbgetentities", "ids": "|".join(batch), "props": "claims"})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            time.sleep(1)
        for q, e in data["entities"].items():
            ids = [c["mainsnak"]["datavalue"]["value"] for c in e.get("claims", {}).get("P2446", [])
                   if "datavalue" in c["mainsnak"]]
            out[q] = ids[0] if len(ids) == 1 else None   # none, or ambiguous: unlinked
    return out


def read_starts() -> tuple[dict, dict[str, str], Counter]:
    """(starts[(tm player, season, tm club)] -> Counter of our positions, club names, dropped)."""
    season_of, names = {}, {}
    with gzip.open(DOWNLOADS / "games.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            season_of[r["game_id"]] = int(r["season"])
            names[r["home_club_id"]] = r["home_club_name"]
            names[r["away_club_id"]] = r["away_club_name"]
    starts: dict = defaultdict(Counter)
    dropped: Counter = Counter()
    with gzip.open(DOWNLOADS / "game_lineups.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            season = season_of.get(r["game_id"])
            if season is None or season < MEASURED_FROM or r["type"] != "starting_lineup":
                continue
            pos = TM_POSITION.get(r["position"])
            if pos is None:
                dropped[r["position"] or "(blank)"] += 1
                continue
            starts[(r["player_id"], season, r["club_id"])][pos] += 1
    return starts, names, dropped


def build() -> dict:
    squads = [s for s in json.loads(SQUADS.read_text())["squads"] if s["season"] >= MEASURED_FROM]
    files = download()
    tm = transfermarkt_ids([p["id"] for s in squads for p in s["players"]])
    starts, names, dropped = read_starts()
    by_player: dict = defaultdict(dict)        # (tm player, season) -> {club: Counter}
    for (pid, season, club), counts in starts.items():
        by_player[(pid, season)][club] = counts

    out = []
    for s in squads:
        votes: Counter = Counter()
        for p in s["players"]:
            for club, counts in by_player.get((tm.get(p["id"]), s["season"]), {}).items():
                votes[club] += sum(counts.values())
        if not votes:
            raise SystemExit(f"{s['season']} {s['club']}: no line-ups found for any listed player")
        club, n = votes.most_common(1)[0]
        players = {}
        for p in s["players"]:
            pid = tm.get(p["id"])
            counts = by_player.get((pid, s["season"]), {}).get(club, Counter())
            players[p["title"]] = {"id": p["id"], "tm": pid,
                                   "starts": {k: counts[k] for k in sorted(counts, key=lambda k: (-counts[k], k))}}
        out.append({"season": s["season"], "club": s["club"], "tm_club": names.get(club, ""),
                    "tm_club_id": club, "squad_start_share": round(n / sum(votes.values()), 3),
                    "players": players})
    return {
        "source": {"dataset": DATASET, "files": {k: f"sha256:{v}" for k, v in files.items()},
                   "positions": TM_POSITION, "measured_from": MEASURED_FROM,
                   "dropped_labels": dict(dropped.most_common())},
        "club_seasons": out,
    }


def main() -> None:
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    cs = doc["club_seasons"]
    print(f"wrote {OUT.relative_to(ROOT)}: {len(cs)} club-seasons")
    for s in sorted(cs, key=lambda s: s["squad_start_share"])[:8]:
        print(f"  lowest share: {s['season']} {s['club']} -> {s['tm_club']} ({s['squad_start_share']:.0%})")


if __name__ == "__main__":
    main()
