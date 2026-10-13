"""The daily challenge (C32) and saved results with the profile (C31)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from game import daily as rules
from game.deck import load_deck
from game.tournament import league_of
from web import auth, daily, db, results
from web.app import app


# -- the rules, no database ----------------------------------------------------

@pytest.mark.parametrize("kind, target, gf, ga, ok", [
    ("win", 1, 1, 0, True), ("win", 1, 1, 1, False),
    ("win_by", 2, 3, 1, True), ("win_by", 2, 2, 1, False),
    ("clean_sheet", 0, 2, 0, True), ("clean_sheet", 0, 2, 1, False), ("clean_sheet", 0, 0, 0, False),
    ("score", 3, 3, 4, True), ("score", 3, 2, 0, False),
])
def test_what_counts_as_meeting_the_goal(kind, target, gf, ga, ok):
    assert rules.met(kind, target, gf, ga) is ok


def test_a_challenge_is_measured_into_the_band_and_is_the_same_every_time():
    deck = load_deck()
    league = league_of(deck)
    a = rules.make_challenge(deck, league, "2026-01-01", 424242)
    b = rules.make_challenge(deck, league, "2026-01-01", 424242)
    assert a == b
    lo, hi = rules.SUCCESS_BAND
    assert lo <= a.success_rate <= hi
    you = rules.side_of(rules.best_pick_draft(deck, a.seed, a.formation))
    assert rules.success_rate(league, you, deck.by_key[a.opponent], a.kind, a.target, a.seed) == pytest.approx(a.success_rate, abs=0.001)


def test_the_daily_draft_has_no_rerolls():
    from game.draft import IllegalMove, Reroll
    deck = load_deck()
    ch = rules.Challenge("2026-01-01", 5, "433", deck.club_seasons[0].key, "win", 1, 0.4)
    with pytest.raises(IllegalMove, match="rerolls"):
        rules.draft(deck, ch, [Reroll()])


def test_streaks_hold_until_a_day_is_missed():
    t = date(2026, 5, 10)
    d = lambda n: t - timedelta(days=n)                                  # noqa: E731
    assert results.streaks([], t) == (0, 0)
    assert results.streaks([d(0), d(1), d(2)], t) == (3, 3)
    assert results.streaks([d(1), d(2)], t) == (2, 2)                    # today not played YET: still alive
    assert results.streaks([d(2), d(3)], t) == (0, 2)                    # yesterday missed: broken
    assert results.streaks([d(0), d(2), d(3), d(4), d(5)], t) == (1, 4)


# -- with a database -------------------------------------------------------------

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
    name = f"daily{next(_n)}"
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    c.account_id = r.json()["account"]["id"]
    return c


def drafted(c):
    """An eleven for today's draft: the first player each deal offers (the draft is
    blind, so there is no rating to choose by)."""
    moves = []
    while True:
        s = c.get("/api/daily/draft", params={"moves": ".".join(map(str, moves))}).json()
        if s["complete"]:
            return ".".join(map(str, moves))
        moves.append(next(x["i"] for x in s["deal"]["cards"] if x["takeable"]))


def test_the_seeds_are_secret_and_differ_by_purpose(monkeypatch):
    d = date(2026, 3, 1)
    deal, ranked, practice = (daily.seed_for(d, p) for p in ("deal", "ranked", "practice"))
    assert len({deal, ranked, practice}) == 3
    monkeypatch.setenv("SESSION_SECRET", "another-secret")
    assert daily.seed_for(d, "ranked") != ranked


def test_one_ranked_attempt_a_day_and_it_is_saved():
    c = player()
    moves = drafted(c)
    r = c.post("/api/daily/submit", json={"moves": moves})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ranked"] and out["fixture"]["shots"] and len(out["journey"]["players"]) >= 11   # and substitutes (C42)
    assert out["board"]["mine"]["rank"] >= 1 and out["streak"]["current"] == 1
    assert c.post("/api/daily/submit", json={"moves": moves}).status_code == 409
    again = c.get("/api/daily").json()
    assert again["mine"]["gf"] == out["gf"] and again["mine"]["ga"] == out["ga"]   # replayed, the same
    prof = c.get("/api/profile").json()
    assert prof["daily"]["played"] == 1 and prof["recent"][0]["source"] == "daily"


def test_an_unfinished_or_rerolled_eleven_is_refused():
    c = player()
    assert c.post("/api/daily/submit", json={"moves": "0.0"}).status_code == 400
    assert c.post("/api/daily/submit", json={"moves": "r"}).status_code == 400


def test_signed_out_play_is_practice_on_its_own_seed():
    c, anon = player(), TestClient(app)
    moves = drafted(c)
    assert anon.post("/api/daily/submit", json={"moves": moves}).status_code == 401
    practice = anon.post("/api/daily/practice", json={"moves": moves}).json()
    assert practice["ranked"] is False
    # Both elevens are on the match screen (C38), but with no rating: practice stays blind.
    assert [len(lu["xi"]) for lu in practice["fixture"]["lineups"]] == [11, 11]
    assert "rating" not in str(practice["fixture"]["lineups"])
    ranked = c.post("/api/daily/submit", json={"moves": moves}).json()
    # Different seeds: the two matches are different games (shots and goals' minutes differ).
    assert practice["fixture"]["shots"] != ranked["fixture"]["shots"]


def test_the_board_ranks_goal_met_then_goal_difference():
    rows = TestClient(app).get("/api/daily").json()["board"]["rows"]
    key = [(not r["met"], -(r["gf"] - r["ga"]), -r["gf"]) for r in rows]
    assert key == sorted(key)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_a_future_day_and_a_bad_day_are_refused():
    c = TestClient(app)
    assert c.get("/api/daily", params={"day": (daily.today() + timedelta(days=1)).isoformat()}).status_code == 400
    assert c.get("/api/daily", params={"day": "yesterday"}).status_code == 400


def test_the_day_is_stored_once_and_read_back():
    c = TestClient(app)
    a = c.get("/api/daily").json()["challenge"]
    b = c.get("/api/daily").json()["challenge"]
    assert a == b and a["day"] == daily.today().isoformat()


def test_an_admin_can_reset_a_day(monkeypatch):
    boss, c = player(), player()
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", str(boss.account_id))
    c.post("/api/daily/submit", json={"moves": drafted(c)})
    assert c.delete(f"/api/admin/daily/{c.account_id}").status_code == 404
    assert boss.delete(f"/api/admin/daily/{c.account_id}").json()["reset"] is True
    assert c.post("/api/daily/submit", json={"moves": drafted(c)}).status_code == 200


# -- saving a tournament and the profile -------------------------------------------

def finished_state(c, seed):
    s = c.post("/api/draft", json={"seed": seed}).json()
    while not s["complete"]:
        i = next(x["i"] for x in s["deal"]["cards"] if x["takeable"])
        s = c.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    return s["state"]


def test_saving_a_solo_run_is_replayed_here_and_saving_twice_is_harmless():
    c = player()
    state = finished_state(c, 31)
    assert c.get("/api/results/saved", params={"source": "solo", "key": state}).json() == {"saved": False}
    assert c.post("/api/results", json={"source": "solo", "key": state}).json() == {"saved": True, "new": True}
    assert c.post("/api/results", json={"source": "solo", "key": state}).json() == {"saved": True, "new": False}
    assert c.get("/api/results/saved", params={"source": "solo", "key": state}).json() == {"saved": True}
    t = c.get(f"/api/tournament/{state}").json()
    p = c.get("/api/profile").json()
    assert p["tournaments"] == 1 and p["recent"][0]["reached"] == t["reached"]
    assert p["titles"] == (t["reached"] == "Champions")
    assert p["gf"] == t["journey"]["goals_for"]
    scorers = {r["name"]: r["value"] for r in p["boards"]["goals"]}
    for pl in t["journey"]["players"]:
        if pl["goals"]:
            assert scorers.get(pl["name"]) == pl["goals"]


def test_the_profile_lists_a_first_round_only_once_it_has_a_finish():
    """Both formats' first rounds are finishes (C50), but a profile of league runs alone
    should not show an empty "Group stage" row, nor a league-less one an empty play-off."""
    c = player()
    with db.connection() as conn:
        for key, reached in (("a", "League phase"), ("b", "League phase"), ("c", "Quarter-finals")):
            conn.execute("insert into results (account_id, source, natural_key, formation, reached, champion,"
                         " won, drawn, lost, gf, ga, players) values (%s, 'solo', %s, '4-3-3', %s, false,"
                         " 1, 1, 1, 3, 3, '[]')", (c.account_id, key, reached))
    p = c.get("/api/profile").json()
    assert [(f["stage"], f["n"]) for f in p["finishes"]] == [
        ("Champions", 0), ("Runners-up", 0), ("Semi-finals", 0), ("Quarter-finals", 1), ("Round of 16", 0),
        ("League phase", 2)]
    assert p["best_finish"] == "Quarter-finals"


def test_unsaved_lists_the_finished_solo_links_not_yet_saved():
    c = player()
    done, kept = finished_state(c, 41), finished_state(c, 42)
    c.post("/api/results", json={"source": "solo", "key": kept})
    keys = [done, kept, "41-433", "not-a-state", done]
    u = c.post("/api/results/unsaved", json={"keys": keys}).json()
    assert [x["key"] for x in u["solo"]] == [done]          # unfinished, junk, saved and repeats left out
    assert u["solo"][0]["seed"] == 41 and u["solo"][0]["formation"]
    assert u["rooms"] == []
    assert TestClient(app).post("/api/results/unsaved", json={"keys": keys}).status_code == 401


def test_an_unfinished_draft_or_a_stranger_cannot_save():
    c = player()
    assert c.post("/api/results", json={"source": "solo", "key": "1-433"}).status_code == 409
    assert TestClient(app).post("/api/results", json={"source": "solo", "key": finished_state(c, 4)}).status_code == 401
    assert c.post("/api/results", json={"source": "daily", "key": "2026-01-01"}).status_code == 400


def test_the_profile_needs_an_account():
    assert TestClient(app).get("/api/profile").status_code == 401


def test_the_board_orders_planted_results_whatever_order_they_came_in():
    # Submitted worst-first, so a board in arrival order is visibly wrong.
    day = daily.today() - timedelta(days=3)
    TestClient(app).get("/api/daily", params={"day": day.isoformat()})      # makes the day
    people = [player() for _ in range(4)]
    planted = [(False, 1, 0, 6.0), (True, 1, 0, 6.5), (True, 3, 0, 6.1), (True, 3, 0, 6.9)]
    with db.connection() as conn:
        for p, (met, gf, ga, mark) in zip(people, planted):
            conn.execute("insert into daily_results (day, account_id, moves, met, gf, ga, mark)"
                         " values (%s, %s, '', %s, %s, %s, %s)", (day, p.account_id, met, gf, ga, mark))
    rows = people[0].get("/api/daily", params={"day": day.isoformat()}).json()["board"]["rows"]
    got = [(r["met"], r["gf"], r["mark"]) for r in rows]
    assert got == [(True, 3, 6.9), (True, 3, 6.1), (True, 1, 6.5), (False, 1, 6.0)]
    mine = people[0].get("/api/daily", params={"day": day.isoformat()}).json()["board"]["mine"]
    assert mine["rank"] == 4


# -- drafted blind (C33) -----------------------------------------------------------

def test_the_daily_draft_shows_no_ratings_and_lists_each_line_by_name():
    c = player()
    moves = []
    for _ in range(4):
        s = c.get("/api/daily/draft", params={"moves": ".".join(map(str, moves))}).json()
        cards = s["deal"]["cards"]
        assert all(x["rating"] is None for x in cards + s["picks"])
        for pos in ("GK", "DF", "MF", "FW"):
            names = [x["name"] for x in cards if x["pos"] == pos]
            assert names == sorted(names)
        moves.append(next(x["i"] for x in cards if x["takeable"]))


def test_the_opponent_s_ratings_show_only_after_the_ranked_match():
    c = player()
    before = c.get("/api/daily").json()["challenge"]
    assert before["ratings_hidden"] and all(x["rating"] is None for x in before["opponent"]["xi"])
    out = c.post("/api/daily/submit", json={"moves": drafted(c)}).json()
    assert all(isinstance(x["rating"], int) for x in out["opponent"]["xi"])
    assert all(isinstance(p["rating"], int) for p in out["journey"]["players"])
    after = c.get("/api/daily").json()["challenge"]
    assert not after["ratings_hidden"] and all(isinstance(x["rating"], int) for x in after["opponent"]["xi"])


def test_practice_doesn_t_reveal_ratings_either():
    # Or practising would tell you your eleven's ratings before the ranked attempt.
    c, anon = player(), TestClient(app)
    out = anon.post("/api/daily/practice", json={"moves": drafted(c)}).json()
    assert all(p["rating"] is None for p in out["journey"]["players"])
    assert all(x["rating"] is None for x in out["opponent"]["xi"])


# -- benches (C42) -----------------------------------------------------------------

def test_a_bench_day_is_measured_into_the_band_with_engine_2_and_is_the_same_every_time():
    deck = load_deck()
    league = league_of(deck)
    a = rules.make_challenge(deck, league, "2026-11-01", 31337, bench=True)
    assert a == rules.make_challenge(deck, league, "2026-11-01", 31337, bench=True)
    assert a.bench and a.engine == 2
    lo, hi = rules.SUCCESS_BAND
    assert lo <= a.success_rate <= hi
    s = rules.best_pick_draft(deck, a.seed, a.formation, bench=True)
    assert len(s.picks) == 14
    you = rules.side_of(s)
    assert rules.success_rate(league, you, deck.by_key[a.opponent], a.kind, a.target, a.seed,
                              engine=2) == pytest.approx(a.success_rate, abs=0.001)


def test_a_day_without_a_bench_plays_engine_1_and_takes_no_plan():
    deck = load_deck()
    league = league_of(deck)
    a = rules.make_challenge(deck, league, "2026-01-01", 424242)
    assert not a.bench and a.engine == 1
    assert len(rules.draft(deck, a, []).picks) == 0 and rules.draft(deck, a, []).total == 11
    from game.draft import Change, IllegalMove
    with pytest.raises(IllegalMove, match="no bench"):
        daily.plan_of(a, (Change(0, 60, "any"),))


def test_today_has_a_bench_and_the_ranked_match_plays_and_stores_its_plan():
    c = player()
    ch = c.get("/api/daily").json()["challenge"]
    assert ch["bench"] and ch["squads"] == 14
    moves = drafted(c)
    s = c.get("/api/daily/draft", params={"moves": moves}).json()
    assert len(s["picks"]) == 14 and all(b["rating"] is None and b["can_replace"] for b in s["bench"])
    assert s["plan"] is None, "blind: the automatic plan's order would rank the substitutes"
    slot = s["bench"][1]["can_replace"][0]
    starter, sub = s["xi"][slot]["name"], s["bench"][1]["name"]
    plan = [{"on": 1, "minute": 45, "when": "any", "off": slot}]
    assert c.post("/api/daily/practice", json={"moves": moves, "changes": [{**plan[0], "off": 0}]}).status_code == 400
    out = c.post("/api/daily/submit", json={"moves": moves, "changes": plan}).json()
    mine = [x for x in out["fixture"]["subs"] if x["side"] == 0]
    assert [(x["minute"], x["off"], x["on"]) for x in mine] == [(45, starter, sub)]
    with db.connection() as conn:
        (stored,) = conn.execute("select plan from daily_results where day = %s and account_id = %s",
                                 (daily.today(), c.account_id)).fetchone()
    assert stored == f"p1a45o{slot}"
    again = c.get("/api/daily").json()["mine"]
    assert again["fixture"]["subs"] == out["fixture"]["subs"] and (again["gf"], again["ga"]) == (out["gf"], out["ga"])


def test_the_automatic_plan_is_stored_written_out():
    c = player()
    out = c.post("/api/daily/submit", json={"moves": drafted(c)}).json()
    with db.connection() as conn:
        (stored,) = conn.execute("select plan from daily_results where day = %s and account_id = %s",
                                 (daily.today(), c.account_id)).fetchone()
    import re
    assert re.fullmatch(r"p\da60\.\da70\.\da80", stored)
    assert c.get("/api/daily").json()["mine"]["fixture"]["subs"] == out["fixture"]["subs"]


# -- made ahead of the day's first visitor (C49) -----------------------------------

def test_prepare_makes_today_and_tomorrow_once_and_keeps_tomorrow_hidden(monkeypatch):
    day = date(2031, 3, 14)
    monkeypatch.setattr(daily, "today", lambda: day)
    made = []
    real = rules.make_challenge
    monkeypatch.setattr(rules, "make_challenge", lambda *a, **k: made.append(a[2]) or real(*a, **k))
    c = TestClient(app)
    r = c.post("/api/daily/prepare").json()
    assert r == {"ready": ["2031-03-14", "2031-03-15"]} and made == ["2031-03-14", "2031-03-15"]
    assert c.post("/api/daily/prepare").json() == r and len(made) == 2          # stored: nothing made again
    assert c.get("/api/daily").json()["challenge"]["day"] == "2031-03-14" and len(made) == 2
    assert c.get("/api/daily", params={"day": "2031-03-15"}).status_code == 400  # not yet
    monkeypatch.setattr(daily, "today", lambda: day + timedelta(days=1))         # midnight
    assert c.get("/api/daily").json()["challenge"]["day"] == "2031-03-15" and len(made) == 2


# -- the daily's team sheet and an admin's controls (C55) ----------------------------

def a_swap(s):
    """A move that changes who starts: a substitute onto the pitch, as the server offers it."""
    for b in s["bench"]:
        for to in b["to"]:
            if to.startswith("s"):
                return b, to
    raise AssertionError("no substitute could start anywhere")


def test_a_bench_day_takes_a_team_sheet_and_the_ranked_match_plays_it():
    from game.draft import encode_sheet
    c = player()
    moves = drafted(c)
    s = c.get("/api/daily/draft", params={"moves": moves}).json()
    assert s["sheet"] is None and all("to" in x and "p" in x for x in [*s["xi"], *s["bench"]])
    sub, to = a_swap(s)
    out = c.post("/api/daily/sheet", json={"moves": moves, "man": sub["p"], "to": to}).json()
    sheet = out["sheet"]
    off = s["xi"][int(to[1:])]["name"]                               # he replaces that slot's starter
    assert sheet and sub["name"] in [x["name"] for x in out["xi"]] and off in [x["name"] for x in out["bench"]]
    assert all(x["rating"] is None for x in [*out["xi"], *out["bench"], *out["picks"]]), "the daily stays blind"
    # The sheet the page keeps reads back the same draft, and back to the drafted order is None.
    again = c.get("/api/daily/draft", params={"moves": moves, "sheet": encode_sheet(tuple(sheet))}).json()
    assert [x["name"] for x in again["xi"]] == [x["name"] for x in out["xi"]] and again["sheet"] == sheet
    assert c.post("/api/daily/sheet", json={"moves": moves, "current": sheet}).json()["sheet"] is None
    played = c.post("/api/daily/submit", json={"moves": moves, "sheet": sheet}).json()
    assert sub["name"] in [x["name"] for x in played["fixture"]["lineups"][0]["xi"]], "he starts"
    with db.connection() as conn:
        (stored,) = conn.execute("select sheet from daily_results where day = %s and account_id = %s",
                                 (daily.today(), c.account_id)).fetchone()
    assert stored == encode_sheet(tuple(sheet))
    mine = c.get("/api/daily").json()["mine"]
    assert mine["fixture"]["lineups"] == played["fixture"]["lineups"] and (mine["gf"], mine["ga"]) == (played["gf"], played["ga"])


def test_a_sheet_that_doesn_t_fit_is_refused_everywhere():
    c = player()
    moves = drafted(c)
    s = c.get("/api/daily/draft", params={"moves": moves}).json()
    keeper = next(x["p"] for x in s["xi"] if x["slot"] == "GK")
    others = [x for x in range(14) if x != keeper]
    bad = [*others[:11], keeper, *others[11:]]                       # the keeper on the bench
    for r in (c.post("/api/daily/practice", json={"moves": moves, "sheet": bad}),
              c.post("/api/daily/submit", json={"moves": moves, "sheet": bad}),
              c.post("/api/daily/sheet", json={"moves": moves, "current": bad, "man": 0, "to": "b0"}),
              c.post("/api/daily/submit", json={"moves": moves, "sheet": list(range(13))})):
        assert r.status_code == 400, r.text
    unfinished = moves.rsplit(".", 1)[0]
    assert c.post("/api/daily/sheet", json={"moves": unfinished, "man": 0, "to": "s1"}).status_code == 400
    assert c.post("/api/daily/submit", json={"moves": moves}).status_code == 200      # the attempt wasn't used


def test_a_sheet_on_a_day_without_a_bench_is_refused():
    deck = load_deck()
    ch = rules.make_challenge(deck, league_of(deck), "2026-01-01", 424242)
    from game.draft import IllegalMove
    with pytest.raises(IllegalMove, match="no bench"):
        daily.sheet_of(ch, list(range(14)))


def test_without_a_sheet_the_daily_side_is_placed_as_before():
    """side_of reads the session's placed eleven now; with no sheet that is exactly where
    Side placed the first eleven picks, so no day already played changes."""
    from game.tournament import Side
    deck = load_deck()
    for seed in (5, 77, 1234):
        for formation in ("433", "352", "4231"):
            s = rules.best_pick_draft(deck, seed, formation, True)
            old = Side("YOU", "Your XI", "YOU", s.formation, s.picks[:11], you=True)
            assert [(c.id, c.slot) for c in rules.side_of(s).xi] == [(c.id, c.slot) for c in old.xi]


def test_edition_0_keeps_the_seeds_every_day_had():
    import hashlib, hmac
    d = date(2026, 3, 1)
    for purpose in ("deal", "ranked", "practice"):
        mac = hmac.new(b"test-secret", f"daily:{d.isoformat()}:{purpose}".encode(), hashlib.sha256)
        assert daily.seed_for(d, purpose, 0) == int.from_bytes(mac.digest()[:8], "big") % (2**31 - 2) + 1
        assert daily.seed_for(d, purpose, 1) != daily.seed_for(d, purpose, 0)


def admin_and(monkeypatch):
    boss = player()
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", str(boss.account_id))
    return boss


def test_an_admin_sees_a_day_and_nobody_else_does(monkeypatch):
    boss, c = admin_and(monkeypatch), player()
    c.post("/api/daily/submit", json={"moves": drafted(c)})
    assert c.get("/api/admin/daily").status_code == 404
    d = boss.get("/api/admin/daily").json()
    assert d["day"] == d["now"] == daily.today().isoformat() and d["today"]
    assert d["challenge"]["goal"] and c.account_id in [r["id"] for r in d["rows"]]
    assert d["days"][0]["day"] == d["day"]
    tomorrow = (daily.today() + timedelta(days=1)).isoformat()
    assert boss.get("/api/admin/daily", params={"day": tomorrow}).status_code == 400   # never tomorrow
    past = boss.get("/api/admin/daily", params={"day": "2020-02-02"}).json()
    assert past["challenge"] is None and past["rows"] == []
    with db.connection() as conn:                                                    # and not made by looking
        assert conn.execute("select 1 from daily_challenges where day = '2020-02-02'").fetchone() is None


def test_an_admin_can_clear_a_day_for_everyone(monkeypatch):
    boss, a, b = admin_and(monkeypatch), player(), player()
    for c in (a, b):
        assert c.post("/api/daily/submit", json={"moves": drafted(c)}).status_code == 200
    assert a.post("/api/admin/daily/clear").status_code == 404
    out = boss.post("/api/admin/daily/clear").json()
    assert out["cleared"] >= 2 and out["rows"] == []
    with db.connection() as conn:
        assert conn.execute("select count(*) from results where source = 'daily' and natural_key = %s",
                            (daily.today().isoformat(),)).fetchone()[0] == 0
    for c in (a, b):
        assert c.post("/api/daily/submit", json={"moves": drafted(c)}).status_code == 200


def test_an_admin_can_make_today_again(monkeypatch):
    boss, c = admin_and(monkeypatch), player()
    before = c.get("/api/daily").json()["challenge"]
    old = drafted(c)
    assert c.post("/api/daily/submit", json={"moves": old, "edition": before["edition"]}).status_code == 200
    assert c.post("/api/admin/daily/remake").status_code == 404
    out = boss.post("/api/admin/daily/remake").json()
    assert out["cleared"] >= 1 and out["rows"] == [] and out["challenge"]["edition"] == before["edition"] + 1
    after = c.get("/api/daily").json()
    assert after["challenge"]["edition"] == before["edition"] + 1 and after["mine"] is None
    with db.connection() as conn:
        (seed,) = conn.execute("select seed from daily_challenges where day = %s", (daily.today(),)).fetchone()
    assert seed == daily.seed_for(daily.today(), "deal", before["edition"] + 1)
    # A draft made against the old edition is refused, never replayed into the new squads.
    stale = {"moves": old, "edition": before["edition"]}
    assert c.post("/api/daily/practice", json=stale).status_code == 409
    assert c.post("/api/daily/submit", json=stale).status_code == 409
    assert c.get("/api/daily/draft", params=stale).status_code == 409
    assert c.post("/api/daily/sheet", json={**stale, "man": 0, "to": "s1"}).status_code == 409
    new = drafted(c)
    assert c.post("/api/daily/submit", json={"moves": new, "edition": after["challenge"]["edition"]}).status_code == 200


def test_only_today_can_be_made_again(monkeypatch):
    deck = load_deck()
    with db.connection() as conn, pytest.raises(daily.DailyError, match="only today"):
        daily.remake(conn, deck, league_of(deck), daily.today() - timedelta(days=1))


def test_an_admin_can_let_one_account_play_a_past_day_s_attempt_go(monkeypatch):
    boss, c = admin_and(monkeypatch), player()
    yesterday = daily.today() - timedelta(days=1)
    with db.connection() as conn:
        daily.get_challenge(conn, load_deck(), league_of(load_deck()), yesterday)
        conn.execute("insert into daily_results (day, account_id, moves, met, gf, ga) values (%s, %s, '', true, 1, 0)",
                     (yesterday, c.account_id))
    assert boss.delete(f"/api/admin/daily/{c.account_id}", params={"day": yesterday.isoformat()}).json()["reset"] is True
    with db.connection() as conn:
        assert daily.result_of(conn, yesterday, c.account_id) is None
