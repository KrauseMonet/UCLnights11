"""The draft on the real deck: replay, legality and the state string."""

import pytest

from game.deck import build_deck, load_deck
from game.draft import (BENCH, Change, IllegalMove, Pick, Reroll, REROLLS_ALLOWED, can_replace, decode,
                        decode_plan, decode_state, encode, encode_plan, replay, why_not)
from game.formations import FORMATIONS


def first_takeable(s):
    return next(i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None)


def draft_to_the_end(seed, code="433"):
    deck, moves = load_deck(), []
    s = replay(deck, seed, code, moves)
    while not s.complete:
        moves.append(Pick(first_takeable(s)))
        s = replay(deck, seed, code, moves)
    return s, moves


@pytest.mark.parametrize("code", list(FORMATIONS))
def test_every_formation_completes_with_every_man_in_a_slot_he_holds(code):
    s, _ = draft_to_the_end(11, code)
    xi, f = s.xi, FORMATIONS[code]
    assert sorted(c.slot for c in xi) == sorted(f.slots)
    assert all(c.slot in c.positions for c in xi)
    assert {ln: sum(1 for c in xi if c.pos == ln) for ln in f.lines} == f.lines   # slot lines


def test_a_pick_moves_an_earlier_one_rather_than_being_refused():
    """Matching, not first come first served: a right-back/midfielder taken first is moved
    into midfield when a pure right-back arrives, instead of the right-back being refused."""
    from dataclasses import replace
    deck = load_deck()
    s = replay(deck, 1, "433", [])
    base = next(c for cs in deck.club_seasons for c in cs.cards)
    kimmich = replace(base, id="K", positions=("RB", "DM"))
    back = replace(base, id="B", positions=("RB",))
    assert why_not(back, s.formation, [kimmich]) is None
    from game.positions import arrange
    placed = {c.id: c.slot for c in arrange(s.formation.slots, [kimmich, back])}
    assert placed == {"K": "DM", "B": "RB"}
    # ...and once both RB and DM are taken, a third man who plays only those is refused.
    third = replace(base, id="T", positions=("DM", "RB"))
    assert why_not(third, s.formation, [kimmich, back]) == "no DM/RB place left"


def test_a_position_the_formation_lacks_is_refused_by_name():
    from dataclasses import replace
    deck = load_deck()
    s = replay(deck, 1, "442", [])
    base = next(c for cs in deck.club_seasons for c in cs.cards)
    winger = replace(base, id="W", positions=("LW", "RW"))
    assert why_not(winger, s.formation, []) == "no LW/RW in a 4-4-2"


def test_replay_is_deterministic():
    s1, moves = draft_to_the_end(42)
    s2 = replay(load_deck(), 42, "433", moves)
    assert [c.id for c in s1.picks] == [c.id for c in s2.picks]
    assert s1.dealt == s2.dealt


def test_the_same_person_on_another_card_cannot_be_picked_again():
    # One person, two cards: the realistic case (Messi 2008-09 and Messi 2011-12),
    # which a draft rarely meets by chance, so it is built directly.
    deck = load_deck()
    by_person = {}
    for cs in deck.club_seasons:
        for c in cs.cards:
            by_person.setdefault(c.id, []).append(c)
    first, second = next(cards for cards in by_person.values() if len(cards) >= 2)[:2]
    assert first is not second
    s = replay(deck, 1, "433", [])
    assert why_not(second, s.formation, [first]) == "already in your eleven"


def test_a_full_line_refuses_another_player():
    deck = load_deck()
    s = replay(deck, 3, "433", [])
    keepers = [c for cs in deck.club_seasons for c in cs.cards if c.pos == "GK"]
    first, other = keepers[0], next(k for k in keepers if k.id != keepers[0].id)
    assert why_not(other, s.formation, [first]) == "goalkeeper taken"
    assert why_not(first, s.formation, [first]) == "already in your eleven"


