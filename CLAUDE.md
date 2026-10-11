# Working notes

Read `SPEC.md` first. This file tracks state, commands, and decisions.

The site is **UCLnights11** (the repository folder keeps the working name, Campeones).
It is a sibling of IPLegends (cricket) and borrows its habits: a figure is
measured before it is stated, a rule that lives in code has a test that has been
seen to fail, and nothing in the deck is invented.

## Environment

Python 3.11 via `uv`. The deck is a committed JSON file built from committed inputs and
the solo game keeps no state. **Accounts and rooms live in Neon Postgres** (project
`steep-cake-84438492`, branch `production`): `DATABASE_URL` and `SESSION_SECRET` must be
set, locally in `.env.local` or `.env` (both gitignored; `neon deploy` writes `DATABASE_URL` and `DATABASE_URL_UNPOOLED` to `.env.local`) and in
Vercel's environment. Without them the solo game runs exactly as before and the friends
routes answer 503. Tests start a throwaway Postgres from the `pgserver` dev dependency,
so the suite needs no database of yours.

**The Mac's DNS cannot resolve Neon hostnames** (the cricket site's A139, hit again here):
look the direct endpoint up through Google and pass the address, which keeps the hostname
for TLS: `dig +short @8.8.8.8 <host>`, then `PGHOSTADDR=<ip> uv run python -m tools.migrate`.
Production's endpoint is in `aws-ap-southeast-1`; the function runs in `bom1`. Vercel's
own DNS is unaffected. Migrations 001–004 are applied to Neon `production` (003 and 004 on 2026-10-10, before the code that reads them).

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
# match statistics, marks, journey cards and analysis: game.match (C26), game.journey (C27), game.analysis (C28)
uv run python -m tools.fetch_crests     # crests from Wikipedia/Commons -> assets/crests
uv run python -m tools.build_crests     # -> web/static/crests/*.webp (needs Pillow)
uv run python -m tools.migrate          # apply migrations/*.sql (over DATABASE_URL_UNPOOLED when set)
uv run python -m tools.migrate --status # list pending, change nothing
uv run uvicorn web.app:app --port 8030  # the site (solo game; rooms use .env.local's database, i.e. PRODUCTION)
uv run python -m tools.devserver        # the site on :8031 with a throwaway Postgres: rooms without touching Neon
uv run python -m tools.stamp_assets     # content-hash every page's css/js references (--check: a deploy gate)
uv run python -m tools.failures         # what browsers reported going wrong, commonest first
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q
```

**Neon CLI** (`npm i -g neon@latest`): `neon.ts` (an empty policy), `package.json` and the
Neon agent skills in `.claude/skills/` came from `neon config init` and `neon skills`. All of
it is local tooling and `.vercelignore` keeps it out of the deploy.

**Note:** the daily's seeds come from SESSION_SECRET; rotating it changes every future day's squads and matches, never a stored result.

**Gates before any deploy:** `tools.migrate --status` shows nothing pending on Neon, `etl.deck --check`, `tools.build_crests --check`,
`tools.build_brand --check` and `tools.stamp_assets --check` (all exit 1 when stale), and the test suite
(which also fails on a stale stamp). **Migrations go to Neon before the code that needs them**:
the room routes read `rooms.memory` (003). **Vercel env:** `ADMIN_ACCOUNT_IDS` (comma-separated
account ids) names the admins; unset, there are none and `/admin` shows "Not here". The og:image addresses in every page name the
production origin (`https://uclnights11.vercel.app`); change them when the custom domain lands.

