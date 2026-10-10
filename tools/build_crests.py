"""Shrink the fetched crests (assets/crests) to the served WebP files.

Every crest becomes a 160 px WebP with its transparency kept; 160 covers a
80 px slot on a 2x screen. ``--check`` exits 1 if any served file is missing or
stale, so a fetched crest that was never built cannot ship as a broken image.

Run: ``uv run python -m tools.build_crests`` (needs Pillow, a dev dependency).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "crests"
OUT = ROOT / "web" / "static" / "crests"
SIZE = 160


def render(path: Path) -> bytes:
    from PIL import Image

    im = Image.open(path).convert("RGBA")
    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


def sources() -> dict[str, Path]:
    found = {p.stem: p for p in SRC.glob("*.png")}
    found.update({p.stem: p for p in (SRC / "eras").glob("*.png")})
    return found


def main() -> None:
    check = "--check" in sys.argv
    stale = []
    OUT.mkdir(parents=True, exist_ok=True)
    for key, path in sorted(sources().items()):
        dest = OUT / f"{key}.webp"
        if check:
            if not dest.exists():
                stale.append(key)
            continue
        dest.write_bytes(render(path))
    if check:
        if stale:
            print("crests not built: " + ", ".join(stale), file=sys.stderr)
            sys.exit(1)
        print("crests are built")
        return
    total = sum(p.stat().st_size for p in OUT.glob("*.webp"))
    print(f"built {len(list(OUT.glob('*.webp')))} crests, {total // 1024} kB")


if __name__ == "__main__":
    main()
