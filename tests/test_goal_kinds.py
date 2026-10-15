"""Goal kinds and commentary (C61): measured where they can be, declared where they can't,
never a hint of a rating, and never a word about what comes after the goal."""

import random
from dataclasses import replace

from fastapi.testclient import TestClient

from etl.goal_kinds import parse
from game import commentary, goal_kinds, tournament as T
from game.deck import Card, load_deck
from game.match import Goal
from web.app import app

client = TestClient(app)


def card(pos, n=0, rating=80, side=0):
    return Card(id=f"Q{side}{pos}{n}", name=f"{pos} {n}", title=f"{pos} {n}", pos=pos, positions=(),
                source="declared", nation=None, rating=rating, season=2004, label="2004–05",
                club="T", club_name="T", short="T", key="k", crest="T")


def model(**over):
    """A made-up model in the shape etl.goal_kinds writes, so a rule can be asked directly."""
    m = {"made_by": {line: {"pass": 0.5, "cross": 0.3, "corner": 0.2} for line in ("GK", "DF", "MF", "FW")},
         "headed": {made: {"DF": 0.5, "MF": 0.2, "FW": 0.2, "all": 0.3} for made in ("pass", "cross", "corner")},
         "unassisted": {line: {"foot": 0.4, "penalty": 0.4, "free_kick": 0.1, "header": 0.1}
                        for line in ("DF", "MF", "FW")},
         "foot": {}, "right": 0.6}
    m.update(over)
    return m


def real_goals(seeds=range(6)):
    """(match name, goals, starters) for every match of a few real tournaments."""
    deck = load_deck()
    league = T.league_of(deck)
    out = []
    for seed in seeds:
        t = T.play_tournament(deck, league, seed, T.club_side(deck.club_seasons[seed * 13]), engine=2)
        for f in t.fixtures:
            if f.result.goals:
                out.append((goal_kinds.match_name(f.stage, f.label, f.home.xi, f.away.xi), f.result.goals,
                            ({c.id for c in f.home.xi}, {c.id for c in f.away.xi}), f))
    return out


# -- reading Transfermarkt ------------------------------------------------------------

def test_the_etl_reads_a_goals_kind_and_how_it_was_made():
    assert parse(", Header, 1. Tournament Goal Assist: , Corner, 1. Tournament Assist") == ("header", "corner", True)
    assert parse(", Left-footed shot, 2. Tournament Goal Assist: , Shot on goal, 1. Tournament Assist") == \
        ("left", "rebound", True)
    assert parse(", Right-footed shot, 1. Tournament Goal") == ("right", None, False)
    assert parse(", Right-footed shot, 1. Tournament Goal Assist: Without assist") == ("right", None, False)


def test_a_penaltys_assist_is_who_won_it_so_it_is_unassisted():
    assert parse(", Penalty, 1. Tournament Goal Assist: , Penalty: Fouled player") == ("penalty", None, False)
    assert parse(", Penalty, 2. Tournament Goal Assist: Handball by") == ("penalty", None, False)
    assert parse(", Penalty, 1. Tournament Goal Assist: , Fouled player") == ("penalty", None, False)


def test_own_goals_and_transfermarkts_finer_tags_are_not_kinds_of_their_own():
    assert parse(", Own-goal Assist: , Cross, 1. Tournament Assist")[0] is None
    assert parse(", Own-goal")[0] is None
    # A tagged foot shot is a foot shot, its foot unknown: the tags could not be measured.
    assert parse(", Counter attack goal, 1. Tournament Goal Assist: , Pass, 1. Tournament Assist")[0] == "foot"
    assert parse(", Long distance kick, 1. Tournament Goal")[0] == "foot"


def test_the_deck_carries_the_measured_model_with_feet_for_its_own_people_only():
    deck = load_deck()
    m = deck.goal_kinds
    people = {c.id for s in deck.club_seasons for c in s.cards}
    assert m["foot"] and set(m["foot"]) <= people
    assert set(m["made_by"]) == {"GK", "DF", "MF", "FW"}
    for line in ("DF", "MF", "FW"):
        assert abs(sum(m["unassisted"][line].values()) - 1) < 1e-3
        assert abs(sum(m["made_by"][line].values()) - 1) < 1e-3


