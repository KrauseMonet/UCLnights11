"""The completed draft's ratings by line (game.squad_ratings). Pure: no database."""

from dataclasses import replace

import pytest

from game.deck import load_deck
from game.formations import FORMATIONS
from game.positions import place
from game.squad_ratings import FIGURES, better_than, deck_field, squad_ratings
from game.tournament import best_xi, club_bench

DECK = load_deck()
BASE = DECK.club_seasons[0].cards[0]


def man(n, positions, rating):
    return replace(BASE, id=f"Q{n}", name=f"Man {n}", positions=positions, rating=rating)


def test_each_line_is_the_mean_of_the_men_standing_in_it():
    _, xi = best_xi(DECK.by_key[DECK.club_seasons[40].key])
    r = squad_ratings(xi)
    mean = lambda cs: sum(c.rating for c in cs) / len(cs)  # noqa: E731
    assert r.overall == mean(xi)
    for line, got in (("GK", r.goalkeeper), ("DF", r.defence), ("MF", r.midfield), ("FW", r.attack)):
        assert got == mean([c for c in xi if c.pos == line])
    assert r.bench is None


def test_a_man_counts_in_the_line_of_his_slot_not_his_natural_one():
    # A holding midfielder (DM first) placed at centre-back defends: Kimmich at right-back.
    slots = FORMATIONS["433"].slots
    xi = [place(man(j, (s,), 80), s) for j, s in enumerate(slots)]
    cb = slots.index("CB")
    xi[cb] = place(man(99, ("DM", "CB"), 99), "CB")
    r = squad_ratings(xi)
    defenders = [c.rating for c in xi if c.slot in ("RB", "CB", "LB")]
    assert r.defence == sum(defenders) / len(defenders) > 80
    assert r.midfield == 80


def test_an_unplaced_or_short_eleven_is_refused():
    cs = DECK.club_seasons[0]
    with pytest.raises(ValueError):
        squad_ratings(cs.cards[:11])                  # cards straight from a squad: no slots
    with pytest.raises(ValueError):
        squad_ratings(best_xi(cs)[1][:10])


def test_better_than_counts_only_what_a_figure_is_strictly_above():
    field = [80.0, 85.0, 85.0, 90.0]
    assert [better_than(v, field) for v in (70, 80, 85, 90, 91)] == [0, 0, 25, 75, 100]
    assert better_than(None, field) is None


def test_the_field_is_every_club_season_at_its_best_with_its_bench():
    f = deck_field(DECK)
    n = len(DECK.club_seasons)
    assert set(f) == set(FIGURES) and all(len(f[k]) == n for k in FIGURES)
    some = DECK.club_seasons[7]
    r = squad_ratings(best_xi(some)[1], club_bench(some))
    assert r.overall in f["overall"] and r.bench in f["bench"]
    assert f["overall"] == sorted(f["overall"])
