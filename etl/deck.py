"""Build ``data/deck.json`` from the squads, the club table and the ratings.

Three inputs, three owners:

* ``data/squads.json`` -- who was in each squad, read from Wikipedia (etl.squads);
* ``data/clubs.csv`` -- display names, short codes and colours (declared);
* ``data/ratings/<season>.txt`` -- one rating per player-season, a game-design
  judgement written by hand (see SPEC.md "Ratings"). A ``# Club`` line opens
  each club, then one ``Player|rating[|pos]`` line per player: club and player
  are the canonical Wikipedia titles exactly as squads.json has them (a title
  can never contain ``|`` or ``#``, which is why those are the separators), and
  ``pos`` optionally corrects the position Wikipedia gave.

The build refuses, rather than warns, when a rating names a player who is not
in that squad: that is either a typo or a player who was not there, and both
would put a card in the deck that the source does not support.

A club-season enters the deck only if its rated players can field a legal XI
in at least one formation, so the opposition never has to invent a player.

Run: ``uv run python -m etl.deck`` (``--check`` exits 1 if deck.json is stale).
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from game.colours import palette
from game.crests import crest_key
from game.formations import FORMATIONS
from game.nations import nation

ROOT = Path(__file__).resolve().parent.parent
SQUADS = ROOT / "data" / "squads.json"
CLUBS = ROOT / "data" / "clubs.csv"
RATINGS = ROOT / "data" / "ratings"
OUT = ROOT / "data" / "deck.json"

MIN_RATING, MAX_RATING = 50, 99
POSITIONS = ("GK", "DF", "MF", "FW")


class BuildError(Exception):
    pass


def season_label(start: int) -> str:
    return f"{start}–{str(start + 1)[-2:]}" if start != 1999 else "1999–2000"


def display_name(title: str) -> str:
    """'Luis García (footballer, born 1978)' -> 'Luis García'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def parse_ratings(text: str, name: str) -> tuple[dict[str, dict[str, tuple[int, str | None]]], list[str]]:
    """Read one season's ratings file. Returns (club -> player -> (rating, pos), errors)."""
    out: dict[str, dict[str, tuple[int, str | None]]] = {}
    errors, club = [], None
    for n, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        where = f"{name}:{n}"
        if not line or line.startswith("//"):
            continue
        if line.startswith("#"):
            club = line[1:].strip()
            out.setdefault(club, {})
            continue
        if club is None:
            errors.append(f"{where}: a player before any '# Club' header")
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) not in (2, 3):
            errors.append(f"{where}: expected 'Player|rating[|pos]', got {line!r}")
            continue
        player, rating_s, pos = parts[0], parts[1], (parts[2] if len(parts) == 3 else "") or None
        if not rating_s.isdigit():
            errors.append(f"{where}: rating {rating_s!r} is not an integer")
            continue
        rating = int(rating_s)
        if not MIN_RATING <= rating <= MAX_RATING:
            errors.append(f"{where}: rating {rating} outside {MIN_RATING}-{MAX_RATING}")
        if pos and pos not in POSITIONS:
            errors.append(f"{where}: position {pos!r} is not one of {POSITIONS}")
        if player in out[club]:
            errors.append(f"{where}: {player} rated twice")
        out[club][player] = (rating, pos)
    return out, errors


def load_ratings() -> dict[tuple[int, str], dict[str, tuple[int, str | None]]]:
    out: dict[tuple[int, str], dict[str, tuple[int, str | None]]] = {}
    errors = []
    for path in sorted(RATINGS.glob("*.txt")):
        clubs, errs = parse_ratings(path.read_text(encoding="utf-8"), path.name)
        errors += errs
        for club, players in clubs.items():
            out[(int(path.stem), club)] = players
    if errors:
        raise BuildError("\n".join(errors))
    return out


def fields_xi(counts: dict[str, int]) -> bool:
    """Can players in these position counts fill some formation exactly?"""
    return any(all(counts.get(p, 0) >= n for p, n in f.lines.items()) for f in FORMATIONS.values())


def build() -> dict:
    squads = json.loads(SQUADS.read_text())["squads"]
    with CLUBS.open(newline="", encoding="utf-8") as f:
        clubs = {row["title"]: row for row in csv.DictReader(f)}
    ratings = load_ratings()

    errors, out, skipped = [], [], []
    known = {(s["season"], s["club"]) for s in squads}
    for key in ratings:
        if key not in known:
            errors.append(f"ratings for {key[1]} {season_label(key[0])}: no such club-season in squads.json")

    for squad in squads:
        key = (squad["season"], squad["club"])
        rated = ratings.get(key, {})
        club = clubs.get(squad["club"])
        if club is None:
            errors.append(f"{squad['club']}: missing from clubs.csv")
            continue
        by_title = {p["title"]: p for p in squad["players"]}
        for title in rated:
            if title not in by_title:
                errors.append(f"{season_label(key[0])} {squad['club']}: {title!r} is not in the squad")
        players = []
        for title, (rating, pos) in rated.items():
            p = by_title.get(title)
            if p is None:
                continue
            players.append({
                "id": p["id"],
                "name": display_name(title),
                "title": title,
                "pos": pos or p["pos"],
                "nation": nation(p["nation"]),
                "rating": rating,
            })
        players.sort(key=lambda p: (POSITIONS.index(p["pos"]), -p["rating"], p["name"]))
        counts = {pos: sum(1 for p in players if p["pos"] == pos) for pos in POSITIONS}
        if not fields_xi(counts):
            if rated:
                skipped.append(f"{season_label(key[0])} {club['name']}: {counts} cannot field an XI")
            continue
        out.append({
            "key": f"{squad['season']}-{club['short']}",
            "season": squad["season"],
            "label": season_label(squad["season"]),
            "club": squad["club"],
            "name": club["name"],
            "short": club["short"],
            "primary": club["primary"],
            "secondary": club["secondary"],
            "crest": crest_key(club["short"], squad["season"]),
            **palette(club["primary"], club["secondary"]),
            "players": players,
        })
    if errors:
        raise BuildError("\n".join(errors))
    out.sort(key=lambda s: (s["season"], s["name"]))
    return {"version": 1, "club_seasons": out, "skipped": skipped}


def serialise(deck: dict) -> str:
    return json.dumps(deck, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main() -> None:
    try:
        deck = build()
    except BuildError as e:
        print(f"deck build refused:\n{e}", file=sys.stderr)
        sys.exit(2)
    text = serialise(deck)
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("data/deck.json is stale: run `uv run python -m etl.deck`", file=sys.stderr)
            sys.exit(1)
        print("data/deck.json is current")
        return
    OUT.write_text(text)
    cards = sum(len(s["players"]) for s in deck["club_seasons"])
    print(f"wrote data/deck.json: {len(deck['club_seasons'])} club-seasons, {cards} cards")
    for line in deck["skipped"]:
        print("  skipped " + line)


if __name__ == "__main__":
    main()
