"""Accounts and rooms end to end, through the API, against a real Postgres."""

import re

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
    assert c.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).status_code == 401


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
    assert c.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).status_code == 401


# -- rooms ------------------------------------------------------------------

def test_a_lobby_fills_and_refuses_once_full():
    host, guest, late = player(), player(), player()
    room = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()
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
    assert c.post("/api/rooms", json={"bench": False, "size": 6, "style": "own"}).status_code == 400
    assert c.post("/api/rooms", json={"bench": False, "size": 4, "formation": "4141"}).status_code == 400


def test_only_the_host_starts_and_the_draft_then_locks_the_room():
    host, guest, late = player(), player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 8, "style": "own"}).json()["code"]
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
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    a = host.get(f"/api/rooms/{code}").json()["draft"]
    b = guest.get(f"/api/rooms/{code}").json()["draft"]
    assert a["deal"]["key"] == b["deal"]["key"] and a["seed"] == b["seed"]


def test_a_room_completes_only_when_the_last_eleven_is_full():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
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
    code = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()["code"]
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
    code = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    assert stranger.post(f"/api/rooms/{code}/pick", json={"index": 0, "expect": 0}).status_code == 403
    assert stranger.get(f"/api/rooms/{code}").json()["draft"] is None


def test_the_host_can_finish_a_wandering_friends_draft():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    draft_to_the_end(guest, code, stop_after=4)
    assert guest.post(f"/api/rooms/{code}/finish").status_code == 403
    room = host.post(f"/api/rooms/{code}/finish").json()
    assert room["status"] == "complete" and all(s["complete"] for s in room["seats"])


def test_the_room_tournament_has_every_friend_and_real_sides_for_the_rest():
    host, guest, stranger = player("host_t"), player("guest_t"), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 8, "style": "own"}).json()["code"]
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


def test_unsaved_lists_my_completed_rooms_until_saved():
    host, guest, stranger = player(), player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    unsaved = lambda c: [r["code"] for r in c.post("/api/results/unsaved", json={}).json()["rooms"]]  # noqa: E731
    host.post(f"/api/rooms/{code}/start")
    draft_to_the_end(host, code)
    assert code not in unsaved(host)                         # not complete yet
    draft_to_the_end(guest, code)
    assert code in unsaved(host) and code in unsaved(guest)
    assert code not in unsaved(stranger)                     # no seat, nothing to save
    assert host.post("/api/results", json={"source": "room", "key": code}).status_code == 200
    assert code not in unsaved(host) and code in unsaved(guest)


def test_a_thirty_two_room_plays_groups():
    host = player()
    code = host.post("/api/rooms", json={"bench": False, "size": 32, "style": "own"}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    host.post(f"/api/rooms/{code}/finish")
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert len(t["groups"]) == 8 and len(t["players"]) == 1
    assert len([f for f in t["your_matches"] if f["stage"] == "Group stage"]) == 6


def test_the_host_leaving_a_lobby_passes_the_room_on():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert host.post(f"/api/rooms/{code}/leave").status_code == 200
    room = guest.get(f"/api/rooms/{code}").json()
    assert room["is_host"] and len(room["seats"]) == 1
    guest.post(f"/api/rooms/{code}/leave")
    assert guest.get(f"/api/rooms/{code}").status_code == 404     # the last one out closes it


def test_the_host_can_remove_a_player_from_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
    gid = next(s["id"] for s in guest.post(f"/api/rooms/{code}/join").json()["seats"] if s["you"])
    assert guest.post(f"/api/rooms/{code}/kick", json={"account_id": gid}).status_code == 403
    room = host.post(f"/api/rooms/{code}/kick", json={"account_id": gid}).json()
    assert len(room["seats"]) == 1


def test_my_rooms_lists_the_rooms_i_sit_in():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 16, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    mine = guest.get("/api/rooms").json()["rooms"]
    assert mine[0]["code"] == code and mine[0]["players"] == 2 and not mine[0]["host"]


# -- memory mode ------------------------------------------------------------

def ratings_in(draft):
    return [c["rating"] for c in draft["picks"] + draft["deal"]["cards"]]


def test_a_memory_room_sends_no_ratings_while_drafting_and_shows_them_after():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "memory": True, "style": "own"}).json()["code"]
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
    code = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()["code"]
    d = host.post(f"/api/rooms/{code}/start").json()["draft"]
    assert all(isinstance(r, int) for r in ratings_in(d))


