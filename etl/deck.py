"""Build ``data/deck.json`` from the squads, the club table and the ratings.

Three inputs, three owners:

* ``data/squads.json`` -- who was in each squad, read from Wikipedia (etl.squads);
* ``data/clubs.csv`` -- display names, short codes and colours (declared);
* ``data/ratings/<season>.txt`` -- one rating per player-season, a game-design
  judgement written by hand (see SPEC.md "Ratings"). A ``# Club`` line opens
  each club, then one ``Player|rating`` line per player: club and player are the
  canonical Wikipedia titles exactly as squads.json has them (a title can never
  contain ``|`` or ``#``, which is why those are the separators);
* positions (C35): ``data/positions/measured.json`` (etl.positions) gives every
  player's starts by position for 2013-14 onwards, and ``data/positions/<season>.txt``
  declares them by hand, in the ratings' layout as ``Player|CB,RB``, for the seasons
  before and for a measured-season player with no starts.

The build refuses, rather than warns, when a rating names a player who is not
in that squad: that is either a typo or a player who was not there, and both
would put a card in the deck that the source does not support. It refuses the same
way when a rated player has no positions, when a declared line names a player who
isn't rated, and when a declared line would override a measured player: measurement
always wins, and a declaration may only fill a gap.

A club-season enters the deck only if its rated players can field a legal XI
in at least one formation, so the opposition never has to invent a player. The
strongest such eleven is worked out here, once, and stored with the squad.

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
from game.positions import LINE, MAX_POSITIONS, POSITIONS as CODES, best_eleven

ROOT = Path(__file__).resolve().parent.parent
SQUADS = ROOT / "data" / "squads.json"
CLUBS = ROOT / "data" / "clubs.csv"
RATINGS = ROOT / "data" / "ratings"
POSITION_FILES = ROOT / "data" / "positions"
MEASURED = POSITION_FILES / "measured.json"
OUT = ROOT / "data" / "deck.json"

MIN_RATING, MAX_RATING = 50, 99
LINES = ("GK", "DF", "MF", "FW")


class BuildError(Exception):
    pass


def season_label(start: int) -> str:
    return f"{start}–{str(start + 1)[-2:]}" if start != 1999 else "1999–2000"


def display_name(title: str) -> str:
    """'Luis García (footballer, born 1978)' -> 'Luis García'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def parse_ratings(text: str, name: str) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Read one season's ratings file. Returns (club -> player -> rating, errors)."""
    out: dict[str, dict[str, int]] = {}
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
        if len(parts) != 2:
            errors.append(f"{where}: expected 'Player|rating', got {line!r}"
                          + (" (positions live in data/positions/)" if len(parts) == 3 else ""))
            continue
        player, rating_s = parts
        if not rating_s.isdigit():
            errors.append(f"{where}: rating {rating_s!r} is not an integer")
            continue
        rating = int(rating_s)
        if not MIN_RATING <= rating <= MAX_RATING:
            errors.append(f"{where}: rating {rating} outside {MIN_RATING}-{MAX_RATING}")
        if player in out[club]:
            errors.append(f"{where}: {player} rated twice")
        out[club][player] = rating
    return out, errors


def load_ratings() -> dict[tuple[int, str], dict[str, int]]:
    out: dict[tuple[int, str], dict[str, int]] = {}
    errors = []
    for path in sorted(RATINGS.glob("*.txt")):
        clubs, errs = parse_ratings(path.read_text(encoding="utf-8"), path.name)
        errors += errs
        for club, players in clubs.items():
            out[(int(path.stem), club)] = players
    if errors:
        raise BuildError("\n".join(errors))
    return out


def parse_positions(text: str, name: str) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """Read one season's declared positions. Returns (club -> player -> positions, errors)."""
    out: dict[str, dict[str, list[str]]] = {}
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
        if len(parts) != 2 or not parts[1]:
            errors.append(f"{where}: expected 'Player|POS,POS', got {line!r}")
            continue
        player, codes = parts[0], [c.strip() for c in parts[1].split(",")]
        bad = [c for c in codes if c not in CODES]
        if bad:
            errors.append(f"{where}: {bad} not among {CODES}")
        if len(set(codes)) != len(codes):
            errors.append(f"{where}: a position listed twice")
        if len(codes) > MAX_POSITIONS:
            errors.append(f"{where}: {len(codes)} positions, at most {MAX_POSITIONS}")
        if player in out[club]:
            errors.append(f"{where}: {player} declared twice")
        out[club][player] = codes
    return out, errors


