"""Dynasty mode (C64): men ageing into their next real season, transfer windows, the state."""

import pytest

from game import dynasty as dy
from game.deck import build_deck, load_deck
from game.draft import (
    BENCH,
    IllegalMove,
    Pick,
    Reroll,
    Session,
    decode_solo,
    decode_state,
    replay,
    why_not,
)
from game.formations import FORMATIONS
from game.positions import LINE
from game.tournament import Side, auto_plan, league_of, play_tournament

SLOTS = FORMATIONS["433"].slots


# -- a made-up deck: the rules that rarely act on the real one are asked of it (C7) ---------

def player(i, positions, rating=80):
    return {"id": f"Q{i}", "name": f"P{i}", "title": f"P{i}", "pos": LINE[positions[0]],
            "positions": list(positions), "source": "declared", "nation": None, "rating": rating}


def club(key, season, players, name=None):
    return {"key": f"{season}-{key}", "season": season, "label": f"{season}–{(season + 1) % 100:02d}",
            "club": name or key, "name": name or key, "short": key, "primary": "#000", "secondary": "#fff",
            "crest": key, "team": "#000", "deep": "#000", "ink": "#fff",
            "best": {"formation": "433", "xi": [[players[0]["id"], players[0]["positions"][0]]]},
            "players": players}


def fillers(season, base):
    """Two of every 4-3-3 position, people of their own, so a window can always be filled."""
    return club("F", season, [player(base + k, (slot,), 70) for k, slot in enumerate(SLOTS * 2)])


def made_up_deck():
    """Club A in 2000 holds a 4-3-3 and a bench (Q0-Q10 the eleven in slot order, Q11-Q13
    the bench). In 2001: most carry on a point better; Q1 skips to 2003; Q2 next turns up in
    2004, past JUMP; Q3 is measured only at LM, which a 4-3-3 hasn't got; Q12, a striker,
    is a centre-back in 2003, where a window's open places are; Q5 is in two
    squads, A's and Z's. Q14 is in 2009 alone, inside JUMP of the deck's last season, 2010."""
    a2000 = [player(i, (slot,)) for i, slot in enumerate(SLOTS)]
    a2000 += [player(11, ("CM",)), player(12, ("ST",)), player(13, ("RB",))]
    carried = [i for i in range(14) if i not in (1, 2, 3)]
    a2001 = [player(i, (SLOTS[i] if i < 11 else ("CM", "ST", "RB")[i - 11],), 81) for i in carried]
    a2001.append(player(3, ("LM",), 81))
    return build_deck({"club_seasons": [
        club("A", 2000, a2000), club("A", 2001, a2001),
        club("Z", 2001, [player(5, (SLOTS[5],), 60)]),
        club("A", 2003, [player(1, (SLOTS[1],), 79), player(12, ("CB",), 75)]),
        club("A", 2004, [player(2, (SLOTS[2],), 79)]),
        club("A", 2009, [player(14, ("ST",))]),
        fillers(2000, 100), fillers(2001, 200), fillers(2010, 300),
    ]})


def season_2000(deck):
    a = deck.by_key["2000-A"]
    return Session(seed=1, formation=FORMATIONS["433"], picks=list(a.cards), bench_size=BENCH)


def card(deck, key, i):
    return next(c for c in deck.by_key[key].cards if c.id == f"Q{i}")


def test_a_man_moves_on_to_his_next_season_in_the_deck_within_jump():
    deck = made_up_deck()
    a = deck.by_key["2000-A"]
    n = dy.advance(deck, a.cards[0])
    assert n is card(deck, "2001-A", 0) and n.rating == 81              # the deck's own next card
    assert dy.advance(deck, a.cards[1]) is card(deck, "2003-A", 1)      # two seasons skipped
    assert dy.advance(deck, a.cards[2]) is None                         # 2004 is past JUMP


def test_a_man_in_two_squads_in_one_season_stays_with_his_club():
    deck = made_up_deck()
    assert dy.advance(deck, deck.by_key["2000-A"].cards[5]).club == "A"


