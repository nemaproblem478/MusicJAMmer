"""Physical key layout, by SDL scancode so it works with any keyboard layout (e.g. Ukrainian).

    Roots       A W S E D F T G Y H U J   (piano-style: A=C, W=C#, S=D, ...)
    Chord type  Z X C V B N M             (in registration order: maj, min, dim, ...)
    Extension   6 7 8 9 0                 (in registration order: 6, b7, maj7, 9, ...)
    Confirm     Enter
"""

from __future__ import annotations

from dataclasses import dataclass

from ..theory import CHORD_TYPES, EXTENSIONS, NO_EXTENSION


def letter(ch: str) -> int:
    return 4 + ord(ch.upper()) - ord("A")


def digit(ch: str) -> int:
    return 39 if ch == "0" else 29 + int(ch)


SC_RETURN = 40
SC_ESCAPE = 41
SC_TAB = 43
SC_SPACE = 44

ROOT_KEYS = "AWSEDFTGYHUJ"
TYPE_KEYS = "ZXCVBNM"
EXTENSION_KEYS = "67890"


@dataclass(frozen=True)
class RootKey:
    pitch_class: int


@dataclass(frozen=True)
class TypeKey:
    type_id: str


@dataclass(frozen=True)
class ExtensionKey:
    extension_id: str


@dataclass(frozen=True)
class Confirm:
    pass


Action = RootKey | TypeKey | ExtensionKey | Confirm


def build_keymap() -> dict[int, Action]:
    keymap: dict[int, Action] = {letter(k): RootKey(pc) for pc, k in enumerate(ROOT_KEYS)}
    for k, type_id in zip(TYPE_KEYS, CHORD_TYPES):
        keymap[letter(k)] = TypeKey(type_id)
    extensions = [e for e in EXTENSIONS if e != NO_EXTENSION.id]
    for k, ext_id in zip(EXTENSION_KEYS, extensions):
        keymap[digit(k)] = ExtensionKey(ext_id)
    keymap[SC_RETURN] = Confirm()
    return keymap


def key_labels() -> dict[Action, str]:
    """Printable key name for every action, for on-screen hints."""
    labels: dict[Action, str] = {}
    for scancode, action in build_keymap().items():
        if isinstance(action, Confirm):
            labels[action] = "Enter"
        elif 4 <= scancode <= 29:
            labels[action] = chr(ord("A") + scancode - 4)
        else:
            labels[action] = "0" if scancode == 39 else str(scancode - 29)
    return labels