# -- the kinds ---------------------------------------------------------------------------

def test_an_assisted_goal_is_never_a_penalty_or_a_direct_free_kick():
    m = model(unassisted={line: {"penalty": 1.0} for line in ("DF", "MF", "FW")})
    for i in range(300):
        g = Goal(10, 0, card("FW"), card("MF"))
        k = goal_kinds.kind_of(m, random.Random(i), g)
        assert k.finish in ("foot", "header") and k.made is not None


def test_an_unassisted_goal_takes_its_kind_from_the_scorers_line():
    m = model(unassisted={"DF": {"header": 1.0}, "MF": {"free_kick": 1.0}, "FW": {"penalty": 1.0}})
    assert goal_kinds.kind_of(m, random.Random(1), Goal(10, 0, card("DF"), None)).finish == "header"
    assert goal_kinds.kind_of(m, random.Random(1), Goal(10, 0, card("MF"), None)).finish == "free_kick"
    assert goal_kinds.kind_of(m, random.Random(1), Goal(10, 0, card("FW"), None)).finish == "penalty"


def test_how_it_was_made_follows_the_assister_and_the_header_the_scorer():
    m = model(made_by={"GK": {"pass": 1.0}, "DF": {"cross": 1.0}, "MF": {"corner": 1.0}, "FW": {"pass": 1.0}},
              headed={"cross": {"DF": 1.0, "MF": 0.0, "FW": 0.0}, "corner": {"DF": 0.0, "MF": 0.0, "FW": 1.0},
                      "pass": {"DF": 0.0, "MF": 0.0, "FW": 0.0}})
    for i in range(50):
        rng = lambda: random.Random(i)
        assert goal_kinds.kind_of(m, rng(), Goal(10, 0, card("DF"), card("DF", 1))) == goal_kinds.Kind("header", "cross")
        assert goal_kinds.kind_of(m, rng(), Goal(10, 0, card("FW"), card("DF", 1))).finish == "foot"
        assert goal_kinds.kind_of(m, rng(), Goal(10, 0, card("FW"), card("MF"))) == goal_kinds.Kind("header", "corner")
        assert goal_kinds.kind_of(m, rng(), Goal(10, 0, card("DF"), card("MF"))).made == "corner"


def test_the_foot_follows_the_scorers_own_record_and_the_real_share_without_one():
    lefty, righty, unknown = card("FW", 1), card("FW", 2), card("FW", 3)
    m = model(unassisted={line: {"foot": 1.0} for line in ("DF", "MF", "FW")},
              foot={lefty.id: 0.0, righty.id: 1.0}, right=0.6)
    feet = {c.id: [goal_kinds.kind_of(m, random.Random(i), Goal(10, 0, c, None)).foot for i in range(400)]
            for c in (lefty, righty, unknown)}
    assert set(feet[lefty.id]) == {"left"} and set(feet[righty.id]) == {"right"}
    assert 0.5 < feet[unknown.id].count("right") / 400 < 0.7


def test_only_a_foot_shot_has_a_flavour_and_every_flavour_is_declared():
    for name, goals, starters, f in real_goals(range(3)):
        for k in goal_kinds.kinds(load_deck().goal_kinds, name, goals):
            if k.finish != "foot":
                assert k.flavour is None and k.foot is None
            else:
                assert k.foot in ("left", "right")
                assert k.flavour is None or k.flavour in goal_kinds.DECLARED
    assert goal_kinds.DECLARED == {"long_range", "tap_in", "volley", "solo_run"}


def test_a_kind_never_reads_a_rating():
    """A blind draft (C23, C33) must learn nothing from how its goals went in."""
    m = load_deck().goal_kinds
    for name, goals, starters, f in real_goals(range(2)):
        other = [Goal(g.minute, g.side, replace(g.scorer, rating=50),
                      replace(g.assist, rating=99) if g.assist else None) for g in goals]
        assert goal_kinds.kinds(m, name, goals) == goal_kinds.kinds(m, name, other)
        assert commentary.lines(name, goals, goal_kinds.kinds(m, name, goals), starters) == \
            commentary.lines(name, other, goal_kinds.kinds(m, name, other), starters)


