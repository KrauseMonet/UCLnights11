"""Watching a room's tournament together (C52): the schedule (pure), and the room routes
through the API against a real Postgres: kick-off, what the clock lets out, the host's
skips, and the full tournament held back until the watch ends."""

import json

import pytest

from game import watch
from game.tournament import LEAGUE, play_room
from tests.test_room_tournament import DECK, LEAGUE as ENGINE_LEAGUE, humans
from web import rooms as rooms_mod
from web import db

TOURNAMENTS = {(size, n, seed): play_room(DECK, ENGINE_LEAGUE, seed, humans(n), size)
               for size, n, seed in [(36, 1, 3), (36, 4, 5), (8, 3, 9), (2, 2, 4), (16, 2, 6)]}


# -- the schedule (pure) -------------------------------------------------------------

@pytest.mark.parametrize("k", list(TOURNAMENTS))
def test_rounds_hold_every_friends_match_once_back_to_back_and_none_without_a_friend(k):
    t = TOURNAMENTS[k]
    rs = watch.rounds(t)
    mine = [f for f in t.fixtures if f.home.owner is not None or f.away.owner is not None]
    # Each once. (Two-legged ties are stored tie by tie, both legs together; a round holds
    # every tie's first legs, so the order differs from the stored one.)
    assert sorted(id(f) for r in rs for f in r.fixtures) == sorted(id(f) for f in mine)
    assert all(r.fixtures for r in rs)
    assert rs[0].start == 0 and all(b.start == a.end for a, b in zip(rs, rs[1:]))
    assert all(r.kick == r.start + watch.BREAK_S for r in rs)
    for r in rs:
        assert r.minutes == (120 if r.label in ("Second leg", "Final") else 90)
        assert len({(f.stage, f.label) for f in r.fixtures}) == 1
    assert [r.key for r in rs] == sorted(r.key for r in rs)


def test_a_round_with_no_friend_in_it_is_left_out():
    # Find a league room whose only friend went straight to the round of 16.
    for seed in range(40):
        t = play_room(DECK, ENGINE_LEAGUE, seed, humans(1), 36)
        if [r.side for r in t.table].index(t.sides[0]) < 8:
            break
    else:
        pytest.fail("no seed put the friend in the top eight")
    stages = [r.stage for r in watch.rounds(t)]
    assert "Knockout play-offs" not in stages and stages[8] == "Round of 16"


def _place(rs, p):
    """Where moment p is: (round, phase, how far into it), the match part in minutes."""
    i = watch.current(rs, p)
    r = rs[i]
    d = p - r.start
    if d < watch.BREAK_S:
        return i, "countdown", round(d, 6)
    if d < watch.BREAK_S + r.minutes * r.minute_s:
        return i, "live", round((d - watch.BREAK_S) / r.minute_s, 6)
    return i, "after", round(d - watch.BREAK_S - r.minutes * r.minute_s, 6)


@pytest.mark.parametrize("old,new", [(watch.MINUTE_S, 0.3), (0.3, 0.055), (0.14, 0.14)])
def test_a_new_pace_keeps_the_round_the_phase_and_the_match_minute(old, new):
    t = TOURNAMENTS[(36, 4, 5)]
    a, b = watch.rounds(t, old), watch.rounds(t, new)
    assert all(r.minute_s == old for r in a) and all(r.minute_s == new for r in b)
    assert a[0].end - a[0].kick == pytest.approx(a[0].minutes * old + watch.AFTER_S)
    end = watch.end_at(a)
    for k in range(400):
        p = end * k / 400 + 0.0137
        q = watch.retime(a, b, p)
        assert _place(b, q) == pytest.approx(_place(a, p)), p
        assert watch.retime(b, a, q) == pytest.approx(p)
    # The watch's end maps to the end, and past it as far past.
    assert watch.retime(a, b, end + 3) == pytest.approx(watch.end_at(b) + 3)


def test_a_room_made_before_paces_keeps_the_old_minute():
    assert watch.minute_s(None) == watch.MINUTE_S == 0.1
    assert watch.minute_s("slow") == watch.PACES["slow"] and watch.DEFAULT_PACE in watch.PACES


