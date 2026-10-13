"""The HTTP API and the pages. Stateless: every request replays from its state string.

A draft's whole state is ``SEED-FORMATION-moves`` (game.draft.encode), carried in
the page's URL. The solo game stores nothing, so there is no session to lose, a
draft survives a reload, and a link reproduces it exactly.

Accounts and rooms (playing with friends) are the one part that keeps state, in
Postgres (web.db). They are additive: without DATABASE_URL and SESSION_SECRET the
solo game runs exactly as before and those routes answer 503.
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections import OrderedDict
from datetime import date
from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, Response as PlainResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import analysis as analyses, daily as daily_rules, journey as journeys, match, squad_ratings
from game import watch
from game.deck import Card, ClubSeason, load_deck
from game.draft import (Change, IllegalMove, Pick, Reroll, Session, can_replace, carry_plan, check_sheet, decode,
                        decode_solo, decode_state, default_sheet, encode, is_league, move as move_man, replay,
                        targets, why_not)
from game.formations import DEFAULT, FORMATIONS
from game.positions import arrange
from game.shared_draft import Stranded
from game.tournament import (CUP_STAGES, FINISHES, LEAGUE_STAGES, LEAGUE_TEAMS, STAGES, Fixture, Side,
                             Tournament, auto_plan, club_side, leaders, league_of, play_room, play_tournament)
from web import accounts, admin, auth, daily, db, failures, results, rooms
from web.env import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
# Three sides the home page fans out: the game's idea in one picture.
SHOWCASE = ("1998-MUN", "2010-BAR", "2001-RMA")

load_dotenv()
app = FastAPI(title="UCLnights11")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(rooms.RoomError)
def _room_error(request: Request, e: rooms.RoomError):
    return JSONResponse({"detail": str(e)}, status_code=e.status)


@app.exception_handler(daily.DailyError)
def _daily_error(request: Request, e: daily.DailyError):
    return JSONResponse({"detail": str(e)}, status_code=e.status)


@app.exception_handler(accounts.AccountError)
def _account_error(request: Request, e: accounts.AccountError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(auth.NotConfigured)
def _not_configured(request: Request, e: auth.NotConfigured):
    return JSONResponse({"detail": "Playing with friends is not switched on here yet."}, status_code=503)


@app.exception_handler(psycopg.OperationalError)
def _db_down(request: Request, e: psycopg.OperationalError):
    return JSONResponse({"detail": "The database is not answering; try again in a moment."},
                        status_code=503)


@lru_cache(maxsize=1)
def league() -> match.League:
    return league_of(load_deck())


# A reply that is a pure function of its URL and the deck: no cookie, clock or database
# goes into it. Vercel's CDN keeps it (s-maxage) and empties itself on every deploy, the
# only way the deck or the engine can change, so a cached reply is never a stale one; the
# browser still asks each time (max-age=0), so a deploy shows at once. Set on the
# Response parameter, so an error raised instead carries no such header.
PURE = "public, max-age=0, s-maxage=31536000"


def pure(response: Response) -> None:
    response.headers["cache-control"] = PURE


# -- serialisation ----------------------------------------------------------

def crest_url(key: str | None) -> str | None:
    return f"/static/crests/{key}.webp" if key else None


def colours(x) -> dict:
    return {"team": x.team, "deep": x.deep, "ink": x.ink}


def card_out(c: Card, reason: str | None = None) -> dict:
    """``pos`` is a line, ``positions`` what he can play (most-played first), and ``slot``
    where he stands when the card is placed in an eleven (C35)."""
    return {
        "id": c.id, "name": c.name, "pos": c.pos, "positions": list(c.positions), "source": c.source,
        "slot": c.slot, "nation": c.nation, "rating": c.rating,
        "club": c.club_name, "short": c.short, "season": c.label, "key": c.key,
        "crest": crest_url(c.crest),
        "wiki": "https://en.wikipedia.org/wiki/" + c.title.replace(" ", "_"),
        "takeable": reason is None, "reason": reason,
    }


def club_season_out(cs: ClubSeason, cards: list[dict] | None = None) -> dict:
    out = {"key": cs.key, "name": cs.name, "season": cs.label, "year": cs.season,
           "short": cs.short, "crest": crest_url(cs.crest), **colours(cs)}
    if cards is not None:
        out["cards"] = cards
    return out


LINE_ORDER = ("GK", "DF", "MF", "FW")


def formation_out(f) -> dict:
    return {"code": f.code, "label": f.label, "lines": f.lines, "slots": list(f.slots)}


def eleven_out(f, picks: list[Card], memory: bool) -> list[dict]:
    """The picks placed in their slots, in slot order (game.positions.arrange)."""
    out = [card_out(c) for c in arrange(f.slots, picks)]
    return hide_ratings(out) if memory else out


def session_out(state: str, s: Session, memory: bool = False) -> dict:
    """A draft as the drafter sees it. Every dealt card carries ``i``, its index in the
    deal, which is what a pick names. In Memory mode the ratings are removed here, not
    hidden by the page, and the deal is listed by name: the deck lists a squad best
    first, so the order alone would give the ratings away."""
    deal = None
    if s.deal is not None:
        cards = [{**card_out(c, why_not(c, s.formation, s.picks)), "i": i} for i, c in enumerate(s.deal.cards)]
        if memory:
            cards.sort(key=lambda c: (LINE_ORDER.index(c["pos"]), c["name"]))
        deal = club_season_out(s.deal, cards)
    picks = [card_out(c) for c in s.picks]
    bench = [card_out(c) for c in s.bench]
    xi = [card_out(c) for c in s.xi]
    if memory:
        for c in [*picks, *bench, *xi, *(deal["cards"] if deal else [])]:
            c["rating"] = None
    out = {
        "state": state, "seed": s.seed, "memory": memory,
        "formation": formation_out(s.formation),
        "picks": picks, "xi": xi,
        "bench": bench, "bench_size": s.bench_size, "total": s.total,
        "deal": deal, "rerolls_left": s.rerolls_left, "complete": s.complete,
    }
    if s.complete and s.bench_size:
        plan_fields(s, bench, out, memory)
    return out


def plan_fields(s: Session, bench: list[dict], out: dict, memory: bool = False) -> None:
    """The plan (C41) for a finished bench draft, added to ``out``: the one chosen, or the
    automatic one written out, and on each substitute's card (``bench``, the drafter's own
    view of them) the slots whose starter he could come on for.

    Drafting blind, the automatic plan is NOT written out (``plan`` is None): it brings
    the best-rated man on first, so its order would rank the substitutes for someone
    who can't see their ratings (C42, the C33 rule)."""
    xi = s.xi
    for c, man in zip(bench, s.bench):
        c["can_replace"] = can_replace(s.formation, xi, man)
    # The team sheet (C44): each man's pick index and every place he could be moved to.
    where = {c.id: i for i, c in enumerate(s.picks)}
    to = targets(s)
    for c in [*out["xi"], *bench]:
        c["p"] = where[c["id"]]
        c["to"] = to[c["p"]]
    out["sheet_chosen"] = s.sheet is not None
    if s.plan is None and memory:
        out["plan"] = None
    else:
        out["plan"] = [plan_line_out(c) for c in (s.plan if s.plan is not None else auto_changes(s.bench))]
    out["plan_chosen"] = s.plan is not None


def auto_changes(bench: list[Card]) -> tuple[Change, ...]:
    return tuple(Change(x.on, x.minute, x.when, None) for x in auto_plan(bench))


def plan_line_out(c: Change) -> dict:
    return {"on": c.on, "minute": c.minute, "when": c.when, "off": c.off}


def side_out(side: Side) -> dict:
    out = {"key": side.key, "name": side.name, "short": side.short, "you": side.you,
           "club": side.club_name, "season": side.label, "crest": crest_url(side.crest),
           **colours(side)}
    if side.owner is not None:
        out["human"] = True
    return out


def fixture_out(f: Fixture, timeline: bool = False) -> dict:
    """``timeline`` adds every shot's minute, [minute, side, on target, goal], for a match
    the page plays live (C30); only your own matches carry it, to keep the reply small."""
    r = f.result
    out = {
        "stage": f.stage, "label": f.label, "group": f.group,
        "home": side_out(f.home), "away": side_out(f.away),
        "hg": r.home_goals, "ag": r.away_goals, "extra_time": r.extra_time,
        "pens": list(r.pens) if r.pens else None,
        "goals": [{"minute": g.minute, "side": g.side, "scorer": g.scorer.name,
                   "assist": g.assist.name if g.assist else None} for g in r.goals],
        "stats": stats_out(r),
    }
    if timeline:
        out["shots"] = [[x.minute, x.side, int(x.on_target), int(x.goal)] for x in r.shots]
        out["lineups"] = [lineup_out(f.home), lineup_out(f.away)]
        # Engine 2's changes (C39), each with the eleven after it; none in engine 1.
        out["subs"] = [{"minute": x.minute, "side": x.side, "off": x.off.name, "on": x.on.name,
                        "xi": [{"name": c.name, "slot": c.slot} for c in x.xi]} for x in r.subs]
    return out


