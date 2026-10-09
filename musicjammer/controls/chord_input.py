"""What chord the player is currently holding.

The root must be held down. The chord type and extension latch: pressing a type
key selects it until another type is chosen, and an extension key toggles that
extension. Both stay selected across roots, so C -> F -> G only needs root keys.
"""

from __future__ import annotations

from ..theory import CHORD_TYPES, EXTENSIONS, MAJ, NO_EXTENSION, Chord, ChordType, Extension


class ChordInput:
    def __init__(self) -> None:
        self._held_roots: list[int] = []
        self.chord_type: ChordType = MAJ
        self.extension: Extension = NO_EXTENSION

    @property
    def root(self) -> int | None:
        return self._held_roots[-1] if self._held_roots else None

    @property
    def effective_extension(self) -> Extension:
        """The latched extension, or none if the current chord type doesn't allow it."""
        return self.extension if self.extension.supports(self.chord_type) else NO_EXTENSION

    @property
    def chord(self) -> Chord | None:
        if self.root is None:
            return None
        return Chord(self.root, self.chord_type, self.effective_extension)

    # Each method returns True when the held chord changed.

    def press_root(self, pitch_class: int) -> bool:
        before = self.chord
        if pitch_class in self._held_roots:
            self._held_roots.remove(pitch_class)
        self._held_roots.append(pitch_class)
        return self.chord != before

    def release_root(self, pitch_class: int) -> bool:
        before = self.chord
        if pitch_class in self._held_roots:
            self._held_roots.remove(pitch_class)
        return self.chord != before

    def select_type(self, type_id: str) -> bool:
        before = self.chord
        self.chord_type = CHORD_TYPES[type_id]
        return self.chord != before

    def toggle_extension(self, extension_id: str) -> bool:
        before = self.chord
        extension = EXTENSIONS[extension_id]
        self.extension = NO_EXTENSION if self.extension == extension else extension
        return self.chord != before

    def release_all(self) -> bool:
        before = self.chord
        self._held_roots.clear()
        return self.chord != before
