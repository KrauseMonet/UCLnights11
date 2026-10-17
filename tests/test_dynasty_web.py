"""Dynasty mode's API (C64): the routes edit the last season or open the next one's window."""

from fastapi.testclient import TestClient

from game import dynasty as dy
from game.deck import load_deck
from game.tournament import league_of
from web import app as web_app
from web.app import app, session_out

client = TestClient(app)


def fill(d):
    """Take the best-rated man the deal offers until the season's squad is complete."""
    while not d["complete"]:
        i = max((c for c in d["deal"]["cards"] if c["takeable"]), key=lambda c: c["rating"])["i"]
        d = client.post(f"/api/dynasty/{d['state']}/pick", json={"index": i}).json()
    return d


def first_season(seed=11, formation="433"):
    return fill(client.post("/api/dynasty", json={"formation": formation, "seed": seed}).json())


def test_a_dynasty_starts_as_a_league_draft():
    d = client.post("/api/dynasty", json={"formation": "4231", "seed": 5}).json()
    assert d["state"] == "y5-4231" and d["total"] == 14
    assert d["dynasty"]["season"] == 1 and d["dynasty"]["fates"] == [] and d["waiting"] == []
    assert not d["dynasty"]["reshape"] and d["dynasty"]["length"] == dy.LENGTH


def test_a_finished_season_plays_its_tournament_and_it_is_the_game_modules():
    d = first_season()
    r = client.get(f"/api/dynasty/{d['state']}/tournament")
    assert r.status_code == 200 and "s-maxage" in r.headers["cache-control"]
    t = r.json()
    deck = load_deck()
    game = dy.season_tournament(deck, league_of(deck), dy.replay(deck, d["state"])[-1])
    assert t["reached"] == game.reached(game.you()) and t["dynasty"]["season"] == 1
    assert [(f["hg"], f["ag"]) for f in t["your_matches"]] == \
        [(f.result.home_goals, f.result.away_goals) for f in game.fixtures if game.you() in (f.home, f.away)]


def test_an_unfinished_season_has_no_tournament_and_no_window():
    d = client.post("/api/dynasty", json={"seed": 3}).json()
    assert client.get(f"/api/dynasty/{d['state']}/tournament").status_code == 409
    r = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"})
    assert r.status_code == 409


def test_a_window_says_what_became_of_each_man():
    d = first_season()
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    assert w["state"] == d["state"] + "~433-x" and w["dynasty"]["season"] == 2
    deck = load_deck()
    fates = dy.replay(deck, w["state"])[-1].fates
    assert [f["reason"] for f in w["dynasty"]["fates"]] == [f.reason for f in fates]
    for out, f in zip(w["dynasty"]["fates"], fates):
        assert out["from"]["key"] == f.card.key
        assert (out["to"] or {}).get("key") == (f.next.key if f.next else None)
        assert out["jump"] == (f.next.season - f.card.season if f.next else None)
        assert out["moved"] == (f.next is not None and f.next.club_name != f.card.club_name)
    held = {c["id"] for c in [*w["picks"], *w["waiting"]]}
    assert held == {f.next.id for f in fates if f.reason in ("carried", "skipped")}


def test_a_window_is_chosen_again_only_before_its_first_pick():
    d = first_season()
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    assert w["dynasty"]["reshape"]
    keep = [f["i"] for f in w["dynasty"]["fates"] if f["to"]][:2]
    w = client.post(f"/api/dynasty/{w['state']}/window", json={"formation": "442", "releases": keep[::-1],
                                                               "reshape": True}).json()
    assert w["formation"]["code"] == "442" and w["dynasty"]["released"] == sorted(keep)
    assert all(f["reason"] == "released" for f in w["dynasty"]["fates"] if f["i"] in keep)
    if not w["complete"]:
        i = next(c["i"] for c in w["deal"]["cards"] if c["takeable"])
        w = client.post(f"/api/dynasty/{w['state']}/pick", json={"index": i}).json()
    assert not w["dynasty"]["reshape"]
    r = client.post(f"/api/dynasty/{w['state']}/window", json={"formation": "433", "reshape": True})
    assert r.status_code == 400


def test_a_window_releases_at_most_three():
    d = first_season()
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    keep = [f["i"] for f in w["dynasty"]["fates"] if f["to"]][:4]
    r = client.post(f"/api/dynasty/{w['state']}/window", json={"formation": "433", "releases": keep, "reshape": True})
    assert r.status_code == 400 and "at most" in r.json()["detail"]


def test_season_one_cannot_be_chosen_again_as_a_window():
    d = first_season()
    r = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "442", "reshape": True})
    assert r.status_code == 400


