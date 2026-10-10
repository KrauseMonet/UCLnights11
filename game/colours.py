"""A club's three working colours, derived from the two in data/clubs.csv.

* ``team``: the club's primary colour, unless that is near-white or near-black,
  when the secondary takes over -- so Real Madrid's is its blue, not its white,
  and Manchester United's stays red rather than the brighter yellow trim;
* ``deep``: that hue darkened to a background a card can sit on;
* ``ink``: that hue lifted until it reads on ``deep`` at WCAG AA (4.5:1).

Derived rather than hand-picked, so a club added to clubs.csv needs no design work.
"""

from __future__ import annotations

import colorsys


def _rgb(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in rgb)


def luminance(hex_: str) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _strength(hex_: str) -> float:
    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_))
    return s * (1 - abs(2 * l - 1))     # chroma: zero for white, black and greys


def palette(primary: str, secondary: str) -> dict[str, str]:
    team = primary if _strength(primary) >= 0.25 else max((primary, secondary), key=_strength)
    if _strength(team) < 0.08:          # a black-and-white club (Juventus, Rosenborg)
        team = "#9aa3b5"
    h, l, s = colorsys.rgb_to_hls(*_rgb(team))
    deep = _hex(colorsys.hls_to_rgb(h, 0.17, min(s, 0.75)))
    ink_l = max(l, 0.55)
    while contrast(_hex(colorsys.hls_to_rgb(h, ink_l, s)), deep) < 4.5 and ink_l < 0.97:
        ink_l += 0.02
    return {"team": team, "deep": deep, "ink": _hex(colorsys.hls_to_rgb(h, ink_l, s))}