def test_parts_come_out_in_order_pairs_then_results_then_standings():
    rs = watch.rounds(TOURNAMENTS[(36, 4, 5)])
    times = [r.at(k) for r in rs for k in range(3)]
    assert times == sorted(times)
    r = rs[2]
    before = watch.known(rs, r.start - 0.01)
    # The last round's standings and this one's pairings come out together.
    assert watch.known(rs, r.start) == before + 2
    assert watch.known(rs, r.kick - 0.01) == before + 2               # no result before kick-off
    assert watch.known(rs, r.kick) == before + 3
    assert watch.known(rs, r.end) == before + 5                       # standings, and the next pairings
    assert watch.current(rs, -1) == -1 and watch.current(rs, r.start) == 2
    assert watch.known(rs, watch.end_at(rs)) == 3 * len(rs)


def test_skips_land_on_the_round_the_host_saw_and_past_the_league_phase():
    rs = watch.rounds(TOURNAMENTS[(36, 4, 5)])
    assert watch.skip_target(rs, "kickoff", 3) == rs[3].kick
    assert watch.skip_target(rs, "fulltime", 3) == rs[3].end - watch.AFTER_S
    first_knockout = next(r for r in rs if r.stage != LEAGUE)
    assert watch.skip_target(rs, "phase", 0) == first_knockout.start
    assert watch.skip_target(rs, "end", 0) == watch.end_at(rs)
    cup = watch.rounds(TOURNAMENTS[(8, 3, 9)])
    assert watch.skip_target(cup, "phase", 0) == cup[0].start          # no league phase to skip
    with pytest.raises(ValueError):
        watch.skip_target(rs, "fulltime", len(rs))
    with pytest.raises(ValueError):
        watch.skip_target(rs, "backwards", 0)


@pytest.mark.parametrize("k", list(TOURNAMENTS))
def test_standings_after_the_last_round_are_each_friends_whole_run(k):
    t = TOURNAMENTS[k]
    rs = watch.rounds(t)
    for st in watch.standings(t, rs, len(rs) - 1):
        mine = [f for f in t.fixtures if st.side in (f.home, f.away)]
        assert st.played == len(mine) == st.won + st.drawn + st.lost
        assert st.gf == sum(f.result.home_goals if f.home is st.side else f.result.away_goals for f in mine)
        assert st.out == t.reached(st.side)                           # nobody is still in it


def test_a_friend_is_out_only_once_they_have_no_later_match():
    t = TOURNAMENTS[(36, 4, 5)]
    rs = watch.rounds(t)
    seven = watch.standings(t, rs, 6)                                 # after matchday 7
    assert all(st.out is None and st.played == 7 for st in seven)
    eight = {st.side.key: st for st in watch.standings(t, rs, 7)}
    order = [r.side for r in t.table]
    for s in (x for x in t.sides if x.owner is not None):
        pos = order.index(s) + 1
        assert eight[s.key].position == pos                           # the final table, after the last matchday
        assert (eight[s.key].out == LEAGUE) == (pos > 24)


# -- through the API -----------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def configured(database):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    from web import auth
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield
    db.close_all()
    mp.undo()


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


def finished_room(size=8, n=2, **kw):
    """A completed room watched together, its host and guests."""
    from tests.test_friends import player
    people = [player() for _ in range(n)]
    code = people[0].post("/api/rooms", json={"bench": False, "size": size, "style": "own", **kw}).json()["code"]
    for p in people[1:]:
        p.post(f"/api/rooms/{code}/join")
    people[0].post(f"/api/rooms/{code}/start")
    room = people[0].post(f"/api/rooms/{code}/finish").json()
    assert room["status"] == "complete"
    return people, code


