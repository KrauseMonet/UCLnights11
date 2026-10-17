# UCLnights11 — specification

A football draft game. Each turn deals one real squad that reached the European
Cup's quarter-finals; the player takes one man from it; eleven turns build a side
that then plays a full 36-team tournament, a league phase and knockouts, against real
quarter-finalists.

This is the source of truth for the rules. `CLAUDE.md` tracks state, commands and
the decisions log.

## 1. Scope

- **Seasons:** 1994–95 (the first with a quarter-final round in the Champions
  League era) to 2025–26, the last completed season: **32 seasons**.
- **Club-seasons:** the eight quarter-finalists of each season, **256** in all,
  read from Wikipedia (`etl.quarterfinalists`; exactly eight per season is asserted).
- **In the deck: 243**, every squad that can be read. Thirteen have no squad that can be
  read (eleven have no club-season article at all; Hajduk Split 1994–95's article lists no
  squad; AC Milan 2011–12's tables yield nobody once cells are split correctly, C36). The
  thirteen:
  Göteborg 1994–95, Hajduk Split 1994–95, Nantes, Spartak Moscow and Legia Warsaw
  1995–96, Auxerre, Porto, Ajax and Rosenborg 1996–97, Dynamo Kyiv and Monaco
  1997–98, CSKA Moscow 2009–10, AC Milan 2011–12.

## 2. Data

| Input | Source | Licence | Owner |
|---|---|---|---|
| Quarter-finalists | Wikipedia season / knockout articles | CC BY-SA | `etl.quarterfinalists` |
| Squads | Wikipedia club-season articles | CC BY-SA | `etl.squads` → `data/squads.json` |
| Player identity | Wikidata id via the article (pageprops) | CC0 | `etl.wiki.resolve` |
| Ratings | this game's judgement | — | hand-written `data/ratings/<season>.txt` |
| Positions, 2013–14 on | Transfermarkt line-ups via transfermarkt-datasets | CC0 (as published) | `etl.positions` → `data/positions/measured.json` |
| Positions, before | this game's judgement | — | hand-written `data/positions/<season>.txt` |
| Transfermarkt ids | Wikidata P2446 | CC0 | `etl.positions` |
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
`Player title|rating` lines. Titles are the canonical Wikipedia titles from
`data/squads.json` (a title can never contain `|` or `#`). (A third column once
corrected Wikipedia's line; positions replaced it, §3a, and the build now refuses it.)

**A rating may only name a player the squad lists.** `etl.deck` refuses to build
otherwise. This is the guard against the one real risk in hand ratings: writing a
squad from memory. It has caught every such error so far (see the decisions log).

Not every listed player is rated: the core of each squad is (about 16–22 per
club-season). Unrated players are not draftable.

**2025–26 is the least reliable season** — it runs past the knowledge the ratings
were written from — and is the first to re-check before going public.

## 3a. Positions (C35)

Twelve positions: GK, RB, CB, LB, DM, CM, AM, RM, LM, RW, ST, LW. Each belongs to a line
(GK; RB CB LB = DF; DM CM AM RM LM = MF; RW ST LW = FW). Wide midfielders (LM/RM) and
wingers (LW/RW) are different positions, at the user's choice. A player-season holds
**one to four** positions, most-played first; four is a maximum, not a target.

- **2013–14 onwards: measured.** Every position he STARTED at least once for that club
  that season, in Transfermarkt's line-ups (transfermarkt-datasets, CC0), counted over
  every competition the dataset holds; ranked by starts, ties in the order above, the
  first four kept. A second striker counts as ST (the user's choice), a sweeper as CB;
  line-only labels ("Midfield", "Attack") are dropped. Only starts count: a substitute's
  line-up row carries no match position. A player is linked by Wikidata's Transfermarkt
  id (P2446), never by name; a club-season's Transfermarkt club is the one its squad
  started most for. Transfermarkt's line-ups begin with 2013–14.
- **Before 2013–14: declared**, by hand, like the ratings, in `data/positions/<season>.txt`
  (`# Club title`, then `Player title|CB,RB`). Positions follow Transfermarkt's own
  conventions, so the two eras read alike: wide men are LM/RM in a 4-4-2 and LW/RW in a
  4-3-3 or 4-2-3-1, wing-backs in a back three are LM/RM. A declaration records the roles
  a player held that season and will miss one-off cameos a line-up would catch.
  **Measured, blind, on 299 player-seasons from the measured era** (C35): 92% of the
  positions written were ones he started at least once; 89% of his positions with three
  or more starts were written; the first one written was his most-started 87% of the time.
- A measured-season player with no starts for the club (a reserve keeper) takes a
  declared line in the same files. The build refuses a declared line for anyone who has
  measured starts, a declared line for a player who is not rated, and a rated player
  with no positions.
- A card's line (`pos`) is the line of its first position.

## 4. The deck

A club-season enters `data/deck.json` only if its rated players can field a legal
eleven in at least one formation, so the opposition never needs an invented
player. Its strongest eleven (the highest total rating over every formation, a
maximum-weight assignment of players to slots they hold; ties to the eleven nearer
each man's most-played positions, then to the formation listed first) is worked out by
`etl.deck` and stored with the squad, so the server never searches for it. The deck is
generated (`etl.deck`) and committed; `etl.deck --check` fails if it is stale.

## 5. The draft

- Formations are chosen before the first deal, on their own page (`/start`, C37) with
  whether ratings show; a bare `/draft` goes there. Each is eleven slots, Transfermarkt's
  commonest line-up for the shape (measured over 2013–14 to 2025–26); a shape whose
  commonest slots repeat another's is left out, and the code refuses two with one slot set:

  | | slots |
  |---|---|
  | 4-3-3 | GK RB CB CB LB DM CM CM RW ST LW |
  | 4-4-2 | GK RB CB CB LB RM CM CM LM ST ST |
  | 4-2-3-1 | GK RB CB CB LB DM CM RW AM LW ST |
  | 4-3-1-2 | GK RB CB CB LB DM CM CM AM ST ST |
  | 3-5-2 | GK CB CB CB RM DM CM CM LM ST ST |
  | 3-4-3 | GK CB CB CB RM CM CM LM RW ST LW |
  | 3-4-1-2 | GK CB CB CB RM DM CM LM AM ST ST |
  | 4-4-2 wingers | GK RB CB CB LB DM CM RW LW ST ST |
  | 4-4-2 diamond | GK RB CB CB LB DM RM LM AM ST ST |
  | 4-5-1 | GK RB CB CB LB RM DM DM AM LM ST |
  | 3-4-2-1 | GK CB CB CB RM DM DM LM AM AM ST |
  | 3-1-4-2 | GK CB CB CB RM DM AM AM LM ST ST |
  | 5-3-2 | GK RB CB CB CB LB DM DM AM ST ST |
  | 5-4-1 | GK RB CB CB CB LB CM CM RW LW ST |

  The diamond and the 3-4-1-2 came with positions: Ancelotti's Milan, the Porto and PSV
  diamonds and Dortmund 1997–98 field none of the first five. The last seven came with the
  setup page, at the user's request for more formations (C37).
- Each turn deals **one club-season, uniformly at random over the deck** — Bayern,
  in 24 quarter-finals, comes round 24 times as often as APOEL with one. Rarity is
  meant to feel like an event.
- The drafter takes one rated player, or spends one of **two rerolls**. A pick is legal
  while **the whole eleven so far can still be given distinct slots, each man in a slot
  whose position he holds** (a bipartite matching). Where each man stands is worked out
  afresh after every pick, favouring each man's most-played positions, so the order of a
  draft never strands anyone: a right-back taken after a right-back who also plays
  midfield moves the first one into midfield.
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
- **The bench (C40).** Every new solo draft takes **three more picks after the eleven**,
  for the bench, and its tournament is played by engine 2 (§6), where they come on. A
  bench man must hold a position the formation has, so he can always come on for whoever
  stands there, and is **never a goalkeeper** (the engine never changes the keeper). One
  person once and the deal-time guarantee hold for the bench too; the two rerolls are
  for the whole draft.
- **The plan (C41).** A finished bench draft stops on "Your changes" before kick-off: for
  each substitute, the minute he may come on from (45' to 85', or not used), on what
  score (any, behind, level, ahead, unless ahead, unless behind; in a second leg the
  aggregate), and for whom: a starter he could come on for (the formation still filled;
  never the keeper), or the best change, which replaces whoever it helps most to replace
  and only if it helps. One plan for every match. Each substitute once, each starter
  named once. Left alone, the **automatic plan** applies: the best-rated man first at
  60', then 70', then 80', each the best change, as a club's. The plan is part of the
  state, `-p` and a line per change (`p0b60o9.1a70.2a80`: substitute 0 from 60' if behind
  for the man in slot 9; `p` alone, no changes); with no plan part the automatic one
  applies, so a link from before plans plays as it did. A new plan is a new link and a
  new tournament, and the tournament page offers to change it only before your first
  match is watched.
- **Changes made during the match (C60).** On the plan screen a drafter may choose to make
  the changes themselves. "Make a sub" then stops the match and shows the eleven on the
  pitch, the bench and whom each substitute could replace (a substitute not yet on, at most
  three changes, never the keeper, the formation still filled); the change comes at the next
  break. Nobody comes on otherwise. Any skip asks whether the plan should make the changes
  in what is skipped (from the next break in a match under way) or none be made. The link
  carries it all, so the tournament stays its function: `-m`, then per match with any, its
  number among your own, `a` and a break if the plan took over, and `c` with three
  characters per change (the break in fives, the substitute, the man off as a squad index:
  0-10 the eleven in slot order, 11-13 the bench), in base 36 (`m2c814.4ac`). A change is
  refused unless the engine makes exactly it there. Such a link plays the live engine (§6).
- **On the match card** a change shows in the feed with its minute; the man coming on
  takes the disc of the man going off, and anyone moved to make room slides to his new
  place. A bench draft's state starts with `b`
  (`bSEED-FORMATION-moves`); **a plain state is an eleven-pick draft, played by engine 1,
  and every link to one opens and plays exactly as it did.** Rooms and the daily stay
  eleven-pick drafts for now, and the plain decoder refuses a `b` state so neither can
  mistake one for an eleven.
- **A league draft** (C50), every solo draft made since, is a bench draft whose state
  starts with `l` in place of the `b` (`lSEED-FORMATION-moves`) and whose tournament is
  the league phase of §7. A `b` link keeps the group format. Rooms keep their format by
  size and the daily plays one match, so the decoder they use refuses an `l` state.

## 6. The match engine

Goals are Poisson. A side's expected goals are

    lambda = base * exp(K * ((attack - league_attack) - (opp_defence - league_defence)))

- `base` is the real Champions League home or away scoring rate in regulation
  time (1.72 / 1.33, from 1,962 openfootball matches, 2011–12 to 2025–26); neutral
  is their mean.
- `attack` and `defence` are weighted means of the eleven's ratings. Weights by
  line, attack: GK 0, DF 0.15, MF 0.6, FW 1.0; defence: GK 1.6, DF 1.0, MF 0.45, FW 0.1.
  The line is **the line of the slot a man stands in** (C35), not his natural one: a
  midfielder placed at right-back defends, scores and passes as a defender.
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
  Only your own matches carry the timeline. Since C60 the clock also stops 2.6 s at
  half-time (1.5 s before extra time) with the score and every statistic so far on the card,
  and a match has sound, synthesized in the page (no recording): a whistle at kick-off,
  half-time and full time, the crowd, a roar for a goal; on unless muted.
- **Both elevens** (C38): the match card draws both sides on one pitch, side on, home in
  the left half attacking right and away in the right half attacking left (upright on a
  phone, home at the bottom), each in its club's colours and its formation's slots. A
  scorer's disc lights up with a ball per goal. A line-up carries each man's name and slot
  only, never a rating, so a blind daily stays blind (C33).

### Engine 2: tiredness and substitutes (C39)

Every tournament is played by one engine, chosen when it is played. **Engine 1 is
everything above and does not change**: every shared link, saved result and room
replays its tournament from scratch, so a new rule there would rewrite results people
have already watched; a pinned hash of six tournaments guards it. Engine 2 is opt-in
(`play_tournament(..., engine=2)`, `game --validate --engine 2`); solo drafts, rooms
and days with a bench play it (§5, §7b, §8; C40, C42).

- **A match is played in five-minute blocks.** In each, a side's expected goals are
  engine 1's formula over the eleven ON THE PITCH, with each outfield man's rating moved by
  his tiredness: `u = (min(minutes played, 90) - 45) / 45`, from -1 at kick-off to +1 at
  ninety. He defends `13 x u` points below his rating and attacks `6.5 x u` below it. A
  goalkeeper does not tire. Over a full ninety `u` averages zero, so two average sides
  still score the real rates.
- **Tiredness hurts defending more than attacking**, which is what moves goals late: if
  both sides lost the same in both, the strength edge, and so the scoring, would never
  change. `TIRE = 13` is SET by the real share of goals after half-time, **55.7%** of
  5,975 (openfootball half-time scores): the engine gives 55.7%; with no tiredness it
  gives 50%. The attacking half is declared. The real share also holds added time
  (second halves run longer) and game state, which the engine folds into tiredness,
  so 13 is the most tiredness the yardstick allows, not a measurement of tiredness.
- **Tiredness stops growing at ninety minutes** (declared). Extra time then scores 1.24
  a match; real extra time scored 1.00 in 24 matches, too few to set anything by.
- **Substitutes.** A side has a bench and a plan; up to three changes, made between
  blocks. A plan line names a bench man, the earliest minute, a condition (any, behind,
  level, ahead, not ahead, not behind; on the tie's aggregate in a second leg) and
  either the man he replaces or none, when the engine picks the change that most helps
  attack (behind), defence (ahead) or both, and **makes none if nothing helps**. The
  goalkeeper is never changed. A change must leave an eleven that fills the formation
  (game.positions), and everyone may move to make room. A substitute comes on fresh.
- **Club sides' benches**: the three best-rated outfield men outside the best eleven who
  could each come on for someone; their plan is a change from 60', 70' and 80'. Measured
  over 20,000 matches: 2.98 changes a side, at 70' on average; substitutes score 6.3% of
  goals; an equal-rated bench gives a side 44% more goals after the hour than none.
- **Statistics** are engine 1's, block by block, from a stream of the match's own: each
  block's shots come from its own expected goals and the men on the pitch, passes are
  shared among them, and every shot has its minute, so the timeline is the statistics.
  Each player line carries his minutes; a side's add up to eleven men for the whole match.
- **Scorers and assisters** are drawn from the men on the pitch at the goal's minute; a
  shoot-out's takers are the eleven on the pitch at the end.

- **Live matches (C60)**: `game.tournament.Live`, engine 2 for a tournament someone changes
  while it plays. Every match draws from a stream of its own, named by the tournament's seed
  and its place in the order of play, and its statistics are drawn block by block (each
  block's shots from a stream of the block's own, possession from the men on the pitch in
  each block with one noise for the match, each man's pass spread and accuracy from a stream
  of his own). Everything up to a break is then the same whatever comes after it, and a
  change in one match moves no other match played before it or on the same matchday. The
  formulas are engine 2's: over 20 league tournaments, shots 13.36 a side (engine 2 13.29),
  passes 482 (483), possession sd 0.073 (0.075). A live match also records its running passes
  and possession at every break (`flow`).

Engine 2 against the real results, 20,000 matches between club sides with benches:
home goals 1.767 (real 1.719), away 1.360 (1.327), total SD 1.801 (1.783), home win
0.474 (0.477), draw 0.216 (0.204), away win 0.310 (0.319), after half-time 0.557 (0.557).

## 7. The tournament

The competition's format since 2024–25 (C50): every new draft and every new full-size
room plays it. The rules are UEFA's as Wikipedia's 2024–25 league phase and knockout
phase articles state them; where this game departs from them it says so.

- 36 sides: yours plus **35 different clubs**, each in one season drawn uniformly from
  the deck, at most **five of one association** (four league places and a European
  Performance Spot, the most an association enters without a holder's place), each
  fielding the best eleven its rated players allow. A club's association is the one
  Wikipedia's season articles mark it with (`data/associations.json`; Monaco is France's).
- **Four pots of nine by strength** (not coefficient, which the deck has no equivalent
  of). A pot holds at most **four clubs of one association**: with five no draw exists,
  since each would need two opponents from its own pot among four who can take only
  eight such matches. A fifth waits for the next pot. (Ours; real pots never need it.)
- **The draw:** each side plays two opponents from every pot, its own included, one at
  home and one away; eight different opponents. No club meets a club of its own
  association, and none meets more than two of one association; a drafted eleven has no
  association but also meets at most two of any one. A seeded constraint search
  (`game.league_phase.draw`), like UEFA's software; it never relaxes a rule.
- **Eight matchdays**, every side on each, under UEFA's principles: never more than two
  home or two away in a row, and one home and one away in the first two matchdays and
  in the last two. Built in four blocks of two matchdays, each side home in one and away
  in the other; a draw this construction can't schedule is drawn again (about half are).
- **One table of 36:** 3/1/0 points, then goal difference, goals scored, away goals
  scored, wins, away wins, then the points, goal difference and goals of the opponents
  each side met, then a seeded drawing of lots (in place of disciplinary points and the
  coefficient). 1st–8th go to the round of 16, 9th–24th to the play-offs, 25th–36th out.
- **Knockout play-offs**, two legs: 9/10 v 23/24, 11/12 v 21/22, 13/14 v 19/20, 15/16 v
  17/18, each seeded side drawn against one of its two and at home in the second leg.
- **Round of 16**, a fixed bracket: 1/2 meet the winners from 15/16 v 17/18, 3/4 those
  from 13/14 v 19/20, 5/6 those from 11/12 v 21/22, 7/8 those from 9/10 v 23/24, the
  league side at home in the second leg. Each pair of seeds is drawn into the two halves
  (1 and 2 can meet only in the final) and against its two play-off winners.
- **Quarter- and semi-finals** follow the bracket (in each half, 1/2's tie meets 7/8's
  and 3/4's meets 5/6's); the draw decides only who hosts the first leg. Two legs; level
  on aggregate means extra time in the second leg and then penalties. **No away-goals
  rule** (as since 2021–22).
- Final: one match, neutral ground, extra time and penalties.
- The honours count scorers per (person, side): one man in two drawn club-seasons
  is two rows, never one summed total no single team produced.
- **The group format** is retired for new play, and every link and room made before
  C50 still plays it exactly as it did: a plain or `b` state, a room of 32. 32 sides,
  yours plus 31 different clubs.
  Four pots of eight by strength; eight groups of four, one per pot, avoiding two
  seasons of one club in a group. Home and away, 3/1/0 points; ties broken by goal
  difference, goals scored, then a seeded drawing of lots. Round of 16: group winners
  against runners-up from other groups, winners at home in the second leg; quarter- and
  semi-finals an open draw.

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

## 7a. Dynasty mode (C64)

One squad over ten seasons (`game.dynasty`; the engine and the site's pages come later).

- **Season 1 is a league draft**, its state string with `y` for `l`, and its tournament is
  that draft's own: the same seed.
- **Between seasons every man moves on to the next season the deck has for him, within
  three** (`JUMP`), at that season's rating and positions and with that season's club. With
  none in that time he has **left**; if the deck ends inside that time, the reason says so.
  Nothing is made up for a missing season: the deck holds quarter-finalists only, so a man
  whose club missed the quarter-finals is listed by no squad that year.
- **A transfer window**: the formation may change, up to three men may be released
  (`RELEASES`), and the open places are filled from deals as in the draft (the deal-time
  guarantee, two rerolls a window, one person once, a kept substitute included).
- **The kept men are placed**: as many start as the slots can take, best-rated first; the
  best of the rest sit on the bench (three places, never a keeper, only a position the
  formation has); anyone else has **no place** and leaves without counting as a release.
  A man's positions are his new season's own, so this is common (23% of windows in a
  simulation that kept one formation); another shape can keep him.
- Then a team sheet and a plan, as after any bench draft. Each season's tournament is the
  league phase on engine 2, against opposition drawn fresh, from a seed of the dynasty's
  seed and the season's number, so a later window never moves an earlier season.
- State: `ySEED-FORMATION-moves[-sheet][-plan]`, then per window `~FORMATION-xRELEASES[-moves][-sheet][-plan]`,
  the releases as base-36 indices into the previous season's picks. At most 30 seasons.
  Nothing else reads a `y` state.

## 7b. Saved results, the profile and the daily challenge

- **Saved results** (C31): signed in, a finished solo tournament or room can be saved
  to the account. The server replays it and stores its own summary (how far, record,
  goals, each player's numbers); keyed (account, source, key), so saving twice is
  harmless. A daily result saves itself. The profile adds an account's results up:
  tournaments, titles, finals, best finish, how far you get, career goals/assists/most
  picked/average mark (6+ apps), and the daily's played, met and streak.
- **The daily challenge** (C32), one a day by UTC date, made when first asked for and
  stored. The same eleven squads for everyone, in the day's formation, no rerolls,
  **drafted blind** (C33): no ratings anywhere (the deal, your picks, the opponent's
  eleven, a practice result) until the viewer's ranked match is played or the day ends;
  each line listed by name, as in Memory mode. One
  ninety-minute match on neutral ground against a real side's best eleven (no extra
  time, no penalties) with a goal: win, win by 2+, win without conceding, or score 3+.
  **Each day's goal is measured**: the drafter who takes the best player every deal must
  reach it 30-60% of the time over 200 simulated matches, and the rate is stored with the
  day (measured over 60 days: always in the band, mean 41%; a random drafter, 14%).
- **The seeds are secret**: the deal's and the match's come from SESSION_SECRET by HMAC,
  so the day can't be known ahead nor the best eleven found offline with the public
  engine. One ranked attempt per account per day. **Each account's ranked match has its
  own seed** (C59) on a day made since, so friends don't share the day's luck (one seed for
  everyone kept giving different elevens the same score); older days keep their one seed.
  Signed out, a practice match uses a
  third seed and is kept nowhere. Ranked by goal met, goal difference, goals scored,
  the eleven's average mark, then who played first. A streak lasts until a day is missed.
- **A day with a bench** (C42): every day made from then on is fourteen squads, the last
  three for the bench, with a plan (§5), and its match is played by engine 2 (§6), the
  opponent bringing on its own bench by the automatic plan. Its goal is measured the same
  way, the calibration drafter also taking the best player for its bench and using the
  automatic plan: over 60 days, all in the band, mean 39.5%. A day stored before keeps
  eleven picks and engine 1. The ranked plan is stored with the attempt (the automatic one
  written out), so a played day replays. Drafting blind, the automatic plan's lines are
  not shown, since bringing the best-rated man on first would rank the substitutes; each
  shows "Automatic" until the drafter chooses, and the untouched ones then come on at
  60', 70', 80' in bench order.
- **Making the changes during the match (C60)**, on a bench day. Practice sends every change
  with each request. A ranked match is held on the server (`daily_live`) and let out five
  minutes at a time as the page plays it; a change comes at the break it has been let out
  to, so nobody can see the rest of the match before choosing. It is ranked only once all of
  it is out (or the rest is skipped, with or without the plan), with its changes stored so
  it replays; one left half-way is finished, with no more changes, after 30 minutes or once
  the day is over.
- **After the ranked match**, the page shows your squad with the ratings the draft hid and
  its averages by line (as §5's squad page does).

## 8. Accounts and rooms (playing with friends)

- **Accounts:** username (3–20 of `A–Z a–z 0–9 _`, case-insensitively unique), email
  and password (8+ characters), hashed with PBKDF2-HMAC-SHA256 at 600,000 iterations.
  The session is a signed cookie (HMAC-SHA256, 30 days); there is no session table.
  Signing in is needed only for rooms: the solo game never asks and never touches the
  database.
- **A room** has a six-character code and a size: **2** (a single final), **4**
  (semi-finals and final), **8** (quarter-finals on), **16** (round of 16 on) or **36**
  (the league phase of §7; a room of 32, made before C50, plays the group format). Up to
  `size` signed-in people join with the code; the host
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
- **The bench** (C42) is the host's choice too, on by default for a new room: fourteen
  picks each (fourteen rounds when taking turns, exclusive across the room like the rest),
  then each seat plans its changes (§5) and says it is **ready**; the room completes only
  when every seat is, since the tournament is recomputed on every read and a plan changed
  after it opened would change what everyone had seen. A plan can be changed until then.
  No pick clock runs while plans are made; the host's finish makes any picks left and
  gives anyone not ready the automatic plan. A bench room plays engine 2; a room without
  one, and every room made before benches, plays engine 1.
- **The host can finish the drafts** of anyone who has wandered off: each unfinished
  eleven takes the highest-rated takeable player of each remaining deal.
- **The tournament** starts when the last eleven is full. Places no person took go to
  real sides drawn exactly as in §7 (different clubs, one season each, best eleven).
  A cup of 4–16 is an open draw every round, two legs (extra time and penalties on a
  level aggregate) and a one-match final on neutral ground. It is a pure function of
  (seed, size, the seats' draft states) and is recomputed on every request, never
  stored; a room of one in 36 plays exactly the solo tournament of the same seed.
- **Watching together** (C52) is the host's choice too, on by default for a new room. Once
  the room completes the host kicks off (any seat may, three minutes after it completed,
  if the host hasn't) and every screen follows one clock (`game.watch`): the watch is cut
  into **rounds**, one per matchday or leg in which a friend plays, each an 8 s countdown,
  every friend's match of that round at once at 0.1 s a match minute (120 minutes'
  allowance for a second leg or final, whether or not extra time comes, since an allowance
  that followed the result would give it away), then 5 s at full time. A round with no
  friend in it is left out, which tells nobody anything early: who plays round r+1 is
  settled by the results up to round r. The server stores only when the watch began and
  lets each round out as the clock reaches it: its pairings at the countdown, its results
  at kick-off, the friends' standings (league place and points, then who is out) at full
  time. The whole tournament, its analysis and saving it to a profile are refused until
  the watch ends, 2 s after the last round. **Only the host can skip**, and only forward:
  to this round's kick-off or full time, past the league phase, or to the end; a skip
  moves the start earlier so every screen lands on the same moment, and one naming a
  round already passed changes nothing. A run to the final watches in about six and a half
  minutes. A room without it, and every room made before it, lets each friend watch alone.
- **A live room (C60)**, every room made since that drafts a bench and watches together:
  its matches stop for half-time (3 s) and before extra time (2 s) on every screen, and a
  seat may make its own changes (its choice while planning). Each match of the round being
  played is let out only as far as the clock has gone plus 1.2 s, and its result at the
  round's whistle. "Make a sub" stops everyone's clock (at most 30 s; the seat or the host
  carries on; five pauses without a change each) and the change comes at the first break
  after everything sent: at Normal 9 to 14 match minutes after the click, at Slow 4 to 9, at
  Fast 22 to 27. The host's skip asks whether those seats' plans make the changes in what is
  skipped. The pace changes only between matches. Its tournament plays the live engine (§6),
  and a live room of one in 36 is the solo tournament of a link that makes its own changes.
  A room watching alone keeps the plans: each friend is at a different point of one shared
  tournament, and a change would rewrite what another had already seen.
- **Stored:** `accounts`, `rooms` (code, size, seed, host, status, memory, style, pick
  clock, whether it drafts a bench, the room's moves and when the current turn began,
  whether it watches together, when it completed and when its watch began, a
  version that rises on every write; whether it is live and a pause) and `room_seats` (who,
  seat, formation, draft state string, in a bench room its plan once ready, and in a live
  room its own changes and its pauses without one).
  Lobbies nobody started are swept after three days.
- **A dropped connection is not the end of a room.** The page polls; only a 404 means
  the room is gone. Any other failure keeps the screen, says it is reconnecting and tries
  again with a growing pause (2.5 s doubling to 20 s). A move whose reply was lost is
  settled by the next poll; sent again, its stale move count is refused.

## 9. Not in scope yet

Puzzle games, password reset, auctions. The engine, draft and
deck are built so each can be added without changing their contracts. No UEFA mark is
used. Club crests are used on a non-commercial basis, era-correct where a dated file
exists (`data/crest_eras.csv`), with every source named in `CREDITS.md`.