def test_an_untakeable_pick_is_refused():
    deck = load_deck()
    for seed in range(1, 200):
        s = replay(deck, seed, "433", [])
        gks = [i for i, c in enumerate(s.deal.cards) if c.pos == "GK"]
        if len(gks) >= 2:
            s2 = replay(deck, seed, "433", [Pick(gks[0])])
            # Deal two, find any goalkeeper offered after the first was taken.
            moves = [Pick(gks[0])]
            while True:
                taken = {c.id for c in s2.picks}   # the same man again is a different refusal
                gk_now = [i for i, c in enumerate(s2.deal.cards) if c.pos == "GK" and c.id not in taken]
                if gk_now:
                    with pytest.raises(IllegalMove, match="goalkeeper taken"):
                        replay(deck, seed, "433", moves + [Pick(gk_now[0])])
                    return
                moves.append(Pick(first_takeable(s2)))
                s2 = replay(deck, seed, "433", moves)
                if s2.complete:
                    break
    pytest.fail("no seed dealt a second goalkeeper")


def test_rerolls_are_capped():
    deck = load_deck()
    moves = [Reroll()] * REROLLS_ALLOWED
    assert replay(deck, 9, "433", moves).rerolls_left == 0
    with pytest.raises(IllegalMove, match="no rerolls"):
        replay(deck, 9, "433", moves + [Reroll()])


def _tiny_deck(extra=()):
    """Squad A can fill a whole 4-3-3; squad B is goalkeepers only.

    Once a goalkeeper is picked, B offers nothing takeable, so the deal-time
    guarantee must redraw past it. On the real deck that almost never happens by
    chance, which is why this is built rather than drafted.
    """
    from game.formations import FORMATIONS
    from game.positions import LINE

    def p(i, slot):
        return {"id": f"Q{i}", "name": f"P{i}", "title": f"P{i}", "pos": LINE[slot], "positions": [slot],
                "source": "declared", "nation": None, "rating": 80}
    a = [p(i, slot) for i, slot in enumerate(FORMATIONS["433"].slots)]
    a += [p(40 + i, slot) for i, slot in enumerate(extra)]
    b = [p(i, "GK") for i in range(20, 31)]
    cs = lambda key, players: {"key": key, "season": 2000, "label": "2000–01", "club": key,
                               "name": key, "short": key, "primary": "#000", "secondary": "#fff",
                               "crest": key, "team": "#000", "deep": "#000", "ink": "#fff",
                               "best": {"formation": "433", "xi": [[q["id"], q["positions"][0]] for q in players[:11]]},
                               "players": players}
    return build_deck({"club_seasons": [cs("A", a), cs("B", b)]})


def test_a_deal_with_nothing_takeable_is_redrawn():
    deck = _tiny_deck()
    redrawn = 0
    for seed in range(60):
        s = replay(deck, seed, "433", [Pick(0)])   # card 0 is a goalkeeper in both squads
        assert s.deal.key == "A", "a goalkeepers-only squad was dealt after the goalkeeper was taken"
        redrawn += s.redraws
    assert redrawn > 0                                # the guarantee actually had to act


def test_state_round_trips():
    moves = [Pick(3), Reroll(), Pick(0)]
    assert decode(encode(123, "4231", moves)) == (123, "4231", moves)
    assert encode(5, "433", []) == "5-433"


@pytest.mark.parametrize("bad", ["", "abc", "1-433-x", "1-433-1.2.3.4.5.6.7.8.9.10.11.12.13.14", "1-433-1234"])
def test_malformed_states_are_refused(bad):
    with pytest.raises(IllegalMove):
        decode(bad)


def test_unknown_formation_is_refused():
    with pytest.raises(IllegalMove, match="formation"):
        replay(load_deck(), 1, "4411", [])


# -- the bench (C40) ------------------------------------------------------------

def bench_draft(seed, code="433", deck=None):
    deck, moves = deck or load_deck(), []
    s = replay(deck, seed, code, moves, bench=True)
    while not s.complete:
        moves.append(Pick(first_takeable(s)))
        s = replay(deck, seed, code, moves, bench=True)
    return s, moves


def test_a_bench_draft_is_eleven_then_three_and_the_eleven_is_the_first_eleven():
    s, moves = bench_draft(42)
    assert len(s.picks) == 11 + BENCH and s.complete and s.deal is None
    assert [c.id for c in s.bench] == [c.id for c in s.picks[11:]]
    assert sorted(c.id for c in s.xi) == sorted(c.id for c in s.picks[:11])
    # The same seed and moves without a bench stop at eleven, with the same eleven.
    plain = replay(load_deck(), 42, "433", moves[:11])
    assert plain.complete and [c.id for c in plain.picks] == [c.id for c in s.picks[:11]]
    with pytest.raises(IllegalMove, match="already complete"):
        replay(load_deck(), 42, "433", moves[:11] + [Pick(0)])


