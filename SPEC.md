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
- **Memory mode** hides the ratings while drafting. It is a way of showing a draft, not
  part of it: the state string is the same, and `?memory=1` rides beside it on every
  call. The API then sends no rating for any dealt or picked card and lists each line of
  a deal by name, because the deck lists a squad best first and the order alone would
  give the ratings away. Every dealt card carries `i`, its index in the deal, which is
  what a pick names whatever the order shown. The tournament shows the ratings.

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

### Match statistics

Every match also has possession, shots, shots on target, passes, passes completed
and saves, for each side and each player. **The constants are declared game design,
set by judgement at the user's direction; no real source is fitted** (C26), and the
validator prints what they produce with no "real" column.

- **They never change a result.** They are drawn after the score, from a random stream
  seeded by the match itself (both elevens, the score, the goals), never from the
  tournament's stream.
- **Shots grow from the score's own expected goals.** Every goal is a shot on target by
  its scorer. Saved shots ~ Poisson(1.9 x lambda); shots off target or blocked ~
  Poisson(4.0 + 3.0 x lambda), scaled +/-50% across 0-100% possession; lambda capped
  at 3.2 for the shots of a rout. Shooters are drawn as scorers are.
- **Possession** is 0.5 + 0.012 per point of CONTROL edge (+0.02 at home) + N(0, 0.06),
  kept within 25-75%. Control weights: GK 0.1, DF 0.5, MF 1.0, FW 0.35.
- **Passes:** 480 x 2 x possession (x 4/3 after extra time) x N(1, 0.08), shared by line
  (GK 0.45, DF 1.05, MF 1.35, FW 0.6) and quality. Each player completes his share at
  0.81 + 0.006 per rating point above 80 + 0.30 x (possession - 0.5) + N(0, 0.03),
  within 55-95%.
- **Saves** are the opponent's shots on target that were not goals, all the keeper's.
- A side's totals are its players' lines added up, so the two cannot disagree.
- **Watching a match live** (C30): every shot has a minute, so the page can replay a
  match's statistics as it plays. Goals keep their minutes; every other shot gets a
  minute spread over the time played (to 120 after extra time), from a third random
  stream, so neither a result nor a statistic changes. Passes build evenly through the
  match and possession drifts round its final figure until the whistle, since the
  engine keeps their totals, not their moments; at full time every number is the real
  one. A goal stops the clock for 1.7 s while the card fills with the scorer's colours.
  Only your own matches carry the timeline.

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

### Players' tournaments, the journey card and the analysis

- **One set of totals** (`game.journey.player_totals`) per (side, person): apps, minutes
  (120 after extra time), goals, assists, shots, on target, passes, completed, saves,
  clean sheets and a mark per match. The journey card, the players table and every
  analysis board read it, so they cannot disagree.
- **The mark** out of 10 is declared (C27): 6.4, +0.9 a goal, +0.75 an assist, +0.15 a
  shot on target that didn't go in, +4.0 x (pass accuracy - 0.84) once a player has 10
  passes, +0.2 a save, per goal conceded GK -0.3 / DF -0.1 / MF -0.05, a clean sheet
  GK +0.8 / DF +0.6 / MF +0.2, +0.3 a win, -0.3 a loss; kept within 3-10. A shoot-out
  is a draw for the mark. Measured over 40 tournaments: mean 6.64; by line GK 6.73,
  DF 6.43, MF 6.66, FW 6.89; a 10 in 0.1% of player-matches.
- **The journey card** (C27) is your side's tournament as one 1080 px image: the ending,
  W-D-L and a form strip (knockouts ringed), six team figures, three awards (top
  scorer, most assists, player of the tournament = best average mark), and the eleven
  with each man's apps, goals, assists, a line-specific figure and his average mark.
  Drawn in the browser, downloadable and shareable. No award goes to a 0. In a room,
  each friend's card is their own; someone watching has none.
- **The analysis** (C28), at `/analysis`, covers the whole tournament: headline totals;
  honours (golden boot, most assists, player of the tournament, golden glove, biggest
  win, most goals in a match); goals by quarter-hour (all, or yours scored and
  conceded); your side per match against the field's average; home win / draw / away
  win in matches with a home side; round by round; every side, sortable; and seven
  player boards. A rate (mark, pass accuracy) is ranked only for a player with at least
  half as many matches as anyone; pass accuracy also needs 20 passes a match and is
  outfield only. An empty rate is "–", never 0.