def test_each_fate_says_why():
    deck = made_up_deck()
    a = deck.by_key["2000-A"]
    assert [dy.fate(deck, a.cards[i]).reason for i in (0, 1, 2)] == ["carried", "skipped", "left"]
    assert dy.fate(deck, card(deck, "2009-A", 14)).reason == "end"      # 2009 + JUMP passes 2010


def test_a_window_carries_the_kept_men_in_their_new_seasons():
    deck = made_up_deck()
    s, fates, waiting = dy._window(deck, season_2000(deck), dy.Window("433", (), ()), 2, 7)
    held = [*s.picks, *waiting]
    assert all(c.season in (2001, 2003) for c in held)
    assert {c.id for c in held} == {f"Q{i}" for i in range(14) if i not in (2, 3)}
    assert [f.reason for f in fates[:4]] == ["carried", "skipped", "left", "no place"]


def test_a_man_with_no_place_in_the_shape_leaves_without_counting_as_a_release():
    deck = made_up_deck()
    _, fates, _ = dy._window(deck, season_2000(deck), dy.Window("433", (0, 4, 6), ()), 2, 7)
    assert fates[3].reason == "no place"
    assert sum(f.reason == "released" for f in fates) == 3


def test_another_shape_keeps_him():
    deck = made_up_deck()
    s, fates, waiting = dy._window(deck, season_2000(deck), dy.Window("442", (), ()), 2, 7)
    assert "Q3" in {c.id for c in [*s.picks, *waiting]}
    assert fates[3].reason == "carried"


def test_the_best_rated_kept_men_start():
    deck = made_up_deck()
    a = [player(0, ("GK",)), player(1, ("ST",), 70), player(2, ("ST",), 90), player(3, ("GK",), 95)]
    deck = build_deck({"club_seasons": [club("A", 2000, a)]})
    eleven, bench, unplaced = dy.split_kept(FORMATIONS["433"], list(deck.club_seasons[0].cards))
    assert [c.id for c in eleven] == ["Q2", "Q3"]       # the better keeper and striker
    assert [c.id for c in bench] == ["Q1"]
    assert [c.id for c in unplaced] == ["Q0"]           # keepers stay on: never on the bench


def test_the_bench_holds_three_and_keeps_the_best():
    a = [player(i, ("ST",), 70 + i) for i in range(6)]
    deck = build_deck({"club_seasons": [club("A", 2000, a)]})
    eleven, bench, unplaced = dy.split_kept(FORMATIONS["433"], list(deck.club_seasons[0].cards))
    assert [c.id for c in eleven] == ["Q5"]
    assert [c.id for c in bench] == ["Q2", "Q3", "Q4"]
    assert [c.id for c in unplaced] == ["Q0", "Q1"]


def test_a_released_man_leaves_and_the_window_is_filled_from_deals():
    deck = made_up_deck()
    s, fates, waiting = dy._window(deck, season_2000(deck), dy.Window("433", (0,), ()), 2, 7)
    assert fates[0].reason == "released" and fates[0].next is not None
    assert "Q0" not in {c.id for c in [*s.picks, *waiting]}
    assert s.deal is not None and not s.complete


@pytest.mark.parametrize("releases, match", [
    ((0, 4, 6, 7), "at most"), ((0, 0), "twice"), ((14,), "hasn't got"), ((2,), "already left")])
def test_bad_releases_are_refused(releases, match):
    deck = made_up_deck()
    with pytest.raises(IllegalMove, match=match):
        dy._window(deck, season_2000(deck), dy.Window("433", releases, ()), 2, 7)


def test_a_kept_substitute_waiting_for_the_bench_is_never_taken_again():
    deck = made_up_deck()
    s, _, waiting = dy._window(deck, season_2000(deck), dy.Window("433", (), ()), 2, 7)
    assert waiting, "the kept bench joins once the eleven is full"
    assert "Q12" in {c.id for c in waiting}
    other = card(deck, "2003-A", 12)                         # a CB, and two CB places are open
    assert dy.why_not_window(s, waiting, other) == "already on your bench"
    assert why_not(other, s.formation, s.picks) is None     # the draft alone wouldn't know