def test_a_bench_pick_refuses_a_keeper_a_man_already_taken_and_a_place_the_formation_lacks():
    s, _ = bench_draft(42, "442")
    f, eleven, deck = s.formation, s.picks[:11], load_deck()
    cards = [c for cs in deck.club_seasons for c in cs.cards]
    keeper = next(c for c in cards if c.positions == ("GK",))
    winger = next(c for c in cards if set(c.positions) <= {"LW", "RW"})
    fits = next(c for c in cards if c.positions[0] == "CM" and c.id not in {x.id for x in eleven})
    assert why_not(keeper, f, eleven) == "keepers stay on"
    assert why_not(winger, f, eleven) == f"no {'/'.join(winger.positions)} in a 4-4-2"
    assert why_not(eleven[3], f, eleven) == "already in your eleven"
    assert why_not(fits, f, eleven) is None
    assert why_not(fits, f, eleven + [fits]) == "already on your bench"
    # Any man the eleven's formation could use is fine, even with his line full: he comes
    # on for whoever stands there.
    assert why_not(fits, f, eleven) is None and sum(x.slot == "CM" for x in s.xi) == 2


def test_a_bench_deal_with_nothing_takeable_is_redrawn():
    # Squad B is goalkeepers only, which no bench takes. The eleven fills from A, so every
    # bench deal must be A, and getting there must have needed redraws.
    deck = _tiny_deck(extra=("CM", "ST", "CB", "RW"))
    redrawn = 0
    for seed in range(30):
        s, moves = bench_draft(seed, deck=deck)
        assert s.dealt[-BENCH:] == ["A"] * BENCH
        before = replay(deck, seed, "433", moves[:11], bench=True).redraws
        redrawn += s.redraws - before
    assert redrawn > 0


def test_a_bench_state_round_trips_and_its_cap_counts_the_bench():
    moves = [Pick(3), Reroll(), Pick(0)]
    assert decode_state(encode(123, "4231", moves, bench=True)) == (123, "4231", moves, True, None)
    assert decode_state(encode(123, "4231", moves)) == (123, "4231", moves, False, None)
    long = ".".join(["1"] * (11 + BENCH + REROLLS_ALLOWED))
    assert decode_state(f"b1-433-{long}")[3]
    with pytest.raises(IllegalMove):
        decode_state(f"b1-433-{long}.1")
    with pytest.raises(IllegalMove):
        decode(f"1-433-{long}")
    with pytest.raises(IllegalMove, match="bench"):
        decode("b1-433")


# -- the plan (C41) -----------------------------------------------------------------

def test_a_plan_round_trips_and_rides_at_the_end_of_a_bench_state():
    plan = (Change(0, 60, "behind", 9), Change(1, 70, "any"), Change(2, 85, "not_behind"))
    assert encode_plan(plan) == "p0b60o9.1a70.2w85"
    assert decode_plan(encode_plan(plan)) == plan and decode_plan("p") == ()
    moves = [Pick(1), Pick(2)]
    assert encode(5, "433", moves, bench=True, plan=plan) == "b5-433-1.2-p0b60o9.1a70.2w85"
    assert decode_state("b5-433-1.2-p0b60o9.1a70.2w85")[4] == plan
    assert decode_state("b5-433-1.2")[4] is None


@pytest.mark.parametrize("bad", ["5-433-1.2-p0a60", "b5-433-p0a60", "b5-433-1.2-p0z60", "b5-433-1.2-p0a6",
                                 "b5-433-1.2-p0a60o123", "b5-433-1.2-q", "b5-433-1.2-p0a60.1a60.2a60.0a70"])
def test_a_malformed_plan_is_refused(bad):
    with pytest.raises(IllegalMove):
        decode_state(bad)


