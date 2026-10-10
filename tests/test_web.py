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
