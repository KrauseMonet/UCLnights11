"""The open auction draft (C69): nominations, raises, the lot clock, the replay."""

import pytest

from game import open_auction as oa
from game.auction import BUDGET, MIN_BID
from game.deck import build_deck, load_deck
from game.draft import IllegalMove
from game.formations import FORMATIONS
from game.positions import LINE

SLOTS = FORMATIONS["433"].slots
E = oa.Event


def player(i, positions, rating=80):
    return {"id": f"Q{i}", "name": f"P{i}", "title": f"P{i}", "pos": LINE[positions[0]],
            "positions": list(positions), "source": "declared", "nation": None, "rating": rating}


def club(key, players, season=2000):
    return {"key": f"{season}-{key}", "season": season, "label": f"{season}–01", "club": key, "name": key,
            "short": key, "primary": "#000", "secondary": "#fff", "crest": key, "team": "#000", "deep": "#000",
            "ink": "#fff", "best": {"formation": "433", "xi": [[players[0]["id"], players[0]["positions"][0]]]},
            "players": players}


def tiny_deck():
    """One squad, A: two of every 4-3-3 place (men 0-21), so every deal is A."""
    return build_deck({"club_seasons": [club("A", [player(k, (s,), 70 + k) for k, s in enumerate(SLOTS * 2)])]})


def start(deck=None, seats=2, timer=30.0):
    return oa.replay(deck or tiny_deck(), 1, ["433"] * seats, [], False, timer)


def up(a, deck, t=1.0, i=20):
    """The nominator puts up man ``i`` of his deal at ``t``."""
    oa.apply(a, deck, E(t, "n", a.nominator, i))
    return a.lot


# -- nominating ---------------------------------------------------------------------------

def test_the_nominator_opens_at_the_minimum_and_leads():
    deck = tiny_deck()
    a = start(deck)
    assert a.nominator == 0 and a.deal is not None and a.nominate_by == 30.0
    lot = up(a, deck, 2.0)
    assert (lot.leader, lot.price, lot.ends) == (0, MIN_BID, 2.0 + oa.LOT_SECONDS)


def test_only_the_nominator_nominates_and_only_a_man_he_can_take():
    deck = tiny_deck()
    a = start(deck)
    with pytest.raises(IllegalMove, match="turn"):
        oa.apply(a, deck, E(1.0, "n", 1, 20))
    a.picks[0] = [c for c in deck.club_seasons[0].cards if c.positions == ("GK",)][:1]
    a.taken.add(a.picks[0][0].id)
    other_gk = next(i for i, c in enumerate(a.deal.cards) if c.positions == ("GK",) and c.id not in a.taken)
    with pytest.raises(IllegalMove, match="goalkeeper"):
        oa.apply(a, deck, E(1.0, "n", 0, other_gk))


def test_a_nomination_after_the_timer_and_its_grace_is_refused_and_the_server_puts_one_up():
    deck = tiny_deck()
    a = start(deck, timer=15.0)
    assert a.due(15.0 + oa.GRACE_S - 0.01) is None and a.due(15.0 + oa.GRACE_S) == "a"
    with pytest.raises(IllegalMove, match="still has time"):
        oa.apply(a, deck, E(15.5, "a"))
    with pytest.raises(IllegalMove, match="run out"):
        oa.apply(start(deck, timer=15.0), deck, E(16.5, "n", 0, 20))
    oa.apply(a, deck, E(16.0, "a"))
    assert a.lot is not None and a.reason(a.lot.card, 0) is None
    b = start(deck, timer=15.0)
    oa.apply(b, deck, E(16.0, "a"))
    assert b.lot.card is a.lot.card                                          # seeded: the same man


# -- bidding ------------------------------------------------------------------------------

def test_a_raise_must_beat_the_price_by_the_minimum_and_keep_the_reserve():
    deck = tiny_deck()
    a = start(deck)
    up(a, deck)
    assert a.can_bid(1, MIN_BID) is not None                                 # equal to the price
    assert a.can_bid(1, MIN_BID + oa.MIN_RAISE) is None
    top = BUDGET - MIN_BID * 10
    assert a.max_bid(1) == top and a.can_bid(1, top) is None and a.can_bid(1, top + 1) is not None
    oa.apply(a, deck, E(3.0, "b", 1, 10))
    assert (a.lot.leader, a.lot.price) == (1, 10)
    with pytest.raises(IllegalMove, match="lead"):
        oa.apply(a, deck, E(4.0, "b", 1, 12))


def test_a_bid_must_fit_the_bidders_formation():
    deck = tiny_deck()
    a = start(deck)
    lot = up(a, deck, i=0)                                                   # a keeper
    a.picks[1] = [next(c for c in deck.club_seasons[0].cards if c.positions == ("GK",) and c is not lot.card)]
    a.taken.add(a.picks[1][0].id)
    assert "goalkeeper" in a.can_bid(1)
    with pytest.raises(IllegalMove, match="goalkeeper"):
        oa.apply(a, deck, E(3.0, "b", 1, 5))


def test_a_bid_puts_the_clock_back_but_never_shortens_it():
    deck = tiny_deck()
    a = start(deck)
    up(a, deck, 1.0)                                                         # ends at 13.0
    oa.apply(a, deck, E(2.0, "b", 1, 5))
    assert a.lot.ends == 1.0 + oa.LOT_SECONDS                                # 2 + 8 is earlier
    oa.apply(a, deck, E(9.0, "b", 0, 7))
    assert a.lot.ends == 9.0 + oa.BID_SECONDS