## 7b. Saved results, the profile and the daily challenge

- **Saved results** (C31): signed in, a finished solo tournament or room can be saved
  to the account. The server replays it and stores its own summary (how far, record,
  goals, each player's numbers); keyed (account, source, key), so saving twice is
  harmless. A daily result saves itself. The profile adds an account's results up:
  tournaments, titles, finals, best finish, how far you get, career goals/assists/most
  picked/average mark (6+ apps), and the daily's played, met and streak.
- **The daily challenge** (C32), one a day by UTC date, made when first asked for and
  stored. The same eleven squads for everyone, in the day's formation, no rerolls. One
  ninety-minute match on neutral ground against a real side's best eleven (no extra
  time, no penalties) with a goal: win, win by 2+, win without conceding, or score 3+.
  **Each day's goal is measured**: the drafter who takes the best player every deal must
  reach it 30-60% of the time over 200 simulated matches, and the rate is stored with the
  day (measured over 60 days: always in the band, mean 41%; a random drafter, 14%).
- **The seeds are secret**: the deal's and the match's come from SESSION_SECRET by HMAC,
  so the day can't be known ahead nor the best eleven found offline with the public
  engine. One ranked attempt per account per day. Signed out, a practice match uses a
  third seed and is kept nowhere. Ranked by goal met, goal difference, goals scored,
  the eleven's average mark, then who played first. A streak lasts until a day is missed.

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
- **Two ways to draft, the host's choice in the lobby** (C29). **Take turns** (the
  default, after the cricket site): seats pick in a snake order (host first, then the
  order people sat down; reversed every round), each turn deals one real squad to the
  seat on turn, and **a player taken by anyone is gone for everyone, in every season**.
  No rerolls. A pick clock of 15, 30 or 45 s (30 by default); when it runs out (plus a
  2 s grace) the room picks a random player the seat can take, seeded by the move
  number. It is enforced by whoever polls or moves next; with nobody looking the clock
  waits. A pick sent after its turn has passed is refused with a 409 that carries the
  room. Eleven rounds, so at most 11 x seats x clock. The host can finish the draft,
  taking the best player each remaining deal offers. A draft that runs out of squads for
  a seat is marked failed rather than worked round.
- **Own pace**: the draft is the solo draft (§5), one per seat, each in the seat's own
  formation. Every seat shares the room's seed, so all are dealt the same squads in the
  same order until the deal-time guarantee redraws one for a single seat. Seats draft at
  their own pace; a move carries the move count the player's screen had seen and is
  refused if the draft has moved on. Picks are not exclusive between friends: two
  people can both take Messi 2011–12.
- **Memory mode** (§5) is the host's choice, made in the lobby and fixed once the draft
  starts; in a memory room the API leaves the ratings out of every seat's draft.
- **The host can finish the drafts** of anyone who has wandered off: each unfinished
  eleven takes the highest-rated takeable player of each remaining deal.
- **The tournament** starts when the last eleven is full. Places no person took go to
  real sides drawn exactly as in §7 (different clubs, one season each, best eleven).
  A cup of 4–16 is an open draw every round, two legs (extra time and penalties on a
  level aggregate) and a one-match final on neutral ground. It is a pure function of
  (seed, size, the seats' draft states) and is recomputed on every request, never
  stored; a room of one in 32 plays exactly the solo tournament of the same seed.
- **Stored:** `accounts`, `rooms` (code, size, seed, host, status, memory, style, pick
  clock, the room's moves and when the current turn began, a version that rises on every write) and `room_seats` (who, seat, formation, draft state string).
  Lobbies nobody started are swept after three days.
- **A dropped connection is not the end of a room.** The page polls; only a 404 means
  the room is gone. Any other failure keeps the screen, says it is reconnecting and tries
  again with a growing pause (2.5 s doubling to 20 s). A move whose reply was lost is
  settled by the next poll; sent again, its stale move count is refused.

## 9. Not in scope yet

Puzzle games, saved career stats, password reset, the daily challenge, auctions. The engine, draft and
deck are built so each can be added without changing their contracts. No UEFA mark is
used. Club crests are used on a non-commercial basis, era-correct where a dated file
exists (`data/crest_eras.csv`), with every source named in `CREDITS.md`.
