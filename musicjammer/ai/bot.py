"""The jam partner: alpha-beta picks the move, then the bot adds an extension for colour."""

from __future__ import annotations

import random

from ..game.duel import DuelConfig, DuelRound
from ..theory import EXTENSIONS, NO_EXTENSION, Chord, ChordType
from .alphabeta import DIFFICULTIES, AlphaBetaAI, Difficulty, Move


class Bot:
    def __init__(
        self,
        config: DuelConfig,
        difficulty: Difficulty = DIFFICULTIES["medium"],
        extension_chance: float = 0.35,
        rng: random.Random | None = None,
        chord_types: list[ChordType] | None = None,
    ) -> None:
        self.rng = rng or random.Random()
        self.extension_chance = extension_chance
        self.ai = AlphaBetaAI(config, difficulty, self.rng, chord_types)

    def choose(self, game: DuelRound) -> Move | None:
        """The bot's move, or None when it has no legal move and must miss the bar."""
        move = self.ai.choose(game)
        if move is None:
            return None
        core = move.chord
        if self.rng.random() >= self.extension_chance:
            return move
        options = [e for e in EXTENSIONS.values() if e != NO_EXTENSION and e.supports(core.type)]
        return Move(Chord(core.root, core.type, self.rng.choice(options)), move.joker)