def test_a_plan_must_fit_the_finished_draft():
    s, moves = bench_draft(42)
    deck = load_deck()
    ok = lambda plan: replay(deck, 42, "433", moves, bench=True, plan=plan)   # noqa: E731
    xi = s.xi
    slot = can_replace(s.formation, xi, s.bench[0])[0]
    # A starter both of the first two could come on for, so only the one-change rule refuses.
    both = next(j for j in can_replace(s.formation, xi, s.bench[0]) if j in can_replace(s.formation, xi, s.bench[1]))
    assert ok((Change(0, 60, "behind", slot),)).subs()[0].off == s.xi[slot].id
    assert ok(()).subs() == ()
    for bad in [(Change(0, 60, "any"), Change(0, 70, "any")),             # one substitute twice
                (Change(0, 60, "any", both), Change(1, 70, "any", both)),  # one starter twice
                (Change(0, 60, "any", 0),),                               # the keeper
                (Change(3, 60, "any"),),                                  # no fourth substitute
                (Change(0, 40, "any"),), (Change(0, 90, "any"),), (Change(0, 62, "any"),)]:
        with pytest.raises(IllegalMove):
            ok(bad)
    with pytest.raises(IllegalMove, match="finished"):
        replay(deck, 42, "433", moves[:-1], bench=True, plan=())


def test_can_replace_names_exactly_the_starters_a_man_could_come_on_for():
    from game.positions import fits
    s, _ = bench_draft(42, "352")
    xi = s.xi                     # a property: each read places fresh copies
    for man in s.bench:
        allowed = can_replace(s.formation, xi, man)
        for j, c in enumerate(xi):
            legal = s.formation.slots[j] != "GK" and fits(s.formation.slots, [*(x for x in xi if x is not c), man])
            assert (j in allowed) == legal
        assert allowed
    # Never the keeper, even for a man who could stand there. No keeper reaches a bench
    # (why_not_bench), so this guard is a second one, and only a keeper can show it acting.
    keeper = next(c for cs in load_deck().club_seasons for c in cs.cards
                  if c.positions == ("GK",) and c.id not in {x.id for x in xi})
    assert fits(s.formation.slots, [*xi[1:], keeper]) and can_replace(s.formation, xi, keeper) == []


# -- the team sheet (C44) -----------------------------------------------------

from game.draft import carry_plan, check_sheet, decode_sheet, decode_solo, default_sheet, move, targets  # noqa: E402


def best_bench_draft(seed, code="433"):
    deck, moves = load_deck(), []
    s = replay(deck, seed, code, moves, bench=True)
    while not s.complete:
        ok = [i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None]
        moves.append(Pick(max(ok, key=lambda i: s.deal.cards[i].rating)))
        s = replay(deck, seed, code, moves, bench=True)
    return s, moves


def a_swap(s):
    """A finished bench draft's first legal starter-for-substitute swap: (slot j, bench k)."""
    return next((j, k) for k, man in enumerate(s.bench) for j, slot in enumerate(s.formation.slots)
                if slot != "GK" and slot in man.positions)


def swapped(s, j, k):
    sheet = list(default_sheet(s))
    sheet[j], sheet[11 + k] = sheet[11 + k], sheet[j]
    return tuple(sheet)


def test_the_default_sheet_is_the_draft_as_it_always_played():
    s, moves = bench_draft(21)
    t = replay(load_deck(), 21, "433", moves, bench=True, sheet=default_sheet(s))
    assert [(c.id, c.slot) for c in t.xi] == [(c.id, c.slot) for c in s.xi]
    assert [c.id for c in t.bench] == [c.id for c in s.bench] == [c.id for c in s.picks[11:]]


def test_a_sheet_puts_a_substitute_in_the_eleven_and_the_starter_on_the_bench():
    s, moves = bench_draft(22)
    j, k = a_swap(s)
    t = replay(load_deck(), 22, "433", moves, bench=True, sheet=swapped(s, j, k))
    assert t.xi[j].id == s.bench[k].id and t.xi[j].slot == s.formation.slots[j]
    assert t.bench[k].id == s.xi[j].id
    assert [c.id for n, c in enumerate(t.xi) if n != j] == [c.id for n, c in enumerate(s.xi) if n != j]


