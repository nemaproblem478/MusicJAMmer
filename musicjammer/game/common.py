"""Things every game mode shares."""

from __future__ import annotations

from enum import Enum

from ..theory import Chord, MoveError

ROUND_LENGTHS = (8, 16, 32)


class Side(Enum):
    BOT = "bot"
    PLAYER = "player"

    @property
    def other(self) -> Side:
        return Side.PLAYER if self is Side.BOT else Side.BOT


class IllegalMove(Exception):
    def __init__(self, chord: Chord, reason: MoveError) -> None:
        super().__init__(f"{chord}: {reason.value}")
        self.chord = chord
        self.reason = reason
