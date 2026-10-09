import random

import pytest

import musicjammer.ai.models as models
from musicjammer.ai import DIFFICULTIES, AlphaBetaAI, Bot
from musicjammer.ai.alphabeta import Difficulty
from musicjammer.game import DuelConfig, DuelRound, IllegalMove, Side
from musicjammer.theory import MAJOR, MINOR, Chord, Key, MoveError, RuleSet, all_cores

EXHAUSTIVE = Difficulty("exhaustive", "Exhaustive", max_depth=64, time_limit=1e9, randomness=0.0)
CHORDS = {c.name: c for c in all_cores()}


def play(game, *names):
    for name in names:
        game.play(CHORDS[name])


def test_bot_home_defaults_to_the_opposite_key():
    assert DuelConfig(Key(0, MAJOR)).bot_key == Key(6, MAJOR)
    assert DuelConfig(Key(9, MINOR)).bot_key == Key(3, MINOR)


def test_defaults():
    config = DuelConfig(Key(0, MAJOR))
    assert (config.cadence_rule, config.leftover, config.rules.repeat_window, config.jokers) == (
        "leading_tone", "burn", 8, 1,
    )


def test_trap_from_the_rules_explanation():
    game = DuelRound(DuelConfig(Key(0, MAJOR), rules=RuleSet(), cadence_rule="dominant"))
    play(game, "F", "Am", "Em", "Bm", "D", "B°")
    assert game.pot == 7  # six bars, B° counts double
    bot_options = [c for c in all_cores() if game.check(c) is None]
    assert [c.name for c in bot_options] == ["G"]  # forced into the player's dominant
    play(game, "G")
    assert game.is_cadence(CHORDS["C"])
    bar = game.play(CHORDS["C"])
    assert bar.cadence and bar.won == 8
    assert game.points[Side.PLAYER] == 8 and game.pot == 0


def test_cadence_ignores_connection_rules_and_repeat_ban():
    game = DuelRound(DuelConfig(Key(0, MAJOR), rules=RuleSet(min_common_tones=1, repeat_window=8)))
    play(game, "Em", "C", "G")  # C was just played, B°->C would share no notes
    assert game.check(CHORDS["C"]) is None


def test_own_dominant_resolution_does_not_count():
    game = DuelRound(DuelConfig(Key(0, MAJOR), rules=RuleSet(min_common_tones=1, max_circle_steps=None)))
    play(game, "G", "Em")  # bot plays the player's dominant, but the player doesn't resolve
    play(game, "C")  # bot resolving the player's cadence scores nothing for anyone
    assert not game.bars[-1].cadence and game.points == {Side.BOT: 0, Side.PLAYER: 0}


def test_jokers():
    game = DuelRound(DuelConfig(Key(0, MAJOR)))
    assert game.check(CHORDS["F#"]) is MoveError.NO_COMMON_TONES
    game.play(CHORDS["F#"], joker=True)
    with pytest.raises(IllegalMove):
        play(game, "C")  # player: too far without a joker
    game.play(CHORDS["C"], joker=True)
    assert game.check(CHORDS["F#"], joker=True) is MoveError.NO_JOKERS  # the bot's is spent


def test_unclaimed_pot_goes_to_the_closer_side():
    game = DuelRound(DuelConfig(Key(0, MAJOR), bars=2, leftover="closer"))
    play(game, "Em", "Am")  # Am is in C's territory
    assert game.finished and game.leftover == (Side.PLAYER, 2)
    assert game.points[Side.PLAYER] == 2 and game.winner is Side.PLAYER


def minimax(game: DuelRound, cores: list[Chord]) -> float:
    """Plain minimax over the real duel rules: the final score from here."""
    if game.finished:
        return game.score
    values = []
    for chord in cores:
        for joker in (False, True):
            if game.check(chord, joker) is None and not (joker and game.is_cadence(chord)):
                values.append(minimax(_after(game, lambda g: g.play(chord, joker)), cores))
    if not values:
        values.append(minimax(_after(game, lambda g: g.miss()), cores))
    return max(values) if game.side_to_move is Side.PLAYER else min(values)