def measured_positions(starts: dict[str, int]) -> list[str]:
    """Every position started at least once, most-started first (ties in team-sheet
    order), the first MAX_POSITIONS of them."""
    ranked = sorted((p for p, n in starts.items() if n > 0), key=lambda p: (-starts[p], CODES.index(p)))
    return ranked[:MAX_POSITIONS]


def load_positions() -> tuple[int, dict[tuple[int, str], dict[str, dict[str, int]]],
                             dict[tuple[int, str], dict[str, list[str]]]]:
    """(first measured season, measured starts, declared positions), keyed by (season, club)."""
    doc = json.loads(MEASURED.read_text(encoding="utf-8"))
    measured = {(cs["season"], cs["club"]): {t: p["starts"] for t, p in cs["players"].items()}
                for cs in doc["club_seasons"]}
    declared, errors = {}, []
    for path in sorted(POSITION_FILES.glob("*.txt")):
        clubs, errs = parse_positions(path.read_text(encoding="utf-8"), path.name)
        errors += errs
        for club, players in clubs.items():
            declared[(int(path.stem), club)] = players
    if errors:
        raise BuildError("\n".join(errors))
    return doc["source"]["measured_from"], measured, declared


class _Slotted:
    """What best_eleven needs of a player: his rating and positions."""

    def __init__(self, p: dict):
        self.p, self.rating, self.positions = p, p["rating"], p["positions"]


def best_formation(players: list[dict]) -> dict | None:
    """The strongest eleven these players can field in any formation, as
    {"formation": code, "xi": [[person id, slot], ...]} in slot order, or None. Ties go to
    the eleven nearer each man's most-played positions, then to the formation listed
    first."""
    cards = [_Slotted(p) for p in players]
    best = None
    for f in FORMATIONS.values():
        found = best_eleven(f.slots, cards)
        if found is None:
            continue
        total, xi = found
        rank = sum(c.positions.index(slot) for c, slot in xi)
        if best is None or (total, -rank) > best[0]:
            best = ((total, -rank), f.code, xi)
    if best is None:
        return None
    return {"formation": best[1], "xi": [[c.p["id"], slot] for c, slot in best[2]]}


def build() -> dict:
    squads_doc = json.loads(SQUADS.read_text())
    squads = squads_doc["squads"]
    with CLUBS.open(newline="", encoding="utf-8") as f:
        clubs = {row["title"]: row for row in csv.DictReader(f)}
    ratings = load_ratings()
    measured_from, measured, declared = load_positions()

    errors, out, skipped = [], [], []
    known = {(s["season"], s["club"]) for s in squads}
    for key in ratings:
        if key not in known:
            errors.append(f"ratings for {key[1]} {season_label(key[0])}: no such club-season in squads.json")
    for key, players in declared.items():
        for title in players:
            if title not in ratings.get(key, {}):
                errors.append(f"positions for {key[1]} {season_label(key[0])}: {title!r} is not rated")

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
        for title, rating in rated.items():
            p = by_title.get(title)
            if p is None:
                continue
            where = f"{season_label(key[0])} {squad['club']}: {title}"
            starts = measured.get(key, {}).get(title, {}) if squad["season"] >= measured_from else {}
            said = declared.get(key, {}).get(title)
            if starts and said:
                errors.append(f"{where}: declared positions for a player with measured starts")
                continue
            if starts:
                positions, source = measured_positions(starts), "measured"
            elif said:
                positions, source = said, "declared"
            else:
                errors.append(f"{where}: no positions (none measured, none declared)")
                continue
            players.append({
                "id": p["id"],
                "name": display_name(title),
                "title": title,
                "pos": LINE[positions[0]],
                "positions": positions,
                "source": source,
                "nation": nation(p["nation"]),
                "rating": rating,
            })
        players.sort(key=lambda p: (LINES.index(p["pos"]), -p["rating"], p["name"]))
        best = best_formation(players)
        if best is None:
            if rated:
                held = {c: sum(1 for p in players if c in p["positions"]) for c in CODES}
                skipped.append(f"{season_label(key[0])} {club['name']}: {held} cannot field an XI")
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
            "best": best,
            "players": players,
        })
    if errors:
        raise BuildError("\n".join(errors))
    out.sort(key=lambda s: (s["season"], s["name"]))
    # The quarter-finalists Wikipedia supplies no readable squad for, so the archive page
    # can say why they are missing; carried here so the server needs one data file.
    return {"version": 2, "club_seasons": out, "skipped": skipped, "gaps": squads_doc.get("gaps", [])}


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
