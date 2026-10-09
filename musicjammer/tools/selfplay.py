"""Bot-vs-bot statistics for tuning the duel rules.

    python -m musicjammer.tools.selfplay [games per matchup] [bot home pitch class]

Plays rounds between a greedy bot (looks one move ahead, so it never hands over
a cadence but never sets a trap either), a depth-2 bot and the full-depth bot,
using the default duel rules. Reports the balance when both sides play deep,
how many cadences happen, and how many points per round deeper search is worth.
If deep search gains little over greedy play, the rules leave little to think
about.
"""

from __future__ import annotations

import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from ..ai import DIFFICULTIES, AlphaBetaAI
from ..game import DuelConfig, DuelRound, Side
from ..theory import MAJOR, Key, note_name

LEVELS = {
    "greedy": replace(DIFFICULTIES["easy"], id="greedy", randomness=0.0),
    "depth2": replace(DIFFICULTIES["easy"], id="depth2", max_depth=2, randomness=0.0),
    "deep": replace(DIFFICULTIES["hard"], id="deep", time_limit=0.3),
}
MATCHUPS = [  # (bot, player)
    ("deep", "deep"),
    ("deep", "greedy"),
    ("greedy", "deep"),
    ("deep", "depth2"),
    ("depth2", "deep"),
]


def play(job: tuple[int, str, str, int]) -> tuple[str, str, int, int]:
    bot_home, bot_level, player_level, seed = job
    config = DuelConfig(Key(0, MAJOR), Key(bot_home, MAJOR))
    rng = random.Random(seed)
    game = DuelRound(config)
    ais = {
        Side.BOT: AlphaBetaAI(config, LEVELS[bot_level], rng),
        Side.PLAYER: AlphaBetaAI(config, LEVELS[player_level], rng),
    }
    while not game.finished:
        move = ais[game.side_to_move].choose(game)
        game.miss() if move is None else game.play(move.chord, move.joker)
    return bot_level, player_level, game.score, sum(b.cadence for b in game.bars)


def main() -> None:
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    bot_home = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    jobs = [(bot_home, b, p, seed) for b, p in MATCHUPS for seed in range(games)]
    results: dict[tuple[str, str], list[tuple[int, int]]] = {}
    with ProcessPoolExecutor() as pool:
        for bot, player, score, cadences in pool.map(play, jobs):
            results.setdefault((bot, player), []).append((score, cadences))

    def mean_score(bot: str, player: str) -> float:
        return statistics.mean(r[0] for r in results[(bot, player)])

    deep = results[("deep", "deep")]
    wins, losses = sum(r[0] > 0 for r in deep), sum(r[0] < 0 for r in deep)
    print(f"Player in C major vs bot in {note_name(bot_home)} major, {games} rounds per matchup")
    print(f"deep vs deep: player W/D/L {wins}/{len(deep) - wins - losses}/{losses},"
          f" mean score {mean_score('deep', 'deep'):+.1f},"
          f" cadences per round {statistics.mean(r[1] for r in deep):.1f}")
    print("points per round gained by searching deeper (higher = more strategy):")
    for weaker in ("greedy", "depth2"):
        # Against a deep opponent, how much better does each side do searching deep instead?
        bot_gain = mean_score(weaker, "deep") - mean_score("deep", "deep")
        player_gain = mean_score("deep", "deep") - mean_score("deep", weaker)
        print(f"  deep over {weaker}: as bot {bot_gain:+.1f}, as player {player_gain:+.1f}")


if __name__ == "__main__":
    main()
