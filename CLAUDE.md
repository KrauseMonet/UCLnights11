# Working notes

Read `SPEC.md` first. This file tracks state, commands, and decisions.

The site is **UCLnights11** (the repository folder keeps the working name, Campeones).
It is a sibling of IPLegends (cricket) and borrows its habits: a figure is
measured before it is stated, a rule that lives in code has a test that has been
seen to fail, and nothing in the deck is invented.

## Environment

Python 3.11 via `uv`. No database: the deck is a committed JSON file built from
committed inputs, and the site keeps no state.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync
uv run python -m etl.quarterfinalists   # 256 quarter-finalists -> data/quarterfinalists.json
uv run python -m etl.squads             # squads from Wikipedia  -> data/squads.json
uv run python -m etl.deck               # squads + clubs + ratings -> data/deck.json
uv run python -m etl.deck --check       # exit 1 if deck.json is stale (a deploy gate)
uv run python -m etl.openfootball       # real results, the engine's yardstick
uv run python -m tools.roster 2004      # print a season's squads, for rating
uv run python -m game --validate        # engine vs real Champions League results
uv run python -m game --play 42         # an automatic draft and tournament
uv run python -m tools.fetch_crests     # crests from Wikipedia/Commons -> assets/crests
uv run python -m tools.build_crests     # -> web/static/crests/*.webp (needs Pillow)
uv run uvicorn web.app:app --port 8030  # the site
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q
```

**Gates before any deploy:** `etl.deck --check`, `tools.build_crests --check` and
`tools.build_brand --check` (all exit 1 when stale), the test suite, and bump `?v=N` in every
page when a stylesheet or script changes. The og:image addresses in every page name the
production origin (`https://uclnights11.vercel.app`); change them when the custom domain lands.

**This project is fully separate from IPLegends**, at the user's request: no file, config or
memory of it lives inside `~/IPLegends`. The fonts were copied out of it once (OFL).

Wikipedia responses are cached in `data/wiki/` (gitignored); delete it to re-fetch.
The fetcher sends a descriptive User-Agent and pauses between requests, as
Wikipedia asks.

## Hard rules

- **A player is a Wikidata id, never a name string.**
- **A squad comes from the source.** Never add a player to a squad, and never rate
  a player the squad does not list, however sure you are he was there. `etl.deck`
  refuses the build; do not loosen it. Every error it has caught was a name
  written from memory (see C6).
- **Ratings are judgement and say so.** Do not describe them as derived.
- **Never fabricate a value.** An unknown nationality is blank, not a guess.
- **When falsifying a test, back up the files and restore from the backups, never
  from git, and run with `PYTHONDONTWRITEBYTECODE=1`.** Both traps cost real work
  in IPLegends (A124, A130).
- No LLM or AI API call anywhere in the running site.

## Deck shape (measured)

| | |
|---|---|
| Seasons | **32** (1994–95 to 2025–26) |
| Quarter-finalist club-seasons | **256** |
| Squads read | **244** (12 gaps, SPEC §1) |
| In the deck | **243** club-seasons, **4,654** rated players |
| Players listed across all squads | 7,517 |
| Distinct clubs | 48 |

## Engine vs real results (20,000 simulated, 1,962 real)

| | engine | real |
|---|---|---|
| home goals | 1.788 | 1.719 |
| away goals | 1.365 | 1.327 |
| total-goals SD | 1.784 | 1.783 |
| home win | 0.473 | 0.477 |
| draw | 0.216 | 0.204 |
| away win | 0.311 | 0.319 |

Means run ~0.05 high because the strength term scatters lambda (Jensen): BASE is
the mean at zero edge, and exp() of a spread edge averages above 1. Recorded, not
tuned.

## Decisions log

