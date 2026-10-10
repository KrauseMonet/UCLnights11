"""Accounts and rooms end to end, through the API, against a real Postgres."""

import pytest
from fastapi.testclient import TestClient

from web import auth, db
from web.app import app


@pytest.fixture(scope="module", autouse=True)
def configured(database):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)   # the real count costs ~0.4 s a hash
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield
    db.close_all()
    mp.undo()


_n = iter(range(10_000))


def player(name=None):
    """A signed-in client with a fresh account."""
    name = name or f"player{next(_n)}"
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": name, "email": f"{name}@example.com",
                                           "password": "password1"})
    assert r.status_code == 200, r.text
    return c


def draft_to_the_end(c, code, stop_after=None):
    room = c.get(f"/api/rooms/{code}").json()
    made = 0
    while room["status"] == "drafting" and room["draft"] and not room["draft"]["complete"]:
        if stop_after is not None and made == stop_after:
            break
        d = room["draft"]
        i = next(x["i"] for x in d["deal"]["cards"] if x["takeable"])
        r = c.post(f"/api/rooms/{code}/pick", json={"index": i, "expect": expect(d)})
        assert r.status_code == 200, r.text
        room = r.json()
        made += 1
    return room


def expect(draft):
    parts = draft["state"].split("-")
    return len(parts[2].split(".")) if len(parts) == 3 and parts[2] else 0


# -- accounts ---------------------------------------------------------------

def test_signed_out_is_no_account_and_cannot_make_a_room():
    c = TestClient(app)
    assert c.get("/api/auth/me").json() == {"account": None}
    assert c.post("/api/rooms", json={"size": 4}).status_code == 401


def test_register_sign_out_and_sign_in_again():
    c = player("alice_a")
    assert c.get("/api/auth/me").json()["account"]["username"] == "alice_a"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").json() == {"account": None}
    bad = c.post("/api/auth/login", json={"identifier": "alice_a", "password": "wrong-one"})
    assert bad.status_code == 401
    ok = c.post("/api/auth/login", json={"identifier": "ALICE_A@example.com", "password": "password1"})
    assert ok.status_code == 200 and ok.json()["account"]["username"] == "alice_a"
    assert c.get("/api/auth/me").json()["account"]["username"] == "alice_a"


@pytest.mark.parametrize("body, message", [
    ({"username": "Alice_A", "email": "x@example.com", "password": "password1"}, "taken"),
    ({"username": "newname", "email": "alice_a@EXAMPLE.com", "password": "password1"}, "registered"),
    ({"username": "ab", "email": "y@example.com", "password": "password1"}, "3-20"),
    ({"username": "has space", "email": "y@example.com", "password": "password1"}, "3-20"),
    ({"username": "shortpw", "email": "y@example.com", "password": "short"}, "8"),
    ({"username": "noemail", "email": "nope", "password": "password1"}, "email"),
])
def test_registration_refuses_clashes_and_bad_input(body, message):
    r = TestClient(app).post("/api/auth/register", json=body)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_a_forged_cookie_is_signed_out():
    c = TestClient(app)
    c.cookies.set(auth.COOKIE_NAME, "1.9999999999.deadbeef")
    assert c.get("/api/auth/me").json() == {"account": None}
    assert c.post("/api/rooms", json={"size": 2}).status_code == 401


# -- rooms ------------------------------------------------------------------

def test_a_lobby_fills_and_refuses_once_full():
    host, guest, late = player(), player(), player()
    room = host.post("/api/rooms", json={"size": 2}).json()
    assert room["status"] == "lobby" and room["fillers"] == 1 and room["is_host"]
    code = room["code"]
    joined = guest.post(f"/api/rooms/{code.lower()}/join").json()   # codes are not case-sensitive
    assert len(joined["seats"]) == 2 and joined["fillers"] == 0 and not joined["is_host"]
    assert guest.post(f"/api/rooms/{code}/join").status_code == 200        # twice is harmless
    assert late.post(f"/api/rooms/{code}/join").status_code == 409


def test_an_unknown_code_is_a_404():
    assert player().post("/api/rooms/ZZZZZZ/join").status_code == 404


