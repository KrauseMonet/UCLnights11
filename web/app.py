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
import time
from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, Response as PlainResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import analysis as analyses, daily as daily_rules, journey as journeys, match
from game.deck import Card, ClubSeason, load_deck
from game.draft import IllegalMove, Pick, Reroll, Session, decode, decode_state, encode, replay, why_not
from game.formations import DEFAULT, FORMATIONS
from game.positions import arrange
from game.shared_draft import Stranded
from game.tournament import (CUP_STAGES, Fixture, Side, Tournament, auto_plan, club_side, leaders,
                             league_of, play_room, play_tournament)
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
    bench = picks[11:]
    if memory:
        for c in [*picks, *(deal["cards"] if deal else [])]:
            c["rating"] = None
    return {
        "state": state, "seed": s.seed, "memory": memory,
        "formation": formation_out(s.formation),
        "picks": picks, "xi": eleven_out(s.formation, s.picks[:11], memory),
        "bench": bench, "bench_size": s.bench_size, "total": s.total,
        "deal": deal, "rerolls_left": s.rerolls_left, "complete": s.complete,
    }


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
        # Engine 2's changes (C39), [minute, side, off, on]; none in engine 1.
        out["subs"] = [[x.minute, x.side, x.off.name, x.on.name] for x in r.subs]
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
    groups = [{
        "name": g,
        "table": [{**side_out(r.side), "p": r.played, "w": r.won, "d": r.drawn, "l": r.lost,
                   "gf": r.gf, "ga": r.ga, "pts": r.points} for r in rows],
    } for g, rows in t.tables.items()]
    return {
        "you": None if you is None else {
            **side_out(you), "formation": you.formation.label, "code": you.formation.code,
            "slots": list(you.formation.slots), "xi": [card_out(c) for c in you.xi],
            "bench": [card_out(c) for c in you.bench]},
        "your_matches": [fixture_out(f, timeline=True) for f in t.fixtures if you in (f.home, f.away)],
        "groups": groups, "knockout": knockout,
        "champion": side_out(t.champion), "reached": t.reached(you) if you else None,
        "journey": journey_out(journeys.journey(t, you)) if you else None,
        "golden_boot": [leader_out(c, s, n) for c, s, n in leaders(t, "goals", 10)],
        "assists": [leader_out(c, s, n) for c, s, n in leaders(t, "assists", 5)],
    }


# -- routes -----------------------------------------------------------------

def _decode(state: str):
    """A solo draft's (seed, formation, moves, bench): either kind of state."""
    try:
        return decode_state(state)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None


def _replay(state: str) -> Session:
    seed, formation, moves, bench = _decode(state)
    try:
        return replay(load_deck(), seed, formation, moves, bench)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/health")
def health() -> dict:
    """For the keep-warm ping (.github/workflows/keep-warm.yml). It loads the deck, which
    is what a cold start is slow at, and never touches the database: a ping every few
    minutes must not keep Neon's compute awake."""
    return {"ok": True, "club_seasons": len(load_deck().club_seasons), "accounts": db.configured()}


@app.get("/api/meta")
def meta() -> dict:
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
def showcase() -> list[dict]:
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
def archive() -> dict:
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
def squad(key: str) -> dict:
    cs = load_deck().by_key.get(key)
    if cs is None:
        raise HTTPException(404, "no such squad")
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
    state = encode(seed, body.formation, [], bench=True)
    return session_out(state, _replay(state), memory)


@app.get("/api/draft/{state}")
def get_draft(state: str, memory: bool = False) -> dict:
    return session_out(state, _replay(state), memory)


class PickIn(BaseModel):
    index: int


@app.post("/api/draft/{state}/pick")
def pick(state: str, body: PickIn, memory: bool = False) -> dict:
    seed, formation, moves, bench = _decode(state)
    new = encode(seed, formation, moves + [Pick(body.index)], bench)
    return session_out(new, _replay(new), memory)


@app.post("/api/draft/{state}/reroll")
def reroll(state: str, memory: bool = False) -> dict:
    seed, formation, moves, bench = _decode(state)
    new = encode(seed, formation, moves + [Reroll()], bench)
    return session_out(new, _replay(new), memory)


