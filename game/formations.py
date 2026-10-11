"""The formations a drafter can pick, as eleven slots, each a position (C35).

A player fills a slot whose position he holds (game.positions). Each formation's slots
are Transfermarkt's commonest starting line-up under that shape, measured over its
line-ups from 2013-14 to 2025-26 (share of line-ups in brackets):

    4-3-3    GK RB CB CB LB DM CM CM RW ST LW   (71% of "4-3-3 Attacking")
    4-4-2    GK RB CB CB LB RM CM CM LM ST ST   (34%)
    4-2-3-1  GK RB CB CB LB DM CM RW AM LW ST   (30%)
    4-3-1-2  GK RB CB CB LB DM CM CM AM ST ST   (69%)
    3-5-2    GK CB CB CB RM DM CM CM LM ST ST   (48% of "3-5-2 flat")
    3-4-3    GK CB CB CB RM CM CM LM RW ST LW   (43%)
    3-4-1-2  GK CB CB CB RM DM CM LM AM ST ST   (34%)

Wing-backs in a back three are LM/RM there, as Transfermarkt records them. The diamond
and the 3-4-1-2 were added when positions made shape matter: Ancelotti's Milan, the
Porto and PSV diamonds and Dortmund 1997-98 cannot field the other five at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from game.positions import LINE, POSITIONS


@dataclass(frozen=True)
class Formation:
    code: str
    label: str
    slots: tuple[str, ...]   # positions, goalkeeper first, back to front

    @property
    def lines(self) -> dict[str, int]:
        """How many slots in each line (GK / DF / MF / FW)."""
        return {ln: sum(1 for s in self.slots if LINE[s] == ln) for ln in ("GK", "DF", "MF", "FW")}


FORMATIONS = {
    f.code: f
    for f in (
        Formation("433", "4-3-3", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW")),
        Formation("442", "4-4-2", ("GK", "RB", "CB", "CB", "LB", "RM", "CM", "CM", "LM", "ST", "ST")),
        Formation("4231", "4-2-3-1", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "RW", "AM", "LW", "ST")),
        Formation("4312", "4-3-1-2", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "AM", "ST", "ST")),
        Formation("352", "3-5-2", ("GK", "CB", "CB", "CB", "RM", "DM", "CM", "CM", "LM", "ST", "ST")),
        Formation("343", "3-4-3", ("GK", "CB", "CB", "CB", "RM", "CM", "CM", "LM", "RW", "ST", "LW")),
        Formation("3412", "3-4-1-2", ("GK", "CB", "CB", "CB", "RM", "DM", "CM", "LM", "AM", "ST", "ST")),
    )
}
DEFAULT = "433"

assert all(len(f.slots) == 11 and f.slots[0] == "GK" and f.slots.count("GK") == 1
           and set(f.slots) <= set(POSITIONS) for f in FORMATIONS.values())