def lineup_out(side: Side) -> dict:
    """A side's eleven for the match screen (C38): where each man stands, in its formation's
    slot order. Names and slots only: no rating, so a blind daily stays blind (C33)."""
    return {"formation": side.formation.label, "slots": list(side.formation.slots),
            "xi": [{"name": c.name, "slot": c.slot} for c in side.xi]}


def stats_out(r) -> dict | None:
    """Both sides' match statistics as [home, away] pairs. Possession is whole percents
    that add up to 100, as a scoreboard shows it."""
    if r.stats is None:
        return None
    h, a = r.stats
    ph = round(h.possession * 100)
    return {"possession": [ph, 100 - ph], **{k: [getattr(h, k), getattr(a, k)]
            for k in ("shots", "on_target", "passes", "completed", "saves")}}


def leader_out(card: Card, side: Side, n: int) -> dict:
    out = {"name": card.name, "side": "Your XI" if side.you else side.name,
           "crest": crest_url(side.crest), "you": side.you, "n": n}
    if side.owner is not None:
        out.update(human=True, **colours(side))
    return out


def pct(x: float | None) -> int | None:
    return None if x is None else round(x * 100)


def player_totals_out(p: journeys.PlayerTotals) -> dict:
    c = p.card
    return {
        "id": c.id, "name": c.name, "pos": c.pos, "rating": c.rating, "club": c.club_name,
        "short": c.short, "season": c.label, "crest": crest_url(c.crest),
        "apps": p.apps, "minutes": p.minutes, "goals": p.goals, "assists": p.assists,
        "shots": p.shots, "on_target": p.on_target, "passes": p.passes, "completed": p.completed,
        "accuracy": pct(p.accuracy), "saves": p.saves, "clean_sheets": p.clean_sheets,
        "mark": p.mark, "marks": p.marks,
    }


def journey_out(j: journeys.Journey) -> dict:
    """A side's whole tournament, for its journey card (C27)."""
    def award(p, n):
        return None if p is None else {"name": p.card.name, "n": n, "crest": crest_url(p.card.crest),
                                       "pos": p.card.pos, "short": p.card.short, "season": p.card.label}
    scorer = j.top(lambda p: p.goals)
    maker = j.top(lambda p: p.assists)
    star = j.star
    matches = []
    for m in j.matches:
        f, i = m.fixture, m.side_index
        r = f.result
        mine, theirs = (r.home_goals, r.away_goals) if i == 0 else (r.away_goals, r.home_goals)
        opp = f.away if i == 0 else f.home
        matches.append({"stage": f.stage, "label": f.label, "outcome": m.outcome, "knockout": m.knockout,
                        "for": mine, "against": theirs, "opp": side_out(opp),
                        "pens": None if r.pens is None else list(r.pens if i == 0 else r.pens[::-1]),
                        "extra_time": r.extra_time})
    w, d, l = j.record
    return {
        "reached": j.reached, "record": [w, d, l], "goals_for": j.goals_for,
        "goals_against": j.goals_against, "possession": pct(j.possession), "shots": j.shots,
        "on_target": j.on_target, "passes": j.passes, "completed": j.completed,
        "accuracy": pct(j.completed / j.passes) if j.passes else None,
        "clean_sheets": j.clean_sheets, "matches": matches,
        "players": [{**player_totals_out(p), "sub": any(c.id == p.card.id for c in j.side.bench)}
                    for p in j.players],
        "awards": {"top_scorer": award(scorer, scorer.goals if scorer else 0),
                   "top_assists": award(maker, maker.assists if maker else 0),
                   "star": award(star, star.mark if star else 0)},
    }


def analysis_out(a: analyses.Analysis) -> dict:
    """The tournament analysis (C28). Rates with nothing under them are None."""
    def per(n, d):
        return round(n / d, 2) if d else None

    def side_row(r: analyses.SideRow) -> dict:
        return {**side_out(r.side), "reached": r.reached, "p": r.played, "w": r.won, "d": r.drawn,
                "l": r.lost, "gf": r.gf, "ga": r.ga, "possession": pct(r.possession) if r.played else None,
                "shots": per(r.shots, r.played), "on_target": per(r.on_target, r.played),
                "accuracy": pct(r.completed / r.passes) if r.passes else None,
                "clean_sheets": r.clean_sheets, "mark": r.mark}

    def board(rows, fmt=lambda v: v):
        return [{"name": p.card.name, "pos": p.card.pos, "crest": crest_url(p.card.crest),
                 "side": side_out(p.side), "apps": p.apps, "value": fmt(v)} for p, v in rows]

    def fixture_brief(f):
        return None if f is None else {"stage": f.stage, "label": f.label, "group": f.group,
                                       "home": side_out(f.home), "away": side_out(f.away),
                                       "hg": f.result.home_goals, "ag": f.result.away_goals}

    sides = a.sides
    n = sum(r.played for r in sides)
    average = {"goals": per(sum(r.gf for r in sides), n), "conceded": per(sum(r.ga for r in sides), n),
               "shots": per(sum(r.shots for r in sides), n), "on_target": per(sum(r.on_target for r in sides), n),
               "possession": 50, "accuracy": pct(a.completed / a.passes) if a.passes else None}
    you = None
    if a.you is not None:
        r = a.you
        you = {"goals": per(r.gf, r.played), "conceded": per(r.ga, r.played), "shots": per(r.shots, r.played),
               "on_target": per(r.on_target, r.played), "possession": pct(r.possession) if r.played else None,
               "accuracy": pct(r.completed / r.passes) if r.passes else None}
    return {
        "hero": {"matches": a.matches, "goals": a.goals, "goals_per_match": per(a.goals, a.matches),
                 "shots": a.shots, "on_target": a.on_target,
                 "conversion": pct(a.goals / a.shots) if a.shots else None,
                 "on_target_share": pct(a.on_target / a.shots) if a.shots else None,
                 "accuracy": pct(a.completed / a.passes) if a.passes else None,
                 "extra_time": a.extra_time, "shootouts": a.shootouts},
        "home": {"home_win": a.home[0], "draw": a.home[1], "away_win": a.home[2]},
        "buckets": [f"{lo}–{hi}" if hi <= 90 else "Extra time" for lo, hi in analyses.GOAL_BUCKETS],
        "goal_minutes": a.goal_minutes,
        "your_minutes": None if a.your_minutes is None else {"scored": a.your_minutes[0], "conceded": a.your_minutes[1]},
        "stages": [{"stage": s.stage, "matches": s.matches, "goals": s.goals,
                    "goals_per_match": per(s.goals, s.matches), "shots_per_match": per(s.shots, s.matches * 2),
                    "extra_time": s.extra_time, "shootouts": s.shootouts} for s in a.stages],
        "sides": [side_row(r) for r in sides],
        "you": you, "average": average, "min_apps": a.min_apps,
        "boards": {
            "goals": board(a.boards["goals"]), "assists": board(a.boards["assists"]),
            "on_target": board(a.boards["on_target"]), "mark": board(a.boards["mark"]),
            "accuracy": board(a.boards["accuracy"], pct), "saves": board(a.boards["saves"]),
            "clean_sheets": board(a.boards["clean_sheets"]),
        },
        "biggest_win": fixture_brief(a.biggest_win), "most_goals": fixture_brief(a.most_goals),
    }


def tournament_out(t: Tournament) -> dict:
    """The whole tournament, seen by the side marked ``you`` -- or by a spectator, when
    no side is (someone opening a room's results without a seat in it)."""
    you = next((s for s in t.sides if s.you), None)
    knockout = []
    for stage in t.stages:
        ties = [x for x in t.ties if x.stage == stage]
        knockout.append({"stage": stage, "ties": [{
            "a": side_out(x.a), "b": side_out(x.b), "agg": list(x.aggregate()),
            "winner": x.winner.key, "legs": [fixture_out(f) for f in x.legs],
        } for x in ties]})
    def row_out(r):
        return {**side_out(r.side), "p": r.played, "w": r.won, "d": r.drawn, "l": r.lost,
                "gf": r.gf, "ga": r.ga, "pts": r.points}

    groups = [{"name": g, "table": [row_out(r) for r in rows]} for g, rows in t.tables.items()]
    pot = {id(s): q + 1 for q, members in enumerate(t.pots) for s in members}
    return {
        "format": t.format,
        "table": [{**row_out(r), "pot": pot[id(r.side)]} for r in t.table],
        "you": None if you is None else {
            **side_out(you), "formation": you.formation.label, "code": you.formation.code,
            "slots": list(you.formation.slots), "xi": [card_out(c) for c in you.xi],
            "bench": [card_out(c) for c in you.bench], "plan": plan_out(you)},
        "your_matches": [fixture_out(f, timeline=True) for f in t.fixtures if you in (f.home, f.away)],
        "groups": groups, "knockout": knockout,
        "champion": side_out(t.champion), "reached": t.reached(you) if you else None,
        "journey": journey_out(journeys.journey(t, you)) if you else None,
        "golden_boot": [leader_out(c, s, n) for c, s, n in leaders(t, "goals", 10)],
        "assists": [leader_out(c, s, n) for c, s, n in leaders(t, "assists", 5)],
    }