def test_only_the_host_sets_memory_mode_and_only_in_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert guest.post(f"/api/rooms/{code}/memory", json={"memory": True}).status_code == 403
    assert host.post(f"/api/rooms/{code}/memory", json={"memory": True}).json()["memory"] is True
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/memory", json={"memory": False}).status_code == 409
    assert guest.get(f"/api/rooms/{code}").json()["memory"] is True


# -- taking turns (C29) -------------------------------------------------------

from web import rooms as rooms_mod     # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rooms_mod, "clock", c)
    return c


def turn_room(n=2, size=4, **kw):
    people = [player() for _ in range(n)]
    code = people[0].post("/api/rooms", json={"bench": False, "size": size, **kw}).json()["code"]
    for p in people[1:]:
        p.post(f"/api/rooms/{code}/join")
    room = people[0].post(f"/api/rooms/{code}/start").json()
    return people, code, room


def take(c, code, room):
    t = room["turns"]
    i = next(x["i"] for x in t["deal"]["cards"] if x["takeable"])
    return c.post(f"/api/rooms/{code}/pick", json={"index": i, "expect": t["expect"]})


def test_a_new_room_takes_turns_by_default_and_the_host_can_change_it(clock):
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": False, "size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    room = host.get(f"/api/rooms/{code}").json()
    assert room["style"] == "turns" and room["timer"] == 30
    assert guest.post(f"/api/rooms/{code}/style", json={"style": "own", "timer": 30}).status_code == 403
    assert host.post(f"/api/rooms/{code}/style", json={"style": "turns", "timer": 20}).status_code == 400
    assert host.post(f"/api/rooms/{code}/style", json={"style": "turns", "timer": 45}).json()["timer"] == 45
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/style", json={"style": "own", "timer": 30}).status_code == 409


def on_turn(host, guest, code):
    """Who is on turn, read from the host's view ("you" depends on who is looking)."""
    room = host.get(f"/api/rooms/{code}").json()
    return (host, guest) if room["turns"]["turn"]["you"] else (guest, host)


def test_turns_snake_and_only_the_seat_on_turn_can_pick(clock):
    (host, guest), code, room = turn_room()
    order = []
    for _ in range(4):
        on, off = on_turn(host, guest, code)
        order.append(on)
        refused = take(off, code, off.get(f"/api/rooms/{code}").json())
        assert refused.status_code == 409 and "turn" in refused.json()["detail"]
        assert take(on, code, on.get(f"/api/rooms/{code}").json()).status_code == 200
    assert order == [order[0], order[1], order[1], order[0]] and order[0] is not order[1]


def test_a_stale_pick_is_refused_with_the_room_attached(clock):
    (host, guest), code, room = turn_room()
    on = host if room["turns"]["turn"]["you"] else guest
    seen = on.get(f"/api/rooms/{code}").json()
    assert take(on, code, seen).status_code == 200
    again = take(on, code, seen)                      # the same click, from the old screen
    assert again.status_code == 409 and again.json()["room"]["turns"]["expect"] == 1


