"""A polite, cached reader for English Wikipedia's API.

Every response is written to ``data/wiki/`` keyed by the requested title, so a
re-run of the pipeline reads from disk and never hits Wikipedia twice for the
same page. The cache is not source (it is gitignored): delete it to re-fetch.

Wikipedia asks API clients for a descriptive User-Agent with contact details
and for requests to be made one at a time. Both are done here.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "Campeones/0.1 (fan game; https://github.com/KrauseMonet) urllib"
CACHE = Path(__file__).resolve().parent.parent / "data" / "wiki"
PAUSE_S = 0.5

_last_call = 0.0


class Missing(Exception):
    """The page does not exist (after following redirects)."""


def _cache_path(kind: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE / kind / f"{digest}.json"


def _get(params: dict) -> dict:
    global _last_call
    wait = PAUSE_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                _last_call = time.monotonic()
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def wikitext(title: str) -> tuple[str, str]:
    """(resolved title, wikitext) for a page, following redirects.

    Raises Missing if the page does not exist. A missing page is cached too, so
    a re-run does not ask again.
    """
    path = _cache_path("wikitext", title)
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = _get({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    if "error" in data:
        if data["error"].get("code") == "missingtitle":
            raise Missing(title)
        raise RuntimeError(f"{title}: {data['error']}")
    return data["parse"]["title"], data["parse"]["wikitext"]


def search(query: str, limit: int = 10) -> list[str]:
    """Titles of the best matches for a full-text search."""
    path = _cache_path("search", f"{query}|{limit}")
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = _get({"action": "query", "list": "search", "srsearch": query, "srlimit": limit})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def resolve(titles: list[str]) -> dict[str, tuple[str, str | None]]:
    """Map each title to (canonical article title, Wikidata id), following redirects.

    A title with no article maps to nothing. Cached per batch of 50, the most
    the API accepts at once.
    """
    out: dict[str, tuple[str, str | None]] = {}
    unique = sorted(set(titles))
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        path = _cache_path("resolve", "\n".join(batch))
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = _get({
                "action": "query", "titles": "|".join(batch), "redirects": 1,
                "prop": "pageprops", "ppprop": "wikibase_item",
            })
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
        q = data.get("query", {})
        step = {n["from"]: n["to"] for n in q.get("normalized", [])}
        redirect = {r["from"]: r["to"] for r in q.get("redirects", [])}
        pages = {p["title"]: p for p in q.get("pages", []) if not p.get("missing")}
        for t in batch:
            final = step.get(t, t)
            final = redirect.get(final, final)
            page = pages.get(final)
            if page is not None:
                out[t] = (final, page.get("pageprops", {}).get("wikibase_item"))
    return out