def plan_out(side: Side) -> list[dict]:
    """A side's plan in words' parts, for the tournament page: who, from when, on what
    score, for whom (None: whoever it helps most)."""
    name = {c.id: c.name for c in side.xi}
    return [{"on": side.bench[x.on].name, "minute": x.minute, "when": x.when,
             "off": None if x.off is None else name.get(x.off)} for x in side.plan]


# -- routes -----------------------------------------------------------------

def _decode(state: str):
    """A solo draft's (seed, formation, moves, bench, plan, sheet): either kind of state."""
    try:
        return decode_solo(state)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None


def _replay(state: str) -> Session:
    seed, formation, moves, bench, plan, sheet = _decode(state)
    try:
        return replay(load_deck(), seed, formation, moves, bench, plan, sheet)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/health")
def health() -> dict:
    """For the keep-warm ping (.github/workflows/keep-warm.yml). It loads the deck, which
    is what a cold start is slow at, and never touches the database: a ping every few
    minutes must not keep Neon's compute awake."""
    return {"ok": True, "club_seasons": len(load_deck().club_seasons), "accounts": db.configured()}


@app.get("/api/meta")
def meta(response: Response) -> dict:
    pure(response)
    deck = load_deck()
    seasons = sorted({cs.season for cs in deck.club_seasons})
    return {
        "club_seasons": len(deck.club_seasons),
        "cards": sum(len(cs.cards) for cs in deck.club_seasons),
        "clubs": len({cs.club for cs in deck.club_seasons}),
        "first_season": deck.club_seasons[0].label, "last_season": deck.club_seasons[-1].label,
        "seasons": len(seasons),
        "formations": [{**formation_out(f), "about": f.about} for f in FORMATIONS.values()],
        "default_formation": DEFAULT,
        "crests": sorted({crest_url(cs.short) for cs in deck.club_seasons}),
    }


@app.get("/api/showcase")
def showcase(response: Response) -> list[dict]:
    pure(response)
    deck = load_deck()
    out = []
    for key in SHOWCASE:
        cs = deck.by_key[key]
        top = sorted(cs.cards, key=lambda c: -c.rating)[:3]
        out.append(club_season_out(cs, [card_out(c) for c in top]))
    return out


@lru_cache(maxsize=1)
def _gaps() -> list[str]:
    return json.loads((ROOT / "data" / "deck.json").read_text()).get("gaps", [])


@app.get("/api/archive")
def archive(response: Response) -> dict:
    pure(response)
    deck = load_deck()
    by_season: dict[int, list[ClubSeason]] = {}
    for cs in deck.club_seasons:
        by_season.setdefault(cs.season, []).append(cs)
    seasons = []
    for year in sorted(by_season, reverse=True):
        sides = []
        for cs in sorted(by_season[year], key=lambda c: c.name):
            star = max(cs.cards, key=lambda c: c.rating)
            sides.append({**club_season_out(cs), "players": len(cs.cards),
                          "star": {"name": star.name, "rating": star.rating}})
        seasons.append({"year": year, "label": by_season[year][0].label, "sides": sides})
    return {"seasons": seasons, "gaps": _gaps()}


@app.get("/api/squad/{key}")
def squad(key: str, response: Response) -> dict:
    cs = load_deck().by_key.get(key)
    if cs is None:
        raise HTTPException(404, "no such squad")
    pure(response)
    return club_season_out(cs, [card_out(c) for c in cs.cards])


class StartIn(BaseModel):
    formation: str = DEFAULT
    seed: int | None = None


# Memory mode is how a solo draft is shown, not part of it: the state string is the same
# either way, so `?memory=1` rides alongside it on every call. Every new solo draft has a
# bench (C40); a link to an eleven-pick draft still opens and plays as it always did.
@app.post("/api/draft")
def start(body: StartIn, memory: bool = False) -> dict:
    seed = body.seed if body.seed is not None else random.SystemRandom().randrange(1, 10**9)
    state = encode(seed, body.formation, [], bench=True, league=True)
    return session_out(state, _replay(state), memory)


@app.get("/api/draft/{state}")
def get_draft(state: str, response: Response, memory: bool = False) -> dict:
    out = session_out(state, _replay(state), memory)
    pure(response)
    return out


class PickIn(BaseModel):
    index: int


@app.post("/api/draft/{state}/pick")
def pick(state: str, body: PickIn, memory: bool = False) -> dict:
    seed, formation, moves, bench, *_ = _decode(state)
    new = encode(seed, formation, moves + [Pick(body.index)], bench, league=is_league(state))
    return session_out(new, _replay(new), memory)


@app.post("/api/draft/{state}/reroll")
def reroll(state: str, memory: bool = False) -> dict:
    seed, formation, moves, bench, *_ = _decode(state)
    new = encode(seed, formation, moves + [Reroll()], bench, league=is_league(state))
    return session_out(new, _replay(new), memory)


class ChangeIn(BaseModel):
    on: int
    minute: int
    when: str
    off: int | None = None


class PlanIn(BaseModel):
    changes: list[ChangeIn] | None     # None: back to the automatic plan


@app.post("/api/draft/{state}/plan")
def set_plan(state: str, body: PlanIn, memory: bool = False) -> dict:
    """A finished bench draft's plan (C41). It is part of the state, so the tournament
    stays a pure function of the link; a new plan is a new link and a new tournament."""
    seed, formation, moves, bench, _, sheet = _decode(state)
    plan = None if body.changes is None else tuple(Change(c.on, c.minute, c.when, c.off) for c in body.changes)
    try:
        new = encode(seed, formation, moves, bench, plan, sheet, league=is_league(state))
    except KeyError:
        raise HTTPException(400, "a change comes on a score the plan knows") from None
    return session_out(new, _replay(new), memory)


class SheetIn(BaseModel):
    """One man moved (``man``, a pick index, ``to`` "s<slot>" or "b<bench place>"), or a
    whole ``sheet`` (pick indices, the eleven in slot order then the bench); neither puts
    back the draft's own order."""
    man: int | None = None
    to: str | None = None
    sheet: list[int] | None = None


def new_sheet(before: Session, body: SheetIn) -> tuple[int, ...] | None:
    """The sheet asked for, checked against the finished draft (IllegalMove if it doesn't
    fit) and None when it is just the draft's own order, so a link stays as short as it was."""
    if body.man is not None:
        out = move_man(before, body.man, body.to or "")
    elif body.sheet is not None:
        out = tuple(body.sheet)
    else:
        return None
    check_sheet(before, out)
    return None if out == default_sheet(before) else out


@app.post("/api/draft/{state}/sheet")
def set_sheet(state: str, body: SheetIn, memory: bool = False) -> dict:
    """A finished bench draft's team sheet (C44): who starts where and who sits on the
    bench. Part of the state like the plan, which follows its men across (carry_plan)."""
    seed, formation, moves, bench, _, _ = _decode(state)
    before = _replay(state)
    try:
        sheet = new_sheet(before, body)
        after = replay(load_deck(), seed, formation, moves, bench, None, sheet)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None
    new = encode(seed, formation, moves, bench, carry_plan(before, after, before.plan), sheet,
                 league=is_league(state))
    return session_out(new, _replay(new), memory)


def _solo_side(state: str) -> tuple[Session, Side]:
    """A finished solo draft as the side it plays as: its eleven placed, its bench and
    its plan (the automatic one unless another was chosen)."""
    s = _replay(state)
    if not s.complete:
        raise HTTPException(409, "the squad is not complete yet" if s.bench_size else "the eleven is not complete yet")
    subs = s.subs()
    return s, Side("YOU", "Your XI", "YOU", s.formation, s.xi, you=True,
                   bench=s.bench, plan=auto_plan(s.bench) if subs is None else subs)


