"""Running the bot without freezing the game.

The search is CPU-bound pure Python. In a thread it would hold the GIL and
starve the audio callback, so `BotWorker` runs it in a separate process. Both
players share one interface: `submit(game)` starts thinking about a snapshot of
the round, `poll()` returns PENDING until the move (or None for a miss) is ready.
"""

from __future__ import annotations

import random
from concurrent.futures import Future, ProcessPoolExecutor

from ..game.duel import DuelConfig, DuelRound
from .alphabeta import Difficulty, Move
from .bot import Bot

PENDING = object()

_bot: Bot | None = None  # lives in the worker process


def _init(config: DuelConfig, difficulty: Difficulty, seed: int | None) -> None:
    global _bot
    _bot = Bot(config, difficulty, rng=random.Random(seed))


def _choose(game: DuelRound) -> Move | None:
    return _bot.choose(game)


class BotWorker:
    def __init__(self, config: DuelConfig, difficulty: Difficulty, seed: int | None = None) -> None:
        self._pool = ProcessPoolExecutor(max_workers=1, initializer=_init, initargs=(config, difficulty, seed))
        self._future: Future | None = None

    def submit(self, game: DuelRound) -> None:
        self._future = self._pool.submit(_choose, game)  # the round is pickled: a snapshot

    def poll(self):
        if self._future is None or not self._future.done():
            return PENDING
        future, self._future = self._future, None
        return future.result()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class InlineBot:
    """Same interface, thinking on the spot. For tests and tools."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._result = PENDING

    def submit(self, game: DuelRound) -> None:
        self._result = self.bot.choose(game)

    def poll(self):
        result, self._result = self._result, PENDING
        return result

    def close(self) -> None:
        pass
