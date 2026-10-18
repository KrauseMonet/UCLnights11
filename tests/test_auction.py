"""The sealed-bid auction draft (C68): markets, bids, settling a round, the replay."""

import pytest

from game import auction as au
from game.deck import build_deck, load_deck
from game.draft import IllegalMove
from game.formations import FORMATIONS
from game.positions import LINE
from game.shared_draft import Stranded

SLOTS = FORMATIONS["433"].slots


def player(i, positions, rating=80):
    return {"id": f"Q{i}", "name": f"P{i}", "title": f"P{i}", "pos": LINE[positions[0]],
            "positions": list(positions), "source": "declared", "nation": None, "rating": rating}


def club(key, players, season=2000):
    return {"key": f"{season}-{key}", "season": season, "label": f"{season}–01", "club": key, "name": key,
            "short": key, "primary": "#000", "secondary": "#fff", "crest": key, "team": "#000", "deep": "#000",
            "ink": "#fff", "best": {"formation": "433", "xi": [[players[0]["id"], players[0]["positions"][0]]]},
            "players": players}


def made_up_deck_doc():
    a = [player(i, (s,), 80 + i) for i, s in enumerate(SLOTS)]
    a += [player(11, ("CM",), 75), player(12, ("ST",), 74), player(13, ("GK",), 70)]
    b = [player(i, (s,), 70) for i, s in enumerate(SLOTS)]
    return {"club_seasons": [club("A", a), club("B", b, 2001)]}


def made_up_deck():
    """Squad A: a 4-3-3 of men 0-10 (rated 80-90) and three more (11 a CM, 12 a ST, 13 a GK);
    squad B: the same people a season later, so one person shows up twice."""
    return build_deck(made_up_deck_doc())


def auction(deck, seats=2, bench=False):
    """An auction whose open market is squad A alone, for settling rounds by hand."""
    n = seats
    a = au.Auction(9, [FORMATIONS["433"]] * n, [[] for _ in range(n)], [0] * n, [0] * n,
                   picks_each=11 + (3 if bench else 0))
    a.market = [deck.by_key["2000-A"]]
    return a


def lot(a, i):
    return next(k for k, c in enumerate(a.lots) if c.id == f"Q{i}")


# -- settling a round ---------------------------------------------------------------------

def test_the_winner_pays_one_more_than_the_next_bid_and_never_more_than_he_bid():
    deck = made_up_deck()
    a = auction(deck, 3)
    x = lot(a, 9)
    (sale,) = au.settle(a, {0: [(x, 40)], 1: [(x, 30)], 2: []})
    assert (sale.seat, sale.price, sale.bid) == (0, 31, 40)
    assert a.spent == [31, 0, 0] and [c.id for c in a.picks[0]] == ["Q9"]
    b = auction(deck, 2)
    (tie,) = au.settle(b, {0: [(x, 40)], 1: [(x, 40)]})
    assert tie.price == 40                                  # equal bids: the winner pays his own


def test_a_man_nobody_else_wanted_costs_the_minimum():
    deck = made_up_deck()
    a = auction(deck, 2)
    (sale,) = au.settle(a, {0: [(lot(a, 9), 55)], 1: []})
    assert sale.price == au.MIN_BID and sale.others == ()


def test_a_seat_wins_one_man_a_round_its_best_bid_first():
    deck = made_up_deck()
    a = auction(deck, 2)
    x, y = lot(a, 9), lot(a, 8)
    sales = au.settle(a, {0: [(x, 50), (y, 40)], 1: [(x, 60)]})
    assert {(s.seat, s.card.id) for s in sales} == {(1, "Q9"), (0, "Q8")}
    a2 = auction(deck, 2)
    sales = au.settle(a2, {0: [(x, 50), (y, 40)], 1: [(y, 10)]})
    assert {(s.seat, s.card.id) for s in sales} == {(0, "Q9"), (1, "Q8")}   # 0 took x, so y goes to 1
    # The second price is the best other bid on the man (0's 40 on y), capped at 1's own 10.
    assert next(s for s in sales if s.seat == 1).price == 10


