"""The deck: every rated quarter-finalist squad, loaded once from data/deck.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DECK = Path(__file__).resolve().parent.parent / "data" / "deck.json"


@dataclass(frozen=True, eq=False)
class Card:
    """One player in one club-season. ``id`` is the person (a Wikidata id).

    ``positions`` are what he can play, most-played first (game.positions); ``source``
    says whether they were measured or declared. ``pos`` is a LINE (GK/DF/MF/FW): his
    natural one, from his first position, until he is placed in an eleven, when it
    becomes the line of his slot and ``slot`` names the slot's position."""

    id: str
    name: str
    title: str
    pos: str
    positions: tuple[str, ...]
    source: str
    nation: str | None
    rating: int
    season: int
    label: str
    club: str
    club_name: str
    short: str
    key: str
    crest: str
    slot: str | None = None


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
    crest: str
    team: str
    deep: str
    ink: str
    cards: tuple[Card, ...]
    best: tuple[str, tuple[tuple[int, str], ...]]   # (formation code, ((card index, slot), ...))

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
                id=p["id"], name=p["name"], title=p["title"], pos=p["pos"],
                positions=tuple(p["positions"]), source=p["source"], nation=p["nation"],
                rating=p["rating"], season=s["season"], label=s["label"], club=s["club"],
                club_name=s["name"], short=s["short"], key=s["key"], crest=s["crest"],
            )
            for p in s["players"]
        )
        index = {c.id: i for i, c in enumerate(cards)}
        best = (s["best"]["formation"], tuple((index[pid], slot) for pid, slot in s["best"]["xi"]))
        seasons.append(ClubSeason(
            key=s["key"], season=s["season"], label=s["label"], club=s["club"], name=s["name"],
            short=s["short"], primary=s["primary"], secondary=s["secondary"], crest=s["crest"],
            team=s["team"], deep=s["deep"], ink=s["ink"], cards=cards, best=best,
        ))
    return Deck(tuple(seasons), {s.key: s for s in seasons})


@lru_cache(maxsize=1)
def load_deck() -> Deck:
    return build_deck(json.loads(DECK.read_text(encoding="utf-8")))
