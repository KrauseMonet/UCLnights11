"""Changes made during a match (C60): the live engine, the solo link's live part, the
daily's ranked match held on the server, and a live room's pause; plus the half-time
breaks in a live room's clock."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from game import match, watch
from game.draft import (IllegalMove, LiveEntry, Pick, decode_live, decode_solo, decode_state, encode_live,
                        replay, split_live, why_not)
from game.tournament import (Live, MatchPlan, Side, auto_plan, bench_options, change_made, live_subs, pitch_at,
                             play_room, play_tournament)
from tests.test_room_tournament import DECK, LEAGUE
from web import db
from web.app import app

client = TestClient(app)


def bench_draft(seed, formation="433"):
    moves, s = [], replay(DECK, seed, formation, [], True)
    while not s.complete:
        moves.append(Pick(max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                              key=lambda i: s.deal.cards[i].rating)))
        s = replay(DECK, seed, formation, moves, True)
    return s


S7 = bench_draft(7)


def side(live=None, s=S7, key="YOU", owner=None):
    return Side(key, "Your XI", "YOU", s.formation, s.xi, you=owner is None, owner=owner,
                bench=s.bench, plan=auto_plan(s.bench), live=live)


def mine(t, owner=None):
    me = next(x for x in t.sides if (x.you if owner is None else x.owner == owner))
    return me, [f for f in t.fixtures if me in (f.home, f.away)]


def first_change(me, f, minute):
    s = 0 if f.home is me else 1
    can = bench_options(me, f.result, s, minute)
    on = next(i for i, offs in can.items() if offs)
    return s, on, can[on][0]


def before(r, m):
    """Everything a screen at minute m has seen of a match."""
    return ([(g.minute, g.side, g.scorer.id, g.assist.id if g.assist else None) for g in r.goals if g.minute <= m],
            [x for x in r.shots if x.minute <= m], [x for x in r.flow if x[0] <= m],
            [(x.minute, x.side, x.off.id, x.on.id) for x in r.subs if x.minute < m])


def results(t):
    return [(f.stage, f.label, f.home.key, f.away.key, f.result.home_goals, f.result.away_goals,
             [(g.minute, g.scorer.id) for g in f.result.goals]) for f in t.fixtures]


# -- the engine (pure) -------------------------------------------------------------

def test_a_change_moves_nothing_before_its_break_nor_any_other_match_already_played():
    t = play_tournament(DECK, LEAGUE, 7, side({}), engine=Live("7"), fmt="league")
    me, ms = mine(t)
    # A change that alters the score: one that changed nothing would leave even a shared
    # stream where it was.
    for k, minute in ((k, m) for k in range(8) for m in (20, 40, 60)):
        f = ms[k]
        s, on, off = first_change(me, f, minute)
        t2 = play_tournament(DECK, LEAGUE, 7, side({k: MatchPlan(((minute, on, off),))}), engine=Live("7"), fmt="league")
        _, ms2 = mine(t2)
        if [(g.minute, g.side) for g in ms2[k].result.goals] != [(g.minute, g.side) for g in f.result.goals]:
            break
    else:
        pytest.fail("no change altered a score")
    assert change_made(ms2[k].result, s, minute, me.bench[on], off)
    assert before(ms2[k].result, minute) == before(f.result, minute)
    i = t.fixtures.index(f)
    # Every match before it in the order of play, and every other match on its matchday.
    assert results(t)[:i] == results(t2)[:i]
    same_day = lambda tt, g: [x for x in results(tt) if (x[0], x[1]) == (g.stage, g.label) and "YOU" not in x[2:4]]  # noqa: E731
    assert same_day(t, f) == same_day(t2, ms2[k])


def test_a_live_side_makes_no_change_it_wasn_t_told_to_and_clubs_keep_their_plans():
    t = play_tournament(DECK, LEAGUE, 9, side({}), engine=Live("9"), fmt="league")
    me, ms = mine(t)
    assert all(x.side != (0 if f.home is me else 1) for f in ms for x in f.result.subs)
    assert any(x.side == (1 if f.home is me else 0) for f in ms for x in f.result.subs)


def test_the_plan_takes_over_from_the_minute_a_skip_says():
    me = side({0: MatchPlan((), 70), 1: MatchPlan((), 0)})
    assert [x.minute for x in live_subs(me, 0)] == [70, 70, 80]
    assert live_subs(me, 1) == me.plan and live_subs(me, 2) == ()
    assert live_subs(side(None), 5) == side(None).plan
    t = play_tournament(DECK, LEAGUE, 9, me, engine=Live("9"), fmt="league")
    you, ms = mine(t)
    for k, earliest in ((0, 70), (1, 60)):
        s = 0 if ms[k].home is you else 1
        made = [x.minute for x in ms[k].result.subs if x.side == s]
        assert made and min(made) >= earliest


def test_live_statistics_run_to_the_real_totals_and_never_go_back():
    t = play_tournament(DECK, LEAGUE, 11, side({}), engine=Live("11"), fmt="league")
    for f in t.fixtures[:40]:
        r = f.result
        h, a = r.stats
        assert r.flow[-1][2:] == (h.passes, a.passes, h.completed, a.completed) and r.flow[-1][1] == h.possession
        assert all(x[0] % match.BLOCK == 0 or x[0] == (120 if r.extra_time else 90) for x in r.flow)
        for prev, nxt in zip(r.flow, r.flow[1:]):
            assert all(n >= p - 1 for p, n in zip(prev[2:], nxt[2:]))
        assert sum(x.on_target for x in r.shots if x.side == 0) == h.on_target


def test_a_match_on_a_stream_of_its_own_is_the_same_wherever_it_is_played():
    """Live's per-match stream: the same pairing in the same place of the order of play is
    the same match, whatever was drawn before it."""
    a = play_tournament(DECK, LEAGUE, 13, side({}), engine=Live("13"), fmt="league")
    b = play_tournament(DECK, LEAGUE, 13, side({}), engine=Live("13"), fmt="league")
    assert results(a) == results(b)
    assert results(a) != results(play_tournament(DECK, LEAGUE, 13, side(None), engine=2, fmt="league"))


def test_bench_options_need_a_break_a_substitute_and_never_take_the_keeper():
    t = play_tournament(DECK, LEAGUE, 7, side({}), engine=Live("7"), fmt="league")
    me, ms = mine(t)
    f = ms[0]
    s = 0 if f.home is me else 1
    can = bench_options(me, f.result, s, 40)
    assert set(can) == {0, 1, 2}
    keeper = next(c.id for c in me.xi if c.slot == "GK")
    assert all(keeper not in offs for offs in can.values())
    assert bench_options(me, f.result, s, 42) == {} and bench_options(me, f.result, s, 0) == {}
    assert bench_options(me, f.result, s, 90 if not f.result.extra_time else 120) == {}
    # Three changes made: none left. A man already on: never again.
    plan = []
    for m in (40, 50, 60):
        r = play_tournament(DECK, LEAGUE, 7, side({0: MatchPlan(tuple(plan))}), engine=Live("7"), fmt="league")
        you, rms = mine(r)
        _, on, off = first_change(you, rms[0], m)
        plan.append((m, on, off))
    r = play_tournament(DECK, LEAGUE, 7, side({0: MatchPlan(tuple(plan))}), engine=Live("7"), fmt="league")
    you, rms = mine(r)
    assert pitch_at(you, rms[0].result, s, 60)[2] == 3 and bench_options(you, rms[0].result, s, 65) == {}
    assert sorted(i for i in bench_options(you, rms[0].result, s, 45)) == [plan[1][1], plan[2][1]]


def test_bench_options_ask_the_rules_directly_of_a_keeper_and_a_fourth_man():
    """No keeper reaches a drafted bench and a drafted bench holds three, so neither rule
    could act on one; asked directly, of a bench with a keeper and a fourth man."""
    t = play_tournament(DECK, LEAGUE, 7, side({}), engine=Live("7"), fmt="league")
    me, ms = mine(t)
    keeper = next(c for cs in DECK.club_seasons for c in cs.cards if c.positions == ("GK",) and c.id not in {x.id for x in me.xi})
    extra = next(c for cs in DECK.club_seasons for c in cs.cards if c.positions[0] == "CB"
                 and c.id not in {x.id for x in [*me.xi, *me.bench]})
    big = Side("YOU", "Your XI", "YOU", me.formation, me.xi, you=True, bench=[*me.bench, keeper, extra],
               plan=me.plan, live={})
    f = ms[0]
    s = 0 if f.home is me else 1
    can = bench_options(big, f.result, s, 40)
    gk = next(c.id for c in me.xi if c.slot == "GK")
    assert can[3] == [] and all(gk not in offs for offs in can.values())
    made = f.result.subs + [match.Substitution(m, s, me.xi[j], me.bench[i], tuple(me.xi))
                            for m, i, j in ((10, 0, 9), (15, 1, 10), (20, 2, 8))]
    three = match.Result(f.result.home_goals, f.result.away_goals, f.result.goals, f.result.extra_time, None, None,
                         [], made)
    assert bench_options(big, three, s, 40) == {}


# -- the live part of a solo link -----------------------------------------------------

def test_a_live_part_round_trips_and_bad_ones_are_refused():
    live = {2: LiveEntry(((40, 1, 4), (45, 2, 12))), 4: LiveEntry((), 60), 5: LiveEntry()}
    text = encode_live(live)
    assert text == "m2c814c92c.4ac"
    assert decode_live(text) == {2: live[2], 4: live[4]}
    assert decode_live("m") == {}
    for bad in ("x", "m2c8", "m2c834", "m2c8e4", "m2c814c714", "m2c014", "m2c814c914c914c914", "m2ac.2ac", "m2az"):
        with pytest.raises(IllegalMove):
            decode_live(bad)


def test_only_a_bench_link_carries_a_live_part_and_rooms_and_the_daily_never_read_one():
    assert split_live("l5-433-1.2-p-m2c814") == ("l5-433-1.2-p", "m2c814")
    assert split_live("l5-433-1.2-m") == ("l5-433-1.2", "m")
    assert split_live("5-433-1.2") == ("5-433-1.2", None)
    assert split_live("5-433-1.2-m") == ("5-433-1.2-m", None)          # an eleven-pick link has no bench to change
    assert client.get("/api/tournament/5-433-1.2-m").status_code == 400
    for state in ("b5-433-1.2-m", "l5-433-1.2-m"):
        with pytest.raises(IllegalMove):
            decode_solo(state)
        with pytest.raises(IllegalMove):
            decode_state(state)


def finished_state(seed=21):
    s = client.post("/api/draft", json={"seed": seed}).json()
    while not s["complete"]:
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": next(x["i"] for x in s["deal"]["cards"] if x["takeable"])}).json()
    return s


def test_choosing_to_make_your_own_changes_is_part_of_the_link_and_survives_a_plan_or_sheet():
    s = finished_state()
    assert s["manual"] is False
    m = client.post(f"/api/draft/{s['state']}/mode", json={"manual": True}).json()
    assert m["state"] == s["state"] + "-m" and m["manual"] is True
    p = client.post(f"/api/draft/{m['state']}/plan", json={"changes": [{"on": 0, "minute": 60, "when": "any"}]}).json()
    assert p["state"].endswith("-m") and p["manual"]
    sh = client.post(f"/api/draft/{p['state']}/sheet", json={"sheet": list(reversed(range(11))) + [11, 12, 13]})
    assert sh.status_code in (200, 400)
    # Entries belong to one tournament: a new plan drops them and keeps the choice.
    p2 = client.post(f"/api/draft/{p['state'][:-2]}-m0c802/plan", json={"changes": None}).json()
    assert p2["state"].endswith("-m") and "c802" not in p2["state"]
    back = client.post(f"/api/draft/{m['state']}/mode", json={"manual": False}).json()
    assert back["state"] == s["state"] and back["manual"] is False
    unfinished = client.post("/api/draft", json={"seed": 3}).json()["state"]
    assert client.post(f"/api/draft/{unfinished}/mode", json={"manual": True}).status_code == 409


def test_a_change_made_in_a_solo_match_is_a_new_link_the_same_up_to_its_break():
    st = finished_state()["state"] + "-m"
    t = client.get(f"/api/tournament/{st}").json()
    assert t["you"]["manual"] is True
    assert all(x["side"] != (0 if f["home"]["you"] else 1) for f in t["your_matches"] for x in f["subs"])
    o = client.get(f"/api/tournament/{st}/bench", params={"match_no": 0, "minute": 40}).json()
    assert o["minute"] == 40 and o["left"] == 3 and not o["too_late"] and o["pitch"][0]["rating"] is not None
    b = next(x for x in o["bench"] if x["can_replace"])
    r = client.post(f"/api/tournament/{st}/sub", json={"match_no": 0, "minute": 40, "on": b["i"], "off": b["can_replace"][0]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["state"].startswith(st) and new["state"] != st
    f0, f1 = t["your_matches"][0], new["tournament"]["your_matches"][0]
    cut = lambda f: ([g for g in f["goals"] if g["minute"] <= 40], [x for x in f["shots"] if x[0] <= 40],  # noqa: E731
                     [x for x in f["flow"] if x[0] <= 40])
    assert cut(f0) == cut(f1)
    mine_subs = [x for x in f1["subs"] if x["side"] == (0 if f1["home"]["you"] else 1)]
    assert [(x["minute"], x["on"]) for x in mine_subs] == [(40, b["name"])]
    assert client.get(f"/api/tournament/{new['state']}").json()["your_matches"][0]["subs"] == f1["subs"]
    # Refused: the same man again, a man he can't replace, a break already played, a plan link.
    again = {"match_no": 0, "minute": 45, "on": b["i"], "off": b["can_replace"][0]}
    assert client.post(f"/api/tournament/{new['state']}/sub", json=again).status_code == 400
    keeper = next(c["id"] for c in o["pitch"] if c["slot"] == "GK")
    other = next(x for x in o["bench"] if x["i"] != b["i"])
    assert client.post(f"/api/tournament/{new['state']}/sub", json={**again, "on": other["i"], "off": keeper}).status_code == 400
    assert client.post(f"/api/tournament/{new['state']}/sub", json={**again, "minute": 35, "on": other["i"],
                                                                     "off": other["can_replace"][0]}).status_code == 409
    plain = st[:-2]
    assert client.post(f"/api/tournament/{plain}/sub", json=again).status_code == 409


def test_skipping_with_the_plan_writes_it_into_the_link_and_without_it_changes_nothing():
    st = finished_state()["state"] + "-m"
    no = client.post(f"/api/tournament/{st}/skip", json={"match_no": 0, "minute": 0, "through": 3, "auto": False}).json()
    assert no["state"] == st
    yes = client.post(f"/api/tournament/{st}/skip", json={"match_no": 0, "minute": 52, "through": 2, "auto": True}).json()
    assert split_live(yes["state"])[1] == "m0ab.1a0"
    ms = yes["tournament"]["your_matches"]
    you = lambda f: 0 if f["home"]["you"] else 1  # noqa: E731
    assert all(x["minute"] >= 55 for x in ms[0]["subs"] if x["side"] == you(ms[0]))
    assert [x["side"] == you(ms[2]) for x in ms[2]["subs"]].count(True) == 0
    rest = client.post(f"/api/tournament/{st}/skip", json={"match_no": 0, "through": 99, "auto": True}).json()
    assert len(decode_live(split_live(rest["state"])[1])) == 17


# -- what a screen is sent of a live match --------------------------------------------

def test_a_match_sent_in_pieces_holds_nothing_past_its_minute():
    from web.app import fixture_upto
    t = play_tournament(DECK, LEAGUE, 7, side({}), engine=Live("7"), fmt="league")
    for f in t.fixtures[:60]:
        r = f.result
        out = fixture_upto(f, 37.6)
        assert out["upto"] == 37 and out["done"] is False and out["stats"] is None and out["pens"] is None
        assert all(g["minute"] <= 37 for g in out["goals"]) and all(x[0] <= 37 for x in out["shots"])
        assert out["hg"] == sum(g.side == 0 and g.minute <= 37 for g in r.goals)
        assert all(e[0] <= 40 for e in out["flow"]) and not out["extra_time"]
        whole = fixture_upto(f, 120)
        assert whole["done"] and whole["stats"] and whole["hg"] == r.home_goals


# -- the daily ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def configured(database):
    from web import auth
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield
    db.close_all()
    mp.undo()


def daily_player():
    from tests.test_daily import drafted, player
    c = player()
    return c, drafted(c)


def test_a_ranked_daily_match_with_your_own_changes_is_let_out_as_it_plays(configured):
    from web import daily
    c, moves = daily_player()
    entries = c.get("/api/daily").json()["board"]["entries"]
    r = c.post("/api/daily/submit", json={"moves": moves, "manual": True})
    assert r.status_code == 200, r.text
    live = r.json()
    f = live["fixture"]
    assert live["live"] and live["revealed"] == 10 and f["upto"] == 10 and f["stats"] is None
    assert all(g["minute"] <= 10 for g in f["goals"]) and "rating" not in str(f["lineups"])
    assert c.get("/api/daily").json()["board"]["entries"] == entries    # nothing ranked yet
    assert c.post("/api/daily/submit", json={"moves": moves}).status_code == 409
    assert c.post("/api/daily/submit", json={"moves": moves, "manual": True}).status_code == 409
    more = c.post("/api/daily/live", json={"action": "more"}).json()
    assert more["revealed"] == 15 and not more["finished"]
    o = c.post("/api/daily/live", json={"action": "options"}).json()["options"]
    assert o["minute"] == 15 and all(x["rating"] is None for x in o["pitch"] + o["bench"])
    b = next(x for x in o["bench"] if x["can_replace"])
    keeper = next(x["id"] for x in o["pitch"] if x["slot"] == "GK")
    assert c.post("/api/daily/live", json={"action": "sub", "on": b["i"], "off": keeper}).status_code == 400
    sub = c.post("/api/daily/live", json={"action": "sub", "on": b["i"], "off": b["can_replace"][0]}).json()
    assert [(x["minute"], x["on"]) for x in sub["fixture"]["subs"] if x["side"] == 0] == [(15, b["name"])]
    # A reload carries on from where it was let out to.
    again = c.get("/api/daily").json()
    assert again["live"]["revealed"] == 15 and again["mine"] is None
    done = c.post("/api/daily/live", json={"action": "finish", "auto": False}).json()
    assert done["finished"] and done["ranked"] and done["fixture"]["stats"] and done["board"]["entries"] == entries + 1
    assert [x["minute"] for x in done["fixture"]["subs"] if x["side"] == 0] == [15]
    assert done["squad"]["xi"][0]["rating"] is not None and done["squad"]["ratings"]["overall"]
    with db.connection() as conn:
        (changes,) = conn.execute("select changes from daily_results where day = %s and account_id = %s",
                                  (daily.today(), c.account_id)).fetchone()
        assert daily.live_of(conn, daily.today(), c.account_id) is None
    assert decode_live(changes)[0].changes[0][0] == 15
    replayed = c.get("/api/daily").json()["mine"]
    assert replayed["fixture"]["subs"] == done["fixture"]["subs"] and replayed["gf"] == done["gf"]
    assert c.post("/api/daily/live", json={"action": "more"}).status_code == 409


def test_a_daily_match_run_to_its_end_is_ranked_and_the_plan_can_finish_it(configured):
    c, moves = daily_player()
    c.post("/api/daily/submit", json={"moves": moves, "manual": True})
    out = None
    for _ in range(40):
        out = c.post("/api/daily/live", json={"action": "more"}).json()
        if out["finished"]:
            break
    assert out["finished"] and out["board"]["mine"]
    assert not [x for x in out["fixture"]["subs"] if x["side"] == 0]       # nobody brought on, nobody came on
    c2, moves2 = daily_player()
    c2.post("/api/daily/submit", json={"moves": moves2, "manual": True})
    auto = c2.post("/api/daily/live", json={"action": "finish", "auto": True}).json()
    assert auto["finished"] and [x["minute"] >= 10 for x in auto["fixture"]["subs"] if x["side"] == 0]
    assert any(x["side"] == 0 for x in auto["fixture"]["subs"])


def test_a_daily_match_left_half_way_is_finished_with_no_more_changes(configured):
    from web import daily
    c, moves = daily_player()
    c.post("/api/daily/submit", json={"moves": moves, "manual": True})
    with db.connection() as conn:
        conn.execute("update daily_live set started_at = %s where account_id = %s",
                     (datetime.now(timezone.utc) - daily.LIVE_TTL - timedelta(seconds=1), c.account_id))
    other = TestClient(app)
    board = other.get("/api/daily").json()["board"]
    assert any(True for _ in board["rows"]) and c.get("/api/daily").json()["mine"]["ranked"]


def test_a_practice_match_with_changes_sends_them_all_and_is_checked(configured):
    _, moves = daily_player()
    anon = TestClient(app)
    base = {"moves": moves, "manual": True}
    p = anon.post("/api/daily/practice", json=base).json()
    assert not [x for x in p["fixture"]["subs"] if x["side"] == 0] and "squad" not in p
    o = anon.post("/api/daily/practice/bench", json={**base, "minute": 30}).json()
    b = next(x for x in o["bench"] if x["can_replace"])
    ch = {"minute": 30, "on": b["i"], "off": b["can_replace"][0]}
    p2 = anon.post("/api/daily/practice", json={**base, "live": [ch]}).json()
    assert [(x["minute"], x["on"]) for x in p2["fixture"]["subs"] if x["side"] == 0] == [(30, b["name"])]
    bad = anon.post("/api/daily/practice", json={**base, "live": [{**ch, "minute": 32}]})
    assert bad.status_code == 400


def test_an_admin_reset_or_clear_ends_a_match_being_played(configured):
    from web import daily
    c, moves = daily_player()
    c.post("/api/daily/submit", json={"moves": moves, "manual": True})
    with db.connection() as conn:
        assert daily.reset(conn, daily.today(), c.account_id)
        assert daily.live_of(conn, daily.today(), c.account_id) is None


# -- a live room -----------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 2_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    from web import rooms
    c = Clock()
    monkeypatch.setattr(rooms, "clock", c)
    return c


def live_room(size=4, manual=(True, False)):
    """A completed live room (a bench, watched together) whose seats make their own
    changes as ``manual`` says, kicked off."""
    from tests.test_friends import player
    people = [player() for _ in manual]
    code = people[0].post("/api/rooms", json={"size": size, "style": "own"}).json()["code"]
    for p in people[1:]:
        p.post(f"/api/rooms/{code}/join")
    for p, m in zip(people, manual):
        if m:
            assert p.post(f"/api/rooms/{code}/manual", json={"manual": True}).status_code == 200
    people[0].post(f"/api/rooms/{code}/start")
    room = people[0].post(f"/api/rooms/{code}/finish").json()
    assert room["status"] == "complete" and room["live"]
    people[0].post(f"/api/rooms/{code}/watch/start")
    return people, code


def watched(code):
    from web import rooms
    from web.app import _watched
    with db.connection() as conn:
        room = rooms.load_room(conn, code)
    t, rs = _watched(room)
    return room, t, rs


def test_only_a_live_room_takes_a_seat_that_makes_its_own_changes(configured, clock):
    from tests.test_friends import player
    host = player()
    code = host.post("/api/rooms", json={"size": 4, "bench": False}).json()["code"]
    assert host.get(f"/api/rooms/{code}").json()["live"] is False
    assert host.post(f"/api/rooms/{code}/manual", json={"manual": True}).status_code == 400
    host.post(f"/api/rooms/{code}/bench", json={"bench": True})
    assert host.post(f"/api/rooms/{code}/manual", json={"manual": True}).status_code == 200
    host.post(f"/api/rooms/{code}/together", json={"together": False})
    assert host.get(f"/api/rooms/{code}").json()["live"] is False


def test_a_live_room_lets_a_round_out_as_its_clock_goes_and_stops_for_half_time(configured, clock):
    (host, guest), code = live_room()
    room, t, rs = watched(code)
    r = rs[0]
    assert r.live and r.whistle == pytest.approx(r.kick + r.minutes * r.minute_s + watch.HALF_S
                                                 + (watch.ET_BREAK_S if r.minutes == 120 else 0))
    clock.t += r.kick + 30 * r.minute_s
    w = guest.get(f"/api/rooms/{code}/watch").json()
    lr = w["live_round"]
    assert lr["round"] == 0 and 30 < lr["upto"] < 30 + watch.LEAD_S / r.minute_s + 1
    assert all(g["minute"] <= int(lr["upto"]) for f in lr["fixtures"] for g in f["goals"])
    assert all(p["kind"] == "pairs" for p in w["parts"])                # no results part at kick-off
    assert r.minute_at(r.kick + 45 * r.minute_s + 1) == 45                # held through half-time
    assert r.minute_at(r.kick + 45 * r.minute_s + watch.HALF_S + 2 * r.minute_s) == pytest.approx(47)
    clock.t = room.watch_started_at + r.whistle
    w = guest.get(f"/api/rooms/{code}/watch").json()
    assert "results" in [p["kind"] for p in w["parts"]] and w["live_round"] is None


def test_retiming_a_live_room_keeps_its_minute_and_its_breaks(configured):
    t = play_room(DECK, LEAGUE, 3, [side({}, S7, owner=1, key="P0")], 4, engine=Live("3"))
    a, b = watch.rounds(t, 0.14, True), watch.rounds(t, 0.3, True)
    for p in [a[0].kick + 10 * 0.14, a[0].kick + 45 * 0.14 + 1.5, a[0].end - 1, a[1].kick + 50 * 0.14 + watch.HALF_S]:
        q = watch.retime(a, b, p)
        i = watch.current(a, p)
        assert b[i].minute_at(q) == pytest.approx(a[i].minute_at(p))
        assert watch.retime(b, a, q) == pytest.approx(p)


def test_a_seat_pauses_everyone_makes_a_change_and_the_clock_goes_on(configured, clock):
    (host, guest), code = live_room()
    room, t, rs = watched(code)
    r = rs[0]
    start = room.watch_started_at
    clock.t = start + r.kick + 20 * r.minute_s
    assert guest.post(f"/api/rooms/{code}/watch/pause").status_code == 400     # the guest's plan makes his changes
    w = host.post(f"/api/rooms/{code}/watch/pause").json()
    o = w["options"]
    at = 5 * -(-(20 + watch.LEAD_S / r.minute_s) // 5)
    assert o["minute"] == at and w["paused"]["by"]
    assert host.post(f"/api/rooms/{code}/watch/pause").status_code == 409
    clock.t += 10                                                            # the room waits
    p_paused = guest.get(f"/api/rooms/{code}/watch").json()["paused"]["p"]
    assert p_paused == pytest.approx(r.kick + 20 * r.minute_s)
    b = next(x for x in o["bench"] if x["can_replace"])
    assert guest.post(f"/api/rooms/{code}/watch/sub", json={"on": b["i"], "off": b["can_replace"][0]}).status_code == 409
    before_t = [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in t.fixtures
                if f.stage == r.stage and f.label == r.label and not (f.home.owner or f.away.owner)]
    ok = host.post(f"/api/rooms/{code}/watch/sub", json={"on": b["i"], "off": b["can_replace"][0]})
    assert ok.status_code == 200, ok.text
    room2, t2, _ = watched(code)
    assert room2.watch_paused_at is None and room2.watch_started_at == pytest.approx(start + 10)
    f2 = next(f for f in t2.fixtures if f.home.owner == room2.seats[0].account_id or f.away.owner == room2.seats[0].account_id)
    s = 0 if f2.home.owner == room2.seats[0].account_id else 1
    assert [(x.minute, x.on.name) for x in f2.result.subs if x.side == s] == [(at, b["name"])]
    after_t = [(f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in t2.fixtures
               if f.stage == r.stage and f.label == r.label and not (f.home.owner or f.away.owner)]
    assert before_t == after_t                                                # nobody else's match moved


def test_a_pause_runs_out_and_only_its_seat_or_the_host_carries_on(configured, clock):
    (host, guest, third), code = live_room(manual=(False, True, False))
    room, t, rs = watched(code)
    r = rs[0]
    clock.t = room.watch_started_at + r.kick + 20 * r.minute_s
    assert guest.post(f"/api/rooms/{code}/watch/pause").status_code == 200
    assert third.post(f"/api/rooms/{code}/watch/resume").status_code == 403
    assert host.post(f"/api/rooms/{code}/watch/resume").status_code == 200
    room2, _, _ = watched(code)
    assert room2.watch_paused_at is None and room2.seats[1].idle_pauses == 1
    assert guest.post(f"/api/rooms/{code}/watch/pause").status_code == 200
    clock.t += watch.PAUSE_S + 3
    w = third.get(f"/api/rooms/{code}/watch").json()
    assert w["paused"] is None
    o = guest.get(f"/api/rooms/{code}/watch").json()
    b = 0
    assert guest.post(f"/api/rooms/{code}/watch/sub", json={"on": b, "off": "Q1"}).status_code == 409   # it ran out
    # The clock held for PAUSE_S and then went on.
    from web import rooms
    with db.connection() as conn:
        rm = rooms.load_room(conn, code)
    assert rooms.watched_for(rm, clock.t) == pytest.approx(r.kick + 20 * r.minute_s + 3, abs=1e-3)
    assert o["paused"] is None


def test_the_host_can_skip_with_the_plans_or_with_no_changes(configured, clock):
    (host, guest), code = live_room(manual=(True, True))
    room, t, rs = watched(code)
    clock.t = room.watch_started_at + rs[0].kick + 20 * rs[0].minute_s
    assert host.post(f"/api/rooms/{code}/watch/skip", json={"to": "fulltime", "round": 0, "auto": False}).status_code == 200
    room2, t2, _ = watched(code)
    assert all(s.live == "m" for s in room2.seats)
    host.post(f"/api/rooms/{code}/watch/skip", json={"to": "end", "round": 1, "auto": True})
    room3, t3, _ = watched(code)
    for s in room3.seats:
        entries = decode_live(s.live)
        assert 0 not in entries and entries[1].auto_from == 0 and len(entries) == 16
        mine_ = [f for f in t3.fixtures if s.account_id in (f.home.owner, f.away.owner)]
        assert any(x.side == (0 if f.home.owner == s.account_id else 1) for f in mine_[1:] for x in f.result.subs)
        f0 = mine_[0]
        assert not [x for x in f0.result.subs if x.side == (0 if f0.home.owner == s.account_id else 1)]


def test_the_pace_of_a_live_room_changes_only_between_matches(configured, clock):
    (host, guest), code = live_room()
    room, t, rs = watched(code)
    clock.t = room.watch_started_at + rs[0].kick + 10 * rs[0].minute_s
    assert host.post(f"/api/rooms/{code}/watch/pace", json={"pace": "slow"}).status_code == 409
    clock.t = room.watch_started_at + rs[0].end - 1
    assert host.post(f"/api/rooms/{code}/watch/pace", json={"pace": "slow"}).status_code == 200


def test_a_live_room_of_one_in_36_is_the_solo_tournament_making_its_own_changes():
    from types import SimpleNamespace
    from web import rooms
    from web.app import _solo_tournament
    st = finished_state(21)["state"] + "-m"
    solo = _solo_tournament(st)
    you = solo.you()
    me = Side("P0", "friend", "FRI", you.formation, you.xi, owner=1, bench=you.bench, plan=you.plan, live={})
    room = play_room(DECK, LEAGUE, 21, [me], 36, engine=rooms.engine(SimpleNamespace(live_watch=True, seed=21)))
    strip = lambda rows: [(st, lb, "Y" if h in ("YOU", "P0") else h, "Y" if a in ("YOU", "P0") else a, hg, ag, g)  # noqa: E731
                          for st, lb, h, a, hg, ag, g in rows]
    assert strip(results(room)) == strip(results(solo))
