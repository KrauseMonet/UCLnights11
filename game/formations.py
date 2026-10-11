"""The formations a drafter can pick, as eleven slots, each a position (C35, C37).

A player fills a slot whose position he holds (game.positions). Each formation's slots
are Transfermarkt's commonest starting line-up under that shape, measured over its
line-ups from 2013-14 to 2025-26 (share of that shape's line-ups, and how many there were):

    4-3-3            GK RB CB CB LB DM CM CM RW ST LW   71% of 24,979 ("4-3-3 Attacking")
    4-4-2            GK RB CB CB LB RM CM CM LM ST ST   34% of 7,382
    4-4-2 wingers    GK RB CB CB LB DM CM RW LW ST ST   19% of 13,767 ("4-4-2 double 6")
    4-4-2 diamond    GK RB CB CB LB DM RM LM AM ST ST   62% of 1,730
    4-2-3-1          GK RB CB CB LB DM CM RW AM LW ST   30% of 51,039
    4-3-1-2          GK RB CB CB LB DM CM CM AM ST ST   69% of 2,954
    4-5-1            GK RB CB CB LB RM DM DM AM LM ST   20% of 732
    3-5-2            GK CB CB CB RM DM CM CM LM ST ST   48% of 6,642 ("3-5-2 flat")
    3-4-3            GK CB CB CB RM CM CM LM RW ST LW   43% of 6,395
    3-4-1-2          GK CB CB CB RM DM CM LM AM ST ST   34% of 3,492
    3-4-2-1          GK CB CB CB RM DM DM LM AM AM ST   43% of 7,415
    3-1-4-2          GK CB CB CB RM DM AM AM LM ST ST   76% of 836 ("3-1-4-2"; 84% of "3-5-2 Attacking")
    5-3-2            GK RB CB CB CB LB DM DM AM ST ST   40% of 3,319
    5-4-1            GK RB CB CB CB LB CM CM RW LW ST   26% of 3,128

Wing-backs in a back three are LM/RM there, and in a back five RB/LB, as Transfermarkt
records them. A shape whose commonest slots repeat another's is left out: 4-1-4-1 is the
4-3-3's, "4-3-3 Defending" the 4-2-3-1's, 4-4-1-1 the 4-4-2's (a second striker is a
striker), 4-1-3-2 the 4-4-2 diamond's; the assert below keeps it so.
The diamond and the 3-4-1-2 came with positions (C35): Ancelotti's Milan, the Porto and
PSV diamonds and Dortmund 1997-98 field none of the first five. The rest came with the
setup page (C37), at the user's request for more formations.
"""

from __future__ import annotations

from dataclasses import dataclass

from game.positions import LINE, POSITIONS


@dataclass(frozen=True)
class Formation:
    code: str
    label: str
    slots: tuple[str, ...]   # positions, goalkeeper first, back to front
    about: str = ""          # one line for the setup page

    @property
    def lines(self) -> dict[str, int]:
        """How many slots in each line (GK / DF / MF / FW)."""
        return {ln: sum(1 for s in self.slots if LINE[s] == ln) for ln in ("GK", "DF", "MF", "FW")}


FORMATIONS = {
    f.code: f
    for f in (
        Formation("433", "4-3-3", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"),
                  "A holding midfielder with two in front of him, and wingers either side of a striker."),
        Formation("442", "4-4-2", ("GK", "RB", "CB", "CB", "LB", "RM", "CM", "CM", "LM", "ST", "ST"),
                  "Two banks of four: wide midfielders, two in the centre, two strikers."),
        Formation("4231", "4-2-3-1", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "RW", "AM", "LW", "ST"),
                  "A double pivot, then a 10 and two wingers behind one striker."),
        Formation("4312", "4-3-1-2", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "AM", "ST", "ST"),
                  "The narrow diamond: a holder, two shuttlers, a 10 and two strikers. Width comes from the full-backs."),
        Formation("352", "3-5-2", ("GK", "CB", "CB", "CB", "RM", "DM", "CM", "CM", "LM", "ST", "ST"),
                  "Three centre-backs, wing-backs, a holder with two beside him, two strikers."),
        Formation("343", "3-4-3", ("GK", "CB", "CB", "CB", "RM", "CM", "CM", "LM", "RW", "ST", "LW"),
                  "Three at the back, wing-backs and two central midfielders, a front three."),
        Formation("3412", "3-4-1-2", ("GK", "CB", "CB", "CB", "RM", "DM", "CM", "LM", "AM", "ST", "ST"),
                  "Three at the back, wing-backs and a double pivot, a 10 behind two strikers."),
        Formation("442w", "4-4-2 wingers", ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "RW", "LW", "ST", "ST"),
                  "A holder beside a central midfielder, wingers high up, two strikers."),
        Formation("442d", "4-4-2 diamond", ("GK", "RB", "CB", "CB", "LB", "DM", "RM", "LM", "AM", "ST", "ST"),
                  "A diamond with width: a holder, wide midfielders and a 10, two strikers."),
        Formation("451", "4-5-1", ("GK", "RB", "CB", "CB", "LB", "RM", "DM", "DM", "AM", "LM", "ST"),
                  "Two holders, wide midfielders and a 10 behind a lone striker."),
        Formation("3421", "3-4-2-1", ("GK", "CB", "CB", "CB", "RM", "DM", "DM", "LM", "AM", "AM", "ST"),
                  "Three at the back, wing-backs and two holders, two 10s behind a striker."),
        Formation("3142", "3-1-4-2", ("GK", "CB", "CB", "CB", "RM", "DM", "AM", "AM", "LM", "ST", "ST"),
                  "Three at the back and one holder, wing-backs and two 10s, two strikers."),
        Formation("532", "5-3-2", ("GK", "RB", "CB", "CB", "CB", "LB", "DM", "DM", "AM", "ST", "ST"),
                  "Five at the back with attacking full-backs, two holders and a 10, two strikers."),
        Formation("541", "5-4-1", ("GK", "RB", "CB", "CB", "CB", "LB", "CM", "CM", "RW", "LW", "ST"),
                  "Five at the back, two central midfielders, wingers and a lone striker."),
    )
}
DEFAULT = "433"

assert all(len(f.slots) == 11 and f.slots[0] == "GK" and f.slots.count("GK") == 1
           and set(f.slots) <= set(POSITIONS) and f.about for f in FORMATIONS.values())
# No two formations share a slot set: one would add a name and nothing to play.
assert len({tuple(sorted(f.slots)) for f in FORMATIONS.values()}) == len(FORMATIONS)
