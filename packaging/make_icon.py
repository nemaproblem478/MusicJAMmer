"""Draws the app icon (a little piano roll): packaging/icon.png everywhere, plus
packaging/icon.icns on macOS (via iconutil). On Windows PyInstaller turns the PNG
into the .exe icon itself (it needs Pillow for that)."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame  # noqa: E402

HERE = Path(__file__).parent
BG, PLAYER, BOT, GOLD, ROW = (24, 24, 31), (80, 200, 170), (175, 132, 235), (240, 200, 80), (40, 40, 52)


def draw(size: int = 1024) -> pygame.Surface:
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    pad = size * 0.09  # macOS icons leave a margin around the rounded square
    body = pygame.Rect(pad, pad, size - 2 * pad, size - 2 * pad)
    pygame.draw.rect(s, BG, body, border_radius=int(size * 0.18))
    inner = body.inflate(-size * 0.16, -size * 0.2)
    rows = 9
    row_h = inner.h / rows
    for r in range(rows):
        if r % 2:
            pygame.draw.rect(s, ROW, (inner.x, inner.y + r * row_h, inner.w, row_h))
    half = inner.w / 2
    bar_h = row_h * 0.72

    def chord(x0, rows_used, color):
        for k, r in enumerate(rows_used):
            left = x0 + size * 0.02 + k * size * 0.018
            y = inner.bottom - (r + 1) * row_h + (row_h - bar_h) / 2
            pygame.draw.rect(s, color, (left, y, x0 + half - size * 0.03 - left, bar_h), border_radius=int(bar_h / 2))

    chord(inner.x, (0, 2, 4, 7), BOT)
    chord(inner.x + half, (1, 3, 5, 8), PLAYER)
    pygame.draw.line(s, GOLD, (inner.centerx, inner.y - size * 0.03), (inner.centerx, inner.bottom + size * 0.03),
                     max(3, int(size * 0.014)))
    return s


def main() -> None:
    pygame.display.init()
    icon = draw()
    pygame.image.save(icon, str(HERE / "icon.png"))
    print("wrote", HERE / "icon.png")
    if sys.platform != "darwin":
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 64, 128, 256, 512, 1024):
            image = pygame.transform.smoothscale(icon, (px, px))
            if px <= 512:
                pygame.image.save(image, str(iconset / f"icon_{px}x{px}.png"))
            if px >= 32:
                pygame.image.save(image, str(iconset / f"icon_{px // 2}x{px // 2}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
    print("wrote", HERE / "icon.icns")


if __name__ == "__main__":
    main()
