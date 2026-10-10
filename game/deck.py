"""The deck: every rated quarter-finalist squad, loaded once from data/deck.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DECK = Path(__file__).resolve().parent.parent / "data" / "deck.json"


@dataclass(frozen=True, eq=False)
class Card:
    """One player in one club-season. ``id`` is the person (a Wikidata id)."""

    id: str
    name: str
    title: str
    pos: str
    nation: str | None
    rating: int
    season: int
    label: str
    club: str
    club_name: str
    short: str
    key: str


@dataclass(frozen=True, eq=False)
class ClubSeason:
    key: str
    season: int
    label: str
    club: str
    name: str
    short: str
    primary: str
    secondary: str
    cards: tuple[Card, ...]

    @property
    def title(self) -> str:
        return f"{self.name} {self.label}"


@dataclass(frozen=True)
class Deck:
    club_seasons: tuple[ClubSeason, ...]
    by_key: dict[str, ClubSeason]


def build_deck(doc: dict) -> Deck:
    seasons = []
    for s in doc["club_seasons"]:
        cards = tuple(
            Card(
                id=p["id"], name=p["name"], title=p["title"], pos=p["pos"], nation=p["nation"],
                rating=p["rating"], season=s["season"], label=s["label"], club=s["club"],
                club_name=s["name"], short=s["short"], key=s["key"],
            )
            for p in s["players"]
        )
        seasons.append(ClubSeason(
            key=s["key"], season=s["season"], label=s["label"], club=s["club"], name=s["name"],
            short=s["short"], primary=s["primary"], secondary=s["secondary"], cards=cards,
        ))
    return Deck(tuple(seasons), {s.key: s for s in seasons})


@lru_cache(maxsize=1)
def load_deck() -> Deck:
    return build_deck(json.loads(DECK.read_text(encoding="utf-8")))