def test_the_kept_bench_joins_when_the_eleven_is_full():
    deck = made_up_deck()
    w = dy.Window("433", (), ())
    s, _, waiting = dy._window(deck, season_2000(deck), w, 2, 7)
    moves = []
    while len(s.picks) < 11:
        moves.append(Pick(next(i for i, c in enumerate(s.deal.cards) if dy.why_not_window(s, waiting, c) is None)))
        s, _, waiting = dy._window(deck, season_2000(deck), dy.Window("433", (), tuple(moves)), 2, 7)
    assert not waiting and s.complete                    # the kept three joined: full
    # Q13 (81, RB in 2001) starts over Q1 (79, RB in 2003, skipped ahead), who waits.
    assert [c.id for c in s.bench] == ["Q1", "Q11", "Q12"]
    assert "Q13" in {c.id for c in s.picks[:11]}


def test_a_new_deck_gets_its_own_careers():
    a, b = made_up_deck(), load_deck()
    assert "Q0" in dy.careers(a) and "Q0" not in dy.careers(b)


# -- the real deck ---------------------------------------------------------------------

def best(s, why):
    return Pick(max((i for i, c in enumerate(s.deal.cards) if why(c) is None), key=lambda i: s.deal.cards[i].rating))


def first_season(seed, code="433"):
    deck, moves = load_deck(), []
    s = replay(deck, seed, code, moves, True)
    while not s.complete:
        moves.append(best(s, lambda c, s=s: why_not(c, s.formation, s.picks)))
        s = replay(deck, seed, code, moves, True)
    return moves


def dynasty(seed, seasons, code="433"):
    """A best-pick dynasty's state, ``seasons`` long."""
    deck, moves, windows = load_deck(), first_season(seed, code), []
    for _ in range(seasons - 1):
        w = dy.Window(code, (), ())
        last = dy.replay(deck, dy.encode_dynasty(seed, code, moves, windows=[*windows, w]))[-1]
        while not last.session.complete:
            w = dy.Window(code, (), (*w.moves, best(last.session, last.why_not)))
            last = dy.replay(deck, dy.encode_dynasty(seed, code, moves, windows=[*windows, w]))[-1]
        windows.append(w)
    return dy.encode_dynasty(seed, code, moves, windows=windows)


def fingerprint(t):
    return [(f.stage, f.home.key, f.away.key, f.result.home_goals, f.result.away_goals) for f in t.fixtures]


def test_a_ten_season_dynasty_plays_and_every_kept_man_is_his_next_season():
    deck = load_deck()
    seasons = dy.replay(deck, dynasty(5, dy.LENGTH))
    assert len(seasons) == dy.LENGTH and all(x.session.complete for x in seasons)
    for prev, this in zip(seasons, seasons[1:]):
        held = {c.id: c for c in this.session.picks}
        for f in this.fates:
            if f.reason in ("carried", "skipped"):
                assert held[f.card.id] is dy.advance(deck, f.card)
            else:
                assert f.card.id not in held or held[f.card.id] is not f.next   # signed again from a deal
    t = dy.season_tournament(deck, league_of(deck), seasons[-1])
    assert t.format == "league" and t.reached(t.you())


def test_season_one_is_the_plain_league_drafts_tournament():
    deck = load_deck()
    moves = first_season(8)
    s = replay(deck, 8, "433", moves, True)
    plain = play_tournament(deck, league_of(deck), 8, Side("YOU", "Your XI", "YOU", s.formation, s.xi, you=True,
                                                           bench=s.bench, plan=auto_plan(s.bench)),
                            engine=2, fmt="league")
    first = dy.replay(deck, dy.encode_dynasty(8, "433", moves))[0]
    assert fingerprint(dy.season_tournament(deck, league_of(deck), first)) == fingerprint(plain)


