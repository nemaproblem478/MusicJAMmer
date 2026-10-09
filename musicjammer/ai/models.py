"""The cadence duel as seen by the alpha-beta engine.

The model turns a round into compact search states (tuples) and knows the
moves, rewards and evaluation. Values are from the player's point of view: the
player maximises, the bot minimises.

A state is (bars_left, maximizing, prev, recent, jokers, pot, cadence_possible):
the bars still to play, whether the player is to move, the previous chord's
index, recent chord indices for the repeat ban, jokers left as (bot, player),
the pot, and whether the previous chord was played by the opponent (False at
the start and after a miss), which a cadence needs.

Moves are ints: `i` plays core chord i normally, `i + n` plays it with a joker.
Only a few of the most promising joker moves are considered.
"""

from __future__ import annotations

from ..game.common import Side
from ..game.duel import DuelConfig, DuelRound, cadence_setups, closer_side, tension
from ..theory import Chord, ChordType, all_cores, connection_error, distance

JOKER_CANDIDATES = 6


class DuelModel:
    def __init__(self, config: DuelConfig, chord_types: list[ChordType] | None = None) -> None:
        self.config = config
        self.rules = config.rules
        self.window = config.rules.repeat_window
        homes = {Side.PLAYER: config.key, Side.BOT: config.bot_key}

        self.cores = all_cores(chord_types)
        for key in homes.values():  # tonics must exist even if their chord type isn't playable
            if key.tonic_chord not in self.cores:
                self.cores.append(key.tonic_chord)
        self.n = n = len(self.cores)
        self.index = {c: i for i, c in enumerate(self.cores)}

        # Territory: negative = closer to the player's home, positive = closer to the bot's.
        # Moves are tried in this order: the player's best first.
        self.preference = [distance(c, config.key) - distance(c, config.bot_key) for c in self.cores]
        self.by_preference = sorted(range(n), key=lambda j: self.preference[j])
        self.connected = [
            [j for j in self.by_preference if connection_error(self.cores[i], self.cores[j], self.rules) is None]
            for i in range(n)
        ]
        self.connected_sets = [frozenset(c) for c in self.connected]

        # Indexed by `maximizing`: [bot, player].
        sides = (Side.BOT, Side.PLAYER)
        self.tonic = [self.index[homes[s].tonic_chord] for s in sides]
        self.setups = [
            frozenset(self.index[c] for c in cadence_setups(homes[s], config.cadence_rule) if c in self.index)
            for s in sides
        ]
        self.tension = [tension(c) for c in self.cores]
        self.owner = [closer_side(c, config) if config.leftover == "closer" else None for c in self.cores]

    def state(self, game: DuelRound) -> tuple:
        recent = tuple(self.index[c.core] for c in game.chords[-self.window :]) if self.window else ()
        return (
            game.bars_left,
            game.side_to_move is Side.PLAYER,
            self.index[game.previous_chord.core],
            recent,
            (game.jokers_left[Side.BOT], game.jokers_left[Side.PLAYER]),
            game.pot,
            bool(game.bars) and game.bars[-1].chord is not None,
        )

    @staticmethod
    def bars_left(state: tuple) -> int:
        return state[0]

    @staticmethod
    def maximizing(state: tuple) -> bool:
        return state[1]

    def chord_of(self, move: int) -> tuple[Chord, bool]:
        return self.cores[move % self.n], move >= self.n

    def _cadence_ready(self, state: tuple) -> bool:
        return state[6] and state[2] in self.setups[state[1]]

    def moves(self, state: tuple) -> list[int]:
        """Legal moves, the most promising for the side to move first."""
        _, maximizing, prev, recent, jokers = state[:5]
        moves = [j for j in self.connected[prev] if j not in recent]
        if jokers[maximizing]:
            connected = self.connected_sets[prev]
            order = self.by_preference if maximizing else reversed(self.by_preference)
            extra = []
            for j in order:
                if j not in connected and j not in recent:
                    extra.append(j + self.n)
                    if len(extra) == JOKER_CANDIDATES:
                        break
            moves = sorted(moves + extra, key=lambda m: self.preference[m % self.n])
        if not maximizing:
            moves.reverse()
        if self._cadence_ready(state):
            tonic = self.tonic[maximizing]
            moves = [tonic] + [m for m in moves if m != tonic]  # always legal, always first
        return moves

    def apply(self, state: tuple, move: int) -> tuple[float, tuple]:
        """(reward, child state) for playing `move`."""
        bars_left, maximizing, _, recent, jokers, pot, _ = state
        chord = move % self.n
        recent = (recent + (chord,))[-self.window :] if self.window else ()
        if move >= self.n:
            jokers = (jokers[0], jokers[1] - 1) if maximizing else (jokers[0] - 1, jokers[1])
        child = (bars_left - 1, not maximizing, chord, recent, jokers)
        if chord == self.tonic[maximizing] and self._cadence_ready(state):
            return (pot if maximizing else -pot), child + (0, True)
        return 0.0, child + (pot + self.tension[chord], True)

    def miss(self, state: tuple) -> tuple[float, tuple]:
        bars_left, maximizing, prev, recent, jokers, pot, _ = state
        return 0.0, (bars_left - 1, not maximizing, prev, recent, jokers, pot + 1, False)

    def _leftover(self, prev: int, pot: int) -> float:
        owner = self.owner[prev]
        if owner is None:
            return 0.0
        return pot if owner is Side.PLAYER else -pot

    def terminal(self, state: tuple) -> float:
        return self._leftover(state[2], state[5])

    def leaf(self, state: tuple) -> float:
        """A pending cadence takes the pot; otherwise half the leftover the round would settle on."""
        maximizing, prev, pot = state[1], state[2], state[5]
        if self._cadence_ready(state):
            return pot if maximizing else -pot
        return 0.5 * self._leftover(prev, pot)
