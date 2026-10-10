"""Each quarter-finalist's squad, read from its Wikipedia club-season article.

Club-season articles lay a squad out in several ways, and all of them are read:

* squad-list templates -- ``{{Fs player|...}}``, ``{{football squad player}}``,
  ``{{fb si player}}``, ``{{Efs player2}}`` -- with ``nat``/``nb``, ``pos`` and
  ``name``/``p`` parameters;
* a squad or "Squad statistics" wikitable, one row per player, with a flag, a
  position cell (or a "Goalkeepers"/"Defenders" group row above it) and the name.

What counts as squad is decided by the section a player is listed in: reserve,
youth, loan, transfer and award sections are skipped, because a player loaned
out or sold is not in the side that reached the quarter-finals. A player with no
Wikipedia article is skipped too -- everything downstream keys on the article
(and through it the Wikidata id), never on a name string.

Nothing here invents a squad. A club-season with no article, or an article whose
squad cannot be read, is reported and left out of the deck.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from etl import wiki

HEADING = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$", re.M)
BLOCKED = re.compile(
    r"loan|reserve|youth|primavera|transfer|academy|\bb team|\bii\b|left|"
    r"departure|arrival|under-?\d|u-?\d\d|women|juvenil|castilla|filial|"
    r"b squad|second team|signings|released|debut|milestone|award|captain|"
    r"number change|goalscorer|scorer|assist|clean sheet|discipline|penalt",
    re.I,
)
IN_OR_OUT = re.compile(r"^(in|out|ins|outs)$", re.I)
TABLE_SECTION = re.compile(r"squad|player|statistic|appearance|first[- ]team|roster", re.I)
SQUAD_TEMPLATES = re.compile(
    r"(?:fs player|football squad player2?|fb si player|efs player2?|fs2 player)\s*\|", re.I
)

POSITIONS = {
    "GK": "GK",
    **dict.fromkeys(["DF", "D", "CB", "RB", "LB", "RWB", "LWB", "SW", "WB", "FB"], "DF"),
    **dict.fromkeys(["MF", "M", "DM", "CM", "AM", "RM", "LM", "CDM", "CAM", "WM"], "MF"),
    **dict.fromkeys(["FW", "F", "CF", "ST", "LW", "RW", "SS", "W", "FWD"], "FW"),
}
WORDS = {
    "goalkeeper": "GK", "goalkeepers": "GK", "keeper": "GK",
    "defender": "DF", "defenders": "DF", "defence": "DF",
    "midfielder": "MF", "midfielders": "MF", "midfield": "MF",
    "forward": "FW", "forwards": "FW", "striker": "FW", "strikers": "FW",
    "attacker": "FW", "attackers": "FW",
}


@dataclass(frozen=True)
class Listed:
    """One player as an article lists him."""

    link: str            # the article the name links to, as written
    position: str        # GK / DF / MF / FW
    nation: str | None   # a FIFA code or a country name, as the article gives it


def _matching_close(text: str, start: int) -> int:
    """Index just past the ``}}`` that closes the ``{{`` at ``start``."""
    depth = 0
    i = start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return len(text)


def split_params(body: str) -> list[str]:
    """Split on top-level pipes (not inside [[ ]] or {{ }})."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            depth = max(0, depth - 1)   # an unbalanced close must not open a phantom level
            cur.append(two)
            i += 2
            continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(body[i])
        i += 1
    parts.append("".join(cur))
    return parts


def template_params(call: str) -> tuple[str, dict[str, str], list[str]]:
    """(name, named params, positional params) of one ``{{...}}`` call."""
    parts = split_params(call[2:-2])
    named, positional = {}, []
    for p in parts[1:]:
        if "=" in p and not p.lstrip().startswith(("{{", "[[")):
            k, v = p.split("=", 1)
            named[k.strip().lower()] = v.strip()
        else:
            positional.append(p.strip())
    return parts[0].strip().lower(), named, positional


def _content(cell: str) -> str:
    """A table cell without its leading ``style=... |`` attribute block."""
    parts = split_params(cell)
    if len(parts) > 1 and "=" in parts[0] and "[[" not in parts[0] and "{{" not in parts[0]:
        return parts[-1]
    return cell


def name_link(cell: str) -> str | None:
    """The article a name cell links to: ``[[X|y]]`` or ``{{sortname|A|B|X}}``."""
    cell = _content(cell)
    m = re.search(r"\{\{\s*sortname\s*\|", cell, re.I)
    if m:
        call = cell[m.start():_matching_close(cell, m.start())]
        _, named, pos = template_params(call)
        if named.get("nolink"):
            return None
        first = pos[0] if pos else ""
        last = pos[1] if len(pos) > 1 else ""
        link = pos[2] if len(pos) > 2 else ""
        return (link or f"{first} {last}").strip() or None
    for m in re.finditer(r"\[\[([^\]|#]+)", cell):
        target = m.group(1).strip()
        if not re.match(r"(file|image|category):", target, re.I):
            return target
    return None


def _plain(cell: str) -> str:
    """A cell's visible text: attributes, refs and markup stripped."""
    cell = _content(cell)
    cell = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", cell, flags=re.S)
    cell = re.sub(r"\{\{\s*sort\s*\|[^|}]*\|([^}]*)\}\}", r"\1", cell, flags=re.I)
    cell = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\[\[([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\{\{.*?\}\}|<[^>]+>", " ", cell)
    return cell.replace("'", " ").strip()


def position_of(raw: str) -> str | None:
    """GK/DF/MF/FW from a short position cell ("DF", "[[Goalkeeper|GK]]", "GK (R)")."""
    tokens = re.findall(r"[A-Za-z]+", _plain(raw))
    if not 1 <= len(tokens) <= 3:
        return None
    first = tokens[0]
    if first.isupper() and first in POSITIONS:
        return POSITIONS[first]
    return WORDS.get(first.lower()) if len(tokens) == 1 else None


def group_header(raw: str) -> str | None:
    """A position group row: "Goalkeepers", "Defenders"..."""
    words = re.findall(r"[A-Za-z]+", _plain(raw).lower())
    return WORDS.get(words[0]) if len(words) == 1 else None


FLAG = re.compile(
    r"\{\{\s*(?:flagg\s*\|[^|}]*|flag|flagicon|fb|flagu|fbicon|flagdeco)\s*\|\s*([^|}]+)[^}]*\}\}"
    r"|\[\[(?:File|Image):Flag of (?:the )?([^.|\]]+)\.svg[^\]]*\]\]",
    re.I,
)


def nation_of(cell: str) -> str | None:
    m = FLAG.search(cell)
    if not m:
        return None
    return (m.group(1) or m.group(2)).strip()


def _sections(text: str) -> list[tuple[list[str], str]]:
    """(heading path, body) for every section, the lead included."""
    out, stack, last = [], [], 0
    for m in HEADING.finditer(text):
        out.append(([h for _, h in stack], text[last:m.start()]))
        level = len(m.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, m.group(2)))
        last = m.end()
    out.append(([h for _, h in stack], text[last:]))
    return out


def _from_templates(body: str) -> list[Listed]:
    out = []
    for m in re.finditer(r"\{\{\s*" + SQUAD_TEMPLATES.pattern, body, re.I):
        call = body[m.start():_matching_close(body, m.start())]
        _, named, _ = template_params(call)
        other = named.get("other", "") + " " + named.get("notes", "")
        if re.search(r"\bon loan to\b|\bloaned to\b|^\s*to \[\[", other, re.I):
            continue
        link = name_link(named.get("name") or named.get("p") or "")
        position = position_of(named.get("pos", ""))
        if link and position:
            out.append(Listed(link, position, named.get("nat") or named.get("nb") or None))
    return out


def _from_tables(body: str) -> list[Listed]:
    out = []
    for table in re.finditer(r"\{\|.*?\n\|\}", body, re.S):
        group = None
        for row in re.split(r"\n\|-[^\n]*", table.group(0)):
            cells = [c.strip() for c in re.split(r"\n[|!]|\|\||!!", "\n" + row) if c.strip()]
            if len(cells) == 1 and group_header(cells[0]):
                group = group_header(cells[0])
                continue
            nation = next((nation_of(c) for c in cells if nation_of(c)), None)
            link, link_at = None, -1
            for i, c in enumerate(cells):
                cand = name_link(FLAG.sub("", c))
                if cand:
                    link, link_at = cand, i
                    break
            if not link:
                continue
            position = next(
                (position_of(c) for i, c in enumerate(cells[:8]) if i != link_at and position_of(c)),
                group,
            )
            if position and (nation or group):
                out.append(Listed(link, position, nation))
    return out


def listed_players(text: str) -> list[Listed]:
    """Everyone the article lists as squad, deduplicated on the linked article."""
    seen: dict[str, Listed] = {}
    for path, body in _sections(text):
        if any(BLOCKED.search(h) for h in path) or (path and IN_OR_OUT.match(path[-1])):
            continue
        found = _from_templates(body)
        if any(TABLE_SECTION.search(h) for h in path):
            found += _from_tables(body)
        for p in found:
            seen.setdefault(p.link, p)
    return list(seen.values())


def is_season_article(title: str, label: str) -> bool:
    """A title is this club's SEASON article, not a redirect to the club itself.

    "1996-97 AFC Ajax season" redirects to "AFC Ajax", whose squad section is the
    CURRENT squad -- following it silently put a 2026 Ajax side into 1996-97.
    """
    return title.startswith(label) and title.endswith("season")


def club_season_article(label: str, club: str) -> tuple[str, str] | None:
    """(title, wikitext) of the club-season article, or None if there is none."""
    try:
        found = wiki.wikitext(f"{label} {club} season")
        if is_season_article(found[0], label):
            return found
    except wiki.Missing:
        pass
    short = re.sub(r"\s*\(.*?\)|\b(F\.C\.|FC|CF|S\.K\.|BK|SSC|AFC|S\.L\.)\b", "", club).strip()
    for title in wiki.search(f'intitle:"{label}" intitle:season "{short}"', limit=5):
        if is_season_article(title, label) and short.split()[0] in title:
            found = wiki.wikitext(title)
            if is_season_article(found[0], label):
                return found
    return None

OUT = __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "squads.json"


def main() -> None:
    import json

    from etl.quarterfinalists import OUT as QF, season_label

    seasons = json.loads(QF.read_text())
    raw, gaps = [], []
    for start, clubs in seasons.items():
        for club in clubs:
            found = club_season_article(season_label(int(start)), club)
            players = listed_players(found[1]) if found else []
            if not players:
                gaps.append(f"{season_label(int(start))} {club}" + ("" if found else " (no article)"))
                continue
            raw.append((int(start), club, found[0], players))

    resolved = wiki.resolve([p.link for *_, ps in raw for p in ps])
    out, dropped = [], 0
    for start, club, article, players in raw:
        squad, seen = [], set()
        for p in players:
            hit = resolved.get(p.link)
            if hit is None or hit[1] is None or hit[1] in seen:
                dropped += 1
                continue
            seen.add(hit[1])
            squad.append({"id": hit[1], "title": hit[0], "pos": p.position, "nation": p.nation})
        out.append({"season": start, "club": club, "article": article, "players": squad})

    OUT.write_text(json.dumps({"squads": out, "gaps": gaps}, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} club-seasons, {sum(len(s['players']) for s in out)} players listed, "
          f"{dropped} links dropped (no article or duplicate)")
    print(f"{len(gaps)} gaps:")
    for g in gaps:
        print("  " + g)


if __name__ == "__main__":
    main()