@lru_cache(maxsize=16)
def _solo_tournament(state: str) -> Tournament:
    """A bench draft plays engine 2 with its bench on the automatic plan (C40); an
    eleven-pick draft plays engine 1, as every link to one always has. A league draft
    (every one since C50) plays the league phase, every other link the group format.

    Kept for the next request: the cup page, its analysis and saving it each ask for the
    same tournament, and playing one costs ~100 ms. Callers only read it. A refusal
    (an unfinished draft) raises, and lru_cache keeps no exception."""
    s, you = _solo_side(state)
    return play_tournament(load_deck(), league(), s.seed, you, engine=2 if s.bench_size else 1,
                           fmt="league" if is_league(state) else "groups")


def squad_out(side: Side) -> dict:
    """A finished side for the completed-draft page: its eleven in their slots, its bench
    and plan, and its ratings by line, each set against the deck's own club-seasons
    (game.squad_ratings). Shown only once a draft is over, so Memory mode has nothing
    left to hide."""
    r = squad_ratings.squad_ratings(side.xi, side.bench)
    xi = [card_out(c) for c in side.xi]
    return {**side_out(side), "formation": side.formation.label, "code": side.formation.code,
            "slots": list(side.formation.slots), "xi": xi,
            "bench": [card_out(c) for c in side.bench], "plan": plan_out(side) if side.bench else None,
            "clubs": len({c.key for c in [*side.xi, *side.bench]}),
            "ratings": {k: None if v is None else round(v, 1) for k, v in r.as_dict().items()},
            "better_than": squad_ratings.ranked(load_deck(), r)}


@app.get("/api/draft/{state}/squad")
def solo_squad(state: str, response: Response) -> dict:
    """The completed-draft page for a solo draft: 409 until the draft is finished."""
    _, side = _solo_side(state)
    pure(response)
    return {"state": state, "sides": [squad_out(side)],
            "field": len(load_deck().club_seasons)}


@app.get("/api/tournament/{state}")
def tournament(state: str, response: Response) -> dict:
    out = tournament_out(_solo_tournament(state))
    pure(response)
    return out


@app.get("/api/tournament/{state}/analysis")
def tournament_analysis(state: str, response: Response) -> dict:
    t = _solo_tournament(state)
    you = next((s for s in t.sides if s.you), None)
    pure(response)
    return {"analysis": analysis_out(analyses.tournament_analysis(t, you)), "you": side_out(you)}


# -- accounts ---------------------------------------------------------------

def _viewer_id(request: Request) -> int | None:
    """Who is asking, from the signed cookie alone, for a reply that needs only the id
    (whose seat is whose): no query, so a room poll costs one round trip, not two."""
    token = request.cookies.get(auth.COOKIE_NAME)
    return auth.verify_session_cookie(token) if token else None


def _account(conn, request: Request) -> accounts.Account | None:
    token = request.cookies.get(auth.COOKIE_NAME)
    account_id = auth.verify_session_cookie(token) if token else None
    return accounts.get_account(conn, account_id) if account_id is not None else None


def _signed_in(conn, request: Request) -> accounts.Account:
    me = _account(conn, request)
    if me is None:
        raise HTTPException(401, "sign in to play with friends")
    return me


def _set_session(request: Request, response: Response, account: accounts.Account) -> dict:
    _put_cookie(request, response, auth.make_session_cookie(account.account_id, username=account.username),
                auth.SESSION_MAX_AGE_S)
    return {"account": account_out(account)}


def _put_cookie(request: Request, response: Response, token: str, max_age: int) -> None:
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="lax",
                        secure=https, path="/")


def account_out(a: accounts.Account) -> dict:
    out = {"id": a.account_id, "username": a.username}
    if admin.is_admin(a):
        out["admin"] = True
    return out


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str


class LoginIn(BaseModel):
    identifier: str
    password: str


@app.get("/api/auth/me")
def me(request: Request, response: Response) -> dict:
    """Every page asks this for its nav, so it needs no database: the signed cookie
    carries the username (C48). No cookie costs nothing either, and the solo game keeps
    working on a server with no database at all. A cookie from before C48 has no
    username: it is looked up once and the cookie re-issued with it, expiring when the
    old one would have. Usernames never change, so the cookie's can't go stale; an
    account deleted by an admin still reads as signed in until its cookie runs out,
    though everything that acts on the account refuses it."""
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token or not db.configured():
        return {"account": None}
    session = auth.read_session_cookie(token)
    if session is None:
        return {"account": None}
    account_id, expiry, username = session
    if username is not None:
        return {"account": account_out(accounts.Account(account_id, username))}
    with db.connection() as conn:
        a = accounts.get_account(conn, account_id)
    if a is None:
        return {"account": None}
    _put_cookie(request, response, auth.make_session_cookie(a.account_id, username=a.username, expiry=expiry),
                max(expiry - int(time.time()), 1))
    return {"account": account_out(a)}


@app.post("/api/auth/register")
def register(body: RegisterIn, request: Request, response: Response) -> dict:
    with db.connection() as conn:
        a = accounts.create_account(conn, body.username, body.email, body.password)
    return _set_session(request, response, a)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    with db.connection() as conn:
        a = accounts.authenticate(conn, body.identifier, body.password)
    if a is None:
        raise HTTPException(401, "that username or password is not right")
    return _set_session(request, response, a)


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"account": None}


# -- rooms ------------------------------------------------------------------

ROOM_FORMATS = {2: "Final", 4: "4-team cup", 8: "8-team cup", 16: "16-team cup",
                32: "32-team tournament", LEAGUE_TEAMS: "36-team league"}


STALE_ROOM = ("This room was drafted before players had positions, and its picks no longer "
              "replay under the new rules.")


def _replays(room: rooms.Room) -> bool:
    """Whether the room's draft still replays. One drafted before positions (C35) may not:
    its moves name cards in deals the new rules no longer make."""
    if room.status not in ("drafting", "complete"):
        return True
    try:
        if room.turns:
            rooms.shared_of(load_deck(), room)
        else:
            for seat in room.seats:
                if seat.state:
                    replay(load_deck(), *decode_state(seat.state)[:4])
    except (IllegalMove, Stranded):
        return False
    return True


def room_out(room: rooms.Room, me_id: int | None) -> dict:
    mine = room.seat_of(me_id) if me_id is not None else None
    draft = None
    turns = None
    if not _replays(room):
        room.status, room.failure_reason = "failed", STALE_ROOM
    each = room.picks_each
    picks = {s.account_id: (s.picks, s.picks == s.total) for s in room.seats}
    if room.turns and room.status in ("drafting", "complete"):
        d = rooms.shared_of(load_deck(), room)
        picks = {s.account_id: (len(p), len(p) == each) for s, p in zip(room.seats, d.picks)}
        turns = turns_out(room, d, mine)
        if mine is not None:
            i = room.seats.index(mine)
            mine_picks = [card_out(c) for c in d.picks[i]]
            if room.memory:
                for c in mine_picks:
                    c["rating"] = None
            f = d.formations[i]
            draft = {"formation": formation_out(f),
                     "picks": mine_picks, "xi": eleven_out(f, d.picks[i][:11], room.memory),
                     "bench": mine_picks[11:], "bench_size": each - 11, "total": each,
                     "complete": len(d.picks[i]) == each, "memory": room.memory,
                     "state": room.moves_text}
            if room.bench and len(d.picks[i]) == each and room.status == "drafting":
                # Planning: the eleven and bench as the seat's team sheet has them (C44).
                s = rooms.seat_session(load_deck(), room, mine, d)
                draft["xi"], draft["bench"] = [card_out(c) for c in s.xi], [card_out(c) for c in s.bench]
                if room.memory:
                    for c in [*draft["xi"], *draft["bench"]]:
                        c["rating"] = None
                plan_fields(s, draft["bench"], draft, room.memory)
    elif mine is not None and room.status == "drafting":
        try:
            draft = session_out(mine.state, rooms.seat_session(load_deck(), room, mine), room.memory)
        except IllegalMove as e:
            raise HTTPException(400, str(e)) from None
    if draft is not None:
        draft["ready"] = mine.plan is not None
    return {
        "code": room.code, "size": room.size, "format": ROOM_FORMATS[room.size],
        "memory": room.memory, "style": room.style, "timer": room.timer_seconds, "bench": room.bench,
        "together": room.together, "picks_each": each,
        "stages": CUP_STAGES.get(room.size, LEAGUE_STAGES if room.size == LEAGUE_TEAMS else STAGES),
        "status": room.status, "version": room.version, "failure_reason": room.failure_reason,
        "is_host": me_id is not None and room.host_id == me_id,
        "seated": mine is not None,
        "seats": [{
            "id": s.account_id, "username": s.username, "seat": s.seat,
            "formation": FORMATIONS[s.formation].label, "code": s.formation,
            "picks": picks[s.account_id][0], "complete": picks[s.account_id][1],
            "ready": not room.bench or s.plan is not None,
            "host": s.account_id == room.host_id,
            "you": mine is s, **rooms.seat_palette(s.seat),
        } for s in room.seats],
        "fillers": room.size - len(room.seats),
        "draft": draft,
        "turns": turns,
    }