def test_a_goal_keeps_its_kind_and_its_line_whatever_comes_after_it():
    """A live match (C60) is let out a piece at a time and a change may rewrite the rest:
    what was said about a goal must not move when later goals do."""
    m = load_deck().goal_kinds
    seen = 0
    for name, goals, starters, f in real_goals():
        whole_k = goal_kinds.kinds(m, name, goals)
        whole = commentary.lines(name, goals, whole_k, starters)
        for n in range(1, len(goals)):
            part = goals[:n] + [Goal(goals[n].minute, 1 - goals[n].side, goals[n].scorer, None)]
            part_k = goal_kinds.kinds(m, name, part)
            assert part_k[:n] == whole_k[:n]
            assert commentary.lines(name, part, part_k, starters)[:n] == whole[:n]
            seen += 1
    assert seen > 50


def test_kinds_come_out_near_the_real_shares():
    """The engine's goals given kinds look like the real ones. Penalties run high, because the
    engine assists fewer goals than the real 76% (recorded, not tuned)."""
    m = load_deck().goal_kinds
    ks = [k for name, goals, s, f in real_goals(range(10)) for k in goal_kinds.kinds(m, name, goals)]
    share = lambda finish: sum(k.finish == finish for k in ks) / len(ks)
    assert 0.11 < share("header") < 0.18
    assert 0.07 < share("penalty") < 0.14
    assert 0.01 < share("free_kick") < 0.04


# -- the commentary --------------------------------------------------------------------

def goal(minute, side, scorer, assist=None):
    return Goal(minute, side, scorer, assist)


def tags_of(goals, starters=None):
    starters = starters or ({g.scorer.id for g in goals if g.side == 0}, {g.scorer.id for g in goals if g.side == 1})
    score, trailed, scored, out = [0, 0], [False, False], {}, []
    for g in goals:
        key = (g.side, g.scorer.id)
        scored[key] = scored.get(key, 0) + 1
        out.append(commentary.moment(g, (score[0], score[1]), trailed[g.side], scored[key],
                                     g.scorer.id not in starters[g.side]))
        score[g.side] += 1
        for s in (0, 1):
            trailed[s] = trailed[s] or score[s] < score[1 - s]
    return out


def test_the_moment_is_what_the_goal_was_when_it_went_in():
    a, b, c, d = card("FW", 1), card("FW", 2), card("MF", 3), card("FW", 4, side=1)
    assert tags_of([goal(3, 0, a)]) == ["early"]
    assert tags_of([goal(30, 0, a)]) == ["opener"]
    assert tags_of([goal(30, 0, a), goal(40, 1, d)]) == ["opener", "level"]
    assert tags_of([goal(30, 0, a), goal(40, 1, d), goal(60, 0, b)]) == ["opener", "level", "ahead"]
    assert tags_of([goal(30, 1, d), goal(40, 0, a), goal(60, 0, b)]) == ["opener", "level", "comeback"]
    assert tags_of([goal(30, 1, d), goal(88, 0, a)]) == ["opener", "late_level"]
    assert tags_of([goal(30, 0, a), goal(40, 1, d), goal(86, 0, b)])[-1] == "late_ahead"
    assert tags_of([goal(30, 0, a), goal(40, 1, d), goal(84, 0, b)])[-1] == "ahead"
    assert tags_of([goal(30, 0, a), goal(40, 1, d), goal(100, 0, b)])[-1] == "et_ahead"
    assert tags_of([goal(30, 0, a), goal(40, 1, d), goal(116, 0, b)])[-1] == "late_ahead"
    assert tags_of([goal(30, 0, a), goal(50, 0, a)]) == ["opener", "brace"]
    assert tags_of([goal(30, 0, a), goal(50, 0, a), goal(60, 0, a)])[-1] == "hat_trick"
    assert tags_of([goal(30, 0, a), goal(50, 0, a), goal(60, 0, a), goal(70, 0, a)])[-1] == "haul"
    assert tags_of([goal(30, 0, a), goal(50, 0, b)]) == ["opener", "clear"]
    assert tags_of([goal(30, 0, a), goal(50, 0, b), goal(60, 0, c)])[-1] == "rout"
    assert tags_of([goal(30, 1, d), goal(50, 1, d), goal(60, 0, a)])[-1] == "one_back"
    assert tags_of([goal(30, 0, a), goal(50, 0, c)], ({a.id}, set()))[-1] == "bench"


