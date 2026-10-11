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


def test_the_function_ships_what_accounts_need_and_none_of_the_neon_tooling():
    # Vercel installs requirements.txt, not pyproject.toml: without psycopg there the
    # solo game still runs and every friends route dies on import.
    assert any(line.startswith("psycopg") for line in (ROOT / "requirements.txt").read_text().splitlines())
    ignore = (ROOT / ".vercelignore").read_text().splitlines()
    assert {"node_modules/", "package.json", "neon.ts", "migrations/"} <= set(ignore)


def test_local_database_addresses_never_reach_git_or_the_deploy():
    # `neon deploy` writes .env.local; the repo is public.
    assert ".env.*" in (ROOT / ".gitignore").read_text().splitlines()
    assert ".env.*" in (ROOT / ".vercelignore").read_text().splitlines()


def test_every_page_loads_the_scripts_and_styles_it_was_stamped_with():
    # tools.stamp_assets --check, as a test: a page pinned to an old hash would pair new
    # html with an old script, the cricket site's A106.
    from tools.stamp_assets import stale_pages
    assert [p.name for p in stale_pages()] == []


def test_the_service_worker_is_served_from_the_root_and_never_cached():
    sw = next(r for r in VERCEL["routes"] if r["src"] == "/sw.js")
    assert sw["headers"]["cache-control"] == "no-cache"
    assert sw["headers"]["service-worker-allowed"] == "/"
    from fastapi.testclient import TestClient
    r = TestClient(app).get("/sw.js")
    assert r.status_code == 200 and "/api/" in r.text and r.headers["cache-control"] == "no-cache"


def test_every_page_links_the_manifest():
    for page in (ROOT / "web" / "static").glob("*.html"):
        assert 'rel="manifest" href="/static/manifest.webmanifest"' in page.read_text(), page.name
    manifest = json.loads((ROOT / "web" / "static" / "manifest.webmanifest").read_text())
    for icon in manifest["icons"]:
        assert (ROOT / "web" / icon["src"].lstrip("/")).is_file(), icon["src"]


def test_the_footer_links_only_to_pages_that_exist():
    pages = {r.path for r in app.routes if getattr(r, "name", "") == "serve"}
    common = (ROOT / "web" / "static" / "common.js").read_text()
    footer = common[common.index('class="foot-links"'):]
    footer = footer[:footer.index("</nav>")]
    links = re.findall(r'href="(/[a-z]*)"', footer)
    assert links and set(links) <= pages


def top_level_names(path):
    """Names a classic script declares at the top level: they share one global scope with
    every other script on the page, so a second `const` of the same name stops the whole
    script loading."""
    pat = re.compile(r"^(?:const|let|var|function|async function|class)\s+([A-Za-z_$][\w$]*)", re.M)
    return set(pat.findall(path.read_text()))


def test_no_two_scripts_on_a_page_declare_the_same_top_level_name():
    # archive.js and common.js both declared LINES; the archive page threw a SyntaxError
    # on load and drew nothing, in production, with every test green. Every pair of
    # scripts a page loads is checked, not just each against common.js.
    static = ROOT / "web" / "static"
    for page in static.glob("*.html"):
        scripts = re.findall(r'<script src="/static/([\w.-]+\.js)', page.read_text())
        names = [(s, top_level_names(static / s)) for s in scripts]
        for i, (a, na) in enumerate(names):
            for b, nb in names[i + 1:]:
                assert not na & nb, (page.name, a, b, na & nb)


def test_every_page_preloads_both_fonts_it_draws_with():
    """The headline and the reading font are both preloaded, so neither waits for the
    stylesheet to be parsed before it is fetched (C49). Each names a file that exists."""
    fonts = ["/static/fonts/Unbounded.woff2", "/static/fonts/InstrumentSans.woff2"]
    for f in fonts:
        assert (ROOT / "web" / f.lstrip("/")).is_file(), f
    for page in sorted((ROOT / "web" / "static").glob("*.html")):
        html = page.read_text()
        for f in fonts:
            assert f'<link rel="preload" href="{f}" as="font" type="font/woff2" crossorigin>' in html, (page.name, f)
