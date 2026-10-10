"""The formations a drafter can pick, as counts per line.

A player fills a slot in his own line only (a defender plays in defence). The
order of slots within a line is presentation; the engine reads the counts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Formation:
    code: str
    label: str
    lines: dict[str, int]   # GK / DF / MF / FW -> how many

    def slots(self) -> list[str]:
        return [pos for pos in ("GK", "DF", "MF", "FW") for _ in range(self.lines[pos])]


FORMATIONS = {
    f.code: f
    for f in (
        Formation("433", "4-3-3", {"GK": 1, "DF": 4, "MF": 3, "FW": 3}),
        Formation("442", "4-4-2", {"GK": 1, "DF": 4, "MF": 4, "FW": 2}),
        Formation("4231", "4-2-3-1", {"GK": 1, "DF": 4, "MF": 5, "FW": 1}),
        Formation("352", "3-5-2", {"GK": 1, "DF": 3, "MF": 5, "FW": 2}),
        Formation("343", "3-4-3", {"GK": 1, "DF": 3, "MF": 4, "FW": 3}),
    )
}
DEFAULT = "433"

assert all(sum(f.lines.values()) == 11 for f in FORMATIONS.values())
