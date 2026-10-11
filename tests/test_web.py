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
    assert s["state"] == "99-442"
    while not s["complete"]:
        i = next(i for i, c in enumerate(s["deal"]["cards"]) if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    assert len(s["picks"]) == 11
    t = client.get(f"/api/tournament/{s['state']}").json()
    assert t["you"]["formation"] == "4-4-2"
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
