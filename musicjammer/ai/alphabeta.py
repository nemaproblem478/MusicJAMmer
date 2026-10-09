"""Alpha-beta search for the bot.

The rules, rewards and evaluation come from the game model (see models.py). A node's
value is the sum of the rewards still to come, from the player's point of view;
the player maximises, the bot minimises. Because values only cover what is
still to come, states reached through different move orders share
transposition-table entries.

Iterative deepening runs until the depth cap, the end of the round or the time
budget; the result of the last fully searched depth is used.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from ..theory import Chord, ChordType
from ..game.duel import DuelConfig
from .models import DuelModel

_EXACT, _LOWER, _UPPER = range(3)
_TT_LIMIT = 2_000_000


@dataclass(frozen=True)
class Difficulty:
    id: str
    label: str
    max_depth: int
    time_limit: float  # seconds per move
    randomness: float  # chance of picking one of the next-best moves instead of the best
    top_k: int = 3


DIFFICULTIES: dict[str, Difficulty] = {
    d.id: d
    for d in (
        Difficulty("easy", "Easy", max_depth=1, time_limit=0.2, randomness=0.5),
        Difficulty("medium", "Medium", max_depth=3, time_limit=0.4, randomness=0.15),
        Difficulty("hard", "Hard", max_depth=64, time_limit=0.8, randomness=0.0),
    )
}


@dataclass(frozen=True)
class Move:
    chord: Chord
    joker: bool = False


class _Timeout(Exception):
    pass


@dataclass
class SearchInfo:
    depth: int = 0
    nodes: int = 0
    value: float = 0.0
    seconds: float = 0.0


class AlphaBetaAI:
    def __init__(
        self,
        config: DuelConfig,
        difficulty: Difficulty = DIFFICULTIES["hard"],
        rng: random.Random | None = None,
        chord_types: list[ChordType] | None = None,
    ) -> None:
        self.model = DuelModel(config, chord_types)
        self.difficulty = difficulty
        self.rng = rng or random.Random()
        self.tt: dict[tuple, tuple[int, float, int, int]] = {}
        self.last = SearchInfo()
        self._deadline = 0.0

    @property
    def cores(self) -> list[Chord]:
        return self.model.cores

    def choose(self, game) -> Move | None:
        """Pick a move for the side to move, or None when there is no legal move (the bar is missed).

        The round must not be finished.
        """
        state = self.model.state(game)
        moves = self.model.moves(state)
        if not moves:
            return None

        started = time.perf_counter()
        self._deadline = started + self.difficulty.time_limit
        self.rng.shuffle(moves)  # random tie-breaks keep the bot from sounding canned
        scored = [(0.0, m) for m in moves]
        self.last = SearchInfo()
        max_depth = min(self.difficulty.max_depth, game.bars_left)
        for depth in range(1, max_depth + 1):
            try:
                scored = self._search_root(scored, state, depth)
            except _Timeout:
                break
            self.last.depth = depth
            self.last.value = scored[0][0]
        self.last.seconds = time.perf_counter() - started
        if len(self.tt) > _TT_LIMIT:
            self.tt.clear()
        chord, joker = self.model.chord_of(self._pick(scored))
        return Move(chord, joker)

    def _search_root(self, scored, state, depth):
        maximizing = self.model.maximizing(state)
        exact = self.difficulty.randomness > 0  # need true values of the runners-up
        alpha, beta = float("-inf"), float("inf")
        results = []
        # Search the previous iteration's best moves first.
        for _, m in sorted(scored, key=lambda s: s[0], reverse=maximizing):
            reward, child = self.model.apply(state, m)
            # The child's window is shifted by this move's reward.
            value = reward + self._search(
                child, depth - 1,
                float("-inf") if exact else alpha - reward, float("inf") if exact else beta - reward,
            )
            results.append((value, m))
            if not exact:
                if maximizing:
                    alpha = max(alpha, value)
                else:
                    beta = min(beta, value)
        # Stable sort: among equal values the shuffled order decides.
        return sorted(results, key=lambda s: s[0], reverse=maximizing)

    def _search(self, state, depth, alpha, beta) -> float:
        model = self.model
        if model.bars_left(state) == 0:
            return model.terminal(state)
        if depth == 0:
            return model.leaf(state)
        self.last.nodes += 1
        if self.last.nodes & 1023 == 0 and self.last.depth >= 1 and time.perf_counter() > self._deadline:
            raise _Timeout

        entry = self.tt.get(state)
        best_move = -1
        if entry is not None:
            e_depth, e_value, e_flag, best_move = entry
            if e_depth >= depth:
                if e_flag == _EXACT:
                    return e_value
                if e_flag == _LOWER:
                    alpha = max(alpha, e_value)
                else:
                    beta = min(beta, e_value)
                if alpha >= beta:
                    return e_value

        moves = model.moves(state)
        if not moves:  # forced miss
            reward, child = model.miss(state)
            return reward + self._search(child, depth - 1, alpha - reward, beta - reward)
        if best_move in moves:
            moves.remove(best_move)
            moves.insert(0, best_move)

        maximizing = model.maximizing(state)
        alpha0, beta0 = alpha, beta
        best_value = float("-inf") if maximizing else float("inf")
        for m in moves:
            reward, child = model.apply(state, m)
            value = reward + self._search(child, depth - 1, alpha - reward, beta - reward)
            if maximizing:
                if value > best_value:
                    best_value, best_move = value, m
                alpha = max(alpha, value)
            else:
                if value < best_value:
                    best_value, best_move = value, m
                beta = min(beta, value)
            if alpha >= beta:
                break

        if best_value <= alpha0:
            flag = _UPPER
        elif best_value >= beta0:
            flag = _LOWER
        else:
            flag = _EXACT
        self.tt[state] = (depth, best_value, flag, best_move)
        return best_value

    def _pick(self, scored: list[tuple[float, int]]) -> int:
        d = self.difficulty
        if d.randomness > 0 and len(scored) > 1 and self.rng.random() < d.randomness:
            return self.rng.choice(scored[1 : d.top_k + 1])[1]
        return scored[0][1]