def turns_out(room: rooms.Room, d, mine) -> dict:
    """A room that takes turns (C29): whose turn, the deal everyone is watching, the
    clock and the latest picks. The deal's reasons are the picker's, since it is dealt to
    them; in a memory room nobody sees a rating."""
    active = d.active
    deal = None
    if d.deal is not None and active is not None:
        cards = [{**card_out(c, d.reason(c, active)), "i": i} for i, c in enumerate(d.deal.cards)]
        if room.memory:
            cards.sort(key=lambda c: (LINE_ORDER.index(c["pos"]), c["name"]))
            for c in cards:
                c["rating"] = None
        deal = club_season_out(d.deal, cards)
    seat = room.seats[active] if active is not None else None
    recent = []
    for i, card in reversed(d.log[-12:]):
        c = card_out(card)
        if room.memory and room.status != "complete":
            c["rating"] = None
        recent.append({"username": room.seats[i].username, "seat": room.seats[i].seat, **rooms.seat_palette(room.seats[i].seat), "card": c})
    return {
        "expect": len(d.moves), "total": d.total, "round": d.round, "rounds": d.picks_each,
        "turn": None if seat is None else {"id": seat.account_id, "username": seat.username,
                                           "you": seat is mine, "seat": seat.seat, **rooms.seat_palette(seat.seat)},
        "deal": deal, "recent": recent,
        "server_now": time.time(), "turn_started_at": room.turn_started_at, "timer": room.timer_seconds,
    }


class RoomIn(BaseModel):
    size: int
    formation: str = DEFAULT
    memory: bool = False
    style: str = "turns"
    timer: int = 30
    bench: bool = True
    together: bool = True


class BenchIn(BaseModel):
    bench: bool


class TogetherIn(BaseModel):
    together: bool


class StyleIn(BaseModel):
    style: str
    timer: int = 30


class MemoryIn(BaseModel):
    memory: bool


class FormationIn(BaseModel):
    formation: str


class RoomPickIn(BaseModel):
    index: int
    expect: int


class RoomRerollIn(BaseModel):
    expect: int


class KickIn(BaseModel):
    account_id: int


def _room_reply(conn, request: Request, code: str) -> dict:
    return room_out(rooms.load_room(conn, code), _viewer_id(request))


@app.post("/api/rooms")
def create_room(body: RoomIn, request: Request) -> dict:
    with db.connection() as conn:
        code = rooms.create_room(conn, _signed_in(conn, request), body.size, body.formation, body.memory,
                                 body.style, body.timer, body.bench, body.together)
        return _room_reply(conn, request, code)


@app.get("/api/rooms")
def list_my_rooms(request: Request) -> dict:
    with db.connection() as conn:
        return {"rooms": rooms.my_rooms(conn, _signed_in(conn, request))}


@app.get("/api/rooms/{code}")
def get_room(code: str, request: Request, v: int | None = None) -> dict:
    """The poll. ``v`` is the version the page already shows: when the room hasn't moved
    past it the reply is a few bytes, with no replay. A run-out clock is still resolved
    first, so a quiet room can't sit on an expired turn. One query when nothing is due."""
    with db.connection() as conn:
        room = rooms.resolve_if_due(conn, load_deck(), code)      # a run-out clock picks here
    if v is not None and room.version == v:
        return {"code": room.code, "version": room.version, "unchanged": True, "server_now": time.time()}
    return room_out(room, _viewer_id(request))


@app.post("/api/rooms/{code}/join")
def join_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
        room = rooms.join_room(conn, _signed_in(conn, request), code)
        return _room_reply(conn, request, room.code)


@app.post("/api/rooms/{code}/leave")
def leave_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
        rooms.leave_room(conn, _signed_in(conn, request), code)
    return {"left": True}