def test_a_later_window_never_moves_an_earlier_season():
    deck = load_deck()
    state = dynasty(3, 3)
    two = dy.replay(deck, state.rpartition("~")[0])[1]
    three = dy.replay(deck, state)[1]
    assert [c.key + c.id for c in two.session.picks] == [c.key + c.id for c in three.session.picks]
    assert fingerprint(dy.season_tournament(deck, league_of(deck), two)) == \
        fingerprint(dy.season_tournament(deck, league_of(deck), three))
    assert dy.season_seed(3, 2) != dy.season_seed(3, 3) != 3


def test_a_window_needs_last_seasons_squad_finished():
    with pytest.raises(IllegalMove, match="isn't complete"):
        dy.replay(load_deck(), "y3-433-0~433-x")


def test_an_unfinished_season_plays_no_tournament():
    deck = load_deck()
    first = dy.replay(deck, "y3-433-0")[0]
    with pytest.raises(IllegalMove, match="isn't complete"):
        dy.season_tournament(deck, league_of(deck), first)


def test_a_window_sheet_and_plan_are_checked_and_kept():
    deck = load_deck()
    state = dynasty(4, 2)
    last = dy.replay(deck, state)[-1].session
    with pytest.raises(IllegalMove, match="names every player once"):
        dy.replay(deck, state + "-s" + "0" * 14)
    planned = dy.replay(deck, state + "-p0a60")[-1].session
    assert planned.plan is not None and last.plan is None


# -- state strings ---------------------------------------------------------------------

def test_the_state_round_trips():
    w = dy.Window("4231", (0, 13), (Pick(3), Reroll(), Pick(12)))
    text = dy.encode_dynasty(42, "433", [Pick(1)], windows=[w, dy.Window("433", (), ())])
    assert text == "y42-433-1~4231-x0d-3.r.12~433-x"
    assert dy.decode(text) == (42, "433", [Pick(1)], None, None, [w, dy.Window("433", (), ())])


@pytest.mark.parametrize("bad", ["l42-433", "y42-433~433", "y42-433~433-x!", "y42-433~433-x-1-2",
                                 "y42-433~433-x-" + ".".join(["1"] * 17)])
def test_malformed_dynasties_are_refused(bad):
    with pytest.raises(IllegalMove):
        dy.decode(bad)


def test_a_dynasty_holds_at_most_max_seasons():
    with pytest.raises(IllegalMove, match="at most"):
        dy.decode("y1-433" + "~433-x" * dy.MAX_SEASONS)


def test_nothing_else_reads_a_dynasty():
    for read in (decode_state, decode_solo):
        with pytest.raises(IllegalMove):
            read("y42-433-1")


def test_a_deck_at_a_reused_address_is_not_given_anothers_careers():
    a, b = made_up_deck(), load_deck()
    dy._CAREERS[id(b)] = (a, dy.careers(a))      # as if b had been made where a once lived
    assert "Q0" not in dy.careers(b)


# -- legends, runs and the team of the dynasty (C66) -------------------------------------

def seasons_of(*squads, waiting=()):
    """Seasons whose squads are these lists of made-up people (ids), for the run rules."""
    from game.deck import Card
    def man(i, positions=("CM",), rating=80):
        return Card(id=f"Q{i}", name=f"P{i}", title=f"P{i}", pos="MF", positions=positions, source="declared",
                    nation=None, rating=rating, season=2000, label="2000–01", club="A", club_name="A",
                    short="A", key="2000-A", crest="A")
    out = []
    for n, ids in enumerate(squads, start=1):
        s = Session(seed=1, formation=FORMATIONS["433"], picks=[man(i) for i in ids], bench_size=BENCH)
        out.append(dy.Season(n, s, [], [man(i) for i in waiting] if n == len(squads) else []))
    return out


def test_a_run_counts_seasons_in_a_row_and_starts_again_after_a_gap():
    s = seasons_of([1, 2, 3], [1, 2], [1, 3], [1, 2, 3], waiting=[4])
    assert dy.runs(s) == {"Q1": 4, "Q2": 1, "Q3": 2, "Q4": 1}     # a waiting substitute is in the squad