def test_the_commentary_never_claims_a_goal_was_the_last():
    words = " ".join(p for table in (commentary.MADE, commentary.FINISH, commentary.ALONE, commentary.TAG)
                     for row in table.values() for p in row).lower()
    for claim in ("winner", "winning", "decider", "decisive", "settles it", "game over", "sealed", "clinch"):
        assert claim not in words


def test_every_line_the_commentary_can_make_is_short():
    """Every pairing of how a goal was made and finished, with the longest tag, fits."""
    tag = max((p for row in commentary.TAG.values() for p in row), key=len)
    bodies = [p for row in commentary.ALONE.values() for p in row]
    bodies += [f"{m}, {f}" for row in commentary.MADE.values() for m in row
               for frow in commentary.FINISH.values() for f in frow]
    for body in bodies:
        text = (body + ". " + tag).format(foot="right", N="Seven")
        assert len(text) <= 100, text
    assert all("{" not in p.format(foot="left", N="Four") for p in bodies + [tag])


def test_a_match_never_repeats_a_phrase_while_another_is_left():
    used, rng = {}, random.Random(4)
    options = ["one", "two", "three"]
    picked = [commentary._pick(rng, used, "k", options) for _ in range(3)]
    assert sorted(picked) == sorted(options)
    assert commentary._pick(rng, used, "k", options) in options      # all used: any will do
    assert commentary._pick(rng, used, "other", ["x"]) == "x"          # each list keeps its own count
    # And in real matches: no two goals of one match are told the same way while a list has more.
    seen = 0
    for name, goals, starters, f in real_goals():
        if len(goals) == 2:
            said = commentary.lines(name, goals, goal_kinds.kinds(load_deck().goal_kinds, name, goals), starters)
            assert said[0] != said[1]
            seen += 1
    assert seen > 20


def test_a_line_names_nobody():
    """The burst, the feed and a result row name the scorer and the assister beside the line."""
    for name, goals, starters, f in real_goals(range(2)):
        said = commentary.lines(name, goals, goal_kinds.kinds(load_deck().goal_kinds, name, goals), starters)
        for g, s in zip(goals, said):
            assert g.scorer.name not in s
            assert g.assist is None or g.assist.name not in s


# -- the API -----------------------------------------------------------------------------

def test_your_matches_carry_each_goals_kind_and_line():
    s = client.post("/api/draft", json={"seed": 5}).json()
    while not s["complete"]:
        i = next(c["i"] for c in s["deal"]["cards"] if c["takeable"])
        s = client.post(f"/api/draft/{s['state']}/pick", json={"index": i}).json()
    t = client.get(f"/api/tournament/{s['state']}").json()
    goals = [g for f in t["your_matches"] for g in f["goals"]]
    assert goals
    for g in goals:
        assert g["kind"] in {"foot", "header", "penalty", "free_kick"} | goal_kinds.DECLARED
        assert g["line"]
        assert (g["foot"] is not None) == (g["kind"] not in ("header", "penalty", "free_kick"))
        assert g["kind"] not in ("penalty", "free_kick") or g["assist"] is None
    # Everything else stays as small as it was.
    assert all("line" not in g for r in t["knockout"] for tie in r["ties"] for leg in tie["legs"]
               for g in leg["goals"])


def test_the_page_shows_the_kind_and_the_line():
    js = open("web/static/matchplay.js", encoding="utf-8").read()
    assert "saidLine(g)" in js and "gb-kind" in js
    assert "saidLine(g)" in open("web/static/cup.js", encoding="utf-8").read()
