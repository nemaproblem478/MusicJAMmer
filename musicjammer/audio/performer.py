"""Turns chords into strummed note events on one channel.

The root sounds immediately; the notes above it follow one by one, `strum`
seconds apart. When the chord type changes but the root stays, the root keeps
ringing and the upper notes are re-strummed. When only the extension changes,
the triad keeps ringing and just the fourth note is swapped.
"""

from __future__ import annotations

from ..theory import Chord
from .engine import NoteEngine


class ChordPerformer:
    def __init__(
        self,
        engine: NoteEngine,
        channel: int,
        base_note: int = 48,
        strum: float = 0.06,
        velocity: int = 100,
    ) -> None:
        self.engine = engine
        self.channel = channel
        self.base_note = base_note
        self.strum = strum
        self.velocity = velocity
        self.chord: Chord | None = None
        self.sounding: set[int] = set()
        self._pending: list[tuple[float, int]] = []

    def play(self, chord: Chord, now: float) -> None:
        if self.chord is not None and chord.core == self.chord.core:
            self._swap_extension(chord)
            return
        root, *upper = chord.voicing(self.base_note)
        self._pending.clear()
        for note in self.sounding - {root}:
            self.engine.note_off(self.channel, note)
        if root not in self.sounding:
            self.engine.note_on(self.channel, root, self.velocity)
        self.sounding = {root}
        self._pending = [(now + self.strum * (i + 1), note) for i, note in enumerate(upper)]
        self.chord = chord

    def _swap_extension(self, chord: Chord) -> None:
        """Same core, different fourth note: the triad keeps ringing, only the fourth note changes."""
        new = set(chord.voicing(self.base_note))
        old = set(self.chord.voicing(self.base_note))
        for note in old - new:
            if note in self.sounding:
                self.engine.note_off(self.channel, note)
                self.sounding.discard(note)
        self._pending = [(t, note) for t, note in self._pending if note in new]
        for note in sorted(new - old):
            self.engine.note_on(self.channel, note, self.velocity)
            self.sounding.add(note)
        self.chord = chord

    def update(self, now: float) -> None:
        while self._pending and self._pending[0][0] <= now:
            _, note = self._pending.pop(0)
            self.engine.note_on(self.channel, note, self.velocity)
            self.sounding.add(note)

    def stop(self) -> None:
        self._pending.clear()
        for note in self.sounding:
            self.engine.note_off(self.channel, note)
        self.sounding.clear()
        self.chord = None
