"""The game window: a start screen with the round settings, the sound page and the jam itself.

    python -m musicjammer
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pygame

from ..ai import DIFFICULTIES, BotWorker
from ..audio import METRONOME_CHANNEL, NoteEngine, NumpySynth
from ..controls import ExtensionKey, RootKey, TypeKey, build_keymap, key_labels
from ..controls.keymap import SC_ESCAPE, SC_RETURN, SC_SPACE
from ..export import save_jam
from ..game import ROUND_LENGTHS, Side
from ..session import JamSession, Phase, TimedSession
from ..settings import BPM_RANGE, SettingsStore
from ..theory import CHORD_TYPES, EXTENSIONS, MODES, NO_EXTENSION, note_name
from . import theme
from .pianoroll import PianoRoll
from .synth_screen import SynthScreen

WIDTH, HEIGHT = 1180, 760
SC_RIGHT, SC_LEFT, SC_DOWN, SC_UP = 79, 80, 81, 82
SC_D, SC_L, SC_P, SC_B, SC_T, SC_M, SC_S, SC_E = 7, 15, 19, 5, 23, 16, 22, 8
SC_BRACKET_LEFT, SC_BRACKET_RIGHT = 47, 48
VOLUME_STEPS = (1.0, 0.8, 0.6, 0.4, 0.2, 0.0)


def _cycle(options, current, step=1):
    options = list(options)
    if current not in options:  # e.g. a hand-edited value from the settings file
        return options[0]
    return options[(options.index(current) + step) % len(options)]


class StartScreen:
    def __init__(self, store: SettingsStore) -> None:
        self.store = store

    @property
    def settings(self):
        return self.store.game

    @settings.setter
    def settings(self, value) -> None:
        self.store.game = value

    def handle(self, event, engine: NoteEngine):
        if event.type != pygame.KEYDOWN:
            return self
        sc, s = event.scancode, self.settings
        if sc in (SC_RETURN, SC_SPACE):
            self.store.save()
            return GameScreen(self.store, engine)
        if sc == SC_ESCAPE:
            return None
        if sc == SC_S:
            return SynthScreen(self.store, engine, WIDTH, HEIGHT, back=lambda: StartScreen(self.store))
        if sc in (SC_LEFT, SC_RIGHT):
            self.settings = replace(s, tonic=(s.tonic + (1 if sc == SC_RIGHT else -1)) % 12)
        elif sc in (SC_UP, SC_DOWN):
            self.settings = replace(s, mode=_cycle(MODES, s.mode))
        elif sc == SC_D:
            self.settings = replace(s, difficulty=_cycle(DIFFICULTIES, s.difficulty))
        elif sc == SC_L:
            self.settings = replace(s, bars=_cycle(ROUND_LENGTHS, s.bars))
        elif sc == SC_P:
            self.settings = replace(s, preview_volume=_cycle(VOLUME_STEPS, s.preview_volume))
        elif sc == SC_B:
            self.settings = replace(s, bot_volume=_cycle(VOLUME_STEPS, s.bot_volume))
        elif sc == SC_T:
            self.settings = replace(s, timed=not s.timed)
        elif sc == SC_M:
            self.settings = replace(s, metronome=not s.metronome)
        elif sc in (SC_BRACKET_LEFT, SC_BRACKET_RIGHT):
            bpm = s.bpm + (5 if sc == SC_BRACKET_RIGHT else -5)
            self.settings = replace(s, bpm=min(BPM_RANGE[1], max(BPM_RANGE[0], bpm)))
        return self

    def update(self, now: float, dt: float) -> None:
        pass

    def draw(self, surface: pygame.Surface, now: float) -> None:
        surface.fill(theme.BG)
        cx = WIDTH / 2
        theme.text(surface, "MusicJAMmer", (cx, 90), 64, theme.TEXT, bold=True, anchor="midtop")
        theme.text(surface, "a cadence duel against an alpha-beta bot", (cx, 170), 22, theme.MUTED, anchor="midtop")
        config = self.settings.config()
        rows = [
            ("Your key", str(config.key), "Left / Right, Up / Down"),
            ("Bot's key", str(config.bot_key), "the opposite side of the circle of fifths"),
            ("Difficulty", DIFFICULTIES[self.settings.difficulty].label, "D"),
            ("Round", f"{self.settings.bars} bars", "L"),
            ("Mode", "Timed" if self.settings.timed else "Untimed", "T"),
        ]
        if self.settings.timed:
            rows += [
                ("Tempo", f"{self.settings.bpm} BPM", "[ and ]"),
                ("Metronome", "On" if self.settings.metronome else "Off", "M   (the count-in always clicks)"),
            ]
        else:
            rows += [
                ("Your preview", f"{self.settings.preview_volume:.0%}", "P   (your chords while you choose)"),
                ("Bot on your turn", f"{self.settings.bot_volume:.0%}", "B   (the bot's chord while you choose)"),
            ]
        y = 222
        for name, value, keys in rows:
            theme.text(surface, name, (cx - 40, y), 24, theme.MUTED, anchor="topright")
            theme.text(surface, value, (cx, y), 24, theme.TEXT, bold=True)
            theme.text(surface, keys, (cx + 230, y + 4), 16, theme.MUTED)
            y += 36
        rules = [
            "Every bar adds tension to a shared pot (a diminished chord adds 2).",
            f"If the bot's chord holds your leading tone ({note_name(config.key.tonic + 11)}), answer with "
            f"{config.key.tonic_chord.name} to take the pot.",
            f"The bot does the same with its leading tone ({note_name(config.bot_key.tonic + 11)}) and "
            f"{config.bot_key.tonic_chord.name}. Don't hand it one.",
            "A chord must share a note with the last one and move at most one step around the circle of fifths;",
            "no repeats within 8 bars. Once per round, a joker ignores those rules.",
            "Timed: hold your chord as the line passes the bar (Shift too for the joker). Untimed: Enter / Shift+Enter.",
        ]
        y += 14
        for line in rules:
            theme.text(surface, line, (cx, y), 17, theme.TEXT, anchor="midtop")
            y += 26
        theme.text(surface, "Enter to start   ·   S for sound   ·   Esc to quit", (cx, HEIGHT - 70), 22, theme.GOLD,
                   bold=True, anchor="midtop")

    def close(self) -> None:
        pass


class GameScreen:
    def __init__(self, store: SettingsStore, engine: NoteEngine) -> None:
        self.store = store
        self.settings = settings = store.game
        self.engine = engine
        self.exported = ""
        config = settings.config()
        difficulty = DIFFICULTIES[settings.difficulty]
        now = time.monotonic()
        if settings.timed:
            # The bot must answer before the next downbeat: think for at most half a bar.
            bar_seconds = 240 / settings.bpm
            difficulty = replace(difficulty, time_limit=min(difficulty.time_limit, 0.45 * bar_seconds))
            self.worker = BotWorker(config, difficulty)
            self.session = TimedSession(config, engine, self.worker, now, settings.bpm, settings.metronome)
        else:
            self.worker = BotWorker(config, difficulty)
            self.session = JamSession(config, engine, self.worker, now,
                                      preview_gain=settings.preview_volume, bot_gain=settings.bot_volume)
        self.roll = PianoRoll()
        self.keymap = build_keymap()
        self.labels = key_labels()

    def handle(self, event, engine: NoteEngine):
        now = time.monotonic()
        session = self.session
        if event.type == pygame.WINDOWFOCUSLOST:
            session.release_all(now)
        elif event.type == pygame.KEYDOWN:
            if event.scancode == SC_ESCAPE:
                self.close()
                return StartScreen(self.store)
            if session.phase is Phase.ROUND_OVER:
                if event.scancode in (SC_RETURN, SC_SPACE):
                    self.close()
                    return GameScreen(self.store, engine)
                if event.scancode == SC_E and not self.exported:
                    self._export()
                return self
            if event.scancode == SC_RETURN:
                if not session.timed:
                    session.confirm(now, joker=bool(event.mod & pygame.KMOD_SHIFT))
                return self
            action = self.keymap.get(event.scancode)
            if isinstance(action, RootKey):
                session.press_root(action.pitch_class, now)
            elif isinstance(action, TypeKey):
                session.select_type(action.type_id, now)
            elif isinstance(action, ExtensionKey):
                session.toggle_extension(action.extension_id, now)
        elif event.type == pygame.KEYUP:
            action = self.keymap.get(event.scancode)
            if isinstance(action, RootKey):
                session.release_root(action.pitch_class, now)
        return self

    def update(self, now: float, dt: float) -> None:
        if self.session.timed:
            self.session.joker_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            self.session.update(now)
            self.roll.camera = self.session.camera_at(now)
        else:
            self.session.update(now)
            self.roll.update(self.session.camera_target, dt)

    def draw(self, surface: pygame.Surface, now: float) -> None:
        surface.fill(theme.BG)
        joker_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        self._draw_header(surface)
        roll = pygame.Rect(24, 112, WIDTH - 48, HEIGHT - 112 - 150)
        self.roll.draw(surface, roll, self.session, joker_held)
        if self.session.timed:
            self._draw_count_in(surface, roll, now)
        self._draw_toast(surface, roll, now)
        self._draw_footer(surface, now, joker_held)
        if self.session.phase is Phase.ROUND_OVER:
            self._draw_result(surface)

    def _draw_header(self, surface) -> None:
        s, r = self.session, self.session.round
        pygame.draw.rect(surface, theme.PANEL, (24, 16, WIDTH - 48, 84), border_radius=12)
        for side, x, anchor in ((Side.PLAYER, 48, "topleft"), (Side.BOT, WIDTH - 48, "topright")):
            color = theme.PLAYER if side is Side.PLAYER else theme.BOT
            key = s.config.key if side is Side.PLAYER else s.config.bot_key
            who = "YOU" if side is Side.PLAYER else f"BOT · {DIFFICULTIES[self.settings.difficulty].label}"
            theme.text(surface, f"{who}  ·  {key}", (x, 26), 18, color, bold=True, anchor=anchor)
            joker = "joker ready" if r.jokers_left[side] else "joker used"
            theme.text(surface, f"{r.points[side]} pts   ·   {joker}", (x, 56), 24, theme.TEXT, anchor=anchor)
        theme.text(surface, f"POT {r.pot}", (WIDTH / 2, 22), 36, theme.GOLD, bold=True, anchor="midtop")
        theme.text(surface, s.bar_label, (WIDTH / 2, 66), 16, theme.MUTED, anchor="midtop")

    def _draw_footer(self, surface, now: float, joker_held: bool) -> None:
        s = self.session
        top = HEIGHT - 128
        status, color = self._status(now, joker_held)
        theme.text(surface, status, (WIDTH / 2, top), 22, color, bold=True, anchor="midtop")
        x = 48
        y = top + 44
        for t in CHORD_TYPES.values():
            x = self._chip(surface, x, y, self.labels[TypeKey(t.id)], t.label, t == s.input.chord_type, True)
        x += 24
        for e in EXTENSIONS.values():
            if e == NO_EXTENSION:
                continue
            x = self._chip(surface, x, y, self.labels[ExtensionKey(e.id)], e.label, e == s.input.extension,
                           e.supports(s.input.chord_type))
        if s.timed:
            hint = "hold a root (A W S E D F T G Y H U J) through the line  ·  + Shift for the joker  ·  Esc menu"
        else:
            hint = "hold a root (A W S E D F T G Y H U J)  ·  Enter play  ·  Shift+Enter joker  ·  Esc menu"
        theme.text(surface, hint, (WIDTH - 48, y + 52), 14, theme.MUTED, anchor="topright")

    def _chip(self, surface, x, y, key, label, selected, enabled) -> float:
        """A selector button: the key to press, small, then what it selects."""
        fg = theme.BG if selected else theme.TEXT if enabled else theme.GHOST
        key_image = theme.font(13).render(key, True, fg if selected else theme.MUTED)
        label_image = theme.font(18, True).render(label, True, fg)
        rect = pygame.Rect(x, y, key_image.get_width() + label_image.get_width() + 32, 36)
        pygame.draw.rect(surface, theme.PLAYER if selected else theme.PANEL, rect, border_radius=8)
        surface.blit(key_image, key_image.get_rect(midleft=(rect.x + 12, rect.centery + 1)))
        surface.blit(label_image, label_image.get_rect(midright=(rect.right - 12, rect.centery)))
        return rect.right + 8

    def _draw_count_in(self, surface, roll: pygame.Rect, now: float) -> None:
        count = self.session.count_in(now)
        if count is not None:
            theme.text(surface, str(count), roll.center, 140, theme.GOLD, bold=True, anchor="center")

    def _draw_toast(self, surface, roll: pygame.Rect, now: float) -> None:
        """Events (cadences, jokers, refused chords) float over the top of the roll for a few seconds."""
        message = self.session.current_message(now)
        if not message:
            return
        color = theme.GOLD if "adence" in message else theme.TEXT
        image = theme.font(22, True).render(message, True, color)
        box = image.get_rect(midtop=(roll.centerx, roll.y + 30)).inflate(36, 18)
        pygame.draw.rect(surface, theme.BG, box, border_radius=12)
        pygame.draw.rect(surface, color, box, 2, border_radius=12)
        surface.blit(image, image.get_rect(center=box.center))

    def _status(self, now: float, joker_held: bool) -> tuple[str, tuple]:
        s = self.session
        if s.phase is Phase.BOT_THINKING:
            return "The bot is thinking…", theme.BOT
        if s.phase is Phase.COUNT_IN:
            return "Get ready: the bot plays first", theme.MUTED
        if s.phase is Phase.PLAYER_BAR:
            return "", theme.TEXT
        if not s.preview_open:
            return "", theme.TEXT
        enter = "hold it through the line" if s.timed else "Enter to play"
        chord = s.preview
        tonic = s.config.key.tonic_chord.name
        if chord is None:
            if s.cadence_available:
                return f"Cadence available: play {tonic} to take the pot!", theme.GOLD
            return ("Get your next chord ready" if s.timed else "Your turn: hold a root key"), theme.MUTED
        if s.preview_is_cadence():
            return f"{chord.name} resolves the bot's chord: {enter} to take {s.round.pot}!", theme.GOLD
        error = s.preview_error(joker_held)
        if error is not None:
            return f"{chord.name}: {error.value}", theme.INVALID
        if s.gives_bot_a_cadence(chord):
            bot_tonic = s.config.bot_key.tonic_chord.name
            return f"{chord.name} is legal, but the bot could answer {bot_tonic} and take the pot", theme.WARN
        return f"{chord.name}: {enter}" + (" as your joker" if joker_held else ""), theme.PLAYER

    def _export(self) -> None:
        try:
            path = save_jam(self.session.blocks, self.session.config, self.settings.bpm)
        except OSError as error:
            self.exported = f"Couldn't save the MIDI file: {error.strerror or error}"
            return
        folder = path.parent.as_posix().replace(Path.home().as_posix(), "~", 1)
        if len(folder) > 40:
            folder = "…" + folder[-39:]
        self.exported = f"Saved {path.name} in {folder}"

    def _draw_result(self, surface) -> None:
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        surface.blit(shade, (0, 0))
        panel = pygame.Rect(0, 0, 720, 240)
        panel.center = (WIDTH / 2, HEIGHT / 2)
        pygame.draw.rect(surface, theme.PANEL, panel, border_radius=16)
        theme.text(surface, self.session.result, (panel.centerx, panel.y + 60), 30, theme.GOLD, bold=True,
                   anchor="midtop")
        theme.text(surface, "Enter to play again   ·   E to save as MIDI   ·   Esc for the menu",
                   (panel.centerx, panel.y + 130), 20, theme.MUTED, anchor="midtop")
        if self.exported:
            theme.text(surface, self.exported, (panel.centerx, panel.y + 175), 16, theme.TEXT, anchor="midtop")

    def close(self) -> None:
        self.session.close()


def main() -> None:
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("MusicJAMmer")
    pygame.key.stop_text_input()  # no macOS accent popup when holding a key

    engine = NumpySynth()
    store = SettingsStore(engine)
    store.load()
    for param, value in (("waveform", "square"), ("attack", 0.001), ("decay", 0.05), ("sustain", 0.0),
                         ("release", 0.02), ("volume", 0.35)):
        engine.set_param(METRONOME_CHANNEL, param, value)  # a short click
    engine.start()
    screen = StartScreen(store)
    clock = pygame.time.Clock()
    last = time.monotonic()
    try:
        while screen is not None:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    screen.close()
                    screen = None
                    break
                screen = screen.handle(event, engine)
                if screen is None:
                    break
            if screen is None:
                break
            now = time.monotonic()
            screen.update(now, now - last)
            last = now
            screen.draw(surface, now)
            pygame.display.flip()
            clock.tick(120)
    finally:
        store.save()
        engine.stop()
        pygame.quit()
