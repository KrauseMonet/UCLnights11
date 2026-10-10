# Working notes

Read `SPEC.md` first. This file tracks state, commands, and decisions.

Campeones is a sibling of IPLegends (cricket) and borrows its habits: a figure is
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
uv run uvicorn web.app:app --port 8030  # the site
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q
```

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
| C11 | **No crests, no UEFA marks.** "Champions League", the starball and the anthem are UEFA trademarks; club crests belong to the clubs. The name avoids both; club colours are design data in `data/clubs.csv`. |

## Known limits

- `data/squads.json` carries some junk links from squad tables (a link to the
  article "Midfielder", an odd "Thumbnail crab" entry). They are never rated, so
  never draftable, and are left rather than special-cased.
- Positions are Wikipedia's four lines; wingers are forwards or midfielders as the
  article says. `|POS` in a ratings file corrects an obvious one.
- The static assets are cache-busted by hand (`?v=N` in `index.html`). A stamping
  tool like IPLegends' `tools.stamp_assets` is the next step before deploying.