def test_a_run_out_clock_picks_for_the_seat_and_any_poll_can_trigger_it(clock):
    (host, guest), code, room = turn_room(timer=15)
    first = room["turns"]["turn"]["id"]
    clock.t += 15 + rooms_mod.CLOCK_GRACE_S - 0.5      # inside the grace: nothing yet
    assert guest.get(f"/api/rooms/{code}").json()["turns"]["expect"] == 0
    clock.t += 1.0
    room = guest.get(f"/api/rooms/{code}").json()      # whoever polls, the clock picks
    assert room["turns"]["expect"] == 1 and room["turns"]["turn"]["id"] != first
    assert room["turns"]["recent"][0]["card"]["name"]
    assert host.get(f"/api/rooms/{code}").json()["turns"]["expect"] == 1   # and only once


def test_a_late_pick_keeps_the_clock_s_pick(clock):
    (host, guest), code, room = turn_room(timer=15)
    on = host if room["turns"]["turn"]["you"] else guest
    seen = on.get(f"/api/rooms/{code}").json()
    clock.t += 60
    late = take(on, code, seen)
    assert late.status_code == 409
    # Read the stored moves before anyone polls: a poll would make the same pick again
    # and hide a rollback.
    with db.connection() as conn:
        (moves,) = conn.execute("select moves from rooms where code = %s", (code,)).fetchone()
    assert len(moves.split(".")) == 1


def test_a_turn_room_completes_and_plays_its_tournament(clock):
    (host, guest), code, room = turn_room(size=8)
    while room["status"] == "drafting":
        on, _ = on_turn(host, guest, code)
        r = take(on, code, on.get(f"/api/rooms/{code}").json())
        assert r.status_code == 200, r.text
        room = r.json()
    assert room["status"] == "complete" and all(s["complete"] for s in room["seats"])
    t = host.get(f"/api/rooms/{code}/tournament").json()
    g = guest.get(f"/api/rooms/{code}/tournament").json()
    mine = {c["id"] for c in t["you"]["xi"]}
    theirs = {c["id"] for c in g["you"]["xi"]}
    assert len(mine) == len(theirs) == 11 and not mine & theirs


def test_the_host_can_finish_a_turn_room(clock):
    (host, guest), code, room = turn_room()
    assert guest.post(f"/api/rooms/{code}/finish").status_code == 403
    room = host.post(f"/api/rooms/{code}/finish").json()
    assert room["status"] == "complete" and all(s["picks"] == 11 for s in room["seats"])


def test_no_rerolls_when_taking_turns(clock):
    (host, guest), code, room = turn_room()
    on = host if room["turns"]["turn"]["you"] else guest
    assert on.post(f"/api/rooms/{code}/reroll", json={"expect": 0}).status_code == 400


def test_a_memory_turn_room_shows_no_ratings(clock):
    (host, guest), code, room = turn_room(memory=True)
    assert {c["rating"] for c in room["turns"]["deal"]["cards"]} == {None}
    on = host if room["turns"]["turn"]["you"] else guest
    room = take(on, code, on.get(f"/api/rooms/{code}").json()).json()
    assert room["turns"]["recent"][0]["card"]["rating"] is None


def test_a_spectator_watches_but_has_no_draft(clock):
    (host, guest), code, room = turn_room()
    seen = player().get(f"/api/rooms/{code}").json()
    assert seen["draft"] is None and seen["turns"]["deal"] and not seen["turns"]["turn"]["you"]


