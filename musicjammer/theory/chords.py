"""Chord types, extensions and chords.

A chord is split into a *core* (root + chord type) and an *extension* (the fourth
note). Only the core matters for the game: distance, move validity and the repeat
ban. The extension is pure colour. A chord without an extension doubles the root
an octave higher, so every chord has four notes.

New chord types and extensions are added by registering them; nothing else needs
to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .notes import note_name


class Quality(Enum):
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True)
class ChordType:
    id: str
    label: str  # shown on the type selector, e.g. "min"
    symbol: str  # used in chord names, e.g. "m" -> "Am"
    intervals: tuple[int, ...]  # semitones above the root, root included
    anchor: int  # semitones from the root to the major chord whose circle position this chord takes
    quality: Quality
    tension: int = 0


@dataclass(frozen=True)
class Extension:
    id: str
    label: str  # shown on the extension selector, e.g. "7th"
    interval: int  # semitones above the root of the fourth note
    suffix: str  # appended to the chord name, e.g. "7" -> "C7"
    excluded_types: frozenset[str] = field(default_factory=frozenset)

    def supports(self, chord_type: ChordType) -> bool:
        return chord_type.id not in self.excluded_types


CHORD_TYPES: dict[str, ChordType] = {}
EXTENSIONS: dict[str, Extension] = {}
# Full chord-name suffixes for combinations that don't read as symbol + suffix.
NAME_OVERRIDES: dict[tuple[str, str], str] = {}


def register_chord_type(chord_type: ChordType) -> ChordType:
    CHORD_TYPES[chord_type.id] = chord_type
    return chord_type


def register_extension(extension: Extension) -> Extension:
    EXTENSIONS[extension.id] = extension
    return extension


def register_name_override(type_id: str, extension_id: str, suffix: str) -> None:
    NAME_OVERRIDES[(type_id, extension_id)] = suffix


MAJ = register_chord_type(ChordType("maj", "maj", "", (0, 4, 7), anchor=0, quality=Quality.MAJOR))
# A minor chord sits with its relative major (Am -> C).
MIN = register_chord_type(ChordType("min", "min", "m", (0, 3, 7), anchor=3, quality=Quality.MINOR))
# A diminished chord acts as a rootless dominant seventh (B° -> G7), so it sits with that dominant.
DIM = register_chord_type(
    ChordType("dim", "dim", "°", (0, 3, 6), anchor=-4, quality=Quality.MAJOR, tension=1)
)

NO_EXTENSION = register_extension(Extension("none", "-", 12, ""))
SIXTH = register_extension(Extension("6", "6th", 9, "6"))
SEVENTH = register_extension(Extension("b7", "7th", 10, "7"))
MAJOR_SEVENTH = register_extension(
    Extension("maj7", "maj7", 11, "maj7", excluded_types=frozenset({"dim"}))
)
ADD_NINE = register_extension(Extension("add9", "add9", 14, "add9", excluded_types=frozenset({"dim"})))

register_name_override("min", "maj7", "m(maj7)")
register_name_override("min", "add9", "m(add9)")
register_name_override("dim", "6", "°7")
register_name_override("dim", "b7", "ø7")


@dataclass(frozen=True)
class Chord:
    root: int
    type: ChordType
    extension: Extension = NO_EXTENSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root % 12)
        if not self.extension.supports(self.type):
            raise ValueError(f"extension {self.extension.id!r} is not available for {self.type.id!r}")

    @property
    def core(self) -> Chord:
        """The chord without its extension; this is what the game rules see."""
        if self.extension is NO_EXTENSION:
            return self
        return Chord(self.root, self.type)

    @property
    def pitch_classes(self) -> frozenset[int]:
        """Pitch classes of the core triad."""
        return frozenset((self.root + i) % 12 for i in self.type.intervals)

    def voicing(self, base_note: int = 48) -> list[int]:
        """MIDI notes from the root upwards; the root lands in the octave starting at base_note."""
        root = base_note + self.root
        return [root + i for i in self.type.intervals] + [root + self.extension.interval]

    @property
    def name(self) -> str:
        suffix = NAME_OVERRIDES.get(
            (self.type.id, self.extension.id), self.type.symbol + self.extension.suffix
        )
        return note_name(self.root) + suffix

    def __str__(self) -> str:
        return self.name
