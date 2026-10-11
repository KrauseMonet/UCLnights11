"""Build every served brand image from the one logo the user supplied.

``assets/brand/logo-source.webp`` is the logo on a flat dark navy. The background is
removed by colour-to-alpha against that navy rather than a hard threshold, so the
blue glow round the emblem fades to transparent instead of ending in a dark halo:
each pixel is treated as ``colour = a * ink + (1 - a) * navy`` and solved for the
smallest ``a`` that keeps ``ink`` in range.

Outputs in web/static/brand/: the full logo for the nav, the emblem alone, the
favicons and app icons, and the 1200x630 image link previews show.

Run: ``uv run python -m tools.build_brand`` (needs Pillow). ``--check`` exits 1 if a
served file is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "brand" / "logo-source.webp"
OUT = ROOT / "web" / "static" / "brand"
BG = (7, 8, 15)             # the site's --bg, behind icons and the preview image
FILES = ["logo.webp", "emblem.webp", "favicon-32.png", "apple-touch-icon.png",
         "icon-192.png", "icon-512.png", "og-image.png"]


def unblend(im):
    """Colour-to-alpha against the logo's own background navy."""
    import numpy as np
    from PIL import Image

    rgb = np.asarray(im.convert("RGB")).astype(float)
    h, w, _ = rgb.shape
    corners = np.concatenate([rgb[:20, :20].reshape(-1, 3), rgb[-20:, -20:].reshape(-1, 3),
                              rgb[:20, -20:].reshape(-1, 3), rgb[-20:, :20].reshape(-1, 3)])
    bg = corners.mean(axis=0)
    # The alpha each channel needs: how far the pixel sits from the background,
    # as a share of the room it has to move in that direction.
    # A floor on the room: the navy's red channel is ~1, so without one a pixel a single
    # step darker reads as fully opaque and the whole backdrop survives.
    room = np.maximum(np.where(rgb >= bg, 255 - bg, bg), 64)
    alpha = np.clip((np.abs(rgb - bg) / room).max(axis=2), 0, 1)
    alpha = np.clip((alpha - 0.06) / 0.94, 0, 1)              # the backdrop's own grain and vignette
    safe = np.maximum(alpha, 1e-6)[..., None]
    ink = np.clip((rgb - (1 - alpha[..., None]) * bg) / safe, 0, 255)
    out = np.dstack([ink, alpha * 255]).astype("uint8")
    return Image.fromarray(out, "RGBA")


def tight(im, pad=8):
    box = im.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
    l, t, r, b = box
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def emblem_of(logo):
    """The emblem is everything left of the first clear vertical gap before the word."""
    import numpy as np

    a = np.asarray(logo.getchannel("A")) > 20
    cols = a.any(axis=0)
    x, run = 0, 0
    # Walk right from the emblem's first column until a gap of empty columns.
    start = int(np.argmax(cols))
    for x in range(start, len(cols)):
        run = run + 1 if not cols[x] else 0
        if run >= 12:
            break
    return tight(logo.crop((0, 0, x - run, logo.height)))


def on_square(img, size, fill=0.78, radius=None):
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (size, size), BG + (255,))
    if radius:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
        canvas.putalpha(mask)
    e = img.copy()
    e.thumbnail((int(size * fill), int(size * fill)), Image.LANCZOS)
    canvas.alpha_composite(e, ((size - e.width) // 2, (size - e.height) // 2))
    return canvas


def preview_backdrop(w, h):
    """The site's look behind the preview logo: a cold glow from above, the centre circle
    and the halfway line, as on the home page."""
    import numpy as np
    from PIL import Image, ImageDraw

    y, x = np.mgrid[0:h, 0:w].astype(float)
    glow = np.exp(-(((x - w / 2) / (w * 0.55)) ** 2 + ((y + h * 0.15) / (h * 0.7)) ** 2))
    bg = np.array(BG, float)
    ice = np.array((70, 120, 255), float)
    rgb = bg + (ice - bg) * (glow * 0.16)[..., None]
    im = Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"), "RGB").convert("RGBA")
    lines = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lines)
    r = int(h * 0.42)
    d.ellipse((w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r), outline=(196, 229, 255, 30), width=3)
    d.line((0, h // 2, w, h // 2), fill=(196, 229, 255, 22), width=3)
    im.alpha_composite(lines)
    return im


def build() -> None:
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    logo = tight(unblend(Image.open(SRC)))
    nav = logo.copy()
    nav.thumbnail((10_000, 96), Image.LANCZOS)                 # 48 px tall on a 2x screen
    nav.save(OUT / "logo.webp", "WEBP", quality=90, method=6)
    emblem = emblem_of(logo)
    em = emblem.copy()
    em.thumbnail((256, 256), Image.LANCZOS)
    em.save(OUT / "emblem.webp", "WEBP", quality=90, method=6)
    on_square(emblem, 32, fill=0.9).save(OUT / "favicon-32.png")
    on_square(emblem, 180).save(OUT / "apple-touch-icon.png")
    on_square(emblem, 192, radius=40).save(OUT / "icon-192.png")
    on_square(emblem, 512, radius=108).save(OUT / "icon-512.png")
    og = preview_backdrop(1200, 630)
    big = logo.copy()
    big.thumbnail((1000, 400), Image.LANCZOS)
    og.alpha_composite(big, ((1200 - big.width) // 2, (630 - big.height) // 2))
    og.convert("RGB").save(OUT / "og-image.png", optimize=True)
    total = sum((OUT / f).stat().st_size for f in FILES)
    print(f"built {len(FILES)} brand files, {total // 1024} kB; logo {nav.size}, emblem {em.size}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        missing = [f for f in FILES if not (OUT / f).exists()]
        if missing:
            print("brand files not built: " + ", ".join(missing), file=sys.stderr)
            sys.exit(1)
        print("brand files are built")
    else:
        build()
