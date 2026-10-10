"""The deployment config agrees with the app: a page the app serves but vercel.json does
not route would work locally and 404 in production, which no other test would see."""

import json
import re
from pathlib import Path

from web.app import app

ROOT = Path(__file__).resolve().parent.parent
VERCEL = json.loads((ROOT / "vercel.json").read_text())


def routed(path):
    return any(re.fullmatch(r["src"], path) for r in VERCEL["routes"])


def test_every_page_the_app_serves_is_routed_by_vercel():
    # The site's own pages, registered by web.app._page (FastAPI's /docs and /redoc are not shipped).
    pages = [r.path for r in app.routes if getattr(r, "name", "") == "serve"]
    assert pages, "the app should register its pages"
    missing = [p for p in pages if not routed(p)]
    assert missing == []


def test_the_api_is_routed_to_the_function():
    assert routed("/api/meta") and routed("/api/tournament/1-433-0")


def test_the_deck_is_shipped_with_the_function():
    ignore = (ROOT / ".vercelignore").read_text().splitlines()
    assert "!data/deck.json" in ignore
    assert "data/" not in ignore            # an excluded directory would swallow the negation
    build = next(b for b in VERCEL["builds"] if b["src"] == "api/index.py")
    assert "data/deck.json" in build["config"]["includeFiles"]


def test_link_previews_use_an_absolute_image_url():
    for page in (ROOT / "web" / "static").glob("*.html"):
        text = page.read_text()
        m = re.search(r'property="og:image" content="([^"]+)"', text)
        assert m and m.group(1).startswith("https://"), page.name
        assert "__ORIGIN__" not in text
