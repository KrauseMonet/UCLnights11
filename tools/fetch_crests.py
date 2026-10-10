"""Fetch every club's crest from its English Wikipedia article.

The crest is the ``image`` (or ``logo``) parameter of the article's football-club
infobox. Wikipedia renders a thumbnail of it at a fixed width, SVG or not, so
every crest arrives as a PNG of the same size. Each file's description page is
recorded in ``assets/crests/sources.json`` for the credits.

Club crests belong to their clubs. They are used here, at the user's direction,
on a non-commercial fan site, the same basis IPLegends uses for franchise crests;
CREDITS.md says so and names every source.

Run: ``uv run python -m tools.fetch_crests`` then ``uv run python -m tools.build_crests``.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from etl import wiki

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "crests"
WIDTH = 256


def infobox_image(text: str) -> str | None:
    m = re.search(r"\|\s*(?:image|logo|clubcrest|crest)\s*=\s*(?:\[\[)?(?:File:|Image:)?([^|\]\n<{]+?\.(?:svg|png|jpe?g|gif|webp))",
                  text, re.I)
    return m.group(1).strip() if m else None


COMMONS = "https://commons.wikimedia.org/w/api.php"


def _commons(params: dict) -> dict:
    url = COMMONS + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": wiki.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def file_info(name: str, site: str = "en") -> dict:
    params = {"action": "query", "titles": f"File:{name}", "prop": "imageinfo",
              "iiprop": "url|mime", "iiurlwidth": WIDTH}
    data = _commons(params) if site == "commons" else wiki._get(params)
    page = data["query"]["pages"][0]
    if page.get("missing") and "imageinfo" not in page:
        raise LookupError(name)
    return page["imageinfo"][0]


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": wiki.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "data" / "clubs.csv").open(newline="", encoding="utf-8") as f:
        clubs = list(csv.DictReader(f))
    sources_path = OUT / "sources.json"
    sources = json.loads(sources_path.read_text()) if sources_path.exists() else {}
    missing = []
    for club in clubs:
        short, dest = club["short"], OUT / f"{club['short']}.png"
        if dest.exists() and short in sources:
            continue
        title, text = wiki.wikitext(club["title"])
        name = infobox_image(text)
        if not name:
            missing.append(f"{short}: no image in the infobox of {title}")
            continue
        try:
            info = file_info(name)
        except LookupError:
            missing.append(f"{short}: File:{name} not found")
            continue
        download(info.get("thumburl") or info["url"], dest)
        sources[short] = {"club": club["title"], "file": f"File:{name}",
                          "page": info["descriptionurl"]}
        time.sleep(0.4)
        print(f"{short:4} {name}")
    # Season-specific crests, where a dated historical file exists (data/crest_eras.csv).
    with (ROOT / "data" / "crest_eras.csv").open(newline="", encoding="utf-8") as f:
        eras = list(csv.DictReader(f))
    (OUT / "eras").mkdir(exist_ok=True)
    for era in eras:
        key = f"{era['short']}-{era['first']}"
        dest = OUT / "eras" / f"{key}.png"
        if dest.exists() and key in sources:
            continue
        try:
            info = file_info(era["file"], era["site"])
        except LookupError:
            missing.append(f"{key}: File:{era['file']} not found on {era['site']}")
            continue
        download(info.get("thumburl") or info["url"], dest)
        sources[key] = {"club": era["short"], "file": f"File:{era['file']}", "page": info["descriptionurl"]}
        time.sleep(0.4)
        print(f"{key:9} {era['file']}")
    sources_path.write_text(json.dumps(sources, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    if missing:
        print("\nmissing:\n  " + "\n  ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
