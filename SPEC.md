# UCLnights11 — specification

A football draft game. Each turn deals one real squad that reached the European
Cup's quarter-finals; the player takes one man from it; eleven turns build a side
that then plays a full 32-team tournament against real quarter-finalists.

This is the source of truth for the rules. `CLAUDE.md` tracks state, commands and
the decisions log.

## 1. Scope

- **Seasons:** 1994–95 (the first with a quarter-final round in the Champions
  League era) to 2025–26, the last completed season: **32 seasons**.
- **Club-seasons:** the eight quarter-finalists of each season, **256** in all,
  read from Wikipedia (`etl.quarterfinalists`; exactly eight per season is asserted).
- **In the deck: 243.** Twelve have no squad that can be read (eleven have no
  club-season article at all; Hajduk Split 1994–95's article lists no squad), and
  AC Milan 2011–12's squad table parses only its midfielders, so it is left
  unrated rather than half-rated. The twelve:
  Göteborg 1994–95, Hajduk Split 1994–95, Nantes, Spartak Moscow and Legia Warsaw
  1995–96, Auxerre, Porto, Ajax and Rosenborg 1996–97, Dynamo Kyiv and Monaco
  1997–98, CSKA Moscow 2009–10.

## 2. Data

| Input | Source | Licence | Owner |
|---|---|---|---|
| Quarter-finalists | Wikipedia season / knockout articles | CC BY-SA | `etl.quarterfinalists` |
| Squads | Wikipedia club-season articles | CC BY-SA | `etl.squads` → `data/squads.json` |
| Player identity | Wikidata id via the article (pageprops) | CC0 | `etl.wiki.resolve` |
| Ratings | this game's judgement | — | hand-written `data/ratings/<season>.txt` |
| Club names, codes, colours | declared | — | `data/clubs.csv` |
| Engine yardstick | openfootball Champions League results | CC0 | `etl.openfootball` |

**A player is a Wikidata id, never a name.** Two men can share a name; one man's
article can be linked under two spellings. Every link is resolved through
redirects to its article and from there to its Wikidata id.

**Squads come from the source; nothing is invented.** A squad is whoever the
club-season article lists, in squad-list templates or a squad/statistics table,
outside reserve, youth, loan and transfer sections. A player loaned out is not in
the squad. A player with no article is dropped (he cannot be identified). A
club-season article that redirects to the club's main article is rejected, because
that page's squad is the *current* one.

## 3. Ratings

Ratings are **declared game design, not measurement**, in the same category as
FIFA's: one integer per player-season, 50–99. The scale used:

| | |
|---|---|
| 95–99 | a historic season (Messi 2011–12, Ronaldo 2007–08, Kaká 2006–07) |
| 90–94 | world-class |
| 85–89 | elite |
| 80–84 | a good starter |
| 75–79 | rotation |
| below 75 | fringe |

Each `data/ratings/<season>.txt` holds a `# Club title` line per club and then
`Player title|rating[|POS]` lines. Titles are the canonical Wikipedia titles from
`data/squads.json` (a title can never contain `|` or `#`). `POS` optionally
corrects the position Wikipedia gave (Redondo listed as a defender, Iniesta as a
forward).

**A rating may only name a player the squad lists.** `etl.deck` refuses to build
otherwise. This is the guard against the one real risk in hand ratings: writing a
squad from memory. It has caught every such error so far (see the decisions log).

Not every listed player is rated: the core of each squad is (about 16–22 per
club-season). Unrated players are not draftable.

**2025–26 is the least reliable season** — it runs past the knowledge the ratings
were written from — and is the first to re-check before going public.

## 4. The deck

A club-season enters `data/deck.json` only if its rated players can field a legal
eleven in at least one formation, so the opposition never needs an invented
player. The deck is generated (`etl.deck`) and committed; `etl.deck --check` fails
if it is stale.

## 5. The draft

- Formations: 4-3-3, 4-4-2, 4-2-3-1, 3-5-2, 3-4-3, chosen before the first deal.
- Each turn deals **one club-season, uniformly at random over the deck** — Bayern,
  in 24 quarter-finals, comes round 24 times as often as APOEL with one. Rarity is
  meant to feel like an event.
- The drafter takes one rated player into an open slot **in his own line**
  (GK, DF, MF, FW), or spends one of **two rerolls**.
- **One person once**: the same man on another card (Messi 2008–09 after Messi
  2011–12) cannot be taken again.
- **Deal-time guarantee:** a deal with nothing takeable is redrawn before it is
  shown; redraws are counted.
- The whole draft is `SEED-FORMATION-moves` (moves are card indices or `r`) and is
  replayed from scratch on every request. The server stores nothing.

## 6. The match engine

Goals are Poisson. A side's expected goals are

    lambda = base * exp(K * ((attack - league_attack) - (opp_defence - league_defence)))

- `base` is the real Champions League home or away scoring rate in regulation
  time (1.72 / 1.33, from 1,962 openfootball matches, 2011–12 to 2025–26); neutral
  is their mean.
- `attack` and `defence` are weighted means of the eleven's ratings. Weights by
  line, attack: GK 0, DF 0.15, MF 0.6, FW 1.0; defence: GK 1.6, DF 1.0, MF 0.45, FW 0.1.
- `league_attack`, `league_defence` are the deck's mean best eleven, derived at
  boot, so two average sides score exactly the real rates.
- `K = 0.075` per rating point is a declared constant.
- Scorers are drawn by line (FW 1.0, MF 0.5, DF 0.14, GK never) scaled by rating;
  72% of goals carry an assist.
- Extra time: thirty minutes at the same rate, played when a tie is level on
  **aggregate**. Penalties: five each then sudden death; conversion 0.76 adjusted
  by taker and keeper ratings.

`uv run python -m game --validate` prints the engine beside the real results.
Means are calibrated by construction; draw rate, result split and spread are
**reported, not tuned**.

## 7. The tournament

- 32 sides: yours plus **31 different clubs**, each in one season drawn uniformly
  from the deck, each fielding the best eleven its rated players allow.
- Four pots of eight by strength; eight groups of four, one per pot, avoiding two
  seasons of one club in a group. Home and away, 3/1/0 points; ties broken by goal
  difference, goals scored, then a seeded drawing of lots.
- Round of 16: group winners against runners-up from other groups, winners at home
  in the second leg. Quarter- and semi-finals an open draw. Two legs; level on
  aggregate means extra time in the second leg and then penalties. **No away-goals
  rule** (as since 2021–22).
- Final: one match, neutral ground, extra time and penalties.
- The honours count scorers per (person, side): one man in two drawn club-seasons
  is two rows, never one summed total no single team produced.

## 8. Accounts and rooms (playing with friends)

- **Accounts:** username (3–20 of `A–Z a–z 0–9 _`, case-insensitively unique), email
  and password (8+ characters), hashed with PBKDF2-HMAC-SHA256 at 600,000 iterations.
  The session is a signed cookie (HMAC-SHA256, 30 days); there is no session table.
  Signing in is needed only for rooms: the solo game never asks and never touches the
  database.
- **A room** has a six-character code and a size: **2** (a single final), **4**
  (semi-finals and final), **8** (quarter-finals on), **16** (round of 16 on) or **32**
  (the full format of §7). Up to `size` signed-in people join with the code; the host
  starts the draft; nobody joins or leaves after that.
- **The draft** is the solo draft (§5), one per seat, each in the seat's own
  formation. Every seat shares the room's seed, so all are dealt the same squads in the
  same order until the deal-time guarantee redraws one for a single seat. Seats draft at
  their own pace; a move carries the move count the player's screen had seen and is
  refused if the draft has moved on. Picks are not exclusive between friends: two
  people can both take Messi 2011–12.
- **The host can finish the drafts** of anyone who has wandered off: each unfinished
  eleven takes the highest-rated takeable player of each remaining deal.
- **The tournament** starts when the last eleven is full. Places no person took go to
  real sides drawn exactly as in §7 (different clubs, one season each, best eleven).
  A cup of 4–16 is an open draw every round, two legs (extra time and penalties on a
  level aggregate) and a one-match final on neutral ground. It is a pure function of
  (seed, size, the seats' draft states) and is recomputed on every request, never
  stored; a room of one in 32 plays exactly the solo tournament of the same seed.
- **Stored:** `accounts`, `rooms` (code, size, seed, host, status, a version that
  rises on every write) and `room_seats` (who, seat, formation, draft state string).
  Lobbies nobody started are swept after three days.

## 9. Not in scope yet

Puzzle games, saved career stats, password reset, the daily challenge, auctions. The engine, draft and
deck are built so each can be added without changing their contracts. No UEFA mark is
used. Club crests are used on a non-commercial basis, era-correct where a dated file
exists (`data/crest_eras.csv`), with every source named in `CREDITS.md`.
