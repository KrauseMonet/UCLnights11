"""Auction rooms (C70) end to end, through the API, against a real Postgres: the host's
choice, sealed rounds and open lots on the server's clock, and on to the tournament."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from game import auction as sealed
from game import open_auction as opened
from web import auth, db
from web import rooms as rooms_mod
from web.app import app


@pytest.fixture(scope="module", autouse=True)
def configured(database):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield
    db.close_all()
    mp.undo()


_n = iter(range(10_000))


def player():
    name = f"auc{next(_n)}"
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    return c


class Clock:
    def __init__(self):
        self.t = 2_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rooms_mod, "clock", c)
    return c


def auction_room(style, n=2, size=4, **kw):
    people = [player() for _ in range(n)]
    body = {"bench": False, "together": False, "size": size, "style": style,
            "timer": 45 if style == "sealed" else 30, **kw}
    r = people[0].post("/api/rooms", json=body)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    for p in people[1:]:
        p.post(f"/api/rooms/{code}/join")
    room = people[0].post(f"/api/rooms/{code}/start").json()
    return people, code, room


def market_lot(room, seat_view=True):
    """A man in the market this viewer can take."""
    return next(c["i"] for cs in room["auction"]["market"] for c in cs["cards"] if c["takeable"])


# -- the host's choice --------------------------------------------------------------------

def test_the_host_chooses_an_auction_in_the_lobby():
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4, "bench": False, "together": False}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert guest.post(f"/api/rooms/{code}/style", json={"style": "sealed", "timer": 45}).status_code == 403
    assert host.post(f"/api/rooms/{code}/style", json={"style": "sealed", "timer": 15}).status_code == 400
    assert host.post(f"/api/rooms/{code}/style", json={"style": "sealed", "timer": 60}).json()["style"] == "sealed"
    assert host.post(f"/api/rooms/{code}/style", json={"style": "open", "timer": 60}).status_code == 400
    assert host.post(f"/api/rooms/{code}/style", json={"style": "open", "timer": 15}).json()["style"] == "open"


def test_an_open_auction_is_for_rooms_of_eight_at_most():
    host = player()
    r = host.post("/api/rooms", json={"size": 16, "style": "open", "timer": 30})
    assert r.status_code == 400 and "sealed" in r.json()["detail"]
    assert host.post("/api/rooms", json={"size": 16, "style": "sealed", "timer": 45}).status_code == 200


def test_an_auction_room_bids_and_a_turn_room_picks():
    (host, guest), code, room = auction_room("sealed")
    assert host.post(f"/api/rooms/{code}/pick", json={"index": 0, "expect": 0}).status_code == 400
    people = [player(), player()]
    turn = people[0].post("/api/rooms", json={"size": 4, "bench": False, "together": False}).json()["code"]
    people[1].post(f"/api/rooms/{turn}/join")
    people[0].post(f"/api/rooms/{turn}/start")
    assert people[0].post(f"/api/rooms/{turn}/bids", json={"round": 1, "bids": []}).status_code == 400


# -- sealed rounds ------------------------------------------------------------------------

def test_a_sealed_bid_is_secret_until_the_round_closes(clock):
    (host, guest), code, room = auction_room("sealed")
    a = room["auction"]
    assert a["kind"] == "sealed" and a["round"] == 1 and a["has_bid"] == [False, False]
    lot = market_lot(room)
    r = host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 37]]}).json()
    assert r["auction"]["bid"] == [[lot, 37]] and r["auction"]["has_bid"] == [True, False]
    seen = guest.get(f"/api/rooms/{code}").json()
    assert seen["auction"]["bid"] is None and seen["auction"]["has_bid"] == [True, False]
    text = json.dumps(seen)
    assert f"{lot}.37" not in text and '"amount"' not in text and seen["auction"]["sales"] == []
    assert all(s["spent"] == 0 for s in seen["auction"]["seats"])


def test_a_round_closes_once_everyone_still_buying_has_bid(clock):
    (host, guest), code, room = auction_room("sealed")
    lot = market_lot(room)
    host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 30]]})
    clock.t += 10.0
    r = guest.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 20]]}).json()
    a = r["auction"]
    assert a["round"] == 2 and a["has_bid"] == [False, False] and a["bid"] is None
    (s,) = a["last_round"]
    assert (s["seat"], s["price"], s["others"]) == (0, 21, [{"seat": 1, "amount": 20}])   # the second price
    assert a["seats"][0]["spent"] == 21 and a["seats"][0]["places"] == 10
    assert a["closes_at"] == pytest.approx(clock.t + 45)          # the next round's clock starts now


def test_a_bid_can_be_changed_until_the_round_closes(clock):
    (host, guest), code, room = auction_room("sealed")
    lot = market_lot(room)
    host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 30]]})
    r = host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": []}).json()
    assert r["auction"]["bid"] == [] and r["auction"]["round"] == 1


def test_a_bid_for_a_round_already_closed_is_refused_with_the_room(clock):
    (host, guest), code, room = auction_room("sealed")
    lot = market_lot(room)
    host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 5]]})
    guest.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": []})
    late = host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, 6]]})
    assert late.status_code == 409 and late.json()["room"]["auction"]["round"] == 2


def test_an_illegal_sealed_bid_is_a_400(clock):
    (host, guest), code, room = auction_room("sealed")
    lot = market_lot(room)
    r = host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": [[lot, sealed.BUDGET]]})
    assert r.status_code == 400 and "keep" in r.json()["detail"]


def test_a_round_whose_clock_runs_out_closes_with_an_auto_bid_for_the_silent(clock):
    (host, guest), code, room = auction_room("sealed", timer=30)
    host.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": []})
    clock.t += 30 + rooms_mod.CLOCK_GRACE_S - 0.5
    assert guest.get(f"/api/rooms/{code}").json()["auction"]["round"] == 1
    clock.t += 1.0
    a = guest.get(f"/api/rooms/{code}").json()["auction"]
    assert a["round"] == 2
    (s,) = a["last_round"]
    assert s["seat"] == 1 and s["price"] == sealed.MIN_BID


# -- open lots ----------------------------------------------------------------------------

def nominate_any(c, code, room):
    a = room["auction"]
    i = next(x["i"] for x in a["deal"]["cards"] if x["takeable"])
    return c.post(f"/api/rooms/{code}/nominate", json={"lot": a["lots_done"] + 1, "index": i})


def test_the_nominator_puts_a_man_up_and_others_raise(clock):
    (host, guest), code, room = auction_room("open")
    a = room["auction"]
    assert a["kind"] == "open" and a["nominator"] == 0 and a["deal"] and a["lot"] is None
    assert nominate_any(guest, code, guest.get(f"/api/rooms/{code}").json()).status_code == 400   # not his turn
    clock.t += 4.0
    lot = nominate_any(host, code, room).json()["auction"]["lot"]
    assert (lot["number"], lot["leader"], lot["price"]) == (1, 0, sealed.MIN_BID)
    assert lot["ends_at"] == pytest.approx(clock.t + opened.LOT_SECONDS, abs=0.02)
    assert host.post(f"/api/rooms/{code}/bid", json={"lot": 1, "amount": 5}).status_code == 400   # he leads
    r = guest.post(f"/api/rooms/{code}/bid", json={"lot": 1, "amount": 9}).json()["auction"]["lot"]
    assert (r["leader"], r["price"]) == (1, 9)
    assert guest.post(f"/api/rooms/{code}/bid", json={"lot": 2, "amount": 12}).status_code == 409


def test_a_lot_closes_on_its_clock_and_the_next_seat_nominates(clock):
    (host, guest), code, room = auction_room("open")
    nominate_any(host, code, room)
    guest.post(f"/api/rooms/{code}/bid", json={"lot": 1, "amount": 7})
    clock.t += opened.BID_SECONDS + opened.LOT_SECONDS          # well past the clock and its grace
    a = host.get(f"/api/rooms/{code}").json()["auction"]
    assert a["lot"] is None and a["lots_done"] == 1 and a["nominator"] == 1
    (s,) = a["sales"]
    assert (s["seat"], s["price"]) == (1, 7)
    late = host.post(f"/api/rooms/{code}/bid", json={"lot": 1, "amount": 8})
    assert late.status_code == 409
    stale = dict(room, auction={**a, "lots_done": 0})                # a screen still showing lot 1
    assert nominate_any(guest, code, stale).status_code == 409
    assert nominate_any(guest, code, guest.get(f"/api/rooms/{code}").json()).status_code == 200


def test_a_nominator_out_of_time_has_a_man_put_up_for_him(clock):
    (host, guest), code, room = auction_room("open", timer=15)
    clock.t += 15 + opened.GRACE_S - 0.2
    assert guest.get(f"/api/rooms/{code}").json()["auction"]["lot"] is None
    clock.t += 0.5
    lot = guest.get(f"/api/rooms/{code}").json()["auction"]["lot"]
    assert lot is not None and lot["nominator"] == 0 and lot["leader"] == 0
    assert nominate_any(host, code, room).status_code == 409                # his own nomination now comes late


def test_a_server_clock_running_backwards_never_breaks_the_auction(clock):
    (host, guest), code, room = auction_room("open")
    clock.t += 5.0
    nominate_any(host, code, room)
    clock.t -= 2.0                                           # another server, a little behind
    assert guest.post(f"/api/rooms/{code}/bid", json={"lot": 1, "amount": 4}).status_code == 200


# -- to the tournament --------------------------------------------------------------------

@pytest.mark.parametrize("style", ["sealed", "open"])
def test_the_hosts_finish_fills_every_squad_and_the_tournament_plays(clock, style):
    (host, guest), code, room = auction_room(style)
    assert guest.post(f"/api/rooms/{code}/finish").status_code == 403
    r = host.post(f"/api/rooms/{code}/finish").json()
    assert r["status"] == "complete" and all(s["picks"] == 11 for s in r["seats"])
    a = r["auction"]
    assert a["complete"] and all(s["money"] >= 0 and s["places"] == 0 for s in a["seats"])
    t = host.get(f"/api/rooms/{code}/tournament")
    assert t.status_code == 200 and len(t.json()["players"]) == 2


def test_a_bench_auction_plans_before_it_completes(clock):
    (host, guest), code, room = auction_room("sealed", bench=True)
    while True:
        room = host.get(f"/api/rooms/{code}").json()
        if room["auction"]["complete"]:
            break
        for c in (host, guest):
            seen = c.get(f"/api/rooms/{code}").json()
            if seen["auction"]["complete"] or not seen["auction"]["seats"][seen["auction"]["you"]]["places"]:
                continue
            c.post(f"/api/rooms/{code}/bids", json={"round": seen["auction"]["round"], "bids": [[market_lot(seen), 1]]})
    assert room["status"] == "drafting" and room["draft"]["total"] == 14 and room["draft"]["complete"]
    assert room["draft"]["plan"] is not None                  # the automatic plan, written out
    host.post(f"/api/rooms/{code}/plan", json={"changes": None})
    assert guest.post(f"/api/rooms/{code}/plan", json={"changes": None}).json()["status"] == "complete"


def test_a_memory_auction_shows_no_rating_until_it_completes(clock):
    (host, guest), code, room = auction_room("sealed", memory=True)
    cards = [c for cs in room["auction"]["market"] for c in cs["cards"]]
    assert cards and all(c["rating"] is None for c in cards)
    done = host.post(f"/api/rooms/{code}/finish").json()
    assert all(s["card"]["rating"] is not None for s in done["auction"]["sales"])


def test_an_auction_room_that_loses_a_seat_is_failed(clock, database):
    (host, guest, third), code, room = auction_room("sealed", n=3)
    with psycopg.connect(database) as conn:
        conn.execute("delete from room_seats where room_code = %s and seat = 2", (code,))
        conn.commit()
    with db.connection() as conn:
        rooms_mod.seat_removed(conn, code)
    assert host.get(f"/api/rooms/{code}").json()["status"] == "failed"


def test_the_hosts_finish_in_a_bench_room_plans_for_everyone(clock):
    (host, guest), code, room = auction_room("open", bench=True)
    r = host.post(f"/api/rooms/{code}/finish").json()
    assert r["status"] == "complete" and all(s["picks"] == 14 and s["ready"] for s in r["seats"])
    assert host.get(f"/api/rooms/{code}/tournament").status_code == 200


def test_an_auction_that_no_longer_replays_shows_as_failed(clock, database):
    (host, guest), code, room = auction_room("sealed")
    with psycopg.connect(database) as conn:
        conn.execute("update rooms set auction = %s where code = %s", (f"0:0.{sealed.BUDGET}", code))
        conn.commit()
    assert host.get(f"/api/rooms/{code}").json()["status"] == "failed"


def test_the_database_refuses_a_malformed_bid(clock, database):
    (host, guest), code, room = auction_room("sealed")
    with psycopg.connect(database) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("update room_seats set bids = 'x' where room_code = %s", (code,))


def test_only_a_seat_in_the_room_may_bid(clock):
    (host, guest), code, room = auction_room("sealed")
    outsider = player()
    r = outsider.post(f"/api/rooms/{code}/bids", json={"round": 1, "bids": []})
    assert r.status_code == 403
    (h, g), open_code, open_room = auction_room("open")
    assert outsider.post(f"/api/rooms/{open_code}/bid", json={"lot": 1, "amount": 3}).status_code == 403