**Repo and hosting:** public GitHub repo `KrauseMonet/UCLnights11`, pushed over a deploy key
used by this repo only (`core.sshCommand` -> `~/.ssh/uclnights11_deploy`; the Mac's default
key is IPLegends' deploy key and cannot push here). Vercel project `uclnights11`, connected to
the repo: **a push to `main` deploys production**, so run the gates before pushing.
Production: https://uclnights11.vercel.app

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

Match statistics from the same run (40,000 sides; declared, no real column, C26):
shots 13.4 (sd 4.9), on target 4.6 (sd 2.5), possession 50% (sd 8; 1st-99th
percentile 32-68%), passes 480 (sd 83), pass accuracy 85% (sd 3), saves 3.0.

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
| C19 | **Sign-in and rooms, at the user's request, built on the cricket site's structure** (its A102 accounts, A120 connection reuse, rooms polled rather than pushed). Email+password with stdlib PBKDF2 and a signed cookie, no OAuth and no email service, as there. Sign-in gates rooms only. **The first state to outlive a request**, so C10's "no database until something has to outlive a request" is now answered: Neon, but only for who sits where and each seat's draft string. The tournament is still recomputed from those on every read, never stored. |
| C20 | **Every seat drafts its own eleven, at its own pace, from one shared seed** — not the cricket site's turn-based shared pool. A 32-person turn-by-turn draft is 352 turns of waiting; parallel drafts from one shuffle keep it fair (everyone sees the same squads in the same order) without anyone waiting on anyone. Picks are not exclusive between friends. The host's "finish their drafts" (best takeable player each deal) is the escape hatch for a friend who wanders off, in place of the cricket site's turn timer. |
| C21 | **Rooms of 2, 4, 8 and 16 are straight knockouts; 32 is the solo format**, and empty places are filled by `draw_opposition` exactly as solo fills them. Refactoring `play_tournament` to share the knockout code was checked by fingerprinting six seeds' full tournaments before and after: identical, so no shared solo link changed. A test pins that a room of one in 32 IS the solo tournament. The room rules (completion only when the last eleven is full, stale-move refusal, host-only start, full-room refusal, membership on moves, one season per club among fillers) were each deleted once and their test seen to fail. |
| C15 | **Four pages: home, draft, tournament, archive.** The archive is new to this site: every club-season with its crest, its star and a drawer holding the full rated squad, plus the list of quarter-finalists Wikipedia cannot supply a squad for, so their absence is explained rather than silent. On the tournament page the groups, bracket and scorers stay hidden until your own run has been watched. |
| C22 | **A room survives a dropped connection (2026-10-10), after a real one was lost.** Production room 4X2943: three picks, the tab hidden ~20 s (a phone), two more polls, then "Back to friends"; every request in the logs was a 200. Reproduced locally by failing one poll: `room.js` treated ANY failed request as "Not here" and wiped the screen, and the polls that then succeeded never repainted it, because the version had not changed and the deal's state was still marked as shown. Now only a 404 ends a room; anything else keeps the screen, shows "Reconnecting…" and backs off 2.5 s doubling to 20 s. One poll runs at a time (a timer, a tab waking and a failed move could each start their own, and every chain then kept itself going). `api()` carries the HTTP status (0 = no reply) and retries a GET once on 0/502/503/504, never a write (the cricket site's A169). A pick whose reply was lost is settled by the next poll; sent again, its stale `expect` is a 409. All three cases were driven in the browser by replacing `fetch`. The same pass fixed the phone layout: the nav overflowed 100 px (the account control is now one button and a menu, and the logo becomes the emblem under 480 px), the seat strip is one sideways-scrolling row, the deal scrolls back into view after a pick, a line-count bar sits above the deal, and the cup's match card no longer squeezes both sides into slivers. Built with `tools.devserver`, which starts its own Postgres because `.env.local` points at production. |
| C23 | **Memory mode hides the ratings while drafting, at the user's request (2026-10-10), and the API enforces it rather than the page.** A view of a draft, not part of it: the state string is unchanged and `?memory=1` rides alongside. In memory mode `session_out` nulls every rating and **lists each line by name**, because the deck lists a squad best first (etl.deck sorts by rating) and the order alone would give the ratings away. Each dealt card carries `i`, its index in the deal, which is what a pick names. Solo: chosen on home, remembered in localStorage. Rooms: the host's choice in the lobby (migration 003 `rooms.memory`), refused after the start; server-side matters there because friends compete. The tournament reveals the ratings. Each rule (nulling, name order, `i`, the room flag, host-only, lobby-only) was broken once and its test seen to fail. |
| C24 | **The basics from the cricket site (2026-10-10):** content-hashed asset URLs (`tools.stamp_assets`, its A106; the hand-bumped `?v=11` is gone and a stale stamp fails a test), About/FAQ/Privacy/Terms pages linked from the footer, browser failure reports (`/api/client-failures`, migration 004, its A180: no account, IP or query string, 30 days, 2,000 an hour), `/api/health` plus a GitHub cron pinging it every 5 minutes (it never opens the database, so it cannot keep Neon awake; a test fails if it does), an installable app (manifest, `sw.js` with A132's rules: never cache `/api`, pages network-first, hashed assets cache-first; not registered on localhost, where it would hide edits) and an admin page (its A154: `ADMIN_ACCOUNT_IDS`, a 404 to everyone else; overview, account search, set a password, delete an account, list and delete rooms). **Deleting an account would cascade to every room it hosts**, so `admin.delete_account` first passes each to the next seat and afterwards completes a drafting room whose remaining elevens are full. The failure-kind check is guarded twice (Python and the table's CHECK), so its test calls `record()` directly; through the endpoint the quiet 204 hid either. |
| C26 | **Match statistics: possession, shots, on target, passes, passes completed and saves, per side and per player (2026-10-10). The constants are declared, at the user's direction.** The only open Champions League event data found was StatsBomb's (15 matches, 14 of them finals); its terms ask for its name and logo on anything published. The user chose declared constants with no source over that, so no StatsBomb figure was used, and the downloaded files were deleted. **The statistics cannot change a result:** they are drawn after the score from a stream seeded by the match itself (`match._stats_rng`). Verified by fingerprinting every result of 240 tournaments (40 solo, 200 rooms) before and after: identical. The test that guards it checks that `play()` takes exactly the goals' draws from the shared stream. Its first version (statistics switched off, tournaments compared) passed with a stray draw added, because both runs made it. Shots grow from the score's own expected goals, so a side that dominated on paper usually dominates the numbers. Every goal is its scorer's shot on target, every other shot on target is the keeper's save, and team totals are the players' lines added up. Shown at full time on the match card (the engine has totals, not when each shot happened) and in every result row, which opens. Each invariant was broken once and its test seen to fail. |
| C27 | **The journey card and the match mark (2026-10-11), after the cricket site's A80.** Your side's tournament as a 1080 px canvas image (ending, W-D-L and form, six team figures, three awards, the eleven with per-player numbers), downloadable and shareable from the phone's share sheet, plus the same numbers as a table on the page, since a picture can't be read aloud. **The mark is declared**, a broadcaster's out-of-ten built from the C26 statistics. First pass: defenders averaged 5.83 against forwards' 6.55, because conceding cost more than anything else could earn; rebalanced and measured over 40 tournaments to GK 6.73 / DF 6.43 / MF 6.66 / FW 6.89, mean 6.64. **One totals function for every screen** (`journey.player_totals`, keyed by (side, person); the A175 lesson): the same man drafted by a friend and drawn with his club is two rows. The mark's colour on the card first came from the unrounded 5.95 while it read "6.0"; it now follows the shown value. Each rule (side keying, the 3-10 clamp, the 10-pass floor, no award for 0, 120 minutes after extra time, goals) was broken once and its test seen to fail. The extra-time test first passed with the rule broken, because its tournament never went to extra time; a forced extra-time match fixed it. |
| C28 | **The tournament analysis (2026-10-11), after the cricket site's A104: a page, `/analysis`, linked from a finished tournament.** It reads the tournament the engine already played and adds nothing to it. Seven sections, inline SVG and tables with no chart library (A104). **Colours run through the dataviz validator against the panel colour `#0c1a36`**: the site's own gold and blue failed its dark-mode lightness band, so the charts use deeper steps of both, `#c08a1e` / `#4a86d8` (every check passes), with grey `#56637f` only as a neutral midpoint (a draw) or the field's average. Every chart carries its numbers as labels, so nothing is told by colour alone. **Rate boards need half the most matches anyone played**, not a fixed count, because a room of two plays one final and a fixed 3 emptied every board. Pass accuracy is also outfield only. Two tests passed with their rule deleted (the goalkeeper exclusion and the minute edges) because the data never exercised them. They were rewritten to use a board long enough to hold every keeper, and the exact edges 15/16, 90/91. |
| C29 | **Rooms take turns from a shared pool, at the user's request (2026-10-11), after the cricket site; this supersedes C20 as the default.** C20 had made every seat draft its own eleven at its own pace, so nobody waited; the user wanted the cricket site's turn-by-turn draft instead. `game.shared_draft` is a pure replay of (seed, the seats' formations, the room's moves): snake order, one squad dealt per turn to the seat on turn (the deal-time guarantee per seat), **exclusive by person across the room**, no rerolls (a move's turn is its place in the list), eleven rounds. Stored: `rooms.moves` and `turn_started_at` (migration 005; epoch seconds from the app's clock, never compared with Postgres `now()`). The clock is the cricket site's: 15/30/45 s, a 2 s grace (A146), a random seeded auto-pick (A103), enforced lazily by polls and moves (lock-free look first, locked only when expired, A92), a 5 s `lock_timeout`, a stale pick refused with a 409 that carries the room (A146), and the display clock synced NTP-style (A119). **Own pace stays as the host's other choice**, and rooms made before 005 keep it. Adapted: everyone watches the squad being picked from and a latest-picks feed. **A turn room cannot lose a seat mid-draft** (every later pick's owner is its place in the snake), so an admin deleting a player marks it failed. Every rule (exclusivity, snake, grace, seeded auto-pick, only the seat on turn, polls resolve, memory, no rerolls) was broken once and its test seen to fail. Exclusivity's test first passed with the rule deleted, because its deals rarely held a taken man and "already in your eleven" refused him anyway; it now asks the rule directly about a man held by the other seat, in every season. The rollback test passed too, because the next poll quietly re-made the same pick; it now reads the stored moves before anyone polls. And the explicit commit it guarded turned out to be redundant, since the real danger is raising instead of returning. Played in the browser: two players, a clock run out into Manuel Akanji, the host finishing the draft. |
| C30 | **A match's statistics build as it plays, and a goal has its moment (2026-10-11).** The engine kept shot totals, not their minutes, so it now records a timeline (`match.shot_timeline`): goals at their own minutes, every other shot at a minute drawn from a THIRD stream, after the statistics are fixed. Fingerprinted before and after, 20 tournaments' every result and every statistic, plus the 240-tournament result fingerprint: identical. The page replays shots, on target and saves from it. Passes build evenly and possession drifts to its final figure, because the engine has no moments for them; the copy doesn't claim otherwise, and at full time every number is the real one. A goal pauses the clock 1.7 s under a burst in the scorer's colours (reduced motion: no movement). Only your own matches carry the timeline. **A pinned hash now guards the statistics** (`STATS_PINNED`): the test that compared statistics with the timeline switched off passed with a stray draw added inside the statistics, the same blind spot as C26's first test, because both runs made the draw. The extra-time spread test also first passed with shots squeezed into ninety minutes; it now requires some to land after 90. Checked in the browser by freezing the burst's animations at 0.65 s, because the pane was hidden and a hidden page doesn't run CSS animations. |
| C31 | **Saved results and the profile (2026-10-11), after the cricket site's A108/A109.** Migration 006 `results`: one row per (account, source, key), the summary worked out by the server REPLAYING the tournament (never figures a browser sent), the players' numbers as JSON; saving twice is a no-op. The profile adds one account's rows up in Python. Solo saves have a known limit: the state is unsigned and a seed can be chosen, so titles on a profile can be farmed; that's harmless while the profile ranks nobody, and the daily (the one ranked thing) can't be. Each rule (idempotent save, the replay, signed-in only, the streak's "until a day is missed") was broken once and its test seen to fail. |
| C32 | **The daily challenge (2026-10-11), after the cricket site's A125-A133.** One a day by UTC date, made on first request and stored (`daily_challenges`), so later code can't change a played day. The same eleven squads for everyone in the day's formation, no rerolls; one ninety-minute neutral match against a strong real side with a goal (win / win by 2 / clean-sheet win / score 3). **The goal is measured, not chosen**: the best-pick drafter must reach it 30-60% of the time over 200 matches; 60 days measured all in the band, mean 41%, while a random drafter managed 14%. Kinds are tried in a shuffled order because taking the first that fit gave "win" most days and a clean sheet never. **The seeds are HMACs of SESSION_SECRET**: the engine is public, so with a public seed anyone could try every eleven offline and submit the winner. A signed-out practice match uses a third seed, so practising reveals nothing; in the browser the same eleven lost 0-2 in practice and won 4-0 ranked. One ranked attempt (`daily_results` primary key, plus a check first: either alone holds, both together tested). Re-showing a played day replays its picks; if they no longer replay (a deck change) the stored score stands without the match, found when a planted test result had no picks. The board test first passed with the ranking deleted, because test results happened to arrive in rank order; it now plants them worst-first. **A test-tooling mistake, recorded so it isn't repeated:** backing up `web/daily.py` and `game/daily.py` into one flat folder kept only one, and the restore copied the game module over the web one (both untracked, so git had neither). It was rewritten from this session's own record and the suite re-run; backups now keep their folders. The match card, live stats and goal burst moved to `matchplay.js`, shared by the cup and the daily. |
| C33 | **The daily is drafted blind, at the user's request (2026-10-11).** Memory mode, always on and enforced by the API: the deal and your picks carry no ratings and each line is listed by name (`session_out(memory=True)`). The opponent's eleven is hidden too, since its ratings would give away the scale for the same men in your squads. A **practice** result hides them as well, because otherwise practising tells you your eleven's ratings and you could redraft knowing them before the ranked attempt. Everything shows once your ranked match is played, or the day is over. The stored success rate still describes a drafter who CAN see ratings, and the page now says so; a blind human will usually find the day harder. Each hiding rule was broken once and its test seen to fail. |
| C25 | **The archive page drew nothing in production, with every test green.** `archive.js` and `common.js` both declared a top-level `const LINES`; classic scripts share one global scope, so `archive.js` threw a SyntaxError on load. Found by reading the browser console while checking the new pages. `test_no_page_script_redeclares_a_name_common_js_declares` now compares every page script's top-level names with `common.js`'s, and fails with the duplicate put back. |