def test_a_tie_goes_to_the_seat_with_more_places_left():
    deck = made_up_deck()
    a = auction(deck, 2)
    a.picks[0].append(deck.by_key["2000-A"].cards[0])        # seat 0 already has a keeper
    a.taken.add("Q0")
    x = lot(a, 9)
    (sale,) = au.settle(a, {0: [(x, 20)], 1: [(x, 20)]})
    assert sale.seat == 1


def test_a_tie_between_equals_is_a_seeded_draw():
    deck = made_up_deck()
    winners = set()
    for seed in range(12):
        a = auction(deck, 2)
        a.seed = seed
        x = lot(a, 9)
        winners.add(au.settle(a, {0: [(x, 20)], 1: [(x, 20)]})[0].seat)
        b = auction(deck, 2)
        b.seed = seed
        assert au.settle(b, {0: [(x, 20)], 1: [(x, 20)]})[0].seat in winners      # the same seed, the same draw
    assert winners == {0, 1}


def test_a_silent_seat_bids_the_minimum_on_someone_it_can_take():
    deck = made_up_deck()
    a = auction(deck, 2)
    (bid,) = au.auto_bid(a, 1)
    assert bid[1] == au.MIN_BID and a.reason(a.lots[bid[0]], 1) is None
    assert au.auto_bid(a, 1) == au.auto_bid(a, 1)
    sales = au.settle(a, {0: []})
    assert [s.seat for s in sales] == [1] and a.passes == [1, 0]


# -- bids ---------------------------------------------------------------------------------

def test_a_bid_keeps_the_minimum_for_every_other_place():
    deck = made_up_deck()
    a = auction(deck, 2)
    assert a.max_bid(0) == au.BUDGET - au.MIN_BID * 10
    au.check_bids(a, 0, [(lot(a, 9), a.max_bid(0))])
    with pytest.raises(IllegalMove, match="keep"):
        au.check_bids(a, 0, [(lot(a, 9), a.max_bid(0) + 1)])
    with pytest.raises(IllegalMove, match="keep"):
        au.check_bids(a, 0, [(lot(a, 9), 0)])


@pytest.mark.parametrize("bids, match", [
    ([(0, 5)] * 1 + [(k, 5) for k in range(1, au.MAX_BIDS + 1)], "at most"),
    ([(0, 5), (0, 6)], "one bid a man"),
    ([(99, 5)], "no man"),
])
def test_bad_bids_are_refused(bids, match):
    a = auction(made_up_deck(), 2)
    with pytest.raises(IllegalMove, match=match):
        au.check_bids(a, 0, bids)


def test_a_bid_must_fit_the_formation():
    deck = made_up_deck()
    a = auction(deck, 2)
    a.picks[0].append(deck.by_key["2000-A"].cards[0])        # a keeper
    with pytest.raises(IllegalMove, match="goalkeeper"):
        au.check_bids(a, 0, [(lot(a, 13), 5)])


def test_one_person_once_whatever_the_season():
    deck = made_up_deck()
    a = auction(deck, 2)
    au.settle(a, {0: [(lot(a, 9), 5)], 1: []})
    a.market = [deck.by_key["2001-B"]]
    later = next(k for k, c in enumerate(a.lots) if c.id == "Q9")
    assert a.reason(a.lots[later], 1) == "already bought"
    with pytest.raises(IllegalMove, match="already bought"):
        au.check_bids(a, 1, [(later, 5)])


def test_a_seat_may_pass_only_so_often():
    a = auction(made_up_deck(), 2)
    a.passes[0] = au.PASSES
    with pytest.raises(IllegalMove, match="passed"):
        au.check_bids(a, 0, [])
    a.passes[0] = au.PASSES - 1
    au.check_bids(a, 0, [])