def test_a_bad_size_or_formation_is_refused():
    c = player()
    assert c.post("/api/rooms", json={"size": 6}).status_code == 400
    assert c.post("/api/rooms", json={"size": 4, "formation": "4141"}).status_code == 400


def test_only_the_host_starts_and_the_draft_then_locks_the_room():
    host, guest, late = player(), player(), player()
    code = host.post("/api/rooms", json={"size": 8}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert guest.post(f"/api/rooms/{code}/formation", json={"formation": "352"}).status_code == 200
    assert guest.post(f"/api/rooms/{code}/start").status_code == 403
    room = host.post(f"/api/rooms/{code}/start").json()
    assert room["status"] == "drafting"
    assert late.post(f"/api/rooms/{code}/join").status_code == 409
    assert guest.post(f"/api/rooms/{code}/leave").status_code == 409
    assert guest.post(f"/api/rooms/{code}/formation", json={"formation": "433"}).status_code == 409
    mine = guest.get(f"/api/rooms/{code}").json()["draft"]
    assert mine["formation"]["code"] == "352" and mine["picks"] == []


def test_every_seat_is_dealt_the_same_first_squad():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    a = host.get(f"/api/rooms/{code}").json()["draft"]
    b = guest.get(f"/api/rooms/{code}").json()["draft"]
    assert a["deal"]["key"] == b["deal"]["key"] and a["seed"] == b["seed"]


def test_a_room_completes_only_when_the_last_eleven_is_full():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    assert host.get(f"/api/rooms/{code}/tournament").status_code == 409
    room = draft_to_the_end(host, code)
    assert room["status"] == "drafting"
    assert [s["complete"] for s in room["seats"]] == [True, False]
    room = draft_to_the_end(guest, code)
    assert room["status"] == "complete"
    assert host.post(f"/api/rooms/{code}/pick", json={"index": 0, "expect": 11}).status_code == 409


def test_a_stale_or_illegal_move_is_refused_and_changes_nothing():
    host = player()
    code = host.post("/api/rooms", json={"size": 2}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    d = host.get(f"/api/rooms/{code}").json()["draft"]
    i = next(i for i, x in enumerate(d["deal"]["cards"]) if x["takeable"])
    assert host.post(f"/api/rooms/{code}/pick", json={"index": i, "expect": 0}).status_code == 200
    # The same click again, from a screen that had not seen the first: refused.
    assert host.post(f"/api/rooms/{code}/pick", json={"index": i, "expect": 0}).status_code == 409
    assert host.post(f"/api/rooms/{code}/pick", json={"index": 999, "expect": 1}).status_code == 400
    after = host.get(f"/api/rooms/{code}").json()["draft"]
    assert len(after["picks"]) == 1
    assert host.post(f"/api/rooms/{code}/reroll", json={"expect": 1}).json()["draft"]["rerolls_left"] == 1


def test_someone_outside_the_room_cannot_draft_in_it():
    host, stranger = player(), player()
    code = host.post("/api/rooms", json={"size": 2}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    assert stranger.post(f"/api/rooms/{code}/pick", json={"index": 0, "expect": 0}).status_code == 403
    assert stranger.get(f"/api/rooms/{code}").json()["draft"] is None


def test_the_host_can_finish_a_wandering_friends_draft():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    draft_to_the_end(guest, code, stop_after=4)
    assert guest.post(f"/api/rooms/{code}/finish").status_code == 403
    room = host.post(f"/api/rooms/{code}/finish").json()
    assert room["status"] == "complete" and all(s["complete"] for s in room["seats"])


def test_the_room_tournament_has_every_friend_and_real_sides_for_the_rest():
    host, guest, stranger = player("host_t"), player("guest_t"), player()
    code = host.post("/api/rooms", json={"size": 8}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    draft_to_the_end(host, code)
    draft_to_the_end(guest, code)
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert t["room"]["size"] == 8
    assert {p["name"] for p in t["players"]} == {"host_t", "guest_t"}
    assert t["you"]["name"] == "host_t" and t["your_matches"]
    assert [r["stage"] for r in t["knockout"]] == ["Quarter-finals", "Semi-finals", "Final"]
    sides = {x["key"]: x for r in t["knockout"] for tie in r["ties"] for x in (tie["a"], tie["b"])}
    assert len(sides) == 8 and sum(1 for x in sides.values() if x.get("human")) == 2
    g = guest.get(f"/api/rooms/{code}/tournament").json()
    assert g["you"]["name"] == "guest_t" and g["champion"]["key"] == t["champion"]["key"]
    legs = lambda v: [(f["home"]["key"], f["away"]["key"], f["hg"], f["ag"])   # noqa: E731
                      for r in v["knockout"] for x in r["ties"] for f in x["legs"]]
    assert legs(g) == legs(t)          # one tournament, whoever is looking at it
    spectator = stranger.get(f"/api/rooms/{code}/tournament").json()
    assert spectator["you"] is None and spectator["your_matches"] == []
    # Each friend gets their own journey card; someone watching gets none.
    assert len(t["journey"]["players"]) == 11 and len(t["journey"]["matches"]) == len(t["your_matches"])
    assert g["journey"]["players"] != t["journey"]["players"] or g["you"]["xi"] == t["you"]["xi"]
    assert spectator["journey"] is None
    an = host.get(f"/api/rooms/{code}/analysis").json()
    assert an["room"]["code"] == code and an["you"]["name"] == "host_t"
    assert an["analysis"]["hero"]["matches"] == len(legs(t)) and len(an["analysis"]["sides"]) == 8
    assert stranger.get(f"/api/rooms/{code}/analysis").json()["you"] is None
    assert spectator["champion"]["key"] == t["champion"]["key"]


def test_a_thirty_two_room_plays_groups():
    host = player()
    code = host.post("/api/rooms", json={"size": 32}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    host.post(f"/api/rooms/{code}/finish")
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert len(t["groups"]) == 8 and len(t["players"]) == 1
    assert len([f for f in t["your_matches"] if f["stage"] == "Group stage"]) == 6


def test_the_host_leaving_a_lobby_passes_the_room_on():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert host.post(f"/api/rooms/{code}/leave").status_code == 200
    room = guest.get(f"/api/rooms/{code}").json()
    assert room["is_host"] and len(room["seats"]) == 1
    guest.post(f"/api/rooms/{code}/leave")
    assert guest.get(f"/api/rooms/{code}").status_code == 404     # the last one out closes it


def test_the_host_can_remove_a_player_from_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    gid = next(s["id"] for s in guest.post(f"/api/rooms/{code}/join").json()["seats"] if s["you"])
    assert guest.post(f"/api/rooms/{code}/kick", json={"account_id": gid}).status_code == 403
    room = host.post(f"/api/rooms/{code}/kick", json={"account_id": gid}).json()
    assert len(room["seats"]) == 1


def test_my_rooms_lists_the_rooms_i_sit_in():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 16}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    mine = guest.get("/api/rooms").json()["rooms"]
    assert mine[0]["code"] == code and mine[0]["players"] == 2 and not mine[0]["host"]


# -- memory mode ------------------------------------------------------------

def ratings_in(draft):
    return [c["rating"] for c in draft["picks"] + draft["deal"]["cards"]]


def test_a_memory_room_sends_no_ratings_while_drafting_and_shows_them_after():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4, "memory": True}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    room = host.post(f"/api/rooms/{code}/start").json()
    assert room["memory"]
    room = draft_to_the_end(guest, code, stop_after=3)
    d = room["draft"]
    assert len(d["picks"]) == 3 and set(ratings_in(d)) == {None}
    draft_to_the_end(host, code)
    draft_to_the_end(guest, code)
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert all(isinstance(c["rating"], int) for c in t["you"]["xi"])   # the reveal


def test_an_ordinary_room_still_shows_ratings():
    host = player()
    code = host.post("/api/rooms", json={"size": 2}).json()["code"]
    d = host.post(f"/api/rooms/{code}/start").json()["draft"]
    assert all(isinstance(r, int) for r in ratings_in(d))


def test_only_the_host_sets_memory_mode_and_only_in_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert guest.post(f"/api/rooms/{code}/memory", json={"memory": True}).status_code == 403
    assert host.post(f"/api/rooms/{code}/memory", json={"memory": True}).json()["memory"] is True
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/memory", json={"memory": False}).status_code == 409
    assert guest.get(f"/api/rooms/{code}").json()["memory"] is True