def test_a_starter_moved_to_another_position_stands_there_and_the_rest_make_room():
    # Pirlo coming on for a central midfielder in seed 23's 4-3-3: he only plays DM, so
    # Moutinho moves up from DM to make room, and nobody else moves.
    s, moves = best_bench_draft(23)
    pirlo = next(i for i, c in enumerate(s.picks) if c.name == "Andrea Pirlo")
    cm = s.formation.slots.index("CM")
    t = replay(load_deck(), 23, "433", moves, bench=True, sheet=move(s, pirlo, f"s{cm}"))
    assert next(c for c in t.xi if c.name == "Andrea Pirlo").slot == "DM"
    moved = {c.name for a, c in zip(s.xi, t.xi) if a.id != c.id}
    assert moved == {"Andrea Pirlo", "João Moutinho"}        # two places change: Pirlo in, Moutinho across
    assert s.xi[cm].id in {c.id for c in t.bench}
    with pytest.raises(IllegalMove, match="doesn't play"):
        move(s, default_sheet(s)[0], f"s{cm}")              # the keeper at CM


@pytest.mark.parametrize("seed", [23, 31, 32])
def test_every_place_offered_is_taken_and_every_other_refused(seed):
    s, moves = best_bench_draft(seed)
    offered = targets(s)
    places = [f"s{j}" for j in range(11)] + [f"b{k}" for k in range(3)]
    for man in range(14):
        for to in places:
            if to in offered[man]:
                sheet = move(s, man, to)
                t = replay(load_deck(), seed, "433", moves, bench=True, sheet=sheet)   # a legal sheet
                if to.startswith("s") and man in default_sheet(s)[:11]:
                    assert t.xi[int(to[1:])].id == s.picks[man].id
            else:
                with pytest.raises(IllegalMove):
                    move(s, man, to)


def test_a_sheet_refuses_a_keeper_on_the_bench_a_repeat_and_an_unfinished_draft():
    s, moves = bench_draft(24)
    keeper = s.formation.slots.index("GK")
    k = next(k for k, man in enumerate(s.bench))
    with pytest.raises(IllegalMove):
        check_sheet(s, swapped(s, keeper, k))          # nobody on a bench keeps goal: the slot refuses him
    from dataclasses import replace
    gk_only = replace(s.picks[default_sheet(s)[keeper]], positions=("GK",))
    s.picks[default_sheet(s)[keeper]] = gk_only
    s.picks[default_sheet(s)[11]] = replace(s.picks[default_sheet(s)[11]], positions=("GK",))
    sheet = list(default_sheet(s))
    with pytest.raises(IllegalMove, match="keepers stay on"):
        check_sheet(s, tuple(sheet))
    s2, _ = bench_draft(24)
    with pytest.raises(IllegalMove, match="every player once"):
        check_sheet(s2, (0, 0, *default_sheet(s2)[2:]))
    short = replay(load_deck(), 24, "433", moves[:5], bench=True)
    with pytest.raises(IllegalMove, match="finished draft"):
        check_sheet(short, tuple(range(14)))
    eleven, _ = draft_to_the_end(24)
    with pytest.raises(IllegalMove, match="finished draft with a bench"):
        check_sheet(eleven, tuple(range(11)))


def test_a_sheet_rides_in_a_solo_state_before_the_plan_and_nowhere_else():
    s, moves = bench_draft(25)
    sheet, plan = swapped(s, *a_swap(s)), (Change(0, 60, "any"),)
    state = encode(25, "433", moves, bench=True, plan=plan, sheet=sheet)
    assert "-s" in state and state.index("-s") < state.index("-p")
    assert decode_solo(state) == (25, "433", moves, True, plan, sheet)
    assert decode_solo(encode(25, "433", moves, bench=True, sheet=sheet))[5] == sheet
    assert decode_sheet("s0123456789abcd") == tuple(range(14))
    with pytest.raises(IllegalMove):
        decode_state(state)                              # rooms and the daily never take one
    for bad in ("s0123", "s0123456789abcD", "x0123456789abcd"):
        with pytest.raises(IllegalMove):
            decode_sheet(bad)


