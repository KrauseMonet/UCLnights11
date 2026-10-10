"""Stamp a content hash onto every script and stylesheet a page loads.

    uv run python -m tools.stamp_assets          # rewrite the pages, print what changed
    uv run python -m tools.stamp_assets --check  # exit 1 if any stamp is stale (a deploy gate)

Pages are served must-revalidate, so a deploy reaches everyone at once, while scripts
and styles are cached for a year (vercel.json). With a hand-bumped `?v=11` that pairing
breaks the moment someone forgets to bump: a returning visitor gets the new page and the
old script. The cricket site shipped exactly that (its A106, a home page dying on a
function only the new script had). A hash of the file's own bytes cannot be forgotten:
a changed file is a changed URL.

The stamped pages are committed, as there is no build step; `--check` is what stops a
forgotten run from reaching production.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
# src="/static/x.js" or href="/static/x.css", with or without a ?v= already on it.
REF = re.compile(r'((?:src|href)="/static/([\w./-]+\.(?:js|css)))(?:\?v=[\w]+)?"')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def stamped(page: Path) -> str:
    def swap(m: re.Match) -> str:
        target = STATIC / m.group(2)
        if not target.is_file():
            raise SystemExit(f"{page.name} loads /static/{m.group(2)}, which does not exist")
        return f'{m.group(1)}?v={digest(target)}"'
    return REF.sub(swap, page.read_text(encoding="utf-8"))


def stale_pages() -> list[Path]:
    return [p for p in sorted(STATIC.glob("*.html")) if stamped(p) != p.read_text(encoding="utf-8")]


def main(argv: list[str]) -> int:
    stale = stale_pages()
    if "--check" in argv:
        if stale:
            print("stale asset stamps: " + ", ".join(p.name for p in stale))
            print("run: uv run python -m tools.stamp_assets")
            return 1
        print("asset stamps current")
        return 0
    for p in stale:
        p.write_text(stamped(p), encoding="utf-8")
    print(f"stamped {len(stale)} page(s){': ' + ', '.join(p.name for p in stale) if stale else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
