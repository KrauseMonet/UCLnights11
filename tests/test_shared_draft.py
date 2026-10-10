"""The turn-by-turn shared draft, on its own (C29)."""

import pytest

from game import shared_draft as sd
from game.deck import load_deck
from game.draft import IllegalMove


@pytest.fixture(scope="module")
def deck():
    return load_deck()


def drafted(deck, forms, seed=5, until=None):
    moves = []
    d = sd.replay_shared(deck, seed, forms, moves)
    while not d.complete and (until is None or len(moves) < until):
        moves.append(sd.autopick(d))
        d = sd.replay_shared(deck, seed, forms, moves)
    return d


def test_the_order_snakes():
    assert [sd.turn_seat(i, 3) for i in range(12)] == [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0]
    assert [sd.turn_seat(i, 1) for i in range(3)] == [0, 0, 0]


def test_everyone_gets_eleven_and_nobody_shares_a_man(deck):
    d = drafted(deck, ["433", "442", "352", "4231"])
    assert d.complete and [len(p) for p in d.picks] == [11] * 4
    ids = [c.id for p in d.picks for c in p]
    assert len(ids) == len(set(ids))
    for f, picks in zip(d.formations, d.picks):
        assert {pos: sum(c.pos == pos for c in picks) for pos in f.lines} == f.lines


def test_a_man_taken_by_anyone_is_gone_for_everyone_in_any_season(deck):
    d = drafted(deck, ["433", "433"], until=7)
    taken = {c.id for p in d.picks for c in p}
    for i, c in enumerate(d.deal.cards):
        if c.id in taken:
            assert d.reason(c, d.active) is not None
            assert i not in d.takeable(d.active)


def test_a_pick_of_a_taken_man_is_refused(deck):
    moves = []
    d = sd.replay_shared(deck, 8, ["433", "433"], moves)
    for _ in range(40):
        moves.append(sd.autopick(d))
        d = sd.replay_shared(deck, 8, ["433", "433"], moves)
        bad = [i for i, c in enumerate(d.deal.cards) if c.id in d.taken]
        if bad:
            with pytest.raises(IllegalMove, match="drafted|eleven"):
                sd.replay_shared(deck, 8, ["433", "433"], moves + [bad[0]])
            return
    pytest.fail("no deal ever held a taken man; the test needs one")


def test_every_deal_offers_the_seat_on_turn_something(deck):
    moves = []
    d = sd.replay_shared(deck, 3, ["343", "352", "4231"], moves)
    while not d.complete:
        assert d.takeable(d.active)
        moves.append(sd.autopick(d))
        d = sd.replay_shared(deck, 3, ["343", "352", "4231"], moves)


def test_the_auto_pick_is_seeded_so_a_replay_never_rerolls_it(deck):
    a = drafted(deck, ["433", "442"], seed=21, until=6)
    b = drafted(deck, ["433", "442"], seed=21, until=6)
    assert a.moves == b.moves and sd.autopick(a) == sd.autopick(b)


def test_moves_round_trip_and_junk_is_refused():
    assert sd.decode_moves(sd.encode_moves([3, 0, 12])) == [3, 0, 12]
    assert sd.decode_moves("") == []
    for junk in ("1..2", "a", "1234", "-1"):
        with pytest.raises(IllegalMove):
            sd.decode_moves(junk)


def test_too_many_moves_are_refused(deck):
    with pytest.raises(IllegalMove, match="too many"):
        sd.replay_shared(deck, 1, ["433"], [0] * 12)


def test_a_man_held_by_one_seat_is_refused_to_the_other_in_any_season(deck):
    # Asked directly of the rule, so it can't pass by never meeting the case.
    d = drafted(deck, ["433", "433"], seed=13, until=1)
    held = d.picks[0][0]
    assert d.reason(held, 1) == "already drafted"
    other_seasons = [c for cs in deck.club_seasons for c in cs.cards if c.id == held.id and c.key != held.key]
    for c in other_seasons:
        assert d.reason(c, 1) == "already drafted"