def _solo_tournament(state: str) -> Tournament:
    """A bench draft plays engine 2 with its bench on the automatic plan (C40); an
    eleven-pick draft plays engine 1, as every link to one always has."""
    s = _replay(state)
    if not s.complete:
        raise HTTPException(409, "the squad is not complete yet" if s.bench_size else "the eleven is not complete yet")
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks[:11], you=True,
               bench=s.bench, plan=auto_plan(s.bench))
    return play_tournament(load_deck(), league(), s.seed, you, engine=2 if s.bench_size else 1)


@app.get("/api/tournament/{state}")
def tournament(state: str) -> dict:
    return tournament_out(_solo_tournament(state))


@app.get("/api/tournament/{state}/analysis")
def tournament_analysis(state: str) -> dict:
    t = _solo_tournament(state)
    you = next((s for s in t.sides if s.you), None)
    return {"analysis": analysis_out(analyses.tournament_analysis(t, you)), "you": side_out(you)}


# -- accounts ---------------------------------------------------------------

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
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE_NAME, auth.make_session_cookie(account.account_id),
                        max_age=auth.SESSION_MAX_AGE_S, httponly=True, samesite="lax",
                        secure=https, path="/")
    return {"account": account_out(account)}


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
def me(request: Request) -> dict:
    # No cookie, no database: a signed-out visitor costs nothing, and the solo game
    # keeps working on a server with no database at all.
    if not request.cookies.get(auth.COOKIE_NAME) or not db.configured():
        return {"account": None}
    with db.connection() as conn:
        a = _account(conn, request)
    return {"account": account_out(a) if a else None}


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
                32: "32-team tournament"}


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
                    replay(load_deck(), *decode(seat.state))
    except (IllegalMove, Stranded):
        return False
    return True