def _after(game: DuelRound, action) -> DuelRound:
    child = DuelRound(game.config)
    child.bars, child.chords = list(game.bars), list(game.chords)
    child.jokers_left, child.points, child.pot = dict(game.jokers_left), dict(game.points), game.pot
    action(child)
    return child


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("near_bot", [False, True])
@pytest.mark.parametrize("cadence_rule, leftover", [("dominant", "closer"), ("leading_tone", "burn")])
def test_alphabeta_matches_minimax(seed, near_bot, cadence_rule, leftover, monkeypatch):
    monkeypatch.setattr(models, "JOKER_CANDIDATES", 99)  # let the search see every joker move
    key = Key(seed, MAJOR if seed % 2 else MINOR)
    bot_key = Key(seed + 7, MAJOR) if near_bot else None
    config = DuelConfig(key, bot_key, bars=8, cadence_rule=cadence_rule, leftover=leftover)
    rng = random.Random(seed)
    game = DuelRound(config)
    cores = AlphaBetaAI(config).cores
    for _ in range(5 + seed % 2):  # random opening, then brute-force the last 2-3 bars
        options = [c for c in cores if game.check(c) is None]
        game.play(rng.choice(options)) if options else game.miss()
    ai = AlphaBetaAI(config, EXHAUSTIVE, random.Random(seed))
    ai.choose(game)
    already = game.score
    assert ai.last.depth == game.bars_left
    assert already + ai.last.value == pytest.approx(minimax(game, cores))


def test_leading_tone_rule_widens_the_setups():
    config = DuelConfig(Key(0, MAJOR), cadence_rule="leading_tone", rules=RuleSet(1, max_circle_steps=None))
    game = DuelRound(config)
    play(game, "Em", "Am")  # Em holds B, C's leading tone, but the bot played it, so no cadence yet
    assert not game.bars[-1].cadence
    play(game, "E")  # the bot plays E (E G# B)
    assert game.is_cadence(CHORDS["C"])


def test_burnt_leftover():
    game = DuelRound(DuelConfig(Key(0, MAJOR), bars=2, leftover="burn"))
    play(game, "Em", "Am")
    assert game.leftover == (None, 2) and game.points[Side.PLAYER] == 0


@pytest.mark.parametrize("level", ["easy", "medium"])
def test_bots_play_legal_moves_through_a_whole_round(level):
    config = DuelConfig(Key(0, MAJOR))
    game = DuelRound(config)
    bots = {side: Bot(config, DIFFICULTIES[level], rng=random.Random(side.value)) for side in Side}
    while not game.finished:
        move = bots[game.side_to_move].choose(game)
        game.miss() if move is None else game.play(move.chord, move.joker)  # play() raises if illegal
    assert game.finished and game.pot == 0


def test_bot_decorates_its_chord_without_changing_the_move():
    config = DuelConfig(Key(0, MAJOR))
    game = DuelRound(config)
    bot = Bot(config, DIFFICULTIES["easy"], extension_chance=1.0, rng=random.Random(3))
    move = bot.choose(game)
    assert move.chord.extension.id != "none"
    assert game.check(move.chord, move.joker) is None


def test_bot_springs_the_trap():
    """With the bot forced onto G, a deep player answers C and takes the pot."""
    config = DuelConfig(Key(0, MAJOR), rules=RuleSet(repeat_window=4), cadence_rule="dominant")
    game = DuelRound(config)
    play(game, "F", "Am", "Em", "Bm", "D", "B°", "G")
    ai = AlphaBetaAI(config, EXHAUSTIVE, random.Random(0))
    assert ai.choose(game).chord == CHORDS["C"]


def test_bot_worker_thinks_in_another_process():
    import time

    from musicjammer.ai import PENDING, BotWorker

    config = DuelConfig(Key(0, MAJOR), bars=8)
    game = DuelRound(config)
    worker = BotWorker(config, DIFFICULTIES["easy"], seed=1)
    try:
        worker.submit(game)
        deadline = time.monotonic() + 30
        while (move := worker.poll()) is PENDING:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert game.check(move.chord, move.joker) is None
    finally:
        worker.close()
