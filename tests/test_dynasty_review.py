"""The end of a dynasty (C76): every season read back off the tournaments already played."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from game import dynasty as dy, dynasty_review as dr
from game.deck import load_deck
from game.journey import journey, side_result
from game.tournament import league_of
from tests.test_dynasty import dynasty
from web.app import app

client = TestClient(app)
SEASONS = 4


@pytest.fixture(scope="module")
def played():
    deck = load_deck()
    state = dynasty(11, SEASONS)      # two titles, and draws inside its longest unbeaten run
    seasons = dy.replay(deck, state)
    ts = [dy.season_tournament(deck, league_of(deck), x) for x in seasons]
    return state, seasons, ts, dr.review(deck, seasons, ts)


def mine(ts):
    """Every match of yours, in order, as (season, scored, conceded, outcome)."""
    out = []
    for n, t in enumerate(ts, start=1):
        for m in journey(t, t.you()).matches:
            r = m.fixture.result
            gf, ga = (r.home_goals, r.away_goals) if m.side_index == 0 else (r.away_goals, r.home_goals)
            out.append((n, gf, ga, side_result(m.fixture, m.side_index)))
    return out


def test_each_season_is_its_tournaments_record(played):
    _, seasons, ts, rv = played
    assert [s.number for s in rv.seasons] == list(range(1, SEASONS + 1))
    for s, t in zip(rv.seasons, ts):
        rec = dy.record(t)
        assert (s.reached, s.won, s.drawn, s.lost, s.scored, s.conceded) == \
            (rec.reached, rec.won, rec.drawn, rec.lost, rec.scored, rec.conceded)
        rows = [r.side for r in t.table]
        assert s.position == rows.index(t.you()) + 1
        assert s.points == t.table[s.position - 1].points
        assert s.champion is t.champion


def test_out_by_is_the_side_that_won_the_tie_you_lost(played):
    _, _, ts, rv = played
    for s, t in zip(rv.seasons, ts):
        you = t.you()
        lost = [x for x in t.ties if you in (x.a, x.b) and x.winner is not you]
        if s.reached in ("Champions", "League phase"):
            assert s.out_by is None
        else:
            assert len(lost) == 1 and s.out_by is lost[0].winner


def test_turnover_counts_the_summers_fates(played):
    _, seasons, _, rv = played
    first = {c.id for c in dy.squad(seasons[0])}
    for s, x in zip(rv.seasons, seasons):
        men = dy.squad(x)
        if x.number == 1:
            assert (s.kept, s.released, s.left, s.signed) == (None, 0, 0, len(men))
        else:
            kept = [f for f in x.fates if f.reason in ("carried", "skipped")]
            assert s.kept == len(kept) and s.signed == len(men) - len(kept)
            assert s.released == sum(f.reason == "released" for f in x.fates)
            assert s.left == sum(f.reason in ("left", "end", "no place") for f in x.fates)
        assert s.originals == sum(c.id in first for c in men)


def test_the_records_are_the_extremes_of_every_match(played):
    _, _, ts, rv = played
    every = mine(ts)
    assert len(rv.matches) == len(every)
    wins = [m for m in every if m[1] > m[2]]
    best = max(m[1] - m[2] for m in wins)
    assert rv.biggest_win.scored - rv.biggest_win.conceded == best
    # The first of equals, and the more goals among the widest margins.
    first = next(m for m in wins if m[1] - m[2] == best and m[1] == max(w[1] for w in wins if w[1] - w[2] == best))
    assert (rv.biggest_win.season, rv.biggest_win.scored, rv.biggest_win.conceded) == first[:3]
    worst = max((m[2] - m[1] for m in every if m[2] > m[1]), default=None)
    got = rv.heaviest_defeat.conceded - rv.heaviest_defeat.scored if rv.heaviest_defeat else None
    assert got == worst
    assert rv.most_goals.scored + rv.most_goals.conceded == max(m[1] + m[2] for m in every)


def score(n, gf, ga):
    return SimpleNamespace(n=n, scored=gf, conceded=ga)


def test_the_record_matches_and_their_tie_breaks():
    ms = [score(0, 3, 0), score(1, 4, 1), score(2, 4, 1), score(3, 1, 1), score(4, 2, 4), score(5, 0, 2),
          score(6, 3, 5), score(7, 2, 4), score(8, 5, 3)]
    assert dr.biggest_win(ms).n == 1            # three clear either way; four scored beats three; the first of equals
    assert dr.heaviest_defeat(ms).n == 6        # two down three times; five conceded beats four
    assert dr.most_goals(ms).n == 8             # eight goals twice; the win beats the defeat
    assert dr.biggest_win([score(0, 1, 1)]) is None and dr.heaviest_defeat([score(0, 2, 0)]) is None


def longest(seq, ok):
    best = cur = 0
    for x in seq:
        cur = cur + 1 if ok(x) else 0
        best = max(best, cur)
    return best


def test_runs_are_unbroken_and_a_shoot_out_is_a_draw(played):
    _, _, ts, rv = played
    every = mine(ts)
    assert rv.unbeaten.length == longest(every, lambda m: m[3] != "l")
    assert rv.winning.length == longest(every, lambda m: m[3] == "w")
    assert rv.unbeaten.length > rv.winning.length      # else the data can't tell the two rules apart


def test_a_run_restarts_after_a_break_and_keeps_the_first_of_equals():
    ms = [SimpleNamespace(n=i, ok=v) for i, v in enumerate([1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1])]
    r = dr._longest(ms, lambda m: m.ok)
    assert (r.length, r.first.n, r.last.n) == (3, 6, 8)
    assert dr._longest([SimpleNamespace(ok=0)], lambda m: m.ok) is None


def test_opponents_are_grouped_by_club_across_seasons(played):
    _, _, ts, rv = played
    clubs = {}
    for t in ts:
        you = t.you()
        for f in t.fixtures:
            if you in (f.home, f.away):
                o = f.away if f.home is you else f.home
                clubs[o.club_name] = clubs.get(o.club_name, 0) + 1
    assert rv.met == len(clubs)
    n = rv.nemesis
    assert n.played == clubs[n.club]
    losses = {}
    for m in rv.matches:
        if m.scored < m.conceded:
            losses[m.opponent.club_name] = losses.get(m.opponent.club_name, 0) + 1
    assert n.lost == max(losses.values()) and rv.favourite.won >= 1


def test_the_boards(played):
    _, _, _, rv = played
    pool = [c for c in rv.careers.values() if c.mark is not None]
    most = max(c.apps for c in pool)
    assert rv.min_apps == -(-most // 2)
    assert all(c.apps >= rv.min_apps for c, _ in rv.boards["mark"])
    assert [v for _, v in rv.boards["mark"]] == sorted((v for _, v in rv.boards["mark"]), reverse=True)
    assert rv.boards["apps"][0][1] == most
    assert all(c.card.pos == "GK" for c, _ in rv.boards["clean_sheets"])
    assert rv.boards["goals"][0][1] == max(c.goals for c in pool)


def test_the_clean_sheets_are_the_journeys(played):
    _, _, ts, rv = played
    for pid, c in rv.careers.items():
        assert c.clean_sheets == sum(p.clean_sheets for t in ts for p in journey(t, t.you()).players if p.card.id == pid)


def test_each_man_counts_once_at_the_club_he_first_came_from(played, monkeypatch):
    _, seasons, ts, _ = played
    monkeypatch.setattr(dr, "CLUBS_SHOWN", 10_000)
    rv = dr.review(load_deck(), seasons, ts)
    first = {}
    for x in seasons:
        for c in dy.squad(x):
            first.setdefault(c.id, c.club_name)
    assert rv.players == len(first) and sum(n for _, n in rv.clubs) == len(first)
    want = {}
    for club in first.values():
        want[club] = want.get(club, 0) + 1
    assert {c.club_name: n for c, n in rv.clubs} == want


def line(n, reached, points, gd):
    return SimpleNamespace(number=n, reached=reached, points=points, scored=gd, conceded=0)


def test_the_best_and_worst_seasons():
    ls = [line(1, "Semi-finals", 15, 10), line(2, "Champions", 12, 3), line(3, "Champions", 12, 3),
          line(4, "League phase", 6, -2), line(5, "League phase", 6, -2)]
    assert dr.best_season(ls).number == 2
    assert dr.worst_season(ls).number == 5
    assert dr.best_season(ls[:1] + [line(6, "Semi-finals", 16, 0)]).number == 6


def test_a_review_needs_every_seasons_tournament(played):
    _, seasons, ts, _ = played
    with pytest.raises(ValueError):
        dr.review(load_deck(), seasons, ts[:-1])


def test_careers_from_journeys_are_the_same_as_from_tournaments(played):
    _, _, ts, _ = played
    a = dy.careers_of(ts)
    b = dy.careers_of(ts, [journey(t, t.you()) for t in ts])
    assert {k: (c.apps, c.goals, c.clean_sheets, c.marks) for k, c in a.items()} == \
        {k: (c.apps, c.goals, c.clean_sheets, c.marks) for k, c in b.items()}


# -- the route ---------------------------------------------------------------------------

def test_the_review_route_covers_the_finished_seasons_of_the_state_it_is_given(played):
    state, _, _, rv = played
    assert client.get("/api/dynasty/y3-433/review").status_code == 409
    r = client.get(f"/api/dynasty/{state}/review")
    assert r.status_code == 200 and "s-maxage" in r.headers["cache-control"]
    d = r.json()
    assert [s["number"] for s in d["seasons"]] == list(range(1, SEASONS + 1))
    assert [s["state"] for s in d["seasons"]] == dy.season_states(state)
    assert d["totals"]["w"] == sum(s["w"] for s in d["seasons"]) and d["totals"]["matches"] == len(rv.matches)
    assert d["totals"]["titles"] == sum(s["reached"] == "Champions" for s in d["seasons"]) > 0
    assert d["totals"]["finals"] == sum(s["reached"] in ("Champions", "Runners-up") for s in d["seasons"])
    assert d["legacy"] == client.get(f"/api/dynasty/{state}/legacy").json()
    assert d["length"] == dy.LENGTH and d["seed"] == "11"
    # A window opened and not yet finished is left out.
    opened = client.post(f"/api/dynasty/{state}/window", json={"formation": "433"}).json()["state"]
    assert len(client.get(f"/api/dynasty/{opened}/review").json()["seasons"]) == SEASONS


def test_the_review_reply_holds_no_engine_figure():
    """The squad's lines are a team sheet's averages; the engine's weighted means stay off."""
    d = client.get(f"/api/dynasty/{dynasty(11, 1)}/review").json()
    assert set(d["seasons"][0]["ratings"]) == {"overall", "attack", "midfield", "defence", "goalkeeper", "bench"}


def test_the_legacy_page_is_served():
    r = client.get("/legacy")
    assert r.status_code == 200 and "legacy.js" in r.text