def room_out(room: rooms.Room, me: accounts.Account | None) -> dict:
    mine = room.seat_of(me.account_id) if me else None
    draft = None
    turns = None
    if not _replays(room):
        room.status, room.failure_reason = "failed", STALE_ROOM
    picks = {s.account_id: (s.picks, s.complete) for s in room.seats}
    if room.turns and room.status in ("drafting", "complete"):
        d = rooms.shared_of(load_deck(), room)
        picks = {s.account_id: (len(p), len(p) == 11) for s, p in zip(room.seats, d.picks)}
        turns = turns_out(room, d, mine)
        if mine is not None:
            i = room.seats.index(mine)
            mine_picks = [card_out(c) for c in d.picks[i]]
            if room.memory:
                for c in mine_picks:
                    c["rating"] = None
            f = d.formations[i]
            draft = {"formation": formation_out(f),
                     "picks": mine_picks, "xi": eleven_out(f, d.picks[i], room.memory), "complete": len(d.picks[i]) == 11, "memory": room.memory,
                     "state": room.moves_text}
    elif mine is not None and room.status == "drafting":
        draft = session_out(mine.state, _replay(mine.state), room.memory)
    return {
        "code": room.code, "size": room.size, "format": ROOM_FORMATS[room.size],
        "memory": room.memory, "style": room.style, "timer": room.timer_seconds,
        "stages": CUP_STAGES.get(room.size, ["Group stage", *CUP_STAGES[16]]),
        "status": room.status, "version": room.version, "failure_reason": room.failure_reason,
        "is_host": me is not None and room.host_id == me.account_id,
        "seated": mine is not None,
        "seats": [{
            "id": s.account_id, "username": s.username, "seat": s.seat,
            "formation": FORMATIONS[s.formation].label, "code": s.formation,
            "picks": picks[s.account_id][0], "complete": picks[s.account_id][1],
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
        "expect": len(d.moves), "total": d.total, "round": d.round, "rounds": 11,
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
    return room_out(rooms.load_room(conn, code), _account(conn, request))


@app.post("/api/rooms")
def create_room(body: RoomIn, request: Request) -> dict:
    with db.connection() as conn:
        code = rooms.create_room(conn, _signed_in(conn, request), body.size, body.formation, body.memory,
                                 body.style, body.timer)
        return _room_reply(conn, request, code)


@app.get("/api/rooms")
def list_my_rooms(request: Request) -> dict:
    with db.connection() as conn:
        return {"rooms": rooms.my_rooms(conn, _signed_in(conn, request))}


@app.get("/api/rooms/{code}")
def get_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
        rooms.resolve_if_due(conn, load_deck(), code)      # a run-out clock picks here
        return _room_reply(conn, request, code)


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


REACHED_ORDER = ["Champions", "Runners-up", "Semi-finals", "Quarter-finals", "Round of 16",
                 "Group stage"]


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
    return sorted(out, key=lambda p: (REACHED_ORDER.index(p["reached"]), -(p["gf"] - p["ga"]), -p["gf"]))


def _room_tournament(code: str, request: Request) -> tuple[rooms.Room, Tournament]:
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
        me = _account(conn, request)
    if room.status != "complete":
        raise HTTPException(409, "the room's elevens are not all complete yet")
    if not _replays(room):
        raise HTTPException(409, STALE_ROOM)
    deck = load_deck()
    humans = rooms.sides(deck, room)
    for side in humans:
        side.you = me is not None and side.owner == me.account_id
    return room, play_room(deck, league(), room.seed, humans, room.size)


def room_brief(room: rooms.Room) -> dict:
    return {"code": room.code, "size": room.size, "format": ROOM_FORMATS[room.size]}


@app.get("/api/rooms/{code}/tournament")
def room_tournament(code: str, request: Request) -> dict:
    room, t = _room_tournament(code, request)
    return {**tournament_out(t), "room": room_brief(room), "players": players_out(t)}


@app.get("/api/rooms/{code}/analysis")
def room_analysis(code: str, request: Request) -> dict:
    room, t = _room_tournament(code, request)
    you = next((s for s in t.sides if s.you), None)
    return {"analysis": analysis_out(analyses.tournament_analysis(t, you)),
            "you": side_out(you) if you else None, "room": room_brief(room)}


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


@app.get("/api/profile")
def profile(request: Request) -> dict:
    with db.connection() as conn:
        return results.profile(conn, _signed_in(conn, request), daily.today())


# -- the daily challenge (C32) -----------------------------------------------------

class DailyIn(BaseModel):
    moves: str = ""


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
            "success_rate": pct(ch.success_rate)}


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
                    fx, j = daily.play(load_deck(), league(), ch, daily.moves_of(ch, row[0]), "ranked")
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


@app.get("/api/daily/draft")
def daily_draft(request: Request, moves: str = "", day: str | None = None) -> dict:
    d = daily.parse_day(day)
    with db.connection() as conn:
        ch = daily.get_challenge(conn, load_deck(), league(), d)
    try:
        s = daily_rules.draft(load_deck(), ch, daily.moves_of(ch, moves))
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None
    # Always blind (C33): no ratings, and each line listed by name, not best first.
    return {**session_out(moves, s, memory=True), "rerolls_left": 0}


@app.post("/api/daily/submit")
def daily_submit(body: DailyIn, request: Request) -> dict:
    with db.connection() as conn:
        me = _signed_in(conn, request)
        try:
            ch, fx, j, ok = daily.submit(conn, load_deck(), league(), me, daily.today(), body.moves)
        except IllegalMove as e:
            raise HTTPException(400, str(e)) from None
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
    try:
        fx, j = daily.play(load_deck(), league(), ch, daily.moves_of(ch, body.moves), "practice")
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None
    r = fx.result
    return daily_result_out(ch, fx, j, daily_rules.met(ch.kind, ch.target, r.home_goals, r.away_goals), False)


@app.delete("/api/admin/daily/{account_id}")
def admin_reset_daily(account_id: int, request: Request) -> dict:
    with db.connection() as conn:
        _admin(conn, request)
        return {"reset": daily.reset(conn, daily.today(), account_id)}


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
         ("/analysis", "analysis"), ("/daily", "daily"), ("/profile", "profile"))
for _path, _name in PAGES:
    app.add_api_route(_path, _page(_name), methods=["GET"], include_in_schema=False)


# The service worker is served from the root so its scope is the whole site; vercel.json
# routes it the same way and never lets it be cached.
@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                        headers={"cache-control": "no-cache", "service-worker-allowed": "/"})