def test_the_deal_says_why_by_the_seasons_own_rule(monkeypatch):
    # The window's rule (a kept substitute waiting for the bench) is the season's, not the
    # draft's: the reply must ask the season.
    d = first_season()
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    assert not w["complete"], "this seed's window has places to fill"
    monkeypatch.setattr(dy.Season, "why_not", lambda self, card: "asked the season")
    w = client.get(f"/api/dynasty/{w['state']}").json()
    assert {c["reason"] for c in w["deal"]["cards"]} == {"asked the season"}


def test_session_out_uses_the_rule_it_is_given():
    deck = load_deck()
    s = dy.replay(deck, "y3-433")[-1].session
    out = session_out("y3-433", s, why=lambda c: "given")
    assert {c["reason"] for c in out["deal"]["cards"]} == {"given"}


def test_a_plan_and_sheet_are_the_last_seasons():
    d = first_season()
    assert client.post("/api/dynasty/y3-433/plan", json={"changes": []}).status_code == 409
    k, man = next((k, c) for k, c in enumerate(d["bench"]) if any(x.startswith("s") for x in c["to"]))
    p = client.post(f"/api/dynasty/{d['state']}/plan", json={"changes": [{"on": k, "minute": 60, "when": "any"}]})
    assert p.status_code == 200 and p.json()["plan_chosen"] and p.json()["state"].endswith(f"-p{k}a60")
    to = next(x for x in man["to"] if x.startswith("s"))
    s = client.post(f"/api/dynasty/{p.json()['state']}/sheet", json={"man": man["p"], "to": to}).json()
    assert s["sheet_chosen"] and "-s" in s["state"]
    # The plan followed its men (carry_plan): its substitute now starts, so his line went.
    assert s["plan_chosen"] and s["plan"] == []


def test_the_record_holds_finished_seasons_only():
    d = first_season()
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    r = client.get(f"/api/dynasty/{w['state']}/record").json()
    t = client.get(f"/api/dynasty/{d['state']}/tournament").json()
    if w["complete"]:
        assert len(r["seasons"]) == 2
    else:
        assert len(r["seasons"]) == 1
    assert r["seasons"][0]["reached"] == t["reached"]
    mine = t["your_matches"]
    assert sum(x["w"] + x["d"] + x["l"] for x in r["seasons"][:1]) == len(mine)


def test_a_bad_state_is_a_400():
    assert client.get("/api/dynasty/l3-433").status_code == 400
    assert client.get("/api/dynasty/y3-433~433-x").status_code == 400


def test_the_dynasty_page_is_served():
    assert client.get("/dynasty").status_code == 200
    assert web_app.PAGES[-1] == ("/dynasty", "dynasty")


# -- the dynasty so far (C66) --------------------------------------------------------------

def test_the_legacy_needs_a_finished_season_and_covers_only_the_state_it_is_given():
    assert client.get("/api/dynasty/y3-433/legacy").status_code == 409
    d = first_season()
    w = fill(client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "442"}).json())
    one = client.get(f"/api/dynasty/{d['state']}/legacy").json()
    two = client.get(f"/api/dynasty/{w['state']}/legacy").json()
    assert one["seasons"] == 1 and two["seasons"] == 2
    assert one["team"]["formation"]["code"] == "433"
    assert two["team"]["formation"]["code"] == "442"                    # a tie: the later
    apps = lambda L: sum(c["apps"] for c in L["scorers"])  # noqa: E731
    assert apps(two) >= apps(one)
    goals = [c["goals"] for c in two["scorers"]]
    assert goals == sorted(goals, reverse=True) and len(goals) <= 5
    for x in two["team"]["xi"]:
        if x["man"]:
            assert x["slot"] in x["man"]["played"]          # a place he held in a season with you


def test_every_man_in_the_squad_has_his_run():
    d = first_season()
    assert set(d["dynasty"]["runs"]) == {c["id"] for c in d["picks"]} and set(d["dynasty"]["runs"].values()) == {1}
    w = client.post(f"/api/dynasty/{d['state']}/window", json={"formation": "433"}).json()
    kept = {f["to"]["id"] for f in w["dynasty"]["fates"] if f["reason"] in ("carried", "skipped")}
    assert all(w["dynasty"]["runs"][i] == 2 for i in kept)
    assert w["dynasty"]["legend"] == dy.LEGEND


def test_a_career_says_every_position_he_held_with_you():
    from game.deck import Card
    from web.app import career_out
    card = Card(id="Q1", name="P1", title="P1", pos="MF", positions=("CM",), source="declared", nation=None,
                rating=80, season=2005, label="2005–06", club="A", club_name="A", short="A", key="2005-A", crest="A")
    out = career_out(dy.Career(card, {"CM", "DM"}, 2, 20, 1, 2, [7.0] * 20))
    assert out["played"] == ["CM", "DM"] and out["positions"] == ["CM"] and out["mark"] == 7.0
