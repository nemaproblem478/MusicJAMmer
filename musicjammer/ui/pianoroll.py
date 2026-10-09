"""The piano roll: two bar-wide slots, the latest chord on the left, the next one on the right.

Slot i is bar i of the round; slot -1 holds the silent tonic the round starts
from. The camera is the slot index shown on the left. It glides towards the
session's camera target, so a newly played chord first appears on the right
and then slides over to the left.
"""

from __future__ import annotations

import math

import pygame

from ..game import Side
from ..session import Block, JamSession
from ..theory import Chord
from . import theme

LOWEST_NOTE, HIGHEST_NOTE = 46, 76  # every voicing (roots C3..B3 plus up to a ninth) fits
KEYBOARD_WIDTH = 46
BLACK_PCS = {1, 3, 6, 8, 10}
STRUM_OFFSET = 12  # px each higher note starts later, echoing the arpeggio
BASE_NOTE = 48


class PianoRoll:
    def __init__(self) -> None:
        self.camera = -1.0

    def update(self, target: float, dt: float) -> None:
        self.camera += (target - self.camera) * min(1.0, dt * 6.0)
        if abs(target - self.camera) < 0.001:
            self.camera = target

    def draw(self, surface: pygame.Surface, rect: pygame.Rect, session: JamSession, joker_held: bool) -> None:
        rows = HIGHEST_NOTE - LOWEST_NOTE + 1
        row_h = rect.h / rows
        roll = pygame.Rect(rect.x + KEYBOARD_WIDTH, rect.y, rect.w - KEYBOARD_WIDTH, rect.h)
        slot_w = roll.w / 2

        def y_of(note: int) -> float:
            return rect.bottom - (note - LOWEST_NOTE + 1) * row_h

        def x_of(slot: int) -> float:
            return roll.x + (slot - self.camera) * slot_w

        self._draw_keyboard(surface, rect, row_h, y_of, session)

        surface.set_clip(roll)
        for note in range(LOWEST_NOTE, HIGHEST_NOTE + 1):
            color = theme.ROW_DARK if note % 12 in BLACK_PCS else theme.ROW
            pygame.draw.rect(surface, color, (roll.x, y_of(note), roll.w, math.ceil(row_h)))
        layer = pygame.Surface(roll.size, pygame.SRCALPHA)
        first, last = math.floor(self.camera) - 1, math.ceil(self.camera) + 2
        for slot in range(first, last + 1):
            x = x_of(slot) - roll.x
            pygame.draw.line(layer, theme.BAR_LINE, (x, 0), (x, roll.h), 2)
            if session.timed:
                for beat in (1, 2, 3):
                    bx = x + beat * slot_w / 4
                    pygame.draw.line(layer, (*theme.BAR_LINE, 110), (bx, 0), (bx, roll.h), 1)
            if 0 <= slot < session.config.bars:
                theme.text(layer, str(slot + 1), (x + 8, 6), 14, theme.MUTED)

        def to_layer(note: int) -> float:
            return y_of(note) - roll.y

        if first <= -1:
            tonic = session.config.key.tonic_chord
            self._draw_chord(layer, x_of(-1) - roll.x, slot_w, to_layer, row_h, tonic, theme.GHOST, 150,
                             label=f"{tonic.name}  start")
        for slot, block in enumerate(session.blocks):
            if first <= slot <= last:
                self._draw_block(layer, x_of(slot) - roll.x, slot_w, to_layer, row_h, block)

        preview = session.preview
        if preview is not None:
            slot = session.preview_slot
            self._draw_preview(layer, x_of(slot) - roll.x, slot_w, to_layer, row_h, session, preview, joker_held)
        if session.timed:  # the playhead: chords are played as their bar reaches this line
            pygame.draw.line(layer, theme.GOLD, (roll.w / 2, 0), (roll.w / 2, roll.h), 3)
        surface.blit(layer, roll.topleft)
        surface.set_clip(None)

    # --- pieces ---

    def _draw_keyboard(self, surface, rect, row_h, y_of, session: JamSession) -> None:
        sounding = session.player_voice.sounding | session.bot_voice.sounding
        for note in range(LOWEST_NOTE, HIGHEST_NOTE + 1):
            black = note % 12 in BLACK_PCS
            width = KEYBOARD_WIDTH * (0.62 if black else 1.0)
            color = theme.BLACK_KEY if black else theme.WHITE_KEY
            if note in session.bot_voice.sounding:
                color = theme.BOT
            if note in session.player_voice.sounding:
                color = theme.PLAYER
            key = pygame.Rect(rect.x, y_of(note), width - 2, math.ceil(row_h) - 1)
            pygame.draw.rect(surface, color, key, border_bottom_right_radius=3, border_top_right_radius=3)
            if note % 12 == 0:
                label_color = theme.BG if note in sounding or not black else theme.TEXT
                theme.text(surface, f"C{note // 12 - 1}", (rect.x + KEYBOARD_WIDTH - 6, key.centery), 12,
                           label_color, anchor="midright")

    def _note_rects(self, x, slot_w, to_layer, row_h, notes: list[int]):
        for k, note in enumerate(notes):
            left = x + 14 + k * STRUM_OFFSET
            yield note, pygame.Rect(left, to_layer(note) + 1, x + slot_w - 14 - left, max(3, row_h - 2))

    def _draw_chord(self, layer, x, slot_w, to_layer, row_h, chord: Chord, color, alpha, label="",
                    outline=None, note_style=None) -> None:
        notes = chord.voicing(BASE_NOTE)
        for note, r in self._note_rects(x, slot_w, to_layer, row_h, notes):
            pygame.draw.rect(layer, (*color, alpha), r, border_radius=4)
            style = note_style(note) if note_style else None
            if style is not None:
                pygame.draw.rect(layer, style, r, 2, border_radius=4)
        top = to_layer(max(notes))
        if outline is not None:
            box = pygame.Rect(x + 6, top - 30, slot_w - 12, to_layer(min(notes)) + row_h - top + 36)
            pygame.draw.rect(layer, outline, box, 2, border_radius=8)
        if label:
            theme.text(layer, label, (x + 16, top - 26), 20, color, bold=True)

    def _draw_block(self, layer, x, slot_w, to_layer, row_h, block: Block) -> None:
        color = theme.PLAYER if block.side is Side.PLAYER else theme.BOT
        who = "YOU" if block.side is Side.PLAYER else "BOT"
        if block.chord is None:
            theme.text(layer, f"{who}: missed", (x + slot_w / 2, layer.get_height() / 2), 22, theme.MUTED,
                       bold=True, anchor="center")
            return
        tags = [who]
        if block.joker:
            tags.append("JOKER")
        if block.cadence:
            tags.append(f"CADENCE +{block.won}")
        label = f"{block.chord.name}   " + " · ".join(tags)
        self._draw_chord(layer, x, slot_w, to_layer, row_h, block.chord, color, 235, label,
                         outline=theme.GOLD if block.cadence else None)

    def _draw_preview(self, layer, x, slot_w, to_layer, row_h, session: JamSession, chord: Chord,
                      joker_held: bool) -> None:
        error = session.preview_error(joker_held)
        cadence = session.preview_is_cadence()
        color = theme.GOLD if cadence else theme.INVALID if error else theme.PLAYER
        previous = session.round.previous_chord.pitch_classes
        danger = session.danger_pitch_classes

        def note_style(note: int):
            if note % 12 in danger:
                return theme.WARN
            if note % 12 in previous:
                return theme.TEXT  # shared with the chord before
            return None

        label = chord.name + ("  joker" if joker_held and not cadence else "")
        self._draw_chord(layer, x, slot_w, to_layer, row_h, chord, color, 105, label, note_style=note_style)