@app.post("/api/rooms/{code}/kick")
def kick(code: str, body: KickIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.kick(conn, _signed_in(conn, request), code, body.account_id)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/formation")
def room_formation(code: str, body: FormationIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.set_formation(conn, _signed_in(conn, request), code, body.formation)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/style")
def room_style(code: str, body: StyleIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.set_style(conn, _signed_in(conn, request), code, body.style, body.timer)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/memory")
def room_memory(code: str, body: MemoryIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.set_memory(conn, _signed_in(conn, request), code, body.memory)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/bench")
def room_bench(code: str, body: BenchIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.set_bench(conn, _signed_in(conn, request), code, body.bench)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/together")
def room_together(code: str, body: TogetherIn, request: Request) -> dict:
    with db.connection() as conn:
        rooms.set_together(conn, _signed_in(conn, request), code, body.together)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/plan")
def room_plan(code: str, body: PlanIn, request: Request) -> dict:
    """A seat's plan, which also says it is ready (C42); `changes: null` is the automatic
    plan. The room completes when every seat is ready."""
    plan = None if body.changes is None else tuple(Change(c.on, c.minute, c.when, c.off) for c in body.changes)
    with db.connection() as conn:
        try:
            rooms.set_plan(conn, load_deck(), _signed_in(conn, request), code, plan)
        except (IllegalMove, KeyError) as e:
            raise _plan_refused(e) from None
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/sheet")
def room_sheet(code: str, body: SheetIn, request: Request) -> dict:
    """A seat's team sheet (C44): who starts where and who sits on the bench, once its
    picks are made and until the room completes. An empty body is the draft's own order."""
    with db.connection() as conn:
        try:
            rooms.set_sheet(conn, load_deck(), _signed_in(conn, request), code,
                            lambda before: new_sheet(before, body))
        except IllegalMove as e:
            raise HTTPException(400, str(e)) from None
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/start")
def start_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
        rooms.start_room(conn, _signed_in(conn, request), code)
        return _room_reply(conn, request, code)


def _room_move(code: str, request: Request, move, expect: int):
    with db.connection() as conn:
        try:
            rooms.make_move(conn, load_deck(), _signed_in(conn, request), code, move, expect)
        except IllegalMove as e:
            raise HTTPException(400, str(e)) from None
        except rooms.Conflict as e:
            # Returned, not raised: an exception would roll back any pick the clock made
            # on the way in. Sends the room as it now is (the cricket site's A146).
            return JSONResponse({"detail": str(e), "room": _room_reply(conn, request, code)}, status_code=409)
        return _room_reply(conn, request, code)


@app.post("/api/rooms/{code}/pick")
def room_pick(code: str, body: RoomPickIn, request: Request) -> dict:
    return _room_move(code, request, Pick(body.index), body.expect)


@app.post("/api/rooms/{code}/reroll")
def room_reroll(code: str, body: RoomRerollIn, request: Request) -> dict:
    return _room_move(code, request, Reroll(), body.expect)


@app.post("/api/rooms/{code}/finish")
def finish_drafts(code: str, request: Request) -> dict:
    with db.connection() as conn:
        rooms.finish_drafts(conn, load_deck(), _signed_in(conn, request), code)
        return _room_reply(conn, request, code)


def players_out(t: Tournament) -> list[dict]:
    """Every human side's run, furthest first: the table a room is really about."""
    out = []
    for side in (s for s in t.sides if s.owner is not None):
        mine = [f for f in t.fixtures if side in (f.home, f.away)]
        w = d = l = gf = ga = 0
        for f in mine:
            us, them = ((f.result.home_goals, f.result.away_goals) if f.home is side
                        else (f.result.away_goals, f.result.home_goals))
            gf, ga = gf + us, ga + them
            if f.result.pens is not None:
                won = (f.result.pens[0] > f.result.pens[1]) == (f.home is side)
                w, l = w + won, l + (not won)
            else:
                w, d, l = w + (us > them), d + (us == them), l + (us < them)
        out.append({**side_out(side), "formation": side.formation.label, "code": side.formation.code,
                    "slots": list(side.formation.slots),
                    "reached": t.reached(side), "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
                    "avg": round(sum(c.rating for c in side.xi) / 11),
                    "xi": [card_out(c) for c in side.xi]})
    return sorted(out, key=lambda p: (FINISHES.index(p["reached"]), -(p["gf"] - p["ga"]), -p["gf"]))


def _room_tournament(code: str, request: Request) -> tuple[rooms.Room, Tournament]:
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
    me = _viewer_id(request)
    if room.status != "complete":
        raise HTTPException(409, "the room's elevens are not all complete yet")
    if not _replays(room):
        raise HTTPException(409, STALE_ROOM)
    if not _watch_over(room):
        raise HTTPException(409, "the room is still watching its tournament together")
    deck = load_deck()
    humans = rooms.sides(deck, room)
    for side in humans:
        side.you = me is not None and side.owner == me
    return room, play_room(deck, league(), room.seed, humans, room.size, engine=rooms.engine(room))


def room_brief(room: rooms.Room) -> dict:
    return {"code": room.code, "size": room.size, "format": ROOM_FORMATS[room.size]}


@app.get("/api/rooms/{code}/tournament")
def room_tournament(code: str, request: Request) -> dict:
    room, t = _room_tournament(code, request)
    return {**tournament_out(t), "room": room_brief(room), "players": players_out(t)}


@app.get("/api/rooms/{code}/squads")
def room_squads(code: str, request: Request) -> dict:
    """Every seat's finished side, for the completed-draft page; once the room is
    complete, like its tournament. Your own side first, then the rest by overall rating."""
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
    me = _viewer_id(request)
    if room.status != "complete":
        raise HTTPException(409, "the room's drafts are not all finished yet")
    if not _replays(room):
        raise HTTPException(409, STALE_ROOM)
    humans = rooms.sides(load_deck(), room)
    for side in humans:
        side.you = me is not None and side.owner == me
    out = sorted((squad_out(s) for s in humans), key=lambda x: (not x["you"], -x["ratings"]["overall"]))
    return {"room": room_brief(room), "sides": out, "field": len(load_deck().club_seasons)}


@app.get("/api/rooms/{code}/analysis")
def room_analysis(code: str, request: Request) -> dict:
    room, t = _room_tournament(code, request)
    you = next((s for s in t.sides if s.you), None)
    return {"analysis": analysis_out(analyses.tournament_analysis(t, you)),
            "you": side_out(you) if you else None, "room": room_brief(room)}


# -- watching together (C52) ---------------------------------------------------

WATCH_CACHE_SIZE = 16
_watch_cache: OrderedDict = OrderedDict()
_watch_lock = threading.Lock()   # requests run on a thread pool


def _watched(room: rooms.Room) -> tuple[Tournament, list[watch.Round]]:
    """A completed room's tournament and the rounds it is watched in, at the room's pace.
    Every screen polls the watch every couple of seconds and playing a league tournament
    costs ~100 ms, so it is kept for the next request, keyed by everything the tournament
    is a function of (a seat taken out by an admin changes the key). The rounds are cut
    afresh (well under a millisecond), since the host can change the pace. Its sides are
    never marked as anyone's (``you`` stays False): callers mark their copy of the reply."""
    t = _watched_tournament(room)
    return t, watch.rounds(t, watch.minute_s(room.watch_pace))


def _watched_tournament(room: rooms.Room) -> Tournament:
    deck = load_deck()
    key = (id(deck), room.code, room.seed, room.size, room.bench, room.moves_text,
           tuple((s.account_id, s.formation, s.state, s.plan, s.sheet) for s in room.seats))
    with _watch_lock:
        hit = _watch_cache.get(key)
        if hit is not None and hit[0] is deck:
            _watch_cache.move_to_end(key)
            return hit[1]
    t = play_room(deck, league(), room.seed, rooms.sides(deck, room), room.size, engine=rooms.engine(room))
    with _watch_lock:
        _watch_cache[key] = (deck, t)
        while len(_watch_cache) > WATCH_CACHE_SIZE:
            _watch_cache.popitem(last=False)
    return t


def _watch_over(room: rooms.Room) -> bool:
    """Whether a room's whole tournament may be shown: always, unless it watches together
    (C52) and that watch hasn't reached its end."""
    if not room.together or room.status != "complete":
        return True
    if room.watch_started_at is None:
        return False
    _, rs = _watched(room)
    return rooms.watched_for(room, rooms.clock()) >= watch.end_at(rs)


def _mark_you(x, key: str | None):
    """Mark the viewer's side in a reply built from the shared tournament: every side dict
    (it has a "key" and a "you") says whether it is theirs."""
    if isinstance(x, dict):
        if "key" in x and "you" in x:
            x["you"] = key is not None and x["key"] == key
        for v in x.values():
            _mark_you(v, key)
    elif isinstance(x, list):
        for v in x:
            _mark_you(v, key)
    return x


def _part_out(t: Tournament, rs: list[watch.Round], j: int) -> dict:
    """Part j of the watch (game.watch.known): a round's pairings and timings, its results,
    or the friends' standings after it."""
    i, kind = divmod(j, len(watch.PARTS))
    r = rs[i]
    out = {"n": j, "round": i, "kind": watch.PARTS[kind]}
    if kind == 0:
        out.update(stage=r.stage, label=r.label, start=r.start, kick=r.kick, end=r.end, minutes=r.minutes,
                   pairs=[{"home": side_out(f.home), "away": side_out(f.away)} for f in r.fixtures])
    elif kind == 1:
        out["fixtures"] = [fixture_out(f, timeline=True) for f in r.fixtures]
    else:
        out["standings"] = [{**side_out(st.side), "p": st.played, "w": st.won, "d": st.drawn, "l": st.lost,
                             "gf": st.gf, "ga": st.ga, "pts": st.points, "pos": st.position, "out": st.out}
                            for st in watch.standings(t, rs, i)]
    return out


def watch_out(room: rooms.Room, me_id: int | None, have: int = 0, t0: float | None = None,
              pace: str | None = None) -> dict:
    """The watch as this screen may see it now. ``have`` is how many parts the screen
    holds; only the newer ones are sent, and none that the clock hasn't reached, so
    nobody can read a result before its kick-off. With nothing new and the same start
    (``t0``: no skip since), a few bytes. ``pace`` is the pace the screen's parts were
    timed at ("" before paces): if the host has changed it since, every part is sent again,
    since each round's timings are in its first part."""
    if not room.together:
        return {"code": room.code, "together": False}
    if room.status != "complete":
        raise HTTPException(409, "the room's elevens are not all complete yet")
    if not _replays(room):
        raise HTTPException(409, STALE_ROOM)
    now = rooms.clock()
    mine = room.seat_of(me_id) if me_id is not None else None
    if pace is not None and pace != (room.watch_pace or ""):
        have = 0
    base = {"code": room.code, "together": True, "server_now": now, "t0": room.watch_started_at,
            "started": room.watch_started_at is not None, "pace": room.watch_pace,
            "minute_s": watch.minute_s(room.watch_pace)}
    t, rs = _watched(room)
    p = None if room.watch_started_at is None else rooms.watched_for(room, now)
    n = 0 if p is None else watch.known(rs, p)
    ended = p is not None and p >= watch.end_at(rs)
    if (p is not None and not ended and n == have and t0 is not None
            and abs(t0 - room.watch_started_at) < 1e-6):
        return {**base, "unchanged": True, "have": n, "ended": False}
    host = next((s for s in room.seats if s.account_id == room.host_id), None)
    out = {
        **base, "ended": ended, "have": n,
        "format": ROOM_FORMATS[room.size], "is_host": me_id is not None and room.host_id == me_id,
        "seated": mine is not None, "host": host.username if host else None,
        "can_start": p is None and mine is not None and (room.host_id == me_id or rooms.host_waited(room, now)),
        # Seconds until any seat may kick off, while the host hasn't.
        "host_wait": (max(0.0, watch.HOST_WAIT_S - (now - room.completed_at))
                      if p is None and room.completed_at is not None else None),
        "break_s": watch.BREAK_S,
        "you": f"P{mine.seat}" if mine is not None else None,
        "humans": [side_out(s) for s in t.sides if s.owner is not None] if have == 0 else None,
        "parts": [] if ended else [_part_out(t, rs, j) for j in range(max(0, have), n)],
    }
    return _mark_you(out, out["you"])


class SkipIn(BaseModel):
    to: str
    round: int = -1
    have: int = 0
    pace: str | None = None


class PaceIn(BaseModel):
    pace: str


@app.get("/api/rooms/{code}/watch")
def get_watch(code: str, request: Request, have: int = 0, t0: float | None = None,
              pace: str | None = None) -> dict:
    """The poll while a room watches together. One query, and the tournament from the
    in-process cache."""
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
    return watch_out(room, _viewer_id(request), have, t0, pace)


@app.post("/api/rooms/{code}/watch/start")
def start_watch(code: str, request: Request) -> dict:
    with db.connection() as conn:
        rooms.start_watch(conn, _signed_in(conn, request), code)
        room = rooms.load_room(conn, code)
    return watch_out(room, _viewer_id(request))


@app.post("/api/rooms/{code}/watch/skip")
def skip_watch(code: str, body: SkipIn, request: Request) -> dict:
    """The host's skip (only the host's): to this round's kick-off or full time, past the
    league phase, or to the end."""
    with db.connection() as conn:
        rooms.skip_watch(conn, _signed_in(conn, request), code, lambda r: _watched(r)[1], body.to, body.round)
        room = rooms.load_room(conn, code)
    return watch_out(room, _viewer_id(request), body.have, pace=body.pace)


@app.post("/api/rooms/{code}/watch/pace")
def pace_watch(code: str, body: PaceIn, request: Request) -> dict:
    """The host's pace (C54), before kick-off or during the watch; every screen re-times
    at the moment it was at. The reply holds every part, timed at the new pace."""
    with db.connection() as conn:
        rooms.set_watch_pace(conn, _signed_in(conn, request), code,
                             lambda r, m: watch.rounds(_watched_tournament(r), m), body.pace)
        room = rooms.load_room(conn, code)
    return watch_out(room, _viewer_id(request))


# -- saved results and the profile (C31) ---------------------------------------

class SaveIn(BaseModel):
    source: str
    key: str


def _journey_to_save(source: str, key: str, request: Request):
    """The journey of the caller's side, rebuilt by replaying the tournament here."""
    if source == "solo":
        t = _solo_tournament(key)
    elif source == "room":
        _, t = _room_tournament(key, request)
    else:
        raise HTTPException(400, "only a solo run or a room can be saved by hand")
    you = next((s for s in t.sides if s.you), None)
    if you is None:
        raise HTTPException(403, "you don't have a side in that tournament")
    return journeys.journey(t, you), you.formation.label


@app.post("/api/results")
def save_result(body: SaveIn, request: Request) -> dict:
    j, formation = _journey_to_save(body.source, body.key, request)
    key = body.key.upper() if body.source == "room" else body.key
    with db.connection() as conn:
        me = _signed_in(conn, request)
        new = results.save(conn, me, body.source, key, j, formation)
    return {"saved": True, "new": new}


@app.get("/api/results/saved")
def result_saved(source: str, key: str, request: Request) -> dict:
    if not request.cookies.get(auth.COOKIE_NAME) or not db.configured():
        return {"saved": False}
    with db.connection() as conn:
        me = _account(conn, request)
        key = key.upper() if source == "room" else key
        return {"saved": me is not None and results.is_saved(conn, me, source, key)}


MAX_UNSAVED_KEYS = 200


class UnsavedIn(BaseModel):
    keys: list[str] = []   # solo links a browser has opened; the server keeps no solo run


@app.post("/api/results/unsaved")
def unsaved_results(body: UnsavedIn, request: Request) -> dict:
    """What this account could still save (C46): the finished solo drafts among the links
    a browser names, and the completed rooms it sat in, less what it has saved already.
    Saving each is still a POST to /api/results, which replays it."""
    keys = list(dict.fromkeys(k for k in body.keys if 0 < len(k) <= 200))[:MAX_UNSAVED_KEYS]
    with db.connection() as conn:
        me = _signed_in(conn, request)
        saved = set(conn.execute("select source, natural_key from results where account_id = %s",
                                 (me.account_id,)).fetchall())
        codes = [r[0] for r in conn.execute(
            "select r.code from rooms r join room_seats s on s.room_code = r.code"
            " where s.account_id = %s and r.status = 'complete' order by r.updated_at desc",
            (me.account_id,)).fetchall()]
        mine = rooms.load_rooms(conn, [c for c in codes if ("room", c) not in saved])   # one query, however many
    solo = []
    for k in keys:
        if ("solo", k) in saved:
            continue
        try:
            s = _replay(k)
        except HTTPException:
            continue
        if s.complete:
            solo.append({"key": k, "seed": s.seed, "formation": s.formation.label})
    return {"solo": solo,
            "rooms": [{"code": r.code, "format": ROOM_FORMATS[r.size]} for r in mine
                      if _replays(r) and _watch_over(r)]}


@app.get("/api/profile")
def profile(request: Request) -> dict:
    with db.connection() as conn:
        return results.profile(conn, _signed_in(conn, request), daily.today())


# -- the daily challenge (C32) -----------------------------------------------------

def _plan_refused(e: Exception) -> HTTPException:
    """A move or plan refused: IllegalMove says why; a KeyError is a condition no plan knows."""
    return HTTPException(400, str(e) if isinstance(e, IllegalMove) else "a change comes on a score the plan knows")


class DailyIn(BaseModel):
    moves: str = ""
    changes: list[ChangeIn] | None = None     # a bench day's plan (C42); None: automatic
    sheet: list[int] | None = None            # a bench day's team sheet (C44, C55); None: as drafted
    edition: int | None = None                # the edition of the day it was drafted in (C55)


def _daily_plan(body: DailyIn):
    return None if body.changes is None else tuple(Change(c.on, c.minute, c.when, c.off) for c in body.changes)


def hide_ratings(cards: list[dict]) -> list[dict]:
    for c in cards:
        c["rating"] = None
    return cards


def challenge_out(ch: daily_rules.Challenge, reveal: bool) -> dict:
    """The day. The daily is always drafted blind (C33): the opponent's ratings, like
    every dealt player's, stay hidden until the viewer has played the ranked match, or
    the day is over."""
    deck = load_deck()
    opp = club_side(deck.by_key[ch.opponent])
    f = FORMATIONS[ch.formation]
    xi = [card_out(c) for c in opp.xi]
    return {"day": ch.day, "formation": formation_out(f),
            "opponent": {**side_out(opp), "xi": xi if reveal else hide_ratings(xi), "shape": opp.formation.label},
            "ratings_hidden": not reveal,
            "goal": daily_rules.describe(ch.kind, ch.target), "kind": ch.kind, "target": ch.target,
            "success_rate": pct(ch.success_rate), "bench": ch.bench, "squads": 14 if ch.bench else 11,
            "edition": ch.edition}


def daily_result_out(ch, fx, j, met: bool, ranked: bool) -> dict:
    """A practice result shows no ratings: otherwise practising would tell you your
    eleven's ratings, and you could draft again knowing them before the ranked match."""
    r = fx.result
    journey = journey_out(j)
    if not ranked:
        hide_ratings(journey["players"])
    return {"met": met, "ranked": ranked, "fixture": fixture_out(fx, timeline=True), "journey": journey,
            "gf": r.home_goals, "ga": r.away_goals, "opponent": challenge_out(ch, ranked)["opponent"]}


@app.get("/api/daily")
def daily_today(request: Request, day: str | None = None) -> dict:
    d = daily.parse_day(day)
    with db.connection() as conn:
        ch = daily.get_challenge(conn, load_deck(), league(), d)
        me = _account(conn, request) if request.cookies.get(auth.COOKIE_NAME) else None
        mine = None
        if me is not None:
            row = daily.result_of(conn, d, me.account_id)
            if row is not None:
                try:
                    fx, j = daily.play(load_deck(), league(), ch, daily.moves_of(ch, row[0]), "ranked",
                                       daily.plan_of(ch, row[6]), daily.sheet_of(ch, row[7]))
                    mine = daily_result_out(ch, fx, j, row[1], True)
                except (IllegalMove, ValueError):
                    # The picks no longer replay (the deck changed since that day): the
                    # stored score stands, without the match to watch again.
                    mine = {"met": row[1], "ranked": True, "fixture": None, "journey": None,
                            "gf": row[2], "ga": row[3]}
        board = daily.board(conn, d, me)
        streak = results.streaks(daily.days_played(conn, me.account_id), daily.today()) if me else None
    return {"challenge": challenge_out(ch, reveal=mine is not None or d != daily.today()),
            "today": d == daily.today(), "signed_in": me is not None,
            "mine": mine, "board": board, "streak": None if streak is None else {"current": streak[0], "best": streak[1]}}


@app.post("/api/daily/prepare")
def daily_prepare() -> dict:
    """For the scheduled job (.github/workflows/prepare-daily.yml): today's and tomorrow's
    challenges made now rather than by the day's first visitor. Open to anyone, since it
    can only make what the next visitor would have made anyway, and once both days are
    stored it is two cheap queries. It names the days, never what is in them."""
    with db.connection() as conn:
        days = daily.prepare(conn, load_deck(), league())
    return {"ready": [d.isoformat() for d in days]}


@app.get("/api/daily/draft")
def daily_draft(request: Request, moves: str = "", day: str | None = None, sheet: str = "",
                edition: int | None = None) -> dict:
    """The day's draft so far; once it is finished, with its team sheet (``sheet``, as
    encode_sheet writes it) and where each man could be moved."""
    d = daily.parse_day(day)
    with db.connection() as conn:
        ch = daily.get_challenge(conn, load_deck(), league(), d)
    daily.check_edition(ch, edition)
    try:
        s = daily_rules.draft(load_deck(), ch, daily.moves_of(ch, moves), None, daily.sheet_of(ch, sheet or None))
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None
    # Always blind (C33): no ratings, and each line listed by name, not best first.
    return {**session_out(moves, s, memory=True), "rerolls_left": 0, "sheet": None if s.sheet is None else list(s.sheet)}


class DailySheetIn(SheetIn):
    """A move on today's team sheet (C55): the draft's ``moves``, the sheet it has now
    (``current``, None as drafted) and the move, as SheetIn says; the page keeps the result."""
    moves: str = ""
    current: list[int] | None = None
    edition: int | None = None


@app.post("/api/daily/sheet")
def daily_sheet(body: DailySheetIn) -> dict:
    """Today's team sheet after one move, worked out here (who can stand where, everyone
    else moving as little as possible) and sent back for the page to keep with its picks.
    Nothing is stored: the sheet rides with the ranked match, as the picks and plan do.
    Positions only, never a rating, so the draft stays blind (C33)."""
    with db.connection() as conn:
        ch = daily.get_challenge(conn, load_deck(), league(), daily.today())
    daily.check_edition(ch, body.edition)
    try:
        moves = daily.moves_of(ch, body.moves)
        before = daily_rules.draft(load_deck(), ch, moves, None, daily.sheet_of(ch, body.current))
        sheet = new_sheet(before, body)
        after = daily_rules.draft(load_deck(), ch, moves, None, sheet)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None
    return {**session_out(body.moves, after, memory=True), "rerolls_left": 0,
            "sheet": None if sheet is None else list(sheet)}


@app.post("/api/daily/submit")
def daily_submit(body: DailyIn, request: Request) -> dict:
    with db.connection() as conn:
        me = _signed_in(conn, request)
        try:
            ch, fx, j, ok = daily.submit(conn, load_deck(), league(), me, daily.today(), body.moves,
                                         _daily_plan(body), body.sheet, body.edition)
        except (IllegalMove, KeyError) as e:
            raise _plan_refused(e) from None
        out = daily_result_out(ch, fx, j, ok, True)
        board = daily.board(conn, daily.today(), me)
        streak = results.streaks(daily.days_played(conn, me.account_id), daily.today())
    return {**out, "board": board, "streak": {"current": streak[0], "best": streak[1]}}


@app.post("/api/daily/practice")
def daily_practice(body: DailyIn) -> dict:
    """Signed out: the same draft, played against a PRACTICE seed, kept nowhere, so it
    says nothing about how the ranked match would go."""
    d = daily.today()
    with db.connection() as conn:
        ch = daily.get_challenge(conn, load_deck(), league(), d)
    daily.check_edition(ch, body.edition)
    try:
        fx, j = daily.play(load_deck(), league(), ch, daily.moves_of(ch, body.moves), "practice",
                           daily.plan_of(ch, _daily_plan(body)), daily.sheet_of(ch, body.sheet))
    except (IllegalMove, KeyError) as e:
        raise _plan_refused(e) from None
    r = fx.result
    return daily_result_out(ch, fx, j, daily_rules.met(ch.kind, ch.target, r.home_goals, r.away_goals), False)


# An admin's controls for the daily (C55): see a day, let one account play it again,
# clear everyone's attempts, or make today again.

def _admin_day(day: str | None) -> date:
    """An admin may look at any day that has come, as anyone may: never tomorrow's, which
    the scheduled job may already have made but nobody, an admin included, should see."""
    return daily.parse_day(day)


def admin_daily_out(conn, d: date) -> dict:
    row = conn.execute("select 1 from daily_challenges where day = %s", (d,)).fetchone()
    ch = daily.get_challenge(conn, load_deck(), league(), d) if row or d == daily.today() else None
    out = {"day": d.isoformat(), "today": d == daily.today(), "now": daily.today().isoformat(),
           "days": daily.recent_days(conn, daily.today()),
           "challenge": None, "rows": []}
    if ch is not None:
        opp = load_deck().by_key[ch.opponent]
        made = conn.execute("select created_at from daily_challenges where day = %s", (d,)).fetchone()[0]
        out["challenge"] = {"formation": FORMATIONS[ch.formation].label, "opponent": opp.title,
                            "goal": daily_rules.describe(ch.kind, ch.target), "success_rate": pct(ch.success_rate),
                            "bench": ch.bench, "edition": ch.edition, "made_at": made.isoformat()}
        out.update(daily.admin_day(conn, d))
    return out


@app.get("/api/admin/daily")
def admin_daily(request: Request, day: str | None = None) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        return admin_daily_out(conn, _admin_day(day))


@app.delete("/api/admin/daily/{account_id}")
def admin_reset_daily(account_id: int, request: Request, day: str | None = None) -> dict:
    """One account's attempt at a day (today unless ``day``) gone, so it can play again."""
    with db.connection() as conn:
        _admin(conn, request)
        return {"reset": daily.reset(conn, _admin_day(day), account_id)}


@app.post("/api/admin/daily/clear")
def admin_clear_daily(request: Request, day: str | None = None) -> dict:
    """Every attempt at a day gone: the same challenge, open to everyone again."""
    with db.connection() as conn:
        _admin(conn, request)
        d = _admin_day(day)
        return {"cleared": daily.clear(conn, d), **admin_daily_out(conn, d)}


@app.post("/api/admin/daily/remake")
def admin_remake_daily(request: Request) -> dict:
    """Today made again: new squads, opponent and goal, every attempt cleared."""
    with db.connection() as conn:
        _admin(conn, request)
        before = conn.execute("select count(*) from daily_results where day = %s", (daily.today(),)).fetchone()[0]
        daily.remake(conn, load_deck(), league(), daily.today())
        return {"cleared": before, **admin_daily_out(conn, daily.today())}


# -- what browsers saw go wrong ----------------------------------------------

class FailureIn(BaseModel):
    kind: str
    detail: str
    page: str = ""


@app.post("/api/client-failures", status_code=204)
def client_failure(body: FailureIn) -> PlainResponse:
    """Always 204: a report that can't be kept is lost quietly, never an error the page
    would then try to report."""
    if db.configured():
        try:
            with db.connection() as conn:
                failures.record(conn, body.kind, body.detail, body.page)
        except psycopg.Error:
            pass
    return PlainResponse(status_code=204)


# -- admin ------------------------------------------------------------------

def _admin(conn, request: Request) -> accounts.Account:
    """404, not 403, for anyone who isn't an admin: the routes don't confirm they exist."""
    me = _account(conn, request) if request.cookies.get(auth.COOKIE_NAME) else None
    if not admin.is_admin(me):
        raise HTTPException(404, "Not Found")
    return me


class PasswordIn(BaseModel):
    password: str


@app.get("/api/admin/overview")
def admin_overview(request: Request) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        return admin.overview(conn)


@app.get("/api/admin/accounts")
def admin_accounts(request: Request, q: str = "") -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        return {"accounts": admin.search_accounts(conn, q)}


@app.post("/api/admin/accounts/{account_id}/password")
def admin_password(account_id: int, body: PasswordIn, request: Request) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        admin.set_password(conn, account_id, body.password)
    return {"ok": True}


@app.delete("/api/admin/accounts/{account_id}")
def admin_delete_account(account_id: int, request: Request) -> dict:
    with db.connection() as conn:
        admin.delete_account(conn, account_id, _admin(conn, request))
    return {"ok": True}


@app.get("/api/admin/rooms")
def admin_rooms(request: Request) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        return {"rooms": admin.list_rooms(conn)}


@app.delete("/api/admin/rooms/{code}")
def admin_delete_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        admin.delete_room(conn, code)
    return {"ok": True}


# -- pages ------------------------------------------------------------------

def _page(name: str):
    def serve() -> FileResponse:
        return FileResponse(STATIC / f"{name}.html")
    return serve


PAGES = (("/", "index"), ("/start", "start"), ("/draft", "draft"), ("/cup", "cup"), ("/archive", "archive"),
         ("/friends", "friends"), ("/room", "room"), ("/about", "about"), ("/faq", "faq"),
         ("/privacy", "privacy"), ("/terms", "terms"), ("/offline", "offline"), ("/admin", "admin"),
         ("/analysis", "analysis"), ("/daily", "daily"), ("/profile", "profile"), ("/squad", "squad"))
for _path, _name in PAGES:
    app.add_api_route(_path, _page(_name), methods=["GET"], include_in_schema=False)


# The service worker is served from the root so its scope is the whole site; vercel.json
# routes it the same way and never lets it be cached.
@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                        headers={"cache-control": "no-cache", "service-worker-allowed": "/"})
