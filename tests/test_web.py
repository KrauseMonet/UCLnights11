"""The API end to end, through FastAPI's test client."""

from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)


def test_meta_describes_the_deck():
    m = client.get("/api/meta").json()
    assert m["club_seasons"] > 200 and m["first_season"] == "1994–95"
    assert {f["code"] for f in m["formations"]} >= {"433", "442"}


def test_a_draft_runs_to_a_tournament():
    s = client.post("/api/draft", json={"formation": "442", "seed": 99}).json()
    assert s["state"] == "b99-442" and s["total"] == 14       # every new draft has a bench (C40)
    while not s["complete"]:
        i = next(i for i, c in enumerate(s["deal"]["cards"]) if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    assert len(s["picks"]) == 14 and len(s["xi"]) == 11 and len(s["bench"]) == 3
    t = client.get(f"/api/tournament/{s['state']}").json()
    assert t["you"]["formation"] == "4-4-2"
    assert [c["id"] for c in t["you"]["bench"]] == [c["id"] for c in s["bench"]]
    assert len(t["your_matches"]) >= 6
    assert t["reached"] in {"Group stage", "Round of 16", "Quarter-finals", "Semi-finals",
                            "Runners-up", "Champions"}


def test_the_same_state_gives_the_same_tournament():
    s = client.post("/api/draft", json={"seed": 7}).json()
    while not s["complete"]:
        i = next(i for i, c in enumerate(s["deal"]["cards"]) if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    a = client.get(f"/api/tournament/{s['state']}").json()
    b = client.get(f"/api/tournament/{s['state']}").json()
    assert a == b


def test_an_untakeable_pick_is_a_400_not_a_crash():
    s = client.post("/api/draft", json={"seed": 1}).json()
    bad = next((i for i, c in enumerate(s["deal"]["cards"]) if not c["takeable"]), 999)
    r = client.post(f"/api/draft/{s['state']}/pick", json={"index": bad})
    assert r.status_code == 400


def test_a_tournament_before_the_eleven_is_complete_is_refused():
    assert client.get("/api/tournament/1-433").status_code == 409


def test_garbage_state_is_a_400():
    assert client.get("/api/draft/not-a-state").status_code == 400


# -- memory mode ------------------------------------------------------------

def test_a_memory_draft_sends_no_ratings_and_lists_each_line_by_name():
    s = client.post("/api/draft?memory=1", json={"seed": 11}).json()
    for _ in range(4):
        cards = s["deal"]["cards"]
        assert s["memory"] and all(c["rating"] is None for c in cards + s["picks"])
        for pos in ("GK", "DF", "MF", "FW"):
            names = [c["name"] for c in cards if c["pos"] == pos]
            assert names == sorted(names), pos
        i = next(c["i"] for c in cards if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick?memory=1", json={"index": i}).json()
    assert len(s["picks"]) == 4


def test_a_draft_shows_its_eleven_placed_and_memory_hides_its_ratings():
    for memory in (False, True):
        q = "?memory=1" if memory else ""
        s = client.post(f"/api/draft{q}", json={"seed": 11, "formation": "352"}).json()
        assert s["formation"]["slots"][0] == "GK" and len(s["formation"]["slots"]) == 11
        for _ in range(3):
            i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
            s = client.post(f"/api/draft/{s['state']}/pick{q}", json={"index": i}).json()
        assert len(s["xi"]) == 3 and all(c["slot"] in c["positions"] for c in s["xi"])
        assert all((c["rating"] is None) == memory for c in s["xi"])


def test_memory_mode_lists_a_squad_out_of_rating_order():
    # The deck lists a squad best first; listing it that way in Memory mode would give
    # the ratings away. Seed 11's first squad is one where the two orders differ.
    shown = client.post("/api/draft", json={"seed": 11}).json()["deal"]["cards"]
    hidden = client.post("/api/draft?memory=1", json={"seed": 11}).json()["deal"]["cards"]
    assert [c["i"] for c in shown] == list(range(len(shown)))
    assert [c["i"] for c in hidden] != [c["i"] for c in shown]


def test_a_memory_pick_takes_the_player_it_names():
    s = client.post("/api/draft?memory=1", json={"seed": 11}).json()
    card = [c for c in s["deal"]["cards"] if c["takeable"]][-1]
    after = client.post(f"/api/draft/{s['state']}/pick?memory=1", json={"index": card["i"]}).json()
    assert after["picks"][0]["id"] == card["id"]


def test_the_same_draft_without_memory_shows_ratings():
    s = client.post("/api/draft", json={"seed": 11}).json()
    assert not s["memory"] and all(isinstance(c["rating"], int) for c in s["deal"]["cards"])


def test_every_fixture_carries_its_match_stats():
    s = client.post("/api/draft", json={"seed": 3}).json()
    while not s["complete"]:
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    t = client.get(f"/api/tournament/{s['state']}").json()
    for f in t["your_matches"]:
        st = f["stats"]
        assert sum(st["possession"]) == 100
        assert st["on_target"][0] >= f["hg"] and st["on_target"][1] >= f["ag"]
        assert all(c <= p for c, p in zip(st["completed"], st["passes"]))


def test_only_your_matches_carry_the_shot_timeline():
    s = client.post("/api/draft", json={"seed": 3}).json()
    while not s["complete"]:
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    t = client.get(f"/api/tournament/{s['state']}").json()
    for f in t["your_matches"]:
        assert len(f["shots"]) == sum(f["stats"]["shots"])
        assert [x[0] for x in f["shots"] if x[3]] == sorted(g["minute"] for g in f["goals"])
    assert all("shots" not in leg for r in t["knockout"] for tie in r["ties"] for leg in tie["legs"])


def test_the_setup_page_is_served_and_meta_describes_every_formation():
    """The setup page (C37) draws each formation from /api/meta: its slots, lines and a line
    about it. No two formations may share a slot set, or one adds a name and nothing to play."""
    assert client.get("/start").status_code == 200
    forms = client.get("/api/meta").json()["formations"]
    assert len(forms) == 14
    for f in forms:
        assert len(f["slots"]) == 11 and f["slots"][0] == "GK" and f["about"]
        assert sum(f["lines"].values()) == 11
    assert len({tuple(sorted(f["slots"])) for f in forms}) == len(forms)


def test_your_matches_carry_both_elevens_in_their_formations():
    """The match screen draws both sides (C38): each line-up is its side's eleven in slot order,
    every man in a slot of his side's formation, and nothing but his name and slot."""
    s = client.post("/api/draft", json={"seed": 3, "formation": "532"}).json()
    while not s["complete"]:
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    t = client.get(f"/api/tournament/{s['state']}").json()
    for f in t["your_matches"]:
        for lu, side in zip(f["lineups"], (f["home"], f["away"])):
            assert len(lu["xi"]) == 11 and sorted(c["slot"] for c in lu["xi"]) == sorted(lu["slots"])
            assert all(set(c) == {"name", "slot"} for c in lu["xi"])
        mine = f["lineups"][0 if f["home"]["you"] else 1]
        assert mine["formation"] == "5-3-2"
        assert {c["name"] for c in mine["xi"]} == {c["name"] for c in t["you"]["xi"]}
    assert all("lineups" not in leg for r in t["knockout"] for tie in r["ties"] for leg in tie["legs"])


# -- the bench (C40) --------------------------------------------------------

def _finish(state, picks=None):
    s = client.get(f"/api/draft/{state}").json()
    while not s["complete"] and (picks is None or len(s["picks"]) < picks):
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    return s


def test_an_eleven_pick_link_still_drafts_eleven_and_plays_engine_1():
    from game.deck import load_deck
    from game.draft import decode, replay
    from game.tournament import Side, play_tournament
    from web.app import league
    s = _finish("31-433")
    assert s["state"].startswith("31-433-") and s["total"] == 11 and len(s["picks"]) == 11 and not s["bench"]
    t = client.get(f"/api/tournament/{s['state']}").json()
    seed, f, moves = decode(s["state"])
    d = replay(load_deck(), seed, f, moves)
    one = play_tournament(load_deck(), league(), seed, Side("YOU", "Your XI", "YOU", d.formation, d.picks, you=True))
    mine = [x for x in one.fixtures if x.home.you or x.away.you]
    assert [(m["hg"], m["ag"]) for m in t["your_matches"]] == [(x.result.home_goals, x.result.away_goals) for x in mine]
    assert all(m["subs"] == [] for m in t["your_matches"])


def test_the_bench_is_picked_after_the_eleven_and_holds_no_keeper():
    s = _finish("b31-433", picks=11)
    assert not s["complete"] and len(s["xi"]) == 11 and s["deal"] is not None
    cards = s["deal"]["cards"]
    for c in cards:
        if c["positions"] == ["GK"]:
            assert not c["takeable"] and c["reason"] == "keepers stay on"
    s = _finish(s["state"])
    assert s["complete"] and len(s["bench"]) == 3 and all("GK" != c["positions"][0] or len(c["positions"]) > 1 for c in s["bench"])
    assert client.post(f"/api/draft/{s['state']}/pick", json={"index": 0}).status_code == 400


def test_a_bench_draft_plays_engine_2_and_the_journey_counts_its_substitutes():
    s = _finish("b31-433")
    t = client.get(f"/api/tournament/{s['state']}").json()
    bench = {c["name"] for c in s["bench"]}
    names = {p["name"] for p in t["journey"]["players"]}
    assert len(t["journey"]["players"]) >= 11
    assert names - {c["name"] for c in s["xi"]} <= bench
    assert names & bench, "a bench as good as this one comes on somewhere in a tournament"
    assert {p["name"] for p in t["journey"]["players"] if p["sub"]} == names & bench


def test_your_best_rated_substitute_comes_on_first():
    # The bench is picked in any order; the automatic plan brings it on best first, as a
    # club does. Seed 31's bench is picked worst first.
    s = _finish("b31-433")
    assert [c["rating"] for c in s["bench"]] != sorted((c["rating"] for c in s["bench"]), reverse=True)
    rating = {c["name"]: c["rating"] for c in s["bench"]}
    t = client.get(f"/api/tournament/{s['state']}").json()
    came_on = 0
    for m in t["your_matches"]:
        mine = [x for x in m["subs"] if x["side"] == (0 if m["home"]["you"] else 1)]
        ratings = [rating[x["on"]] for x in sorted(mine, key=lambda x: x["minute"])]
        assert ratings == sorted(ratings, reverse=True)
        came_on += len(mine)
    assert came_on >= 6


def test_memory_hides_the_bench_s_ratings_too():
    s = client.get("/api/draft/b31-433?memory=1").json()
    while len(s["picks"]) < 12:
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick?memory=1", json={"index": i}).json()
    assert len(s["bench"]) == 1 and s["bench"][0]["rating"] is None


def test_a_bench_state_is_not_an_eleven_for_rooms_or_the_daily():
    import pytest
    from game.draft import IllegalMove, decode, decode_state, encode
    assert decode_state("b5-433-1.2") == (5, "433", decode("5-433-1.2")[2], True, None)
    assert encode(5, "433", decode("5-433-1.2")[2], bench=True) == "b5-433-1.2"
    with pytest.raises(IllegalMove):
        decode("b5-433-1.2")



# -- the plan (C41) ---------------------------------------------------------

def _yours(t):
    return [(m, 0 if m["home"]["you"] else 1) for m in t["your_matches"]]


def test_a_finished_bench_draft_offers_its_automatic_plan_and_what_each_man_can_replace():
    s = _finish("b31-433")
    assert not s["plan_chosen"] and [x["minute"] for x in s["plan"]] == [60, 70, 80]
    assert all(x["off"] is None and x["when"] == "any" for x in s["plan"])
    for c in s["bench"]:
        assert c["can_replace"] and 0 not in c["can_replace"]


def test_the_automatic_plan_written_out_plays_the_same_tournament():
    s = _finish("b31-433")
    chosen = client.post(f"/api/draft/{s['state']}/plan", json={"changes": s["plan"]}).json()
    assert chosen["plan_chosen"] and chosen["state"] == s["state"] + "-p" + ".".join(
        f"{x['on']}a{x['minute']}" for x in s["plan"])
    a = client.get(f"/api/tournament/{s['state']}").json()["your_matches"]
    b = client.get(f"/api/tournament/{chosen['state']}").json()["your_matches"]
    assert [(m["hg"], m["ag"], m["subs"]) for m in a] == [(m["hg"], m["ag"], m["subs"]) for m in b]


def test_a_plan_of_no_changes_brings_nobody_on():
    s = _finish("b31-433")
    none = client.post(f"/api/draft/{s['state']}/plan", json={"changes": []}).json()
    assert none["state"].endswith("-p") and none["plan"] == []
    t = client.get(f"/api/tournament/{none['state']}").json()
    assert not any(x["side"] == side for m, side in _yours(t) for x in m["subs"])
    assert any(m["subs"] for m, _ in _yours(t)), "the clubs still make theirs"


def test_a_named_change_takes_off_that_man_and_the_card_shows_the_eleven_after_it():
    s = _finish("b31-433")
    slot = s["bench"][2]["can_replace"][-1]
    starter = s["xi"][slot]["name"]
    plan = [{"on": 2, "minute": 45, "when": "any", "off": slot}]
    new = client.post(f"/api/draft/{s['state']}/plan", json={"changes": plan}).json()
    t = client.get(f"/api/tournament/{new['state']}").json()
    assert t["you"]["plan"] == [{"on": s["bench"][2]["name"], "minute": 45, "when": "any", "off": starter}]
    for m, side in _yours(t):
        mine = [x for x in m["subs"] if x["side"] == side]
        assert [(x["minute"], x["off"], x["on"]) for x in mine] == [(45, starter, s["bench"][2]["name"])]
        names = [c["name"] for c in mine[0]["xi"]]
        assert len(names) == 11 and s["bench"][2]["name"] in names and starter not in names


def test_a_plan_the_draft_cannot_play_is_a_400():
    s = _finish("b31-433")
    for plan in ([{"on": 0, "minute": 60, "when": "any", "off": 0}],
                 [{"on": 0, "minute": 61, "when": "any"}],
                 [{"on": 0, "minute": 60, "when": "sometimes"}],
                 [{"on": 0, "minute": 60, "when": "any"}, {"on": 0, "minute": 70, "when": "any"}]):
        assert client.post(f"/api/draft/{s['state']}/plan", json={"changes": plan}).status_code == 400
    unfinished = _finish("b31-433", picks=12)
    assert client.post(f"/api/draft/{unfinished['state']}/plan", json={"changes": []}).status_code == 400
    back = client.post(f"/api/draft/{s['state']}-p/plan", json={"changes": None}).json()
    assert back["state"] == s["state"] and not back["plan_chosen"]


def test_a_memory_plan_shows_no_ratings():
    s = _finish("b31-433")
    m = client.get(f"/api/draft/{s['state']}?memory=1").json()
    assert m["plan"] and all(c["rating"] is None and c["can_replace"] for c in m["bench"])
