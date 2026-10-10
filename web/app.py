"""The HTTP API and the pages. Stateless: every request replays from its state string.

A draft's whole state is ``SEED-FORMATION-moves`` (game.draft.encode), carried in
the page's URL. The server stores nothing, so there is no session to lose, a
draft survives a reload, and a link reproduces it exactly.
"""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game import match
from game.deck import Card, ClubSeason, load_deck
from game.draft import IllegalMove, Pick, Reroll, Session, decode, encode, replay, why_not
from game.formations import DEFAULT, FORMATIONS
from game.tournament import STAGES, Fixture, Side, Tournament, leaders, league_of, play_tournament

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
# Three sides the home page fans out: the game's idea in one picture.
SHOWCASE = ("1998-MUN", "2010-BAR", "2001-RMA")

app = FastAPI(title="Campeones")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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


def session_out(state: str, s: Session) -> dict:
    deal = None
    if s.deal is not None:
        deal = club_season_out(s.deal, [card_out(c, why_not(c, s.formation, s.picks)) for c in s.deal.cards])
    return {
        "state": state, "seed": s.seed,
        "formation": {"code": s.formation.code, "label": s.formation.label, "lines": s.formation.lines},
        "picks": [card_out(c) for c in s.picks],
        "deal": deal, "rerolls_left": s.rerolls_left, "complete": s.complete,
    }


def side_out(side: Side) -> dict:
    return {"key": side.key, "name": side.name, "short": side.short, "you": side.you,
            "club": side.club_name, "season": side.label, "crest": crest_url(side.crest),
            **colours(side)}


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
    return {"name": card.name, "side": "Your XI" if side.you else side.name,
            "crest": crest_url(side.crest), "you": side.you, "n": n}


def tournament_out(t: Tournament) -> dict:
    you = t.you()
    knockout = []
    for stage in STAGES[1:]:
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
        "you": {**side_out(you), "formation": you.formation.label, "code": you.formation.code,
                "xi": [card_out(c) for c in you.xi]},
        "your_matches": [fixture_out(f) for f in t.fixtures if you in (f.home, f.away)],
        "groups": groups, "knockout": knockout,
        "champion": side_out(t.champion), "reached": t.reached(you),
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
    return json.loads((ROOT / "data" / "squads.json").read_text())["gaps"]


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


@app.post("/api/draft")
def start(body: StartIn) -> dict:
    seed = body.seed if body.seed is not None else random.SystemRandom().randrange(1, 10**9)
    state = encode(seed, body.formation, [])
    return session_out(state, _replay(state))


@app.get("/api/draft/{state}")
def get_draft(state: str) -> dict:
    return session_out(state, _replay(state))


class PickIn(BaseModel):
    index: int


@app.post("/api/draft/{state}/pick")
def pick(state: str, body: PickIn) -> dict:
    seed, formation, moves = _decode(state)
    new = encode(seed, formation, moves + [Pick(body.index)])
    return session_out(new, _replay(new))


@app.post("/api/draft/{state}/reroll")
def reroll(state: str) -> dict:
    seed, formation, moves = _decode(state)
    new = encode(seed, formation, moves + [Reroll()])
    return session_out(new, _replay(new))


@app.get("/api/tournament/{state}")
def tournament(state: str) -> dict:
    s = _replay(state)
    if not s.complete:
        raise HTTPException(409, "the eleven is not complete yet")
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    return tournament_out(play_tournament(load_deck(), league(), s.seed, you))


def _page(name: str):
    def serve() -> FileResponse:
        return FileResponse(STATIC / f"{name}.html")
    return serve


for _path, _name in (("/", "index"), ("/draft", "draft"), ("/cup", "cup"), ("/archive", "archive")):
    app.add_api_route(_path, _page(_name), methods=["GET"], include_in_schema=False)