| # | Decision |
|---|---|
| C1 | **Scope is every Champions League quarter-finalist from 1994–95 to 2025–26.** 1992–93 and 1993–94 had no quarter-final round. The user chose quarter-finalists, so the deck is a few hundred meaningful sides rather than every squad in every group. Measured: 32 seasons x 8 = 256, every season yielded exactly eight (asserted, not assumed). |
| C2 | **Ratings are written by Claude, at the user's direction, as declared game design.** The open data does not support derived ratings: Cricsheet has no football equivalent; StatsBomb's open data holds only a handful of Champions League matches; FBref lost its advanced data in January 2026 and forbids scraping. The user authorised Claude's judgement instead and chose to fix unreliable ratings later rather than pilot first. |
| C3 | **Squads from Wikipedia, at the user's direction; Wikidata membership was measured and rejected.** Wikidata's `member of sports team` records only the YEAR a player joined or left, so Liverpool 2004–05 came back with Reina and Crouch (both 2005 arrivals) and players from 1909. Wikipedia's club-season articles list the actual squad. |
| C4 | **Three squad layouts are read, and a redirect to the club article is rejected.** "1996–97 AFC Ajax season" does not exist and redirects to "AFC Ajax", whose squad section is the CURRENT squad: the first build silently gave 1996–97 Ajax Marc-André ter Stegen and Julian Brandt. `is_season_article` now refuses any resolved title that is not a season article, and a test pins it. |
| C5 | **Removing a flag template left a stray `}}` that broke pipe-splitting, and hid Roy Keane from three Manchester United squads.** A row with a second link after the name (Keane's captaincy) split on the wrong pipe. Fixed twice: the flag pattern now consumes the whole template, and the splitter never lets an unbalanced close open a phantom level. The fix recovered 125 players hidden the same way. **The rule is protected twice, so breaking either fix alone leaves the test green; breaking both fails it** — verified, and recorded so the redundancy is not mistaken for dead code. |
| C6 | **Every rating the build refused was a name written from memory, and the refusal is the reason ratings can be trusted at all.** Caught: "Alessandro" Tacchinardi (it is Alessio); Paul Lambert in Dortmund 1997–98 (not in the listed squad); a whole Dynamo Kyiv 1997–98 block (no article exists, so no source supports it); Raúl Bravo in Real Madrid 2002–03; Nacho Monreal in Málaga 2012–13 (left in January); a stray Tello line rated 0. Also caught, a parser gap rather than a memory error: Manchester City 2021–22's list lacks Ederson and Gündoğan, so they are unrated rather than added by hand. |
| C7 | **The deal-time guarantee and the one-person rule could not be tested on the real deck, because they almost never have to act there.** Both first tests passed with their rule deleted. The guarantee is now tested on a two-squad deck where a goalkeepers-only squad must be redrawn; the person rule on two cards of one real man. Same lesson as IPLegends A133/A136: a rule tested where it never has to act is not tested. |
| C8 | **The match engine is Poisson with line-weighted attack and defence, calibrated to real Champions League scoring and validated against it.** The base rates ARE the real home/away means, so calibration and strength cannot drift into each other; draw rate and spread are reported, not tuned (SPEC §6). |
| C9 | **The opposition is 31 different clubs, one season each.** Drawing club-seasons uniformly put six Real Madrids in one tournament (seen in the browser); a real tournament never holds a club twice. Drawn uniformly over club-seasons and skipping a club already drawn, so the big clubs still turn up more often. |
| C10 | **Stateless and seed-based, like IPLegends A62.** The draft is a URL; the tournament is a pure function of seed and eleven. No database until something has to outlive a request. |
| C11 | **No UEFA marks.** "Champions League", the starball and the anthem are UEFA trademarks; the name and design avoid them. (Club crests: see C12.) |
| C12 | **Club crests are used, at the user's direction**, on a non-commercial fan site — the same basis the cricket site uses — and every source file is named in `CREDITS.md`. Each crest is the club article's infobox image, rendered by Wikipedia at 256 px and shrunk to a 160 px WebP (72 files, 608 kB). **Every crest sits on a light medallion**: Tottenham's crest is navy on transparent and Juventus' is a black J, both invisible on the dark page, and a medallion fixes all of them at once rather than one at a time. |
| C13 | **A club-season wears the crest it had THAT season where a dated historical file exists, otherwise the current crest** (`data/crest_eras.csv`, `game.crests`). Sixteen historical crests across Bayern (1979, 1996, 2002, 2017), PSG (1992, 1996, 2002), Inter (1999, 2007, 2014), Arsenal (1996), Napoli (2007), Galatasaray, Marseille, Wolfsburg and Atalanta. **Measured, the rest cannot be done from these sources**: English Wikipedia's non-free policy keeps a club's current crest only, and Commons holds old crests mainly where they are too simple to copyright. A file named "2017–2023" Atlético was checked by eye and turned out to be the classic crest, so it was dropped. Known anachronisms are listed under Known limits. |
| C14 | **The design is the cricket site's system**: the same fonts (Anton, Archivo, JetBrains Mono), the same floodlit navy, gold for brand and selection, mint for live figures, team-tinted bands, mono labels, a fanned three-card hero and a rolling crest strip. Club colours are DERIVED (`game.colours`): `team` is the primary unless it is near-white or near-black, `deep` is that hue darkened for a background, `ink` is lifted until it reads on `deep` at WCAG AA. Choosing the stronger colour outright was tried first and made Manchester United yellow; a test pins both cases. The contrast test was first written against `deck.json` and passed with the contrast loop deleted, so it now calls `palette()` directly for every club. |
| C16 | **The site is named UCLnights11, the user's choice (2026-10-10).** Domains checked by RDAP against each registry, the method validated first on a known-taken and a made-up domain: `uclnights11.com`, `.in` and `.app` were all unregistered, as were `uclnights.*`. "Campeones" itself is taken on all three, which is why it stayed a working name. **The one tension, raised with the user rather than smoothed over:** "UCL" is UEFA's own shorthand for the competition, so this is the one place the site leans on UEFA's branding where C11 otherwise avoids it; no trademark register was searched. The name lives in one place (`SITE_NAME`/`SITE_MARK` in `common.js`) plus the four page titles. |
| C17 | **The logo is the user's own artwork, used exactly as given, at the user's explicit direction after the risk was put to them.** Its emblem is a ball of white stars, which is UEFA's registered "starball" mark; with "UCL" in the name the logo reads as official branding. The user chose "use it exactly as given" over a starball-free emblem and over holding the deploy. `tools.build_brand` cuts it out by colour-to-alpha against its own navy; the first pass kept the whole backdrop, because the navy's red channel is ~1 and a pixel one step darker read as fully opaque, so the per-channel room now has a floor. |
| C18 | **Deployed on Vercel like the cricket site: static pages and assets on the CDN, the API as one Python function in `bom1`** (`vercel.json`, `api/index.py`, `requirements.txt`). The function ships `data/deck.json` only; the archive's list of missing squads moved into the deck so it needs nothing else. No database: nothing outlives a request (C10), so the Neon question was answered "not yet". `tests/test_deploy.py` fails if a page the app serves is not routed, if `.vercelignore` would strip the deck, or if a link-preview image is not an absolute URL — verified by deleting the `/archive` route. Public GitHub repo, the user's choice. |
| C15 | **Four pages: home, draft, tournament, archive.** The archive is new to this site: every club-season with its crest, its star and a drawer holding the full rated squad, plus the list of quarter-finalists Wikipedia cannot supply a squad for, so their absence is explained rather than silent. On the tournament page the groups, bracket and scorers stay hidden until your own run has been watched. |

## Known limits

- `data/squads.json` carries some junk links from squad tables (a link to the
  article "Midfielder", an odd "Thumbnail crab" entry). They are never rated, so
  never draftable, and are left rather than special-cased.
- Positions are Wikipedia's four lines; wingers are forwards or midfielders as the
  article says. `|POS` in a ratings file corrects an obvious one.
- The static assets are cache-busted by hand (`?v=N` in every page). A content-hash
  stamping tool is the next step before deploying.
- **Crests shown out of era** (the current crest for an earlier season, because no dated
  historical file exists): Juventus before 2017 (oval), Manchester City before 2016,
  Chelsea before 2005, Ajax 1991–2025 (the 1928 crest is shown), Tottenham before 2006,
  Atlético 2017–2024, Roma before 2013, Lyon before 2022, Monaco before 2021, Deportivo,
  and minor redesigns elsewhere. Add a row to `data/crest_eras.csv` when a file turns up.
