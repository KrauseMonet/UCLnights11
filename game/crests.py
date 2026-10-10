"""Which crest a club-season wears: the one it had THAT season where a dated
historical file exists (data/crest_eras.csv), otherwise the club's current crest.

A crest is named by key -- ``BAY`` for the current one, ``BAY-1996`` for the one
worn from 1996-97 -- and served as ``/static/crests/<key>.webp``.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

ERAS = Path(__file__).resolve().parent.parent / "data" / "crest_eras.csv"


@lru_cache(maxsize=1)
def _eras() -> list[tuple[str, int, int]]:
    with ERAS.open(newline="", encoding="utf-8") as f:
        return [(r["short"], int(r["first"]), int(r["last"])) for r in csv.DictReader(f)]


def crest_key(short: str, season: int) -> str:
    """The crest key for a club (by short code) in the season starting ``season``."""
    for s, first, last in _eras():
        if s == short and first <= season <= last:
            return f"{s}-{first}"
    return short
