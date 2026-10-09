"""The sound page: wave, ADSR, EQ and volume for the player's and the bot's synth.

Controls are built from the engine's parameter list, so another backend gets
its own page for free. You can play chords with the usual keys while tweaking.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pygame

from ..audio import BOT_CHANNEL, PLAYER_CHANNEL, ChordPerformer, NoteEngine, Param
from ..controls import ChordInput, ExtensionKey, RootKey, TypeKey, build_keymap
from ..controls.keymap import SC_ESCAPE, SC_RETURN, SC_TAB
from ..audio.eq import response_db
from ..settings import SettingsStore
from . import theme
from .knobs import format_value, from_norm, nudge, to_norm

SC_RIGHT, SC_LEFT, SC_DOWN, SC_UP, SC_L = 79, 80, 81, 82, 15
KNOB_RADIUS = 40
KNOB_SPACING = 140
GROUP_TITLES = {"envelope": "ENVELOPE", "eq": "EQ & LEVEL"}
DRAG_PIXELS = 220  # dragging this far up turns a knob from 0 to 1
SWEEP = 270  # degrees a knob turns through


class SynthScreen:
    def __init__(self, store: SettingsStore, engine: NoteEngine, width: int, height: int, back) -> None:
        self.store = store
        self.engine = engine
        self.width, self.height = width, height
        self.back = back  # () -> the screen to return to
        self.params: list[Param] = engine.params()
        self.channel = PLAYER_CHANNEL
        self.selected = 0
        self.input = ChordInput()
        self.keymap = build_keymap()
        self.voice = ChordPerformer(engine, self.channel)
        self.message = ""
        self._dragging: tuple[int, int, float] | None = None  # (param index, start y, start norm)
        self._hit: list[tuple[pygame.Rect, int, object]] = []  # (area, param index, choice or None)

    # --- editing ---

    def _value(self, param: Param):
        return self.engine.get_param(self.channel, param.id)

    def _set(self, index: int, value) -> None:
        param = self.params[index]
        if self.channel == BOT_CHANNEL and self.store.bot_linked:
            self.store.bot_linked = False
            self.message = "The bot now has its own sound (L links it back to yours)"
        self.engine.set_param(self.channel, param.id, value)
        if self.channel == PLAYER_CHANNEL:
            self.store.sync_bot()

    def _switch_channel(self) -> None:
        self.voice.stop()
        self.input.release_all()
        self.channel = BOT_CHANNEL if self.channel == PLAYER_CHANNEL else PLAYER_CHANNEL
        self.voice = ChordPerformer(self.engine, self.channel)
        self.message = ""

    def _toggle_link(self) -> None:
        self.store.bot_linked = not self.store.bot_linked
        self.store.sync_bot()
        self.message = "The bot plays with your sound" if self.store.bot_linked else "The bot has its own sound"

    # --- events ---

    def handle(self, event, engine: NoteEngine):
        now = time.monotonic()
        if event.type == pygame.KEYDOWN:
            sc = event.scancode
            fine = bool(event.mod & pygame.KMOD_SHIFT)
            if sc in (SC_ESCAPE, SC_RETURN):
                self.close()
                self.store.save()
                return self.back()
            if sc == SC_TAB:
                self._switch_channel()
            elif sc == SC_L and self.channel == BOT_CHANNEL:
                self._toggle_link()
            elif sc in (SC_LEFT, SC_RIGHT):
                self.selected = (self.selected + (1 if sc == SC_RIGHT else -1)) % len(self.params)
            elif sc in (SC_UP, SC_DOWN):
                param = self.params[self.selected]
                steps = (1 if sc == SC_UP else -1) * (0.2 if fine and not param.is_choice else 1)
                self._set(self.selected, nudge(param, self._value(param), steps))
            else:
                self._play_key(self.keymap.get(sc), True, now)
        elif event.type == pygame.KEYUP:
            self._play_key(self.keymap.get(event.scancode), False, now)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for area, index, choice in self._hit:
                if area.collidepoint(event.pos):
                    self.selected = index
                    if choice is not None:
                        self._set(index, choice)
                    else:
                        self._dragging = (index, event.pos[1], to_norm(self.params[index], self._value(self.params[index])))
                    break
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = None
        elif event.type == pygame.MOUSEMOTION and self._dragging is not None:
            index, start_y, start_norm = self._dragging
            self._set(index, from_norm(self.params[index], start_norm + (start_y - event.pos[1]) / DRAG_PIXELS))
        elif event.type == pygame.MOUSEWHEEL:
            param = self.params[self.selected]
            self._set(self.selected, nudge(param, self._value(param), event.y))
        elif event.type == pygame.WINDOWFOCUSLOST:
            if self.input.release_all():
                self.voice.stop()
        return self

    def _play_key(self, action, down: bool, now: float) -> None:
        changed = False
        if isinstance(action, RootKey):
            changed = self.input.press_root(action.pitch_class) if down else self.input.release_root(action.pitch_class)
        elif down and isinstance(action, TypeKey):
            changed = self.input.select_type(action.type_id)
        elif down and isinstance(action, ExtensionKey):
            changed = self.input.toggle_extension(action.extension_id)
        if changed:
            chord = self.input.chord
            self.voice.play(chord, now) if chord else self.voice.stop()

    def update(self, now: float, dt: float) -> None:
        self.voice.update(now)

    # --- drawing ---

    def draw(self, surface: pygame.Surface, now: float) -> None:
        surface.fill(theme.BG)
        self._hit = []
        cx = self.width / 2
        theme.text(surface, "Sound", (cx, 36), 44, theme.TEXT, bold=True, anchor="midtop")
        bot = self.channel == BOT_CHANNEL
        accent = theme.BOT if bot else theme.PLAYER
        for label, active, x in (("YOU", not bot, cx - 70), ("BOT", bot, cx + 70)):
            rect = pygame.Rect(0, 0, 120, 38)
            rect.center = (x, 122)
            color = (theme.BOT if bot else theme.PLAYER) if active else theme.PANEL
            pygame.draw.rect(surface, color, rect, border_radius=10)
            theme.text(surface, label, rect.center, 18, theme.BG if active else theme.MUTED, bold=True, anchor="center")
        theme.text(surface, "Tab", (cx + 150, 122), 14, theme.MUTED, anchor="midleft")
        if bot:
            linked = self.store.bot_linked
            theme.text(surface, f"L   same sound as you: {'on' if linked else 'off'}", (cx, 158), 16,
                       theme.GOLD if linked else theme.MUTED, anchor="midtop")

        choices = [i for i, p in enumerate(self.params) if p.is_choice]
        y = 190
        for index in choices:
            self._draw_choice(surface, index, y, accent)
            y += 110
        # One row of knobs per group, with a picture of what the group does on the right.
        groups: dict[str, list[int]] = {}
        for i, p in enumerate(self.params):
            if not p.is_choice:
                groups.setdefault(p.group, []).append(i)
        graphs = {"envelope": self._draw_envelope, "eq": self._draw_eq_curve}
        for group, indices in groups.items():
            theme.text(surface, GROUP_TITLES.get(group, group.upper()), (80, y), 14, theme.MUTED, bold=True)
            centre_y = y + 30 + KNOB_RADIUS
            for k, index in enumerate(indices):
                self._draw_knob(surface, index, (80 + KNOB_RADIUS + k * KNOB_SPACING, centre_y), accent)
            if group in graphs:
                graphs[group](surface, pygame.Rect(self.width - 480, y + 22, 400, 2 * KNOB_RADIUS + 34), accent)
            y += 2 * KNOB_RADIUS + 110

        hint = ("Left/Right pick  ·  Up/Down turn (Shift: fine)  ·  drag or scroll a knob  ·  "
                "play chords to listen  ·  Esc back")
        theme.text(surface, hint, (cx, self.height - 40), 15, theme.MUTED, anchor="midtop")
        if self.message:
            theme.text(surface, self.message, (cx, self.height - 70), 16, theme.GOLD, anchor="midtop")

    def _draw_choice(self, surface, index: int, y: float, accent) -> None:
        param = self.params[index]
        value = self._value(param)
        selected = index == self.selected
        theme.text(surface, param.label.upper(), (self.width / 2, y), 14, theme.TEXT if selected else theme.MUTED,
                   bold=True, anchor="midtop")
        width = 120
        x = self.width / 2 - (len(param.choices) * (width + 12) - 12) / 2
        for choice in param.choices:
            rect = pygame.Rect(x, y + 24, width, 64)
            on = choice == value
            pygame.draw.rect(surface, accent if on else theme.PANEL, rect, border_radius=10)
            if selected and on:
                pygame.draw.rect(surface, theme.TEXT, rect, 2, border_radius=10)
            fg = theme.BG if on else theme.TEXT
            _draw_wave_icon(surface, choice, pygame.Rect(rect.x + 20, rect.y + 8, width - 40, 26), fg)
            theme.text(surface, choice, (rect.centerx, rect.bottom - 8), 14, fg, anchor="midbottom")
            self._hit.append((rect, index, choice))
            x += width + 12

    def _draw_knob(self, surface, index: int, center, accent) -> None:
        param = self.params[index]
        value = self._value(param)
        norm = to_norm(param, value)
        selected = index == self.selected
        r = KNOB_RADIUS
        box = pygame.Rect(0, 0, 2 * r, 2 * r)
        box.center = center
        start = math.radians(90 + SWEEP / 2)  # bottom-left
        pygame.draw.circle(surface, theme.PANEL, center, r - 8)
        pygame.draw.arc(surface, theme.ROW, box, math.radians(90 - SWEEP / 2), start, 7)
        if norm > 0.001:
            pygame.draw.arc(surface, accent, box, start - math.radians(SWEEP) * norm, start, 7)
        angle = start - math.radians(SWEEP) * norm
        tip = (center[0] + (r - 16) * math.cos(angle), center[1] - (r - 16) * math.sin(angle))
        pygame.draw.line(surface, theme.TEXT, center, tip, 3)
        if selected:
            pygame.draw.circle(surface, theme.TEXT, center, r + 6, 2)
        theme.text(surface, param.label, (center[0], center[1] + r + 10), 16,
                   theme.TEXT if selected else theme.MUTED, bold=True, anchor="midtop")
        theme.text(surface, format_value(param, value), (center[0], center[1] + r + 30), 15, theme.MUTED,
                   anchor="midtop")
        self._hit.append((box.inflate(10, 60), index, None))

    def _draw_envelope(self, surface, rect: pygame.Rect, accent) -> None:
        """The ADSR shape: attack, decay, a held stretch, release."""
        get = lambda pid: self.engine.get_param(self.channel, pid)  # noqa: E731
        try:
            a, d, s, r = get("attack"), get("decay"), get("sustain"), get("release")
        except KeyError:
            return
        hold = 0.6
        total = a + d + hold + r
        x = lambda t: rect.x + rect.w * t / total  # noqa: E731
        y = lambda level: rect.bottom - rect.h * level  # noqa: E731
        points = [(x(0), y(0)), (x(a), y(1)), (x(a + d), y(s)), (x(a + d + hold), y(s)), (x(total), y(0))]
        pygame.draw.rect(surface, theme.PANEL, rect.inflate(24, 24), border_radius=10)
        pygame.draw.lines(surface, accent, False, points, 3)
        for label, t0, t1 in (("A", 0, a), ("D", a, a + d), ("S", a + d, a + d + hold), ("R", a + d + hold, total)):
            theme.text(surface, label, ((x(t0) + x(t1)) / 2, rect.bottom + 2), 12, theme.MUTED, anchor="midtop")

    def _draw_eq_curve(self, surface, rect: pygame.Rect, accent) -> None:
        """How loud each frequency comes out, from 20 Hz to 20 kHz, ±15 dB."""
        get = lambda pid: self.engine.get_param(self.channel, pid)  # noqa: E731
        try:
            gains = get("eq_low"), get("eq_mid"), get("eq_high")
        except KeyError:
            return
        lo, hi, span = math.log10(20), math.log10(20000), 15.0
        freqs = np.logspace(lo, hi, 160)
        db = response_db(*gains, freqs, 44100)
        x = lambda f: rect.x + rect.w * (math.log10(f) - lo) / (hi - lo)  # noqa: E731
        y = lambda v: rect.centery - rect.h / 2 * max(-1.0, min(1.0, v / span))  # noqa: E731
        pygame.draw.rect(surface, theme.PANEL, rect.inflate(24, 24), border_radius=10)
        pygame.draw.line(surface, theme.ROW, (rect.x, rect.centery), (rect.right, rect.centery), 1)
        for f, label in ((100, "100"), (1000, "1k"), (10000, "10k")):
            pygame.draw.line(surface, theme.ROW, (x(f), rect.y), (x(f), rect.bottom), 1)
            theme.text(surface, label, (x(f), rect.bottom + 2), 12, theme.MUTED, anchor="midtop")
        pygame.draw.lines(surface, accent, False, [(x(f), y(v)) for f, v in zip(freqs, db)], 3)

    def close(self) -> None:
        self.voice.stop()


def _draw_wave_icon(surface, wave: str, rect: pygame.Rect, color) -> None:
    points = []
    for i in range(61):
        t = 2 * i / 60  # two cycles
        phase = t % 1.0
        if wave == "sine":
            v = math.sin(2 * math.pi * t)
        elif wave == "triangle":
            v = 1 - 4 * abs(phase - 0.5)
        elif wave == "saw":
            v = 2 * phase - 1
        else:
            v = 1 if phase < 0.5 else -1
        points.append((rect.x + rect.w * i / 60, rect.centery - v * rect.h / 2))
    pygame.draw.lines(surface, color, False, points, 2)
