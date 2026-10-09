"""Colours, fonts and text helpers shared by every screen."""

from __future__ import annotations

from functools import lru_cache

import pygame

BG = (22, 22, 28)
PANEL = (34, 34, 44)
ROW = (40, 40, 52)
ROW_DARK = (30, 30, 39)
BAR_LINE = (62, 62, 78)
TEXT = (232, 232, 238)
MUTED = (135, 135, 152)
PLAYER = (80, 200, 170)
BOT = (175, 132, 235)
GHOST = (110, 110, 125)
INVALID = (235, 85, 85)
WARN = (245, 165, 60)
GOLD = (240, 200, 80)
WHITE_KEY = (225, 225, 232)
BLACK_KEY = (44, 44, 52)


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("helveticaneue,arial", size, bold=bold)


def text(
    surface: pygame.Surface,
    content: str,
    pos: tuple[float, float],
    size: int = 18,
    color=TEXT,
    bold: bool = False,
    anchor: str = "topleft",
) -> pygame.Rect:
    image = font(size, bold).render(content, True, color)
    rect = image.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
    surface.blit(image, rect)
    return rect