def test_a_plan_follows_its_men_to_a_new_sheet():
    s, moves = bench_draft(26)
    deck = load_deck()
    # Swap the first two substitutes: each line goes with its man.
    sheet = list(default_sheet(s))
    sheet[11], sheet[12] = sheet[12], sheet[11]
    t = replay(deck, 26, "433", moves, bench=True, sheet=tuple(sheet))
    plan = (Change(0, 60, "any"), Change(1, 70, "behind"))
    assert carry_plan(s, t, plan) == (Change(1, 60, "any"), Change(0, 70, "behind"))
    # A substitute brought into the eleven loses his line; a named starter sent to the
    # bench leaves "best change" behind.
    j, k = a_swap(s)
    u = replay(deck, 26, "433", moves, bench=True, sheet=swapped(s, j, k))
    others = [n for n in range(3) if n != k]
    named = Change(others[0], 75, "any", j)
    assert carry_plan(s, u, (Change(k, 60, "any"), named)) == (Change(others[0], 75, "any", None),)
    assert carry_plan(s, u, None) is None


# Rules the real deck rarely makes act on their own, asked directly of made-up squads.

from dataclasses import replace as _replace  # noqa: E402

from game.draft import Session  # noqa: E402


def made_up(positions_by_pick):
    """A finished 4-3-3 bench draft of made-up men, picks in the order given."""
    base = load_deck().club_seasons[0].cards[0]
    picks = [_replace(base, id=f"M{n}", name=f"Man {n}", positions=ps, rating=80)
             for n, ps in enumerate(positions_by_pick)]
    return Session(1, FORMATIONS["433"], picks=picks, bench_size=BENCH)


XI_433 = [("GK",), ("RB",), ("CB",), ("CB",), ("LB",), ("DM",), ("CM",), ("CM",), ("RW",), ("ST",), ("LW",)]


def test_a_sheet_refuses_a_man_in_a_slot_he_does_not_hold():
    s = made_up([*XI_433, ("CM",), ("ST",), ("RW",)])
    sheet = list(range(14))
    sheet[1], sheet[8] = sheet[8], sheet[1]           # the right-winger at right-back, and back
    with pytest.raises(IllegalMove, match="doesn't play"):
        check_sheet(s, tuple(sheet))


def test_a_move_leaves_everyone_it_does_not_need_where_they_stand():
    # Two midfielders each standing at their second position: nothing about a winger's
    # move needs them to change, so they don't, though each prefers the other's place.
    s = made_up([("GK",), ("RB",), ("CB",), ("CB",), ("LB",), ("CM", "DM"), ("DM", "CM"), ("CM",),
                 ("RW", "LW"), ("ST",), ("LW", "RW"), ("CM",), ("ST",), ("ST",)])
    s.sheet = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)        # Man 5 at DM, Man 6 at CM
    new = move(s, 8, "s10")                                         # the wingers change flanks
    assert new[5] == 5 and new[6] == 6 and new[8] == 10 and new[10] == 8


def test_a_keeper_is_never_offered_a_place_on_the_bench():
    # A substitute who can also keep goal would fit the keeper's slot, but the keeper
    # going off would sit on a bench where keepers don't.
    s = made_up([*XI_433, ("GK", "CB"), ("ST",), ("RW",)])
    assert "s0" not in targets(s)[11]
    with pytest.raises(IllegalMove, match="keepers stay on"):
        move(s, 11, "s0")


def test_a_carried_plan_drops_a_named_starter_its_substitute_can_no_longer_replace():
    # Man 6 (CM or RW) starts at CM; the plan brings sub 0 (a CM) on for him.
    picks = [*XI_433[:6], ("CM", "RW"), *XI_433[7:], ("CM",), ("ST",), ("CM",)]
    s = made_up(picks)
    plan = (Change(0, 60, "any", 6),)
    # Then Man 6 moves to the right wing, the winger goes to the bench and sub 2 takes
    # the CM place. Man 6 still starts, but nobody left could cover the wing if a CM
    # replaced him, so the line goes back to "best change".
    t = made_up(picks)
    t.sheet = (0, 1, 2, 3, 4, 5, 13, 7, 6, 9, 10, 11, 12, 8)
    assert carry_plan(s, t, plan) == (Change(0, 60, "any", None),)
    # Moved to the right wing with the winger to CM instead, he still can be replaced.
    u = made_up([*picks[:8], ("RW", "CM"), *picks[9:]])
    v = made_up([*picks[:8], ("RW", "CM"), *picks[9:]])
    v.sheet = (0, 1, 2, 3, 4, 5, 8, 7, 6, 9, 10, 11, 12, 13)
    assert carry_plan(u, v, plan) == (Change(0, 60, "any", 8),)
