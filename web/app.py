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
from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, Response as PlainResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import match
from game.deck import Card, ClubSeason, load_deck
from game.draft import IllegalMove, Pick, Reroll, Session, decode, encode, replay, why_not
from game.formations import DEFAULT, FORMATIONS
from game.tournament import (CUP_STAGES, Fixture, Side, Tournament, leaders, league_of,
                             play_room, play_tournament)
from web import accounts, admin, auth, db, failures, rooms
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
    return {
        "id": c.id, "name": c.name, "pos": c.pos, "nation": c.nation, "rating": c.rating,
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
    if memory:
        for c in [*picks, *(deal["cards"] if deal else [])]:
            c["rating"] = None
    return {
        "state": state, "seed": s.seed, "memory": memory,
        "formation": {"code": s.formation.code, "label": s.formation.label, "lines": s.formation.lines},
        "picks": picks,
        "deal": deal, "rerolls_left": s.rerolls_left, "complete": s.complete,
    }


def side_out(side: Side) -> dict:
    out = {"key": side.key, "name": side.name, "short": side.short, "you": side.you,
           "club": side.club_name, "season": side.label, "crest": crest_url(side.crest),
           **colours(side)}
    if side.owner is not None:
        out["human"] = True
    return out


def fixture_out(f: Fixture) -> dict:
    r = f.result
    return {
        "stage": f.stage, "label": f.label, "group": f.group,
        "home": side_out(f.home), "away": side_out(f.away),
        "hg": r.home_goals, "ag": r.away_goals, "extra_time": r.extra_time,
        "pens": list(r.pens) if r.pens else None,
        "goals": [{"minute": g.minute, "side": g.side, "scorer": g.scorer.name,
                   "assist": g.assist.name if g.assist else None} for g in r.goals],
    }


def leader_out(card: Card, side: Side, n: int) -> dict:
    out = {"name": card.name, "side": "Your XI" if side.you else side.name,
           "crest": crest_url(side.crest), "you": side.you, "n": n}
    if side.owner is not None:
        out.update(human=True, **colours(side))
    return out


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
            "xi": [card_out(c) for c in you.xi]},
        "your_matches": [fixture_out(f) for f in t.fixtures if you in (f.home, f.away)],
        "groups": groups, "knockout": knockout,
        "champion": side_out(t.champion), "reached": t.reached(you) if you else None,
        "golden_boot": [leader_out(c, s, n) for c, s, n in leaders(t, "goals", 10)],
        "assists": [leader_out(c, s, n) for c, s, n in leaders(t, "assists", 5)],
    }


# -- routes -----------------------------------------------------------------

def _decode(state: str):
    try:
        return decode(state)
    except IllegalMove as e:
        raise HTTPException(400, str(e)) from None


def _replay(state: str) -> Session:
    seed, formation, moves = _decode(state)
    try:
        return replay(load_deck(), seed, formation, moves)
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
        "formations": [{"code": f.code, "label": f.label} for f in FORMATIONS.values()],
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
# either way, so `?memory=1` rides alongside it on every call.
@app.post("/api/draft")
def start(body: StartIn, memory: bool = False) -> dict:
    seed = body.seed if body.seed is not None else random.SystemRandom().randrange(1, 10**9)
    state = encode(seed, body.formation, [])
    return session_out(state, _replay(state), memory)


@app.get("/api/draft/{state}")
def get_draft(state: str, memory: bool = False) -> dict:
    return session_out(state, _replay(state), memory)


class PickIn(BaseModel):
    index: int


@app.post("/api/draft/{state}/pick")
def pick(state: str, body: PickIn, memory: bool = False) -> dict:
    seed, formation, moves = _decode(state)
    new = encode(seed, formation, moves + [Pick(body.index)])
    return session_out(new, _replay(new), memory)