def test_a_late_bid_counts_within_the_grace_and_not_after():
    deck = tiny_deck()
    a = start(deck)
    up(a, deck, 1.0)
    ends = a.lot.ends
    oa.apply(a, deck, E(ends + oa.GRACE_S - 0.01, "b", 1, 5))
    b = start(deck)
    up(b, deck, 1.0)
    with pytest.raises(IllegalMove, match="closed"):
        oa.apply(b, deck, E(ends + oa.GRACE_S + 0.01, "b", 1, 5))


# -- closing ------------------------------------------------------------------------------

def test_a_contested_lot_closes_only_when_its_clock_and_grace_have_run():
    deck = tiny_deck()
    a = start(deck)
    up(a, deck, 1.0)
    end = a.lot.ends + oa.GRACE_S
    assert a.due(end - 0.01) is None and a.due(end) == "c"
    with pytest.raises(IllegalMove, match="still open"):
        oa.apply(a, deck, E(end - 0.01, "c"))
    oa.apply(a, deck, E(end, "c"))
    assert [c.id for c in a.picks[0]] == ["Q20"] and a.spent == [MIN_BID, 0]


def test_a_lot_nobody_else_can_bid_on_sells_at_once():
    deck = tiny_deck()
    a = start(deck)
    a.picks[1] = list(deck.club_seasons[0].cards[:11])                      # seat 1 is full
    a.taken |= {c.id for c in a.picks[1]}
    up(a, deck, 1.0, i=20)
    assert not a.contested() and a.due(1.0) == "c"
    oa.apply(a, deck, E(1.0, "c"))
    assert a.lot is None and len(a.picks[0]) == 1


def test_the_winner_pays_his_bid_and_the_next_seat_nominates():
    deck = tiny_deck()
    a = start(deck, seats=3)
    up(a, deck, 1.0)
    oa.apply(a, deck, E(2.0, "b", 2, 17))
    oa.apply(a, deck, E(30.0, "c"))
    assert a.spent == [0, 0, 17] and [c.id for c in a.picks[2]] == ["Q20"]
    assert a.nominator == 1 and a.nominate_by == 30.0 + a.timer and a.deal is not None


def test_a_full_seat_is_skipped_in_the_nominating_order():
    deck = tiny_deck()
    a = start(deck, seats=3)
    a.picks[1] = list(deck.club_seasons[0].cards[11:22])
    a.taken |= {c.id for c in a.picks[1]}
    up(a, deck, 1.0, i=0)
    oa.apply(a, deck, E(30.0, "c"))
    assert a.nominator == 2


def test_the_hosts_finish_sells_the_lot_and_fills_every_place():
    deck = load_deck()
    a = oa.replay(deck, 4, ["433", "352", "4231"], [], True)
    oa.apply(a, deck, E(1.0, "n", 0, next(i for i, c in enumerate(a.deal.cards) if a.reason(c, 0) is None)))
    oa.apply(a, deck, E(2.0, "b", 1, 9))
    oa.apply(a, deck, E(3.0, "f"))
    assert a.complete and all(len(p) == 14 for p in a.picks)
    assert a.spent[1] == 9 + MIN_BID * 13 and a.spent[0] == MIN_BID * 14
    assert len({c.id for p in a.picks for c in p}) == 42
    with pytest.raises(IllegalMove, match="over"):
        oa.apply(a, deck, E(4.0, "c"))


def test_events_run_forwards_in_time():
    deck = tiny_deck()
    a = start(deck)
    up(a, deck, 5.0)
    with pytest.raises(IllegalMove, match="forwards"):
        oa.apply(a, deck, E(4.0, "b", 1, 5))


# -- the deal and the replay --------------------------------------------------------------

def test_the_nominator_is_dealt_a_squad_holding_someone_he_can_take():
    keepers = club("K", [player(100 + k, ("GK",)) for k in range(11)], 2001)
    deck = build_deck({"club_seasons": [club("A", [player(k, (s,)) for k, s in enumerate(SLOTS * 2)]), keepers]})
    redrawn = 0
    for seed in range(20):
        a = oa.replay(deck, seed, ["433", "433"], [], False)
        a.picks[1] = [deck.by_key["2000-A"].cards[0]]                       # seat 1 has a keeper...
        a.taken.add(a.picks[1][0].id)
        a.nominator, a.lots_done = 0, seed                                   # ...and seat 0, nominating,
        a.picks[0] = [deck.by_key["2000-A"].cards[11]]                      # has one too
        a.taken.add(a.picks[0][0].id)
        cs = oa._deal(a, deck)
        assert cs.key == "2000-A"
        redrawn += a.redraws
    assert redrawn, "the guarantee never had to act"


def test_the_replay_is_pure_and_the_events_round_trip():
    deck = load_deck()
    a = oa.replay(deck, 6, ["433", "442"], [])
    i = next(k for k, c in enumerate(a.deal.cards) if a.reason(c, 0) is None)
    events = [E(3.5, "n", 0, i)]
    oa.apply(a, deck, events[0])
    bidder = 1 if a.can_bid(1, 6) is None else 0
    events += [E(4.25, "b", 1, 6)] if bidder == 1 else []
    events += [E(40.0, "c"), E(80.0, "a")]
    text = oa.encode_events(events)
    b = oa.replay(deck, 6, ["433", "442"], oa.decode_events(text))
    c = oa.replay(deck, 6, ["433", "442"], events)
    assert [[x.id for x in p] for p in b.picks] == [[x.id for x in p] for p in c.picks]
    assert b.spent == c.spent and b.lot.card is c.lot.card and oa.decode_events(text) == events


@pytest.mark.parametrize("bad", ["x:n:0:1", "100:z", "100:n", "100:b:0", "100:c:1:2", "100:b:0:99999"])
def test_malformed_events_are_refused(bad):
    with pytest.raises(IllegalMove):
        oa.decode_events(bad)