## Known limits

- **Accounts have no password reset, no email verification and no rate limit on sign-in**
  attempts (PBKDF2's cost is the only brake). Each needs something the site does not have
  yet (an email service; shared state for counting attempts).
- Rooms are polled every 2.5 s, not pushed: Vercel's Python functions hold no sockets.

- `data/squads.json` carries some junk links from squad tables (a link to the
  article "Midfielder", an odd "Thumbnail crab" entry). They are never rated, so
  never draftable, and are left rather than special-cased.
- Positions are Wikipedia's four lines; wingers are forwards or midfielders as the
  article says. `|POS` in a ratings file corrects an obvious one.
- **No self-service account deletion.** The privacy page sends people to a GitHub issue;
  an admin deletes from `/admin`. A contact address would be better than a public issue.
- **AC Milan 2011–12 is left out of the deck but not in the archive's list of gaps**
  (`deck.json` `gaps` has the twelve unreadable squads only), so C15's "explained, not
  silent" misses it there; the About and FAQ pages name it.
- **The service worker is checked by hand, not by the suite** (which checks only that it is
  served from the root uncached). On production on 2026-10-10 it registered at scope `/` and
  cached the offline page, crests, fonts, the hashed css/js and `/`, and nothing under `/api/`.
  It won't register on localhost, by design. A worker change needs `VERSION` bumped in `sw.js`
  to clear old caches.
- **Crests shown out of era** (the current crest for an earlier season, because no dated
  historical file exists): Juventus before 2017 (oval), Manchester City before 2016,
  Chelsea before 2005, Ajax 1991–2025 (the 1928 crest is shown), Tottenham before 2006,
  Atlético 2017–2024, Roma before 2013, Lyon before 2022, Monaco before 2021, Deportivo,
  and minor redesigns elsewhere. Add a row to `data/crest_eras.csv` when a file turns up.
