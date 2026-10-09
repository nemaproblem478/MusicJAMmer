"""Sound check: play chords with the game controls and hear the synth.

    python -m musicjammer.tools.piano
"""

from __future__ import annotations

import time

import pygame

from ..audio import PLAYER_CHANNEL, ChordPerformer, NumpySynth
from ..audio.numpy_synth import WAVEFORMS
from ..controls import ChordInput, ExtensionKey, RootKey, TypeKey, build_keymap, key_labels
from ..controls.keymap import SC_ESCAPE, SC_TAB
from ..theory import CHORD_TYPES, EXTENSIONS, MAJOR, NO_EXTENSION, Key, distance

WIDTH, HEIGHT = 960, 560
LOWEST_NOTE, HIGHEST_NOTE = 48, 74  # C3..D5 covers every voicing

BG = (24, 24, 30)
PANEL = (40, 40, 50)
TEXT = (230, 230, 235)
MUTED = (130, 130, 145)
ACCENT = (110, 200, 160)
DISABLED = (70, 70, 80)
WHITE_KEY = (235, 235, 240)
BLACK_KEY = (30, 30, 36)

BLACK_PCS = {1, 3, 6, 8, 10}


def font(size: int, bold: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("helveticaneue,arial", size, bold=bold)


def draw_selector(screen, fonts, y, title, items, labels):
    """items: (action, label, selected, enabled)"""
    screen.blit(fonts["small"].render(title, True, MUTED), (40, y))
    x = 40
    for action, label, selected, enabled in items:
        rect = pygame.Rect(x, y + 24, 96, 56)
        color = ACCENT if selected else (PANEL if enabled else BG)
        pygame.draw.rect(screen, color, rect, border_radius=8)
        if not enabled:
            pygame.draw.rect(screen, DISABLED, rect, 2, border_radius=8)
        fg = BG if selected else (TEXT if enabled else DISABLED)
        screen.blit(fonts["mid"].render(label, True, fg), (rect.x + 12, rect.y + 6))
        screen.blit(fonts["small"].render(labels[action], True, fg), (rect.x + 12, rect.y + 32))
        x += 108


def draw_keyboard(screen, fonts, sounding, root_labels):
    top, height = 400, 130
    whites = [n for n in range(LOWEST_NOTE, HIGHEST_NOTE + 1) if n % 12 not in BLACK_PCS]
    key_w = (WIDTH - 80) / len(whites)
    positions = {}
    for i, n in enumerate(whites):
        rect = pygame.Rect(40 + i * key_w, top, key_w - 2, height)
        positions[n] = rect
        pygame.draw.rect(screen, ACCENT if n in sounding else WHITE_KEY, rect, border_radius=4)
    for n in range(LOWEST_NOTE, HIGHEST_NOTE + 1):
        if n % 12 in BLACK_PCS:
            left = positions[n - 1]
            rect = pygame.Rect(left.right - key_w * 0.3, top, key_w * 0.6, height * 0.62)
            positions[n] = rect
            pygame.draw.rect(screen, ACCENT if n in sounding else BLACK_KEY, rect, border_radius=3)
    for pc, label in root_labels.items():
        rect = positions[LOWEST_NOTE + pc]
        color = BG if LOWEST_NOTE + pc in sounding else (WHITE_KEY if pc in BLACK_PCS else MUTED)
        img = fonts["small"].render(label, True, color)
        screen.blit(img, (rect.centerx - img.get_width() / 2, rect.bottom - 26))


def main() -> None:
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("MusicJAMmer - sound check")
    pygame.key.stop_text_input()  # no macOS accent popup when holding a key
    fonts = {"big": font(72, bold=True), "mid": font(24, bold=True), "small": font(16)}

    synth = NumpySynth()
    synth.start()
    performer = ChordPerformer(synth, PLAYER_CHANNEL)
    chord_input = ChordInput()
    keymap = build_keymap()
    labels = key_labels()
    root_labels = {a.pitch_class: lbl for a, lbl in labels.items() if isinstance(a, RootKey)}
    key = Key(0, MAJOR)
    clock = pygame.time.Clock()

    def refresh() -> None:
        chord = chord_input.chord
        if chord is None:
            performer.stop()
        else:
            performer.play(chord, time.monotonic())

    try:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.WINDOWFOCUSLOST:
                    if chord_input.release_all():
                        refresh()
                elif event.type == pygame.KEYDOWN:
                    if event.scancode == SC_ESCAPE:
                        running = False
                    elif event.scancode == SC_TAB:
                        wave = synth.get_param(PLAYER_CHANNEL, "waveform")
                        synth.set_param(
                            PLAYER_CHANNEL, "waveform", WAVEFORMS[(WAVEFORMS.index(wave) + 1) % len(WAVEFORMS)]
                        )
                    action = keymap.get(event.scancode)
                    changed = False
                    if isinstance(action, RootKey):
                        changed = chord_input.press_root(action.pitch_class)
                    elif isinstance(action, TypeKey):
                        changed = chord_input.select_type(action.type_id)
                    elif isinstance(action, ExtensionKey):
                        changed = chord_input.toggle_extension(action.extension_id)
                    if changed:
                        refresh()
                elif event.type == pygame.KEYUP:
                    action = keymap.get(event.scancode)
                    if isinstance(action, RootKey) and chord_input.release_root(action.pitch_class):
                        refresh()

            performer.update(time.monotonic())

            screen.fill(BG)
            chord = chord_input.chord
            title = chord.name if chord else "hold a root key"
            screen.blit(fonts["big" if chord else "mid"].render(title, True, TEXT), (40, 30))
            if chord:
                info = f"distance to {key}: {distance(chord, key)}"
                screen.blit(fonts["small"].render(info, True, MUTED), (40, 115))

            type_items = [
                (TypeKey(t.id), t.label, t == chord_input.chord_type, True) for t in CHORD_TYPES.values()
            ]
            draw_selector(screen, fonts, 150, "CHORD TYPE (latches)", type_items, labels)
            ext_items = [
                (ExtensionKey(e.id), e.label, e == chord_input.extension, e.supports(chord_input.chord_type))
                for e in EXTENSIONS.values()
                if e != NO_EXTENSION
            ]
            draw_selector(screen, fonts, 260, "EXTENSION (toggles; none = octave)", ext_items, labels)

            wave = synth.get_param(PLAYER_CHANNEL, "waveform")
            hint = f"wave: {wave}  (Tab to change)    Esc to quit"
            img = fonts["small"].render(hint, True, MUTED)
            screen.blit(img, (WIDTH - 40 - img.get_width(), 40))

            draw_keyboard(screen, fonts, performer.sounding, root_labels)
            pygame.display.flip()
            clock.tick(120)
    finally:
        performer.stop()
        synth.stop()
        pygame.quit()


if __name__ == "__main__":
    main()