@app.post("/api/draft/{state}/reroll")
def reroll(state: str, memory: bool = False) -> dict:
    seed, formation, moves = _decode(state)
    new = encode(seed, formation, moves + [Reroll()])
    return session_out(new, _replay(new), memory)


@app.get("/api/tournament/{state}")
def tournament(state: str) -> dict:
    s = _replay(state)
    if not s.complete:
        raise HTTPException(409, "the eleven is not complete yet")
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    return tournament_out(play_tournament(load_deck(), league(), s.seed, you))


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


def room_out(room: rooms.Room, me: accounts.Account | None) -> dict:
    mine = room.seat_of(me.account_id) if me else None
    draft = None
    if mine is not None and room.status == "drafting":
        draft = session_out(mine.state, _replay(mine.state), room.memory)
    return {
        "code": room.code, "size": room.size, "format": ROOM_FORMATS[room.size],
        "memory": room.memory,
        "stages": CUP_STAGES.get(room.size, ["Group stage", *CUP_STAGES[16]]),
        "status": room.status, "version": room.version,
        "is_host": me is not None and room.host_id == me.account_id,
        "seated": mine is not None,
        "seats": [{
            "id": s.account_id, "username": s.username, "seat": s.seat,
            "formation": FORMATIONS[s.formation].label, "code": s.formation,
            "picks": s.picks, "complete": s.complete, "host": s.account_id == room.host_id,
            "you": mine is s, **rooms.seat_palette(s.seat),
        } for s in room.seats],
        "fillers": room.size - len(room.seats),
        "draft": draft,
    }


class RoomIn(BaseModel):
    size: int
    formation: str = DEFAULT
    memory: bool = False


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
        code = rooms.create_room(conn, _signed_in(conn, request), body.size, body.formation, body.memory)
        return _room_reply(conn, request, code)


@app.get("/api/rooms")
def list_my_rooms(request: Request) -> dict:
    with db.connection() as conn:
        return {"rooms": rooms.my_rooms(conn, _signed_in(conn, request))}


@app.get("/api/rooms/{code}")
def get_room(code: str, request: Request) -> dict:
    with db.connection() as conn:
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


def _room_move(code: str, request: Request, move, expect: int) -> dict:
    with db.connection() as conn:
        try:
            rooms.make_move(conn, load_deck(), _signed_in(conn, request), code, move, expect)
        except IllegalMove as e:
            raise HTTPException(400, str(e)) from None
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
                    "reached": t.reached(side), "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
                    "avg": round(sum(c.rating for c in side.xi) / 11),
                    "xi": [card_out(c) for c in side.xi]})
    return sorted(out, key=lambda p: (REACHED_ORDER.index(p["reached"]), -(p["gf"] - p["ga"]), -p["gf"]))


@app.get("/api/rooms/{code}/tournament")
def room_tournament(code: str, request: Request) -> dict:
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
        me = _account(conn, request)
    if room.status != "complete":
        raise HTTPException(409, "the room's elevens are not all complete yet")
    deck = load_deck()
    humans = rooms.sides(deck, room)
    for side in humans:
        side.you = me is not None and side.owner == me.account_id
    t = play_room(deck, league(), room.seed, humans, room.size)
    return {**tournament_out(t), "room": {"code": room.code, "size": room.size,
                                          "format": ROOM_FORMATS[room.size]},
            "players": players_out(t)}


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


PAGES = (("/", "index"), ("/draft", "draft"), ("/cup", "cup"), ("/archive", "archive"),
         ("/friends", "friends"), ("/room", "room"), ("/about", "about"), ("/faq", "faq"),
         ("/privacy", "privacy"), ("/terms", "terms"), ("/offline", "offline"), ("/admin", "admin"))
for _path, _name in PAGES:
    app.add_api_route(_path, _page(_name), methods=["GET"], include_in_schema=False)


# The service worker is served from the root so its scope is the whole site; vercel.json
# routes it the same way and never lets it be cached.
@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                        headers={"cache-control": "no-cache", "service-worker-allowed": "/"})
