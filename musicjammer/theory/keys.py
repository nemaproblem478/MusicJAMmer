"""Modes and keys. New modes (dorian, mixolydian, ...) are added by registering them."""

from __future__ import annotations

from dataclasses import dataclass

from .chords import CHORD_TYPES, Chord, Quality
from .notes import fifths_position, note_name


@dataclass(frozen=True)
class Mode:
    id: str
    label: str
    tonic_type: str  # chord type id of the tonic triad
    parent_offset: int  # semitones from the tonic to the root of the parent major scale
    quality: Quality


MODES: dict[str, Mode] = {}


def register_mode(mode: Mode) -> Mode:
    MODES[mode.id] = mode
    return mode


MAJOR = register_mode(Mode("major", "Major", "maj", 0, Quality.MAJOR))
MINOR = register_mode(Mode("minor", "Minor", "min", 3, Quality.MINOR))


@dataclass(frozen=True)
class Key:
    tonic: int
    mode: Mode = MAJOR

    def __post_init__(self) -> None:
        object.__setattr__(self, "tonic", self.tonic % 12)

    @property
    def tonic_chord(self) -> Chord:
        return Chord(self.tonic, CHORD_TYPES[self.mode.tonic_type])

    @property
    def circle_position(self) -> int:
        return fifths_position(self.tonic + self.mode.parent_offset)

    @property
    def name(self) -> str:
        return f"{note_name(self.tonic)} {self.mode.label.lower()}"

    def __str__(self) -> str:
        return self.name