def test_a_legend_is_legend_seasons_in_a_row():
    seven = [[1, 2]] * dy.LEGEND
    s = seasons_of(*seven, [2], *([[1, 2]] * (dy.LEGEND - 1)))
    got = {g.card.id: (g.seasons, g.first, g.last) for g in dy.legends(s)}
    assert got == {"Q1": (dy.LEGEND, 1, dy.LEGEND), "Q2": (2 * dy.LEGEND, 1, 2 * dy.LEGEND)}
    assert [g.card.id for g in dy.legends(s)] == ["Q2", "Q1"]                  # the longest first
    assert dy.legends(seasons_of(*([[1]] * (dy.LEGEND - 1)))) == []


def career(i, positions, mark, apps, rating=80):
    from game.deck import Card
    c = Card(id=f"Q{i}", name=f"P{i}", title=f"P{i}", pos="MF", positions=tuple(positions), source="declared",
             nation=None, rating=rating, season=2000, label="2000–01", club="A", club_name="A", short="A",
             key="2000-A", crest="A")
    return c.id, dy.Career(c, set(positions), 1, apps, 0, 0, [mark] * apps)


def full_team(extra=()):
    """One regular for every 4-3-3 place, marked 6.0, and whoever else is given."""
    return dict([career(k, [s], 6.0, 30) for k, s in enumerate(SLOTS)] + list(extra))


def test_the_team_takes_the_best_mark_among_regulars_each_man_once():
    team = dy.team_of("433", full_team([career(50, ["ST", "RW"], 8.0, 30), career(51, ["ST"], 7.0, 30)]))
    got = {s: (c.card.id if c else None) for s, c, _ in team if s in ("ST", "RW")}
    assert got == {"RW": "Q50", "ST": "Q51"}                                # Q50 once, where both fit best


def test_a_regular_comes_before_a_better_mark_with_few_matches():
    team = dy.team_of("433", full_team([career(60, ["ST"], 9.5, 10)]))       # 10 < half of 30
    st = next((c, reg) for s, c, reg in team if s == "ST")
    assert st[0].card.id == "Q9" and st[1]


def test_a_place_no_regular_plays_goes_to_the_best_of_the_rest_and_says_so():
    every = full_team([career(70, ["GK"], 7.5, 10), career(71, ["GK"], 7.0, 9)])
    del every["Q0"]                                                          # the regular keeper
    gk = next((c, reg) for s, c, reg in dy.team_of("433", every) if s == "GK")
    assert gk[0].card.id == "Q70" and not gk[1]


def test_a_place_nobody_plays_is_empty():
    every = full_team()
    del every["Q0"]
    assert next(c for s, c, _ in dy.team_of("433", every) if s == "GK") is None


def test_the_most_used_formation_and_the_later_on_a_tie():
    s = seasons_of([1], [1], [1])
    s[0].session.formation, s[1].session.formation = FORMATIONS["442"], FORMATIONS["4231"]
    assert dy.most_used(s) == "433"
    assert dy.most_used(s[:2]) == "4231"


def test_careers_add_up_every_season_you_played():
    from game.journey import journey
    deck = load_deck()
    seasons = dy.replay(deck, dynasty(5, 2))
    ts = [dy.season_tournament(deck, league_of(deck), x) for x in seasons]
    every = dy.careers_of(ts)
    assert all(c.apps for c in every.values())                              # an unused substitute has none
    for t in ts:
        for p in journey(t, t.you()).players:
            if p.apps:
                assert every[p.card.id].positions >= set(p.card.positions)
    assert sum(c.apps for c in every.values()) == sum(p.apps for t in ts for p in journey(t, t.you()).players)
    assert sum(c.goals for c in every.values()) == sum(p.goals for t in ts for p in journey(t, t.you()).players)
    later = {p.card.id: p.card for p in journey(ts[1], ts[1].you()).players if p.apps}
    both = [c for c in every.values() if c.seasons == 2]
    assert both and all(c.card is later[c.card.id] for c in both)          # his latest card with you