def watch_of(c, code, **params):
    r = c.get(f"/api/rooms/{code}/watch", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def schedule(code):
    with db.connection() as conn:
        room = rooms_mod.load_room(conn, code)
    from web.app import _watched
    return room, _watched(room)[1]


def test_a_new_room_watches_together_and_only_the_host_changes_that_in_the_lobby():
    from tests.test_friends import player
    host, guest = player(), player()
    code = host.post("/api/rooms", json={"size": 4}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    assert host.get(f"/api/rooms/{code}").json()["together"] is True
    assert guest.post(f"/api/rooms/{code}/together", json={"together": False}).status_code == 403
    assert host.post(f"/api/rooms/{code}/together", json={"together": False}).json()["together"] is False
    host.post(f"/api/rooms/{code}/together", json={"together": True})
    host.post(f"/api/rooms/{code}/start")
    assert host.post(f"/api/rooms/{code}/together", json={"together": False}).status_code == 409


def test_a_room_that_watches_alone_shows_its_tournament_at_once(clock):
    (host, guest), code = finished_room(together=False)
    assert watch_of(host, code) == {"code": code, "together": False}
    assert host.get(f"/api/rooms/{code}/tournament").status_code == 200


def test_the_tournament_is_held_back_until_the_host_kicks_off_and_the_watch_ends(clock):
    (host, guest), code = finished_room()
    w = watch_of(guest, code)
    assert w["started"] is False and w["parts"] == [] and w["can_start"] is False and w["host"]
    assert watch_of(host, code)["can_start"] is True
    for c in (host, guest):
        assert c.get(f"/api/rooms/{code}/tournament").status_code == 409
        assert c.get(f"/api/rooms/{code}/analysis").status_code == 409
        assert c.post("/api/results", json={"source": "room", "key": code}).status_code == 409
    assert guest.post(f"/api/rooms/{code}/watch/start").status_code == 403
    w = host.post(f"/api/rooms/{code}/watch/start").json()
    assert w["started"] is True and w["t0"] == clock.t
    _, rs = schedule(code)
    clock.t += watch.end_at(rs) - 0.01
    assert host.get(f"/api/rooms/{code}/tournament").status_code == 409
    clock.t += 0.01
    assert watch_of(guest, code)["ended"] is True
    t = host.get(f"/api/rooms/{code}/tournament").json()
    assert t["you"] is not None and t["your_matches"]


def test_a_seat_may_kick_off_once_the_host_has_left_the_room_waiting(clock):
    (host, guest), code = finished_room()
    clock.t += watch.HOST_WAIT_S - 1
    w = watch_of(guest, code)
    assert w["can_start"] is False and 0 < w["host_wait"] <= 1
    assert guest.post(f"/api/rooms/{code}/watch/start").status_code == 403
    clock.t += 1
    assert watch_of(guest, code)["can_start"] is True
    assert guest.post(f"/api/rooms/{code}/watch/start").json()["started"] is True
    t0 = watch_of(host, code)["t0"]
    clock.t += 5
    host.post(f"/api/rooms/{code}/watch/start")                     # a second kick-off changes nothing
    assert watch_of(host, code)["t0"] == t0


def test_the_clock_lets_out_pairings_then_results_then_standings_and_nothing_early(clock):
    (host, guest), code = finished_room()
    host.post(f"/api/rooms/{code}/watch/start")
    _, rs = schedule(code)
    w = watch_of(guest, code)
    assert [p["kind"] for p in w["parts"]] == ["pairs"] and w["have"] == 1
    assert "hg" not in json.dumps(w["parts"])                        # no score before kick-off
    assert w["humans"] and sum(h["you"] for h in w["humans"]) == 1
    # Nothing new: a few bytes, until a skip moves the start.
    small = watch_of(guest, code, have=1, t0=w["t0"])
    assert small["unchanged"] is True and "parts" not in small
    clock.t += rs[0].kick - 0.01
    assert watch_of(guest, code, have=1, t0=w["t0"])["unchanged"] is True
    clock.t += 0.01
    w = watch_of(guest, code, have=1, t0=w["t0"])
    assert [p["kind"] for p in w["parts"]] == ["results"] and w["humans"] is None
    fixtures = w["parts"][0]["fixtures"]
    assert len(fixtures) == len(rs[0].fixtures) and all("shots" in f and "lineups" in f for f in fixtures)
    mine = [f for f in fixtures if f["home"]["you"] or f["away"]["you"]]
    assert len(mine) == 1                                            # the guest's own match, marked
    clock.t += rs[0].end - rs[0].kick
    w = watch_of(guest, code, have=2, t0=w["t0"])
    assert [p["kind"] for p in w["parts"]] == ["after", "pairs"]
    assert {s["name"] for s in w["parts"][0]["standings"]} == {s["name"] for s in watch_of(guest, code)["humans"]}


def test_only_the_host_skips_and_only_forward(clock):
    (host, guest), code = finished_room(size=36)
    host.post(f"/api/rooms/{code}/watch/start")
    _, rs = schedule(code)
    t0 = clock.t
    assert guest.post(f"/api/rooms/{code}/watch/skip", json={"to": "end"}).status_code == 403
    assert host.post(f"/api/rooms/{code}/watch/skip", json={"to": "sideways"}).status_code == 400
    w = host.post(f"/api/rooms/{code}/watch/skip", json={"to": "kickoff", "round": 0}).json()
    assert w["t0"] == pytest.approx(t0 - rs[0].kick)
    w = host.post(f"/api/rooms/{code}/watch/skip", json={"to": "fulltime", "round": 0}).json()
    assert clock.t - w["t0"] == pytest.approx(rs[0].end - watch.AFTER_S)    # the whistle
    assert [p["kind"] for p in w["parts"]][-1] == "results"                 # standings come at the round's end
    # A second click for the same round lands somewhere already passed: nothing moves.
    again = host.post(f"/api/rooms/{code}/watch/skip", json={"to": "fulltime", "round": 0}).json()
    assert again["t0"] == w["t0"]
    w = host.post(f"/api/rooms/{code}/watch/skip", json={"to": "phase"}).json()
    knockout = next(r for r in rs if r.stage != LEAGUE)
    assert clock.t - w["t0"] == pytest.approx(knockout.start)
    # Already past the league phase: skipping it again does nothing.
    assert host.post(f"/api/rooms/{code}/watch/skip", json={"to": "kickoff", "round": 0}).json()["t0"] == w["t0"]
    assert guest.get(f"/api/rooms/{code}/tournament").status_code == 409
    w = host.post(f"/api/rooms/{code}/watch/skip", json={"to": "end"}).json()
    assert w["ended"] is True and w["parts"] == []
    assert guest.get(f"/api/rooms/{code}/tournament").status_code == 200


def test_skipping_needs_a_kick_off_first(clock):
    (host, guest), code = finished_room()
    assert host.post(f"/api/rooms/{code}/watch/skip", json={"to": "end"}).status_code == 409


def test_a_spectator_watches_on_the_same_clock(clock):
    from tests.test_friends import player
    (host, guest), code = finished_room()
    stranger = player()
    host.post(f"/api/rooms/{code}/watch/start")
    _, rs = schedule(code)
    clock.t += rs[0].kick
    w = watch_of(stranger, code)
    assert w["seated"] is False and w["you"] is None and w["can_start"] is False
    assert [p["kind"] for p in w["parts"]] == ["pairs", "results"]
    assert not any(f["home"]["you"] or f["away"]["you"] for f in w["parts"][1]["fixtures"])


def test_unsaved_leaves_out_a_room_still_watching(clock):
    (host, guest), code = finished_room()
    unsaved = lambda: [r["code"] for r in host.post("/api/results/unsaved", json={}).json()["rooms"]]  # noqa: E731
    assert code not in unsaved()
    host.post(f"/api/rooms/{code}/watch/start")
    host.post(f"/api/rooms/{code}/watch/skip", json={"to": "end"})
    assert code in unsaved()


def test_watch_routes_refuse_a_room_still_drafting(clock):
    from tests.test_friends import player
    host = player()
    code = host.post("/api/rooms", json={"size": 4, "style": "own"}).json()["code"]
    host.post(f"/api/rooms/{code}/start")
    assert host.get(f"/api/rooms/{code}/watch").status_code == 409
    assert host.post(f"/api/rooms/{code}/watch/start").status_code == 409


def test_a_skip_reaches_a_screen_that_had_nothing_new(clock):
    (host, guest), code = finished_room()
    host.post(f"/api/rooms/{code}/watch/start")
    _, rs = schedule(code)
    clock.t += rs[0].kick + 1                                        # live: results out, standings not yet
    w = watch_of(guest, code)
    assert watch_of(guest, code, have=w["have"], t0=w["t0"])["unchanged"] is True
    # Full time lands between the same two parts, so only the moved start says it moved.
    host.post(f"/api/rooms/{code}/watch/skip", json={"to": "fulltime", "round": 0})
    after = watch_of(guest, code, have=w["have"], t0=w["t0"])     # the screen still holds the old start
    assert after["have"] == w["have"]
    assert "unchanged" not in after and after["t0"] < w["t0"]


def test_someone_without_a_seat_is_never_offered_the_kick_off(clock):
    from tests.test_friends import player
    (host, guest), code = finished_room()
    stranger = player()
    clock.t += watch.HOST_WAIT_S + 1                                 # long enough for any seat
    assert watch_of(guest, code)["can_start"] is True
    assert watch_of(stranger, code)["can_start"] is False
    assert stranger.post(f"/api/rooms/{code}/watch/start").status_code == 403


# -- the pace (C54) ----------------------------------------------------------------

def set_pace(c, code, pace):
    return c.post(f"/api/rooms/{code}/watch/pace", json={"pace": pace})


def test_a_new_room_watches_at_normal_pace_and_only_the_host_changes_it(clock):
    (host, guest), code = finished_room()
    w = watch_of(guest, code)
    assert w["pace"] == "normal" and w["minute_s"] == watch.PACES["normal"]
    assert set_pace(guest, code, "slow").status_code == 403
    assert set_pace(host, code, "glacial").status_code == 400
    w = set_pace(host, code, "slow").json()                          # before kick-off: stored, nothing moves
    assert w["pace"] == "slow" and w["minute_s"] == watch.PACES["slow"] and w["t0"] is None
    _, rs = schedule(code)
    assert all(r.minute_s == watch.PACES["slow"] for r in rs)


def test_a_pace_changed_mid_match_keeps_every_screen_at_the_same_minute(clock):
    (host, guest), code = finished_room()
    host.post(f"/api/rooms/{code}/watch/start")
    _, rs = schedule(code)
    clock.t += rs[0].kick + 30.5 * watch.PACES["normal"]           # 30 and a half minutes in
    held = watch_of(guest, code)
    w = set_pace(host, code, "slow").json()
    _, slow = schedule(code)
    assert clock.t - w["t0"] == pytest.approx(slow[0].kick + 30.5 * watch.PACES["slow"])
    # Every part comes again, timed at the new pace.
    assert [p["n"] for p in w["parts"]] == [0, 1]
    assert w["parts"][0]["end"] == pytest.approx(slow[0].end)
    # A screen that held the old timings is sent them all again.
    again = watch_of(guest, code, have=held["have"], t0=held["t0"], pace="normal")
    assert [p["n"] for p in again["parts"]] == [0, 1] and again["pace"] == "slow"
    assert watch_of(guest, code, have=2, t0=w["t0"], pace="slow")["unchanged"] is True


def test_a_pace_change_in_the_first_countdown_resends_the_timings_though_the_start_stays(clock):
    (host, guest), code = finished_room()
    host.post(f"/api/rooms/{code}/watch/start")
    clock.t += 3
    held = watch_of(guest, code)
    w = set_pace(host, code, "fast").json()
    assert w["t0"] == pytest.approx(held["t0"])                       # 3 s into the countdown either way
    again = watch_of(guest, code, have=held["have"], t0=held["t0"], pace="normal")
    assert "unchanged" not in again and again["parts"][0]["end"] != held["parts"][0]["end"]


def test_the_pace_cannot_change_once_the_watch_is_over(clock):
    (host, guest), code = finished_room()
    host.post(f"/api/rooms/{code}/watch/start")
    host.post(f"/api/rooms/{code}/watch/skip", json={"to": "end"})
    assert set_pace(host, code, "slow").status_code == 409
    assert guest.get(f"/api/rooms/{code}/tournament").status_code == 200


def test_a_room_made_before_paces_watches_as_it_did(clock):
    (host, guest), code = finished_room()
    with db.connection() as conn:
        conn.execute("update rooms set watch_pace = null where code = %s", (code,))
    w = watch_of(guest, code)
    assert w["pace"] is None and w["minute_s"] == watch.MINUTE_S
    _, rs = schedule(code)
    assert all(r.minute_s == watch.MINUTE_S for r in rs)
    held = watch_of(guest, code, have=0, pace="")
    assert held["pace"] is None


def test_a_room_watching_alone_has_no_pace_to_set(clock):
    (host, guest), code = finished_room(together=False)
    assert set_pace(host, code, "slow").status_code == 400
