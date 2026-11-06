"""Generate the application icon (PNG, ICO, ICNS) with Pillow.

A dark rounded square with two overlapping peaks in the accent colour - the same
palette as the application.  Run from the repository root:

    python packaging/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
BG = (26, 26, 25, 255)
BORDER = (56, 56, 53, 255)
ACCENT = (57, 135, 229, 255)
ACCENT_FILL = (57, 135, 229, 110)
SECOND = (217, 89, 38, 255)
SECOND_FILL = (217, 89, 38, 100)
INK = (240, 239, 236, 255)


def voigt_like(x: float, c: float, w: float) -> float:
    g = math.exp(-0.5 * ((x - c) / (0.5 * w)) ** 2)
    lor = 1.0 / (1.0 + ((x - c) / (0.6 * w)) ** 2)
    return 0.7 * g + 0.3 * lor


def render(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size * 0.22
    d.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=r, fill=BG, outline=BORDER, width=max(2, size // 128)
    )
    left, right = size * 0.12, size * 0.88
    base = size * 0.80
    top = size * 0.20
    n = 400

    def curve(c: float, w: float, amp: float) -> list[tuple[float, float]]:
        pts = []
        for i in range(n + 1):
            t = i / n
            x = left + (right - left) * t
            y = base - (base - top) * amp * voigt_like(t, c, w)
            pts.append((x, y))
        return pts

    main = curve(0.62, 0.16, 1.0)
    second = curve(0.38, 0.22, 0.42)
    for pts, fill, line in ((second, SECOND_FILL, SECOND), (main, ACCENT_FILL, ACCENT)):
        poly = [(left, base)] + pts + [(right, base)]
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(poly, fill=fill)
        img.alpha_composite(layer)
        d.line(pts, fill=line, width=max(3, size // 40), joint="curve")
    env = []
    for i in range(n + 1):
        t = i / n
        y = base - (base - top) * (
            1.0 * voigt_like(t, 0.62, 0.16) + 0.42 * voigt_like(t, 0.38, 0.22)
        )
        env.append((left + (right - left) * t, y))
    d.line(env, fill=INK, width=max(3, size // 48), joint="curve")
    d.line([(left, base), (right, base)], fill=BORDER, width=max(2, size // 100))
    return img


def main() -> None:
    img = render()
    img.save(HERE / "icon.png")
    img.resize((256, 256), Image.LANCZOS).save(HERE / "icon_256.png")
    img.save(
        HERE / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    img.save(HERE / "icon.icns")
    for name in ("icon.png", "icon_256.png", "icon.ico", "icon.icns"):
        print(name, (HERE / name).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