def test_a_full_squad_bids_no_more():
    deck = made_up_deck()
    a = auction(deck, 2)
    a.picks[0] = list(deck.by_key["2000-A"].cards[:11])
    assert a.places_left(0) == 0 and 0 not in a.buying()
    with pytest.raises(IllegalMove, match="full"):
        au.check_bids(a, 0, [(0, 5)])


# -- markets and the replay ---------------------------------------------------------------

def test_every_market_holds_someone_for_every_seat_still_buying():
    deck = load_deck()
    for seed in range(4):
        a = au.replay(deck, seed, ["433", "352", "4231", "541", "442d"], [], bench=True)
        assert len(a.market) >= au.market_size(5)
        assert len({cs.key for cs in a.market}) == len(a.market)
        assert all(a.takeable(s) for s in a.buying())


def test_a_market_draws_on_for_a_seat_nothing_covers():
    """Seat 0 needs only a left winger, and only squad W has one: the market must grow past
    its size until W is in it."""
    import random
    others = [club(f"N{k}", [player(100 + 20 * k + j, (s,), 75) for j, s in enumerate(SLOTS) if s != "LW"])
              for k in range(6)]
    w = club("W", [player(500, ("LW",), 75)])
    deck = build_deck({"club_seasons": [*others, w, made_up_deck_doc()["club_seasons"][0]]})
    grew = 0
    for seed in range(30):
        a = au.Auction(1, [FORMATIONS["433"]] * 2, [[], []], [0, 0], [0, 0])
        a.picks[0] = [c for c in deck.by_key["2000-A"].cards[:11] if c.positions != ("LW",)]
        a.picks[1] = [c for c in deck.by_key["2000-A"].cards if c.positions == ("LW",)]   # A's own winger is gone
        a.taken |= {c.id for c in [*a.picks[0], *a.picks[1]]}
        m = a.market = au._market(random.Random(seed), deck, a)
        assert any(cs.key == "2000-W" for cs in m) and all(a.takeable(s) for s in a.buying())
        grew += len(m) > au.market_size(2)
    assert grew, "the guarantee never had to act"


def test_a_market_nobody_can_serve_is_stranded():
    deck = made_up_deck()
    a = au.Auction(1, [FORMATIONS["433"]] * 2, [[], []], [0, 0], [0, 0])
    a.picks[0] = list(deck.by_key["2000-A"].cards[:10])     # seat 0 needs only a left winger
    a.taken |= {c.id for c in a.picks[0]}
    a.picks[1] = [deck.by_key["2001-B"].cards[10]]           # seat 1 holds Q10 (2001)
    a.taken.add("Q10")
    with pytest.raises(Stranded):
        au._market(__import__("random").Random(0), deck, a)  # nobody else plays LW: no market can serve 0


def test_the_replay_is_pure_and_the_rounds_round_trip():
    deck = load_deck()
    a = au.replay(deck, 5, ["433", "442"], [], bench=False)
    r1 = {0: [(a.takeable(0)[0], 30)], 1: [(a.takeable(1)[0], 12), (a.takeable(1)[-1], 3)]}
    b = au.replay(deck, 5, ["433", "442"], [r1])
    c = au.replay(deck, 5, ["433", "442"], au.decode_rounds(au.encode_rounds([r1])))
    assert [[x.key + x.id for x in p] for p in b.picks] == [[x.key + x.id for x in p] for p in c.picks]
    assert b.spent == c.spent and [m.key for m in b.market] == [m.key for m in c.market]
    assert sum(s.price for s in b.sales) == sum(b.spent)


def test_the_replay_refuses_an_illegal_round():
    deck = load_deck()
    a = au.replay(deck, 5, ["433", "442"], [])
    with pytest.raises(IllegalMove):
        au.replay(deck, 5, ["433", "442"], [{0: [(a.takeable(0)[0], au.BUDGET)]}])