def test_a_memory_room_hides_ratings_in_the_placed_eleven_too():
    host = player()
    code = host.post("/api/rooms", json={"bench": False, "size": 2, "memory": True, "style": "own"}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    d = draft_to_the_end(host, code, stop_after=3)["draft"]
    assert len(d["xi"]) == 3 and {c["rating"] for c in d["xi"]} == {None}
    assert all(c["slot"] in c["positions"] for c in d["xi"])


def test_a_room_whose_picks_no_longer_replay_says_so_instead_of_failing(clock):
    """A room drafted before positions (C35) may hold moves the new rules don't deal: it
    shows as failed with the reason, and its tournament is refused, rather than a 500."""
    (host, guest), code, room = turn_room()
    with db.connection() as conn:
        conn.execute("update rooms set moves = %s where code = %s", ("999", code))
    seen = host.get(f"/api/rooms/{code}")
    assert seen.status_code == 200
    assert seen.json()["status"] == "failed" and "positions" in seen.json()["failure_reason"]


# -- benches (C42) --------------------------------------------------------------

def bench_room(n=2, size=4, style="own", **kw):
    people = [player() for _ in range(n)]
    code = people[0].post("/api/rooms", json={"size": size, "style": style, **kw}).json()["code"]
    for p in people[1:]:
        p.post(f"/api/rooms/{code}/join")
    room = people[0].post(f"/api/rooms/{code}/start").json()
    return people, code, room


def yours(t):
    return [(m, 0 if m["home"]["you"] else 1) for m in t["your_matches"]]


def test_a_new_room_drafts_a_bench_and_only_the_host_changes_that_in_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert host.get(f"/api/rooms/{code}").json()["bench"] is True
    assert guest.post(f"/api/rooms/{code}/bench", json={"bench": False}).status_code == 403
    assert host.post(f"/api/rooms/{code}/bench", json={"bench": False}).json()["bench"] is False
    host.post(f"/api/rooms/{code}/bench", json={"bench": True})
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/bench", json={"bench": False}).status_code == 409


def test_an_own_pace_bench_room_waits_for_every_plan_then_plays_engine_2():
    (host, guest), code, room = bench_room()
    assert room["picks_each"] == 14
    assert host.post(f"/api/rooms/{code}/plan", json={"changes": None}).status_code == 409   # picks first
    room = draft_to_the_end(host, code)
    d = room["draft"]
    assert len(d["picks"]) == 14 and len(d["bench"]) == 3 and d["plan"] and not d["ready"]
    assert room["status"] == "drafting"
    draft_to_the_end(guest, code)
    room = host.get(f"/api/rooms/{code}").json()
    assert room["status"] == "drafting", "every pick is made but nobody is ready"
    assert [s["ready"] for s in room["seats"]] == [False, False]
    # The host names a change: the third substitute on from 45' for a man he can replace.
    sub = room["draft"]["bench"][2]
    slot = sub["can_replace"][0]
    off = room["draft"]["xi"][slot]["name"]
    plan = [{"on": 2, "minute": 45, "when": "any", "off": slot}]
    assert host.post(f"/api/rooms/{code}/plan", json={"changes": [{**plan[0], "off": 0}]}).status_code == 400
    assert not host.get(f"/api/rooms/{code}").json()["draft"]["ready"], "a refused plan is not stored"
    room = host.post(f"/api/rooms/{code}/plan", json={"changes": plan}).json()
    assert room["status"] == "drafting" and room["draft"]["ready"] and room["draft"]["plan_chosen"]
    room = guest.post(f"/api/rooms/{code}/plan", json={"changes": None}).json()
    assert room["status"] == "complete"
    assert host.post(f"/api/rooms/{code}/plan", json={"changes": []}).status_code == 409   # settled
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert [c["name"] for c in t["you"]["bench"]] == [c["name"] for c in d["bench"]]
    for m, side in yours(t):
        mine = [x for x in m["subs"] if x["side"] == side and x["minute"] == 45]
        assert [(x["off"], x["on"]) for x in mine] == [(off, sub["name"])]


def test_a_turn_room_with_a_bench_plays_fourteen_rounds_and_no_clock_runs_on_plans(clock):
    (host, guest), code, room = bench_room(style="turns")
    assert room["turns"]["rounds"] == 14 and room["turns"]["total"] == 28
    while room["turns"]["deal"] is not None:
        on, _ = on_turn(host, guest, code)
        r = take(on, code, on.get(f"/api/rooms/{code}").json())
        assert r.status_code == 200, r.text
        room = r.json()
    assert room["status"] == "drafting" and all(s["picks"] == 14 for s in room["seats"])
    held = [c["id"] for p in (host, guest) for c in p.get(f"/api/rooms/{code}").json()["draft"]["picks"]]
    assert len(held) == len(set(held)) == 28, "a man taken by anyone, bench too, is gone for everyone"
    clock.t += 1000                                    # long past any pick clock
    room = host.get(f"/api/rooms/{code}").json()
    assert room["status"] == "drafting" and room["turns"]["expect"] == 28
    host.post(f"/api/rooms/{code}/plan", json={"changes": []})
    room = guest.post(f"/api/rooms/{code}/plan", json={"changes": None}).json()
    assert room["status"] == "complete"
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert not any(x["side"] == side for m, side in yours(t) for x in m["subs"]), "a plan of no changes"
    g = guest.get(f"/api/rooms/{code}/tournament").json()
    assert any(x["side"] == side for m, side in yours(g) for x in m["subs"]), "the automatic plan"


def test_the_host_finishes_a_bench_room_with_automatic_plans(clock):
    for style in ("own", "turns"):
        (host, guest), code, room = bench_room(style=style)
        room = host.post(f"/api/rooms/{code}/finish").json()
        assert room["status"] == "complete" and all(s["picks"] == 14 and s["ready"] for s in room["seats"]), style
        with db.connection() as conn:
            plans = [p for (p,) in conn.execute("select plan from room_seats where room_code = %s", (code,))]
        # The automatic plan written out: three changes at 60', 70', 80', any score, best change.
        assert all(re.fullmatch(r"p\da60\.\da70\.\da80", p) for p in plans), plans
        t = guest.get(f"/api/rooms/{code}/tournament").json()
        assert len(t["you"]["bench"]) == 3


def test_a_room_without_a_bench_plays_engine_1(clock):
    (host, guest), code, room = turn_room()
    room = host.post(f"/api/rooms/{code}/finish").json()
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert t["you"]["bench"] == [] and all(m["subs"] == [] for m in t["your_matches"])
    assert host.post(f"/api/rooms/{code}/plan", json={"changes": None}).status_code == 400


def test_set_plan_itself_refuses_a_plan_the_draft_cannot_play():
    # Through the API a bad plan is refused twice: set_plan checks it, and were that check
    # gone, reading the room back for the reply would fail on it and roll the write back.
    # Only calling set_plan directly can show its own check acting.
    from game.deck import load_deck
    from game.draft import Change, IllegalMove
    from web import accounts
    (host, guest), code, room = bench_room()
    room = draft_to_the_end(host, code)
    me = host.get("/api/auth/me").json()["account"]["id"]
    with db.connection() as conn:
        account = accounts.get_account(conn, me)
        with pytest.raises(IllegalMove):
            rooms_mod.set_plan(conn, load_deck(), account, code, (Change(0, 60, "any", 0),))


def test_a_finished_room_shows_every_squad_rated_yours_first():
    host, guest, stranger = player("host_q"), player("guest_q"), player()
    code = host.post("/api/rooms", json={"bench": True, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    draft_to_the_end(host, code)
    assert guest.get(f"/api/rooms/{code}/squads").status_code == 409
    host.post(f"/api/rooms/{code}/finish")
    g = guest.get(f"/api/rooms/{code}/squads").json()
    assert [s["name"] for s in g["sides"]][0] == "guest_q" and g["sides"][0]["you"]
    assert {s["name"] for s in g["sides"]} == {"host_q", "guest_q"} and g["room"]["code"] == code
    assert all(len(s["xi"]) == 11 and len(s["bench"]) == 3 and s["ratings"]["bench"] for s in g["sides"])
    t = host.get(f"/api/rooms/{code}/tournament").json()
    h = host.get(f"/api/rooms/{code}/squads").json()
    assert h["sides"][0]["name"] == "host_q"
    assert [c["id"] for c in h["sides"][0]["xi"]] == [c["id"] for c in t["you"]["xi"]]
    watching = stranger.get(f"/api/rooms/{code}/squads").json()["sides"]
    assert not any(s["you"] for s in watching)
    assert [s["ratings"]["overall"] for s in watching] == sorted((s["ratings"]["overall"] for s in watching), reverse=True)


def test_a_seat_changes_its_team_sheet_until_the_room_opens_and_the_tournament_plays_it():
    host, guest = player("host_s"), player("guest_s")
    code = host.post("/api/rooms", json={"bench": True, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/sheet", json={"man": 0, "to": "s1"}).status_code == 409
    d = draft_to_the_end(host, code)["draft"]
    man, to = next((c["p"], t) for c in d["bench"] for t in c["to"] if t.startswith("s"))
    name = d["picks"][man]["name"]
    # Ready first, with a plan for the second substitute; the plan follows him to the front.
    host.post(f"/api/rooms/{code}/plan", json={"changes": [{"on": 1, "minute": 65, "when": "any"}]})
    room = host.post(f"/api/rooms/{code}/sheet", json={"man": d["bench"][1]["p"], "to": "b0"}).json()
    assert room["draft"]["ready"] and room["draft"]["plan"] == [{"on": 0, "minute": 65, "when": "any", "off": None}]
    # Moved back, the sheet is the drafted one again and nothing is stored for it.
    room = host.post(f"/api/rooms/{code}/sheet", json={"man": d["bench"][1]["p"], "to": "b1"}).json()
    assert not room["draft"]["sheet_chosen"]
    room = host.post(f"/api/rooms/{code}/sheet", json={"man": man, "to": to}).json()
    assert name in [c["name"] for c in room["draft"]["xi"]] and room["draft"]["sheet_chosen"]
    assert guest.post(f"/api/rooms/{code}/sheet", json={"man": man, "to": to}).status_code == 409   # not finished
    host.post(f"/api/rooms/{code}/finish")
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert name in [c["name"] for c in t["you"]["xi"]]
    assert host.post(f"/api/rooms/{code}/sheet", json={}).status_code == 409                       # settled


def test_a_turn_room_s_team_sheet_shows_on_its_planning_screen_and_in_its_tournament(clock):
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"bench": True, "size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    room = host.post(f"/api/rooms/{code}/start").json()
    assert room["style"] == "turns"
    while not (room["draft"] and room["draft"]["complete"] and guest.get(f"/api/rooms/{code}").json()["draft"]["complete"]):
        on, _ = on_turn(host, guest, code)
        r = take(on, code, on.get(f"/api/rooms/{code}").json())
        assert r.status_code == 200, r.text
        room = host.get(f"/api/rooms/{code}").json()
    d = room["draft"]
    man, to = next((c["p"], t) for c in d["bench"] for t in c["to"] if t.startswith("s"))
    name = d["picks"][man]["name"]
    room = host.post(f"/api/rooms/{code}/sheet", json={"man": man, "to": to}).json()
    assert name in [c["name"] for c in room["draft"]["xi"]] and not room["draft"]["ready"]
    host.post(f"/api/rooms/{code}/plan", json={"changes": None})
    guest.post(f"/api/rooms/{code}/plan", json={"changes": None})
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert name in [c["name"] for c in t["you"]["xi"]]


# -- the poll, trimmed (speed sweep) ------------------------------------------------

def count_queries(monkeypatch):
    """Every statement sent from here on: each is a round trip to the database."""
    import psycopg
    seen = []
    real = psycopg.Connection.execute

    def counting(self, query, *a, **k):
        seen.append(query)
        return real(self, query, *a, **k)
    monkeypatch.setattr(psycopg.Connection, "execute", counting)
    return seen


def test_a_poll_is_one_query_and_unchanged_when_the_room_has_not_moved(clock, monkeypatch):
    (host, guest), code, room = turn_room()
    v = room["version"]
    seen = count_queries(monkeypatch)
    quiet = guest.get(f"/api/rooms/{code}?v={v}").json()
    assert quiet == {"code": code, "version": v, "unchanged": True, "server_now": quiet["server_now"]}
    assert len(seen) == 1
    seen.clear()
    full = guest.get(f"/api/rooms/{code}").json()      # room, seats and who is asking: still one
    assert len(seen) == 1 and full["seated"] and len(full["seats"]) == 2
    on = host if full["turns"]["turn"]["you"] is False else guest
    assert take(on, code, full).status_code == 200
    moved = guest.get(f"/api/rooms/{code}?v={v}").json()
    assert "unchanged" not in moved and moved["version"] > v and moved["turns"]["expect"] == 1


def test_a_poll_naming_the_current_version_still_lets_a_run_out_clock_pick(clock):
    (host, guest), code, room = turn_room(timer=15)
    clock.t += 15 + rooms_mod.CLOCK_GRACE_S + 1
    room = guest.get(f"/api/rooms/{code}?v={room['version']}").json()
    assert "unchanged" not in room and room["turns"]["expect"] == 1


def test_the_room_draft_cache_is_shared_only_by_the_same_deck_and_moves(monkeypatch):
    import copy
    from types import SimpleNamespace as NS

    from game.deck import load_deck
    deck = load_deck()
    room = NS(seed=11, seats=[NS(formation="433"), NS(formation="442")], moves=[], bench=False)
    d = rooms_mod.shared_of(deck, room)
    assert rooms_mod.shared_of(deck, room) is d
    later = rooms_mod.shared_of(deck, room, [d.takeable(d.active)[0]])
    assert later is not d and len(later.moves) == 1 and len(d.moves) == 0
    # Two decks that happen to get the same id (one freed, the next allocated there):
    # the entry holds its deck, so the second never reads the first's draft.
    monkeypatch.setattr(rooms_mod, "id", lambda x: 1, raising=False)
    first = rooms_mod.shared_of(deck, room)
    assert rooms_mod.shared_of(copy.copy(deck), room) is not first


# -- who am I, and the unsaved panel, without a query each (speed sweep 6 and 7) ------

def test_who_am_i_is_answered_from_the_cookie_with_no_query(monkeypatch):
    c = player()
    seen = count_queries(monkeypatch)
    me = c.get("/api/auth/me").json()["account"]
    assert me["username"].startswith("player") and me["id"] and seen == []


def test_an_older_cookie_is_looked_up_once_and_reissued_with_its_username_and_expiry(monkeypatch):
    c = player()
    me = c.get("/api/auth/me").json()["account"]
    old = auth.make_session_cookie(me["id"], now=2_000_000_000 - auth.SESSION_MAX_AGE_S)   # expires at 2e9
    c.cookies.set(auth.COOKIE_NAME, old)
    seen = count_queries(monkeypatch)
    r = c.get("/api/auth/me")
    assert r.json()["account"] == me and len(seen) == 1
    new = r.cookies.get(auth.COOKIE_NAME)
    assert auth.read_session_cookie(new) == (me["id"], 2_000_000_000, me["username"])
    seen.clear()
    c.cookies.set(auth.COOKIE_NAME, new)
    assert c.get("/api/auth/me").json()["account"] == me and seen == []


def test_the_unsaved_panel_reads_every_completed_room_in_one_query(monkeypatch):
    host, guest = player(), player()

    def finished_room():
        code = host.post("/api/rooms", json={"bench": False, "size": 2, "style": "own"}).json()["code"]
        guest.post(f"/api/rooms/{code}/join")
        host.post(f"/api/rooms/{code}/start")
        draft_to_the_end(host, code)
        draft_to_the_end(guest, code)
        return code

    def statements():
        seen = count_queries(monkeypatch)
        listed = [r["code"] for r in guest.post("/api/results/unsaved", json={}).json()["rooms"]]
        monkeypatch.undo()
        return listed, len(seen)

    first = finished_room()
    one, n1 = statements()
    later = [finished_room(), finished_room()]
    three, n3 = statements()
    assert one == [first] and sorted(three) == sorted([first, *later]) and n3 == n1
