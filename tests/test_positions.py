"""Positions (C35): who can stand where, and where an eleven's men actually stand."""

from dataclasses import replace

from game import match
from game.deck import load_deck
from game.formations import FORMATIONS
from game.positions import LINE, MAX_POSITIONS, POSITIONS, arrange, best_eleven, fits
from game.tournament import Side, best_xi
from tests.test_match import card


def man(i, *positions, rating=80):
    return replace(card("MF", rating, i), id=f"M{i}", positions=tuple(positions), pos=LINE[positions[0]])


F433 = FORMATIONS["433"].slots


def test_a_pick_fits_while_some_assignment_exists_whatever_the_order():
    # Kimmich first (RB, DM), then a pure right-back: the matching moves Kimmich to DM.
    assert fits(F433, [man(0, "RB", "DM"), man(1, "RB")])
    # A third man for those two places: there is no room, whichever comes first.
    assert not fits(F433, [man(0, "RB", "DM"), man(1, "RB"), man(2, "DM")])
    # One goalkeeper slot.
    assert not fits(F433, [man(0, "GK"), man(1, "GK")])


def test_each_man_stands_where_he_played_most_when_he_can():
    # Both could play either place; each gets his own first position.
    a, b = man(0, "CM", "DM"), man(1, "DM", "CM")
    placed = {c.id: c.slot for c in arrange(F433, [a, b])}
    assert placed == {"M0": "CM", "M1": "DM"}


def test_the_best_eleven_is_the_highest_rated_one_that_fits():
    squad = [man(i, s, rating=80) for i, s in enumerate(F433)]
    star = man(50, "ST", "RW", rating=95)          # better than the striker, plays RW too
    total, xi = best_eleven(F433, squad + [star])
    # He replaces the weaker of the two men whose places he can take, not nobody.
    assert total == 80 * 10 + 95
    assert any(c is star for c, _ in xi)
    assert best_eleven(F433, squad[:-1]) is None   # ten men cannot fill eleven places


def test_a_placed_man_carries_his_slot_s_line_into_the_engine():
    # A midfielder drafted at right-back defends as a defender: defence weights by line.
    xi = [man(i, s) for i, s in enumerate(F433)]
    side = Side("A", "A", "A", FORMATIONS["433"], xi)
    assert [c.slot for c in side.xi] == list(F433)
    assert [c.pos for c in side.xi] == [LINE[s] for s in F433]
    kimmich = replace(man(1, "DM", "RB"), rating=95)          # natural line MF, most-played DM
    others = [man(i, s) for i, s in enumerate(F433) if s not in ("RB", "DM")] + [man(30, "DM")]
    placed = Side("B", "B", "B", FORMATIONS["433"], [kimmich, *others]).xi
    at = next(c for c in placed if c.id == kimmich.id)
    assert at.slot == "RB" and at.pos == "DF"
    # ...so he weighs in defence as a defender (1.0), not as a midfielder (0.45).
    assert match.defence(placed) > match.defence([*others, replace(kimmich, pos="MF")])


def test_every_card_holds_one_to_four_known_positions_and_its_line_is_its_first():
    for cs in load_deck().club_seasons:
        for c in cs.cards:
            assert 1 <= len(c.positions) <= MAX_POSITIONS
            assert set(c.positions) <= set(POSITIONS) and len(set(c.positions)) == len(c.positions)
            assert c.pos == LINE[c.positions[0]]
            assert c.source in ("measured", "declared")


def test_every_squad_s_stored_eleven_is_its_best():
    """The eleven etl.deck stored is still the best one the squad can field."""
    for cs in load_deck().club_seasons:
        f, xi = best_xi(cs)
        found = max((best_eleven(g.slots, cs.cards) for g in FORMATIONS.values()),
                    key=lambda r: -1 if r is None else r[0])
        assert sum(c.rating for c in xi) == found[0]


def test_measured_seasons_are_measured_and_earlier_ones_declared():
    deck = load_deck()
    sources = {(cs.season >= 2013, c.source) for cs in deck.club_seasons for c in cs.cards}
    assert (False, "measured") not in sources
    # A measured season declares only the handful with no starts for the club.
    declared_late = [c for cs in deck.club_seasons if cs.season >= 2013 for c in cs.cards if c.source == "declared"]
    assert 0 < len(declared_late) <= 5
