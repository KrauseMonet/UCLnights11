"""Which eight clubs reached each season's quarter-finals, read from Wikipedia.

The deck is every quarter-finalist since the round existed (1994-95; the two
seasons before it went from groups straight to a final or semi-finals).

Wikipedia keeps the knockout rounds in a separate "knockout stage" (or, from
2024-25, "knockout phase") article for most seasons, and inline in the season
article for the rest. Either way the quarter-final section links the clubs; a
club is recognised by also appearing next to an ``{{fbaicon}}`` somewhere in
the season's articles, which is how Wikipedia marks a club rather than a
stadium, city or player link.

The same ``{{fbaicon|ENG}}`` marks name each club's UEFA association (Monaco is
``FRA``, as UEFA counts it), which the league-phase draw needs: no club meets one of
its own association, and none meets more than two of any one. A club marked with two
different codes anywhere is refused rather than settled by a vote.

Run: ``uv run python -m etl.quarterfinalists`` writes ``data/quarterfinalists.json`` and
``data/associations.json``. Exactly eight clubs per season is asserted, not hoped for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from etl import wiki

FIRST_SEASON = 1994  # 1994-95
LAST_SEASON = 2025   # 2025-26, the last completed season
OUT = Path(__file__).resolve().parent.parent / "data" / "quarterfinalists.json"
ASSOCIATIONS = OUT.parent / "associations.json"

FBAICON_LINK = re.compile(r"\{\{\s*fbaicon\|[^}]*\}\}[\s']*\[\[([^\]|#]+)")
# The same mark with its association code kept: (code, club).
FBAICON_CODE = re.compile(r"\{\{\s*fbaicon\|\s*([A-Z]{3})\s*(?:\|[^}]*)?\}\}[\s']*\[\[([^\]|#]+)")
LINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
HEADING = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$", re.M)


def season_label(start: int) -> str:
    return f"{start}–{str(start + 1)[-2:]}" if start != 1999 else "1999–2000"


def season_title(start: int) -> str:
    return f"{season_label(start)} UEFA Champions League"


def section(text: str, name: str) -> str | None:
    """The body of the first section whose heading is ``name``, or None."""
    heads = list(HEADING.finditer(text))
    for i, m in enumerate(heads):
        if m.group(2).strip().lower() == name.lower():
            level = len(m.group(1))
            end = len(text)
            for later in heads[i + 1:]:
                if len(later.group(1)) <= level:
                    end = later.start()
                    break
            return text[m.end():end]
    return None


def bracket_quarterfinal_lines(text: str) -> str | None:
    """The quarter-final rows of a bracket template, if it marks them."""
    m = re.search(r"<!--\s*Quarter-?finals?\s*-->(.*?)<!--", text, re.S | re.I)
    return m.group(1) if m else None


def season_pages(start: int) -> list[str]:
    title = season_title(start)
    pages = []
    for suffix in (" knockout stage", " knockout phase", ""):
        try:
            pages.append(wiki.wikitext(title + suffix)[1])
        except wiki.Missing:
            continue
    if not pages:
        raise RuntimeError(f"{title}: no article found")
    return pages


def associations(pages: list[str], clubs: set[str]) -> dict[str, str]:
    """Each club's association code, as the season articles mark it. A club marked with
    two codes is an error, and so is a club never marked at all."""
    seen: dict[str, set[str]] = {}
    for text in pages:
        for m in FBAICON_CODE.finditer(text):
            club = m.group(2).strip()
            if club in clubs:
                seen.setdefault(club, set()).add(m.group(1))
    errors = [f"{c}: marked {sorted(codes)}" for c, codes in seen.items() if len(codes) > 1]
    errors += [f"{c}: no association mark" for c in sorted(clubs - set(seen))]
    if errors:
        raise RuntimeError("associations:\n" + "\n".join(errors))
    return {c: next(iter(codes)) for c, codes in sorted(seen.items())}


def quarterfinalists(start: int) -> list[str]:
    title = season_title(start)
    pages = season_pages(start)
    clubs = {m.group(1).strip() for text in pages for m in FBAICON_LINK.finditer(text)}

    for text in pages:
        for body in (section(text, "Quarter-finals"), bracket_quarterfinal_lines(text)):
            if not body or "#lst:" in body or "#section" in body:
                continue
            found: list[str] = []
            for m in LINK.finditer(body):
                target = m.group(1).strip()
                if target in clubs and target not in found:
                    found.append(target)
            if len(found) == 8:
                return found
    raise RuntimeError(f"{title}: could not find exactly eight quarter-finalists")


def main() -> None:
    out, pages = {}, []
    for start in range(FIRST_SEASON, LAST_SEASON + 1):
        qf = quarterfinalists(start)
        out[str(start)] = qf
        pages += season_pages(start)
        print(f"{season_label(start)}: {', '.join(qf)}")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parent.parent)}: {len(out)} seasons, {8 * len(out)} club-seasons")
    assoc = associations(pages, {c for qf in out.values() for c in qf})
    ASSOCIATIONS.write_text(json.dumps(assoc, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {ASSOCIATIONS.relative_to(OUT.parent.parent)}: {len(assoc)} clubs, "
          f"{len(set(assoc.values()))} associations")


if __name__ == "__main__":
    main()
