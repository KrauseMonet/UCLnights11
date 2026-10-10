"""The draft on the real deck: replay, legality and the state string."""

import pytest

from game.deck import build_deck, load_deck
from game.draft import (IllegalMove, Pick, Reroll, REROLLS_ALLOWED, decode, encode, replay,
                        why_not)
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
def test_every_formation_completes_with_its_own_line_counts(code):
    s, _ = draft_to_the_end(11, code)
    counts = {p: sum(1 for c in s.picks if c.pos == p) for p in ("GK", "DF", "MF", "FW")}
    assert counts == FORMATIONS[code].lines


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
                gk_now = [i for i, c in enumerate(s2.deal.cards) if c.pos == "GK"]
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


def _tiny_deck():
    """Squad A can fill a whole 4-3-3; squad B is goalkeepers only.

    Once a goalkeeper is picked, B offers nothing takeable, so the deal-time
    guarantee must redraw past it. On the real deck that almost never happens by
    chance, which is why this is built rather than drafted.
    """
    def p(i, pos):
        return {"id": f"Q{i}", "name": f"P{i}", "title": f"P{i}", "pos": pos, "nation": None, "rating": 80}
    a = [p(0, "GK")] + [p(i, "DF") for i in range(1, 5)] + [p(i, "MF") for i in range(5, 8)] \
        + [p(i, "FW") for i in range(8, 11)]
    b = [p(i, "GK") for i in range(20, 25)]
    cs = lambda key, players: {"key": key, "season": 2000, "label": "2000–01", "club": key,
                               "name": key, "short": key, "primary": "#000", "secondary": "#fff",
                               "crest": key, "team": "#000", "deep": "#000", "ink": "#fff",
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