@pytest.mark.parametrize("bad", ["0:", "x:1.2", "0:1.2;0:3.4", "0:1-2", "0:1.99999"])
def test_malformed_rounds_are_refused(bad):
    with pytest.raises(IllegalMove):
        au.decode_rounds(bad)


def test_an_auction_ends_with_every_squad_full_and_within_budget():
    deck = load_deck()
    rounds = []
    a = au.replay(deck, 3, ["433", "352", "4231"], rounds, bench=True)
    while not a.complete:
        rounds.append({s: [(a.takeable(s)[0], 1)] for s in a.buying()})
        a = au.replay(deck, 3, ["433", "352", "4231"], rounds, bench=True)
    assert all(len(p) == 14 for p in a.picks) and all(x <= au.BUDGET for x in a.spent)
    assert len({c.id for p in a.picks for c in p}) == 42
    with pytest.raises(IllegalMove, match="over"):
        au.replay(deck, 3, ["433", "352", "4231"], rounds + [{}], bench=True)


def test_a_market_never_holds_one_squad_twice():
    # Two squads in the deck and a market of two: without the rule, a draw repeats often.
    import random
    deck = made_up_deck()
    for seed in range(20):
        a = au.Auction(seed, [FORMATIONS["433"]] * 2, [[], []], [0, 0], [0, 0])
        m = au._market(random.Random(seed), deck, a)
        assert len({cs.key for cs in m}) == len(m) == 2


# -- the recap (C72) -----------------------------------------------------------------------

def test_the_recap_lists_each_seats_buys_dearest_first_and_the_rooms_biggest_and_bargains():
    deck = made_up_deck()
    a = auction(deck, 2)
    cards = {c.id: c for c in deck.by_key["2000-A"].cards}
    a.sales = [au.Sale(1, 0, cards["Q9"], 40, 40, ()), au.Sale(1, 1, cards["Q8"], 3, 3, ()),
               au.Sale(2, 0, cards["Q7"], 5, 9, ((1, 4),)), au.Sale(2, 1, cards["Q10"], 6, 6, ()),
               au.Sale(3, 0, cards["Q6"], 1, 1, ()), au.Sale(3, 1, cards["Q5"], 2, 2, ())]
    r = au.recap(a)
    assert [s.card.id for s in r.buys[0]] == ["Q9", "Q7", "Q6"]          # 40, 5, 1
    assert [s.price for s in r.biggest] == [40, 6, 5]
    # Bargains: 5 or less, best-rated first (Q8 88 at 3, Q7 87 at 5, Q6 86 at 1); Q10 (90) cost 6.
    assert [s.card.id for s in r.bargains] == ["Q8", "Q7", "Q6"]
    assert all(s.price <= au.BARGAIN for s in r.bargains)


# -- the first price (C75) -----------------------------------------------------------------

def test_a_first_price_winner_pays_what_he_bid_contested_or_not():
    deck = made_up_deck()
    a = auction(deck, 3)
    a.first_price = True
    x, y = lot(a, 9), lot(a, 8)
    sales = au.settle(a, {0: [(x, 40)], 1: [(x, 30), (y, 12)], 2: []})
    assert {(s.seat, s.card.id, s.price) for s in sales} == {(0, "Q9", 40), (1, "Q8", 12)}
    assert a.spent == [40, 12, 0]


def test_the_replay_keeps_the_rule_it_is_given():
    deck = load_deck()
    a = au.replay(deck, 5, ["433", "442"], [])
    lot0 = next(i for i in a.takeable(0) if i in a.takeable(1))
    rounds = [{0: [(lot0, 30)], 1: [(lot0, 20)]}]
    second = au.replay(deck, 5, ["433", "442"], rounds)
    first = au.replay(deck, 5, ["433", "442"], rounds, first_price=True)
    assert second.spent[0] == 21 and first.spent[0] == 30
