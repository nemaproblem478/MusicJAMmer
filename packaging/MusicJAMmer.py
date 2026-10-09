"""Entry point of the packaged app (see build_mac.sh).

    MusicJAMmer             the game
    MusicJAMmer --selftest  a quick bot-vs-bot round without a window, to check a build
"""

import multiprocessing
import random
import sys


def selftest() -> int:
    import time

    from musicjammer.ai import DIFFICULTIES, PENDING, Bot, BotWorker
    from musicjammer.audio import NumpySynth
    from musicjammer.game import DuelConfig, DuelRound, Side
    from musicjammer.theory import MAJOR, Key

    synth = NumpySynth()
    synth.note_on(0, 60)
    assert abs(synth.render(4096)).max() > 0, "the synth is silent"
    config = DuelConfig(Key(0, MAJOR), bars=8)
    game = DuelRound(config)
    worker = BotWorker(config, DIFFICULTIES["easy"], seed=1)  # thinks in a separate process, as in the game
    player = Bot(config, DIFFICULTIES["easy"], rng=random.Random(2))
    try:
        while not game.finished:
            if game.side_to_move is Side.BOT:
                worker.submit(game)
                deadline = time.monotonic() + 30
                while (move := worker.poll()) is PENDING:
                    if time.monotonic() > deadline:
                        print("selftest: the bot process did not answer")
                        return 1
                    time.sleep(0.01)
            else:
                move = player.choose(game)
            game.miss() if move is None else game.play(move.chord, move.joker)
    finally:
        worker.close()
    print(f"selftest ok: {[b.chord.name if b.chord else '-' for b in game.bars]}, score {game.score:+d}")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # lets the bot's worker process start inside the app bundle
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from musicjammer.ui.app import main

    main()
